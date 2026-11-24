"""AIR-400 DeepPhys -> 30초 호흡 파형/BPM -> 학습된 anomaly_v2 추론.

같은 폴더에 air400_npz_anomaly_v2.py를 둔다. video 모드는 기존 AIR-400
환경과 FFmpeg가 필요하다. npz 모드는 기존 추출기의 windows를 그대로 평가한다.
"""

import argparse
import csv
import json
import logging
import subprocess
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from zipfile import BadZipFile

import numpy as np
import torch

from air400_npz_anomaly_v2 import Autoencoder, read_metadata

WINDOW_SEC = 30
VIDEO_FS = 15
WAVE_FS = 10
FRAME_COUNT = WINDOW_SEC * VIDEO_FS
WAVE_COUNT = WINDOW_SEC * WAVE_FS
VIDEO_SUFFIXES = {".mp4", ".webm", ".avi", ".mov", ".mkv", ".m4v"}
COLUMNS = ["video", "window_index", "start_sec", "end_sec", "pred_rr_bpm", "wave_mse",
           "bpm_mse", "anomaly_score", "threshold", "is_anomaly", "status", "reason", "npz_file"]


class InvalidWindow(ValueError):
    """이 구간은 점수를 매기지 않는다."""


class AnomalyV2:
    def __init__(self, checkpoint, device):
        ckpt = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if not isinstance(ckpt, dict) or ckpt.get("model_version") != 2:
            raise ValueError("anomaly_v2가 저장한 air400_ae.pt를 지정하세요. v1은 호환되지 않습니다.")
        self.stats = {k: float(ckpt["stats"][k]) for k in
                      ("wave_mean", "wave_std", "bpm_mean", "bpm_std")}
        self.threshold = float(ckpt["threshold"])
        self.weight = float(ckpt["bpm_weight"])
        if (not np.isfinite([*self.stats.values(), self.threshold, self.weight]).all()
                or min(self.stats["wave_std"], self.stats["bpm_std"]) <= 0
                or self.threshold < 0 or self.weight < 0):
            raise ValueError("v2 체크포인트의 표준화 값, 가중치 또는 임계값이 올바르지 않습니다.")
        self.device = device
        self.model = Autoencoder()
        self.model.load_state_dict(ckpt["state_dict"], strict=True)
        self.model.to(device).eval()

    @torch.inference_mode()
    def score(self, wave, bpm):
        x = np.asarray(wave, dtype=np.float32)
        b = np.asarray(bpm, dtype=np.float32)
        if x.shape != (WAVE_COUNT,) or not np.isfinite(x).all() or x.max() == x.min():
            raise InvalidWindow("10Hz 파형이 300개가 아니거나 유효한 변동이 없습니다.")
        if b.size != 1 or not np.isfinite(b).all() or b.item() <= 0:
            raise InvalidWindow("추정 호흡수가 없거나 유효하지 않습니다.")
        s = self.stats  # 입력 영상으로 평균이나 표준편차를 다시 계산하지 않는다.
        x = (x[None, None, :] - s["wave_mean"]) / s["wave_std"]
        b = (b.reshape(1, 1) - s["bpm_mean"]) / s["bpm_std"]
        x, b = (torch.from_numpy(a).to(self.device) for a in (x, b))
        x_hat, b_hat = self.model(x, b)
        wx = (x_hat - x).square().mean()
        wb = (b_hat - b).square().mean()
        ax = wx + self.weight * wb
        values = torch.stack((wx, wb, ax)).cpu().tolist()
        if not np.isfinite(values).all():
            raise InvalidWindow("복원 오차가 유한하지 않습니다.")
        return values


def resolve_path(path, root):
    return (root / Path(path)).resolve() if path else None


class DeepPhysRunner:
    def __init__(self, args, device):
        import cv2
        import yaml
        from scipy.signal import resample_poly

        root = args.air400_root.resolve()
        if not (root / "models" / "deep_phys.py").is_file():
            raise ValueError(f"--air400-root에 AIR-400 저장소 경로를 지정하세요: {root}")
        sys.path.insert(0, str(root))
        from models.deep_phys import DeepPhys
        from processors.post_processor import PostProcessor
        from processors.pre_processor import PreProcessor

        cfg_path = (args.config.resolve() if args.config else
                    root / "configs" / "inference" / "deepphys_deep_infer.yaml")
        with cfg_path.open(encoding="utf-8-sig") as f:
            cfg = yaml.safe_load(f)
        model_cfg = cfg["MODEL"]
        if model_cfg["NAME"].lower() != "deepphys" or model_cfg["IN_CHANNELS"] != 3:
            raise ValueError("AIR-400 DeepPhys 설정 YAML을 사용하세요.")
        data = cfg["TEST"]["DATA"]
        data = data[0] if isinstance(data, list) else data
        preprocess = dict(data["PREPROCESS"])
        img_size = preprocess["DOWNSAMPLE_SIZE_BEFORE_TRAINING"][1]
        self.resize = (tuple(preprocess["DOWNSAMPLE_SIZE_BEFORE_PREPROCESS"])
                       if preprocess.get("DO_DOWNSAMPLE_BEFORE_PREPROCESS") else None)
        self.cv2 = cv2
        # 원본 프레임을 읽을 때 공식 전처리의 첫 리사이즈를 한 번만 적용한다.
        # 영상은 이미 450프레임씩 나누므로 공식 기본값(180)으로 잘라 버리지 않는다.
        preprocess.update(DO_DOWNSAMPLE_BEFORE_PREPROCESS=False, DO_CHUNK=False,
                          DO_AUGMENTATION=False, OF_RESAMPLE_FS=0)
        if args.no_roi:
            preprocess["DO_CROP_INFANT_REGION"] = False
            print("주의: ROI 크롭을 끈 상태입니다. 학습과 전처리가 다르면 점수 분포도 달라질 수 있습니다.")
        paths = cfg["DATA_PATH"]
        roi_enabled = preprocess.get("DO_CROP_INFANT_REGION", False)
        body = (args.body_detector.resolve() if args.body_detector else
                resolve_path(paths.get("BODY_DETECTOR_PATH"), root))
        face = (args.face_detector.resolve() if args.face_detector else
                resolve_path(paths.get("FACE_DETECTOR_PATH"), root))
        if roi_enabled:
            for name, detector in [("body", body), ("face", face)]:
                if detector is None or not detector.is_file():
                    raise ValueError(f"--{name}-detector에 학습 때 사용한 ROI 가중치 파일을 지정하세요: {detector}")
        method = preprocess.get("OF_METHOD", "raft")
        if preprocess.get("DO_OPTICAL_FLOW") and method == "deep" and not hasattr(
                getattr(cv2, "optflow", None), "createOptFlow_DeepFlow"):
            raise ValueError("DeepFlow가 없는 OpenCV입니다. DeepPhys를 실행하던 환경을 사용하세요.")

        class CheckedPreProcessor(PreProcessor):
            def get_roi_box(self, frames):
                box, detections = super().get_roi_box(frames)
                flag = {"body": 3, "face": 4, "chest": 5}[self.infant_region.lower()]
                if not detections or all(entry[flag] for entry in detections):
                    raise InvalidWindow("이 구간에서 ROI를 찾지 못했습니다.")
                return box, detections

        self.pre = CheckedPreProcessor(preprocess, str(body or ""), str(face or ""))
        if roi_enabled and (self.pre.body_detector is None or self.pre.face_detector is None):
            raise RuntimeError("ROI 가중치를 로드하지 못했습니다. 위 OpenCV/YOLO 로그를 확인하세요.")
        self.post = PostProcessor()
        self.diff_flag = preprocess.get("LABEL_NORMALIZE_TYPE", "DiffNormalized") == "DiffNormalized"
        self.infant_flag = bool(data["INFANT_FLAG"])
        self.rr_method = cfg["INFERENCE"].get("EVALUATION_METHOD", "FFT")
        self.resample = resample_poly
        self.device = device
        self.batch_size = args.frame_batch
        self.model = DeepPhys(in_channels=3, img_size=img_size)
        state = torch.load(args.deepphys_ckpt, map_location="cpu", weights_only=True)
        state = state.get("state_dict", state)
        self.model.load_state_dict({k.removeprefix("module."): v for k, v in state.items()}, strict=True)
        self.model.to(device).eval()

    @torch.inference_mode()
    def extract(self, frames):
        clips, _ = self.pre.preprocess(frames, np.zeros(FRAME_COUNT, dtype=np.float32), VIDEO_FS)
        if clips.ndim != 5 or clips.shape[:2] != (1, FRAME_COUNT) or clips.shape[-1] != 6:
            raise RuntimeError(f"DeepPhys 전처리 결과가 (1, 450, H, W, 6)이 아닙니다: {clips.shape}")
        # DeepPhys는 프레임별 2D CNN이다. 시간순으로 배치하되 끝 프레임을 자르지 않는다.
        pred = []
        for i in range(0, FRAME_COUNT, self.batch_size):
            batch = np.ascontiguousarray(clips[0, i:i+self.batch_size].transpose(0, 3, 1, 2), dtype=np.float32)
            pred.append(self.model(torch.from_numpy(batch).to(self.device)).flatten().cpu())
        raw = torch.cat(pred)
        if raw.numel() != FRAME_COUNT or not torch.isfinite(raw).all() or raw.min() == raw.max():
            raise InvalidWindow("DeepPhys가 유효한 원시 파형을 내지 못했습니다.")
        resp, bpm = self.post.post_process(raw, fs=VIDEO_FS, diff_flag=self.diff_flag,
                                           infant_flag=self.infant_flag, use_bandpass=True,
                                           eval_method=self.rr_method)
        resp = np.asarray(resp, dtype=np.float32).reshape(-1)
        if resp.shape != (FRAME_COUNT,) or not np.isfinite(resp).all():
            raise InvalidWindow("후처리 호흡 파형이 450개가 아니거나 유한하지 않습니다.")
        wave = self.resample(resp, 2, 3).astype(np.float32)
        return raw.numpy(), resp, wave, float(bpm)


def frame_windows(path, ffmpeg, runner):
    # FFmpeg의 시간 기반 FPS 필터: 소스가 30 FPS나 VFR이어도 15 FPS로 해석한다.
    cmd = [ffmpeg, "-nostdin", "-loglevel", "error", "-xerror", "-i", str(path),
           "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", f"setpts=PTS-STARTPTS,fps={VIDEO_FS}",
           "-pix_fmt", "rgb24", "-c:v", "ppm", "-f", "image2pipe", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    batch = []
    try:
        while True:
            magic = proc.stdout.readline()
            if not magic:
                break
            if magic.strip() != b"P6":
                raise RuntimeError("FFmpeg RGB 프레임 헤더를 읽을 수 없습니다.")
            width, height = map(int, proc.stdout.readline().split())
            if width < 1 or height < 1 or proc.stdout.readline().strip() != b"255":
                raise RuntimeError("FFmpeg 프레임 크기 또는 비트 깊이가 올바르지 않습니다.")
            size = width * height * 3
            buf = proc.stdout.read(size)
            if len(buf) != size:
                raise RuntimeError("FFmpeg가 불완전한 프레임을 반환했습니다.")
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
            if runner.resize:
                frame = runner.cv2.resize(frame, runner.resize, interpolation=runner.cv2.INTER_AREA)
            batch.append(frame)
            if len(batch) == FRAME_COUNT:
                frames = np.stack(batch)
                batch.clear()
                yield FRAME_COUNT, frames.astype(np.float32) if runner.resize else frames
        if proc.wait() != 0:
            raise RuntimeError(f"FFmpeg가 영상을 읽지 못했습니다: {path}")
        if batch:
            yield len(batch), None
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def scored(row, scorer, wave, bpm):
    if np.isfinite(bpm):
        row["pred_rr_bpm"] = bpm
    wx, wb, ax = scorer.score(wave, bpm)
    row.update(wave_mse=wx, bpm_mse=wb, anomaly_score=ax, is_anomaly=(ax > scorer.threshold),
               status="anomaly_candidate" if ax > scorer.threshold else "below_threshold")


def video_rows(args, runner, scorer):
    source = args.input.resolve()
    if source.is_file():
        videos = [source]
    else:
        videos = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES)
    if not videos:
        raise ValueError(f"영상 파일을 찾을 수 없습니다: {source}")
    for i, video in enumerate(videos):
        folder = args.out_dir / "windows" / f"{i:05d}_{video.stem}"
        print(f"[{i+1}/{len(videos)}] {video.name}", flush=True)
        with closing(frame_windows(video, args.ffmpeg, runner)) as windows:
            for index, (n, frames) in enumerate(windows):
                start = WINDOW_SEC * index
                row = dict(video=str(video), window_index=index, start_sec=start,
                           end_sec=round(start + n / VIDEO_FS, 6), threshold=scorer.threshold)
                if frames is None:
                    row.update(status="unscored", reason="30초 미만의 마지막 구간")
                else:
                    try:
                        raw, resp, wave, bpm = runner.extract(frames)
                        folder.mkdir(parents=True, exist_ok=True)
                        path = folder / f"{index:06d}.npz"
                        meta = dict(video=str(video), start_sec=start, end_sec=row["end_sec"], window_index=index)
                        np.savez_compressed(path, raw_model=raw, respiration=resp,
                                            time_sec=np.arange(n, dtype=np.float64) / VIDEO_FS, fs=VIDEO_FS,
                                            x_10hz=wave, pred_rr_bpm=bpm,
                                            metadata_json=json.dumps(meta, ensure_ascii=False))
                        row["npz_file"] = path.relative_to(args.out_dir).as_posix()
                        scored(row, scorer, wave, bpm)
                    except InvalidWindow as exc:
                        row.update(status="unscored", reason=str(exc))
                yield row


def npz_rows(args, scorer):
    source = args.input.resolve()
    paths = [source] if source.is_file() else sorted(source.rglob("*.npz"))
    if not paths:
        raise ValueError(f"NPZ가 없습니다: {source}")
    for path in paths:
        row = dict(video=path.parent.name, window_index=path.stem,
                   npz_file=str(path), threshold=scorer.threshold)
        try:
            with np.load(path, allow_pickle=False) as data:
                meta = read_metadata(data, False) or {}
                row["video"] = meta.get("video") or meta.get("video_id") or row["video"]
                row["start_sec"] = meta.get("start_sec", meta.get("window_start_sec", meta.get("start_time_sec", "")))
                row["end_sec"] = meta.get("end_sec", meta.get("window_end_sec", meta.get("end_time_sec", "")))
                if (row["end_sec"] == "" and isinstance(row["start_sec"], (int, float))
                        and np.isfinite(row["start_sec"])):
                    row["end_sec"] = row["start_sec"] + WINDOW_SEC
                wave = data["x_10hz"]
                bpm = float(np.asarray(data["pred_rr_bpm"]).item())
            scored(row, scorer, wave, bpm)
        except (BadZipFile, EOFError, ValueError, KeyError, OSError, TypeError) as exc:
            row.update(status="unscored", reason=str(exc))
        yield row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    for mode in ("video", "npz"):
        p = modes.add_parser(mode)
        p.add_argument("input", type=Path, help="파일 하나 또는 파일이 들어 있는 폴더")
        p.add_argument("--anomaly-ckpt", required=True, type=Path, help="v2 air400_ae.pt")
        p.add_argument("--out-dir", required=True, type=Path, help="새 결과 폴더")
        if mode == "video":
            p.add_argument("--air400-root", required=True, type=Path)
            p.add_argument("--deepphys-ckpt", required=True, type=Path)
            p.add_argument("--config", type=Path, help="학습 때 사용한 DeepPhys YAML")
            p.add_argument("--body-detector", type=Path)
            p.add_argument("--face-detector", type=Path)
            p.add_argument("--no-roi", action="store_true", help="몸통만 이미 잘라 둔 영상 등에서만 사용")
            p.add_argument("--ffmpeg", default="ffmpeg", help="PATH의 ffmpeg 또는 실행 파일 경로")
            p.add_argument("--frame-batch", type=int, default=16)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    try:
        if not args.input.exists():
            raise ValueError(f"입력 경로가 없습니다: {args.input}")
        if args.mode == "video" and args.frame_batch < 1:
            raise ValueError("--frame-batch는 1 이상이어야 합니다.")
        args.out_dir = args.out_dir.resolve()
        if args.out_dir.exists() and (not args.out_dir.is_dir() or any(args.out_dir.iterdir())):
            raise ValueError("기존 결과와 섞이지 않도록 비어 있는 --out-dir를 지정하세요.")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        scorer = AnomalyV2(args.anomaly_ckpt, device)
        rows = (video_rows(args, DeepPhysRunner(args, device), scorer) if args.mode == "video"
                else npz_rows(args, scorer))
        args.out_dir.mkdir(parents=True, exist_ok=True)
        report = args.out_dir / "anomaly_scores.csv"
        counts = Counter()
        with report.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
                counts[row["status"]] += 1
        if not counts:
            raise ValueError("평가할 구간이 없습니다. 입력 영상을 확인하세요.")
        print(f"{report}\n임계값={scorer.threshold:.6g} | 이상 후보 {counts['anomaly_candidate']} | "
              f"임계값 이하 {counts['below_threshold']} | 판정 불가 {counts['unscored']}")
    except (ImportError, OSError, ValueError, RuntimeError, KeyError) as exc:
        parser.exit(1, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
