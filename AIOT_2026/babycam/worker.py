import argparse
import csv
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from .common import Config, RemoteError, atomic_json, select_batch, validate_result

LOG = logging.getLogger("babycam.worker")


class SourceChanged(RuntimeError):
    pass


def file_hash(path):
    with Path(path).open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def signature(cfg):
    files = ["models/air400_detect_v2.py", "models/air400_npz_anomaly_v2.py", "models/deep_phys.py",
             "processors/pre_processor.py", "processors/post_processor.py",
             "configs/inference/deepphys_deep_infer.yaml", "checkpoints/DeepPhys_Deep_Body_best.pth",
             "detectors/yolov8m.pt", "detectors/yolov8n-face.pt", "output/ae_results_v2/air400_ae.pt"]
    source = {p: file_hash(cfg.root / p) for p in files}
    source.update(service=file_hash(Path(__file__)), common=file_hash(Path(__file__).with_name("common.py")),
                  project=cfg.url, bucket=cfg.bucket, prefix=cfg.prefix, stream_id=cfg.stream_id,
                  start_seq=cfg.start_seq, ffmpeg=cfg.ffmpeg, ffprobe=cfg.ffprobe)
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()


class SingleInstance:
    """OS locks are released even if the process crashes; no stale PID file to delete."""
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "worker.lock"

    def __enter__(self):
        self.fp = self.path.open("a+b")
        self.fp.seek(0, os.SEEK_END)
        if self.fp.tell() == 0:
            self.fp.write(b"0")
            self.fp.flush()
        self.fp.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fp.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fp.close()
            raise ValueError("같은 WORK_DIR에서 수집기가 이미 실행 중입니다.") from None
        return self

    def __exit__(self, *_):
        self.fp.close()


def probe(path, ffprobe):
    try:
        proc = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                              capture_output=True, timeout=30, check=True)
        data = json.loads(proc.stdout)
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        duration = float(data["format"]["duration"])
        start = float(data["format"].get("start_time", 0))
        if not math.isfinite(duration) or not 0 < duration <= 60 or not math.isfinite(start):
            raise ValueError()
        return dict(duration=duration, start=start, codec=video["codec_name"],
                    width=video["width"], height=video["height"])
    except (subprocess.SubprocessError, ValueError, KeyError, StopIteration):
        raise ValueError(f"FFprobe 영상 검사 실패: {path.name}") from None


def merge_media(paths, folder, cfg):
    infos = [probe(path, cfg.ffprobe) for path in paths]
    if len({(i["codec"], i["width"], i["height"]) for i in infos}) != 1:
        raise ValueError("15개 TS의 코덱 또는 해상도가 다릅니다.")
    duration = sum(i["duration"] for i in infos)
    if abs(duration - 30) > .25:
        raise ValueError(f"TS 15개 길이 합계 {duration:.3f}초: 30±0.25초 범위 밖입니다.")
    # Paths in this list are generated numeric basenames, never remote-supplied paths.
    listing = folder / "concat.txt"
    listing.write_text("".join(f"file 'segments/{p.name}'\n" for p in paths), encoding="utf-8")
    merged = folder / "merged.mp4"
    with (folder / "merge.log").open("wb") as log:
        try:
            subprocess.run([cfg.ffmpeg, "-nostdin", "-y", "-v", "error", "-xerror", "-f", "concat",
                            "-safe", "1", "-i", str(listing), "-map", "0:v:0", "-an",
                            "-vf", "setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=0.25,trim=duration=30,setpts=PTS-STARTPTS",
                            "-t", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(merged)],
                           stdout=log, stderr=log, timeout=180, check=True)
        except (subprocess.SubprocessError, OSError):
            raise ValueError("FFmpeg 결합 실패: 해당 배치 merge.log를 확인하세요.") from None
    final = probe(merged, cfg.ffprobe)
    if abs(final["duration"] - 30) > .01:
        raise ValueError("결합 영상의 길이가 30초가 아닙니다.")
    gaps = [b["start"] - a["start"] - a["duration"] for a, b in zip(infos, infos[1:])]
    # PTS resets are common in TS files. They do not establish capture continuity.
    pts_consistent = all(abs(gap) <= .25 for gap in gaps)
    if all(b["start"] > a["start"] for a, b in zip(infos, infos[1:])) and any(abs(g) > .25 for g in gaps):
        raise ValueError("연속 증가하는 TS timestamp에서 시간 공백/겹침이 발견되었습니다.")
    return merged, dict(source_duration_sec=duration, duration_sec=final["duration"],
                        continuity={"basis": "sequence_and_pts" if pts_consistent else "sequence_only",
                                    "capture_time_verified": False,
                                    "duration_adjustment_sec": round(30 - duration, 6)})


class ExistingPipeline:
    """Loads the existing AIR-400 v2 objects once; does not duplicate preprocessing/model code."""
    def __init__(self, cfg):
        # Keep Ultralytics settings scoped to this worker rather than changing user-global settings.
        os.environ.setdefault("YOLO_CONFIG_DIR", str(cfg.work_dir / "ultralytics"))
        import torch
        sys.path.insert(0, str(cfg.root / "models"))
        import air400_detect_v2 as existing
        self.existing, self.cfg = existing, cfg
        self.args = SimpleNamespace(air400_root=cfg.root, config=None,
                                    deepphys_ckpt=cfg.root / "checkpoints/DeepPhys_Deep_Body_best.pth",
                                    body_detector=cfg.root / "detectors/yolov8m.pt",
                                    face_detector=cfg.root / "detectors/yolov8n-face.pt",
                                    no_roi=False, ffmpeg=cfg.ffmpeg, frame_batch=16)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.scorer = existing.AnomalyV2(cfg.root / "output/ae_results_v2/air400_ae.pt", device)
        self.runner = existing.DeepPhysRunner(self.args, device)
        LOG.info("기존 DeepPhys/v2 로드 완료: %s, threshold=%.6f", device, self.scorer.threshold)

    def analyze(self, video, out_dir):
        import numpy as np
        out_dir.mkdir(parents=True, exist_ok=False)
        args = SimpleNamespace(**vars(self.args), input=video, out_dir=out_dir)
        rows = list(self.existing.video_rows(args, self.runner, self.scorer))
        with (out_dir / "anomaly_scores.csv").open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=self.existing.COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        if len(rows) != 1 or rows[0]["end_sec"] != 30:
            raise ValueError("기존 추론기가 정확한 30초 구간 하나를 반환하지 않았습니다.")
        row = rows[0]
        wave = None
        if row.get("npz_file"):
            with np.load(out_dir / row["npz_file"], allow_pickle=False) as data:
                wave = {"x_10hz": data["x_10hz"].tolist(), "raw_model": data["raw_model"].tolist(),
                        "fs": 10, "raw_fs": float(data["fs"])}
        return {k: row.get(k) for k in ("status", "is_anomaly", "anomaly_score", "threshold",
                                        "pred_rr_bpm", "wave_mse", "bpm_mse", "reason")} | {"waveform": wave}


class BatchProcessor:
    def __init__(self, cfg, api, pipeline):
        self.cfg, self.api, self.pipeline = cfg, api, pipeline

    def __call__(self, batch, folder, attempt):
        cached = folder / "result.json"
        seg_dir = folder / "segments"
        seg_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = folder / "manifest.json"
        versions = [{k: item.get(k) for k in ("name", "id", "updated_at", "metadata")} for item in batch]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
            "objects": versions, "sha256": {}}
        if manifest["objects"] != versions:
            raise SourceChanged("같은 번호의 원본 TS가 변경되었습니다. 새 prefix/STREAM_ID/WORK_DIR가 필요합니다.")
        if cached.is_file():
            return json.loads(cached.read_text(encoding="utf-8"))
        paths = []
        for item in batch:
            path = seg_dir / item["name"]
            if not path.exists() or manifest["sha256"].get(path.name) != file_hash(path):
                self.api.download(path.name, path)
                manifest["sha256"][path.name] = file_hash(path)
                atomic_json(manifest_path, manifest)
            paths.append(path)
        video, info = merge_media(paths, folder, self.cfg)
        row = validate_result(self.pipeline.analyze(video, folder / f"inference_{attempt}")) | info
        atomic_json(cached, row)
        return row


class Worker:
    def __init__(self, cfg, api, process, model_signature):
        self.cfg, self.api, self.process, self.model_signature = cfg, api, process, model_signature
        self.state_path = cfg.work_dir / "state.json"
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state.get("signature") != model_signature:
                raise ValueError("이 WORK_DIR의 입력/모델/설정이 다릅니다. 새 WORK_DIR를 지정하세요. 기존 상태를 지우지 마세요.")
        else:
            self.state = dict(signature=model_signature, next_seq=cfg.start_seq, pending=None, attempts=0)
            self.save_state()

    def save_state(self):
        atomic_json(self.state_path, self.state)

    def tick(self):
        if self.state["pending"] is None:
            batch = select_batch(self.api.list_segments(), self.state["next_seq"])
            if batch is None:
                LOG.info("연속 TS 15개 대기: next_seq=%s", self.state["next_seq"])
                return "waiting"
            first, last = (int(batch[i]["name"][:-3]) for i in (0, -1))
            if self.state["next_seq"] is None:
                self.state["next_seq"] = first
                self.save_state()
            batch_id = hashlib.sha256(f"{self.model_signature}:{first}:{last}".encode()).hexdigest()
            folder = self.cfg.work_dir / "batches" / f"{first:012}_{last:012}"
            folder.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            LOG.info("분석 시작: %012d..%012d (시도 %d)", first, last, self.state["attempts"] + 1)
            try:
                partial = self.process(batch, folder, self.state["attempts"] + 1)
            except (RemoteError, SourceChanged):
                raise
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
                self.state["attempts"] += 1
                self.save_state()
                LOG.error("배치 처리 실패 %d/3: %s", self.state["attempts"], exc)
                if self.state["attempts"] < 3:
                    return "retry"
                partial = {"status": "unscored", "reason": str(exc)[:500]}
            payload = dict(batch_id=batch_id, stream_id=self.cfg.stream_id, start_seq=first, end_seq=last,
                           segments=[o["name"] for o in batch], model_signature=self.model_signature,
                           processing_sec=round(time.monotonic() - started, 3), **partial)
            self.state["pending"] = validate_result(payload)
            self.save_state()  # Durable outbox BEFORE making the remote write.
        pending = self.state["pending"]
        self.api.save_result(pending)  # An uncertain response is retried with the SAME idempotency key.
        self.state.update(next_seq=pending["end_seq"] + 1, pending=None, attempts=0)
        self.save_state()
        LOG.info("DB 저장 완료: %d..%d status=%s 처리 %.1f초", pending["start_seq"], pending["end_seq"],
                 pending["status"], pending["processing_sec"])
        if pending["processing_sec"] > 30:
            LOG.warning("30초 입력보다 처리 시간이 깁니다. 모든 구간을 순서대로 처리하므로 분석 지연이 누적될 수 있습니다.")
        self.prune_media()
        return "saved"

    def prune_media(self):
        # Retain the latest three source batches; small NPZ/CSV/results remain for review.
        base = (self.cfg.work_dir / "batches").resolve()
        jobs = sorted(p for p in base.glob("*_*") if p.is_dir() and
                      p.name.replace("_", "").isdigit() and p.resolve().parent == base)
        completed = [p for p in jobs if int(p.name.split("_")[-1]) < self.state["next_seq"]]
        for folder in completed[:-3]:
            for path in [folder / "merged.mp4", *(folder / "segments").glob("*.ts")]:
                if path.resolve().is_relative_to(base) and path.is_file():
                    path.unlink()


def main(default_env):
    parser = argparse.ArgumentParser(description="Supabase TS 15개 → 30초 MP4 → 기존 AIR-400 → Supabase 결과")
    parser.add_argument("--env", type=Path, default=default_env)
    parser.add_argument("--check", action="store_true", help="설정·파일·원격 테이블과 목록 확인만 수행")
    parser.add_argument("--once", action="store_true", help="배치 하나만 처리; 대기/재시도는 종료 코드 2")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        from .common import Supabase
        cfg = Config.load(args.env)
        for binary in (cfg.ffmpeg, cfg.ffprobe):
            if not shutil.which(binary):
                raise ValueError(f"실행 파일이 없습니다: {binary}. FFMPEG/FFPROBE 설정을 확인하세요.")
        model_signature = signature(cfg)
        api = Supabase(cfg)
        api.results(1)  # Fail early if the result table/permissions were not configured.
        objects = api.list_segments()
        LOG.info("설정/모델 파일/원격 접근 확인: TS 목록 %d개", len(objects))
        if args.check:
            return 0
        with SingleInstance(cfg.work_dir):
            pipeline = ExistingPipeline(cfg)
            worker = Worker(cfg, api, BatchProcessor(cfg, api, pipeline), model_signature)
            while True:
                try:
                    outcome = worker.tick()
                    if args.once:
                        return 0 if outcome == "saved" else 2
                except RemoteError as exc:
                    LOG.error("%s; 결과/커서를 보존하고 재시도합니다.", exc)
                    if args.once:
                        return 2
                time.sleep(cfg.poll)
    except KeyboardInterrupt:
        LOG.info("수집기 종료. 다음 실행에서 저장된 상태부터 재개합니다.")
        return 0
    except (ValueError, OSError, ImportError, RuntimeError) as exc:
        LOG.error("시작/실행 오류: %s", exc)
        return 1
