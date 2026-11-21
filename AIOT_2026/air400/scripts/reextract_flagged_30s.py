"""Replace only the original 77 flagged windows using the unchanged extraction protocol."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import gc
import json
import subprocess
import time
import traceback

import h5py
import numpy as np
import torch

import extract_oneclass_30s as ex
from download_oneclass_sources import save
from finalize_oneclass_collection import main as finalize

PLAN = ex.OUT / "configs/reextraction_77_plan.json"
STATUS = ex.OUT / "configs/reextraction_77_status.json"


def now():
    return datetime.now().astimezone().isoformat()


def gpu_snapshot():
    result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True)
    used, total, util = map(int, result.stdout.strip().split(","))
    return {"used_mib": used, "total_mib": total, "utilization_percent": util,
            "torch_allocated_mib": torch.cuda.memory_allocated()/2**20,
            "torch_reserved_mib": torch.cuda.memory_reserved()/2**20,
            "torch_peak_allocated_mib": torch.cuda.max_memory_allocated()/2**20,
            "torch_peak_reserved_mib": torch.cuda.max_memory_reserved()/2**20}


def load_plan():
    if PLAN.exists():
        return json.loads(PLAN.read_text(encoding="utf-8"))
    rows = json.loads((ex.OUT/"index.json").read_text(encoding="utf-8"))["samples"]
    selected = [r for r in rows if not r["quality"]["automatic_extraction_ok"]]
    assert len(selected) == 77
    assert all(r["quality"]["sampling_valid_fraction"] == 1 and r["quality"]["body_detection_valid_fraction"] == 0 for r in selected)
    plan = {"created_at": now(), "replacement_policy": "Overwrite existing outputs; retain no old waveform or file backup",
            "protocol_sha256": selected[0]["protocol_sha256"], "target_count": len(selected),
            "targets": [{k: r[k] for k in ("sample_id", "id", "dataset", "subject", "segment_start_sec", "source_video_sha256", "hdf5")} for r in selected],
            "unchanged_hdf5_sha256": {r["sample_id"]: ex.sha(ex.OUT/r["hdf5"]) for r in rows if r not in selected}}
    save(PLAN, plan)
    return plan


def stored_face_update(meta, state):
    """Carry sparse face state through untouched adjacent windows without re-running models."""
    with h5py.File(ex.OUT/meta["hdf5"], "r+") as f:
        n = len(f["face/frame_index"])
        fields = {k: f["face/"+k][:] for k in ("frame_index", "observation_valid", "partial_error", "detected", "confidence", "bbox_xywh", "rotation_retry_deg", "body_valid", "face_center_inside_body")}
        records = [{"frame": int(fields["frame_index"][i]), "execution_valid": bool(fields["observation_valid"][i]),
                    "face_valid": fields["detected"][i] == 1, "partial_error": bool(fields["partial_error"][i]), "confidence": fields["confidence"][i],
                    "face_box": fields["bbox_xywh"][i] if np.isfinite(fields["bbox_xywh"][i]).all() else None,
                    "rotation": fields["rotation_retry_deg"][i], "body_valid": bool(fields["body_valid"][i]),
                    "face_center_inside_body": bool(fields["face_center_inside_body"][i])} for i in range(n)]
        derived = ex.face_arrays(records, meta["segment_start_sec"], state)
        changed = []
        for key in ("absence_duration_sec", "absence_left_censored", "absence_duration_held_grid_sec"):
            if not np.array_equal(f["face/"+key][:], derived[key], equal_nan=True):
                f["face/"+key][:] = derived[key]
                changed.append(key)
    if meta["face_state_at_end"] != state:
        meta["face_state_at_end"] = dict(state)
        save(ex.OUT/"metadata"/meta["dataset"]/meta["subject"]/(meta["sample_id"]+".json"), meta)
    return changed


def main():
    plan = load_plan()
    status = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {
        "started_at": now(), "target_count": len(plan["targets"]), "complete": False, "results": [], "errors": []}
    if status["complete"]:
        print("All 77 replacements already complete", flush=True)
        return
    status.setdefault("previous_attempt_errors", []).extend(status["errors"])
    status["errors"] = []
    done = {r["sample_id"] for r in status["results"]}
    grouped = defaultdict(list)
    for row in plan["targets"]:
        grouped[row["id"]].append(row)
    items = {r["id"]: r for r in ex.sources()}
    processor, model, post, protocol = ex.setup(8)
    assert protocol["protocol_sha256"] == plan["protocol_sha256"]
    status["gpu_at_start"] = gpu_snapshot()
    status["runtime_policy"] = {"source_processes": 1, "flow_threads": 8, "deepphys_batch_frames": 16,
                                "same_protocol": True, "force_recompute": True}
    save(STATUS, status)
    observed = []
    original_detect = ex.detect_roi

    def audited_detect(*args, **kwargs):
        roi, records = original_detect(*args, **kwargs)
        observed.append({"body_execution_errors": sum(bool(r["body_error"]) for r in records),
                         "face_execution_errors": sum(not r["execution_valid"] for r in records),
                         "face_partial_errors": sum(bool(r["partial_error"]) for r in records),
                         "body_success_observations": sum(bool(r["body_valid"]) for r in records)})
        return roi, records

    ex.detect_roi = audited_detect
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for source_id, targets in sorted(grouped.items()):
                if all(r["sample_id"] in done for r in targets):
                    continue
                item = items[source_id]
                print("Decoding", source_id, flush=True)
                frames, pts, info = ex.decode(ex.DATA/item["video"])
                info["source_video_sha256"] = ex.sha(ex.DATA/item["video"])
                assert all(r["source_video_sha256"] == info["source_video_sha256"] for r in targets)
                assert info["native_fps"] >= 9.9
                target_ids = {r["sample_id"] for r in targets}
                source_meta = sorted((ex.OUT/"metadata"/item["dataset"]/item["subject"]).glob(source_id+"_*.json"))
                state = {"missing_start": None, "known_present": False, "left_censored": True}
                for meta_path in source_meta:
                    old = json.loads(meta_path.read_text(encoding="utf-8"))
                    sid = old["sample_id"]
                    if sid not in target_ids or sid in done:
                        changed = stored_face_update(old, state)
                        if changed:
                            status.setdefault("adjacent_face_state_repairs", []).append({"sample_id": sid, "fields": changed})
                        continue
                    with h5py.File(ex.OUT/old["hdf5"], "r") as f:
                        old_wave = f["waveform/filtered"][:]
                        old_body = f["face/body_valid"][:]
                    selected, indices, _, valid = ex.select_window(frames, pts, old["segment_start_sec"])
                    observed.clear()
                    torch.cuda.reset_peak_memory_stats()
                    meta = ex.export_window(item, selected, pts, indices, valid, old["segment_start_sec"], info,
                                            processor, model, post, protocol, pool, 8, state, force=True)
                    assert len(observed) == 1
                    with h5py.File(ex.OUT/meta["hdf5"], "r") as f:
                        wave = f["waveform/filtered"][:]
                        assert wave.shape == (300,) and np.isfinite(wave).all()
                        result = {"sample_id": sid, "completed_at": now(), "quality": meta["quality"],
                                  "old_body_valid_fraction": old["quality"]["body_detection_valid_fraction"],
                                  "body_decisions_identical": bool(np.array_equal(old_body, f["face/body_valid"][:])),
                                  "roi_xywh": meta["roi_body_xywh"], "waveform_max_abs_difference": float(np.max(np.abs(wave-old_wave))),
                                  "summary_all_finite": bool(np.isfinite(f["features/summary"][:]).all()),
                                  "detector_diagnostics": observed[0], "gpu": gpu_snapshot(),
                                  "hdf5_sha256": ex.sha(ex.OUT/meta["hdf5"]), "timing_sec": meta["timing_sec"]}
                    status["results"].append(result)
                    done.add(sid)
                    status["finished_segments"] = len(done)
                    status["updated_at"] = now()
                    save(STATUS, status)
                    print(f"Replaced {len(done)}/77: {sid}; body={meta['quality']['body_detection_valid_fraction']:.3f}; errors={observed[0]}; GPU={result['gpu']['used_mib']}MiB; wave_delta={result['waveform_max_abs_difference']:.6g}", flush=True)
                    del selected, old_wave, wave
                del frames
                gc.collect()
        assert len(done) == plan["target_count"]
        all_meta = json.loads((ex.OUT/"index.json").read_text(encoding="utf-8"))["samples"]
        unexpected = []
        for r in all_meta:
            if r["sample_id"] in plan["unchanged_hdf5_sha256"]:
                if ex.sha(ex.OUT/r["hdf5"]) != plan["unchanged_hdf5_sha256"][r["sample_id"]]:
                    unexpected.append(r["sample_id"])
        repaired = {r["sample_id"] for r in status.get("adjacent_face_state_repairs", [])}
        assert set(unexpected) <= repaired, unexpected
        status["non_target_hdf5_changed"] = unexpected
        # The consolidated bundle still contains the old values until finalize.
        # Compare in memory, retaining only diagnostics rather than old arrays.
        with np.load(ex.OUT/"model_input_candidates.npz", allow_pickle=False) as old_bundle:
            original_rows = {sid: i for i, sid in enumerate(old_bundle["sample_id"])}
            target_paths = {r["sample_id"]: ex.OUT/r["hdf5"] for r in plan["targets"]}
            for result in status["results"]:
                i = original_rows[result["sample_id"]]
                with h5py.File(target_paths[result["sample_id"]], "r") as f:
                    previous_wave = old_bundle["waveform"][i, :, 0].astype(np.float64)
                    current_wave = f["waveform/filtered"][:]
                    result["waveform_correlation_with_previous"] = float(np.corrcoef(previous_wave, current_wave)[0, 1])
                    result["waveform_relative_rmse"] = float(np.sqrt(np.mean((current_wave-previous_wave)**2))/np.std(previous_wave))
                    result["summary_unchanged"] = bool(np.allclose(old_bundle["interval_features"][i], f["features/summary"][:], equal_nan=True, rtol=1e-6, atol=1e-6))
        save(STATUS, status)
        finalize()
        status["summary"] = {
            "replaced": len(done), "body_detection_recovered": sum(r["quality"]["body_detection_valid_fraction"] > 0 for r in status["results"]),
            "still_no_body": sum(r["quality"]["body_detection_valid_fraction"] == 0 for r in status["results"]),
            "body_execution_errors": sum(r["detector_diagnostics"]["body_execution_errors"] for r in status["results"]),
            "face_execution_errors": sum(r["detector_diagnostics"]["face_execution_errors"] for r in status["results"]),
            "face_partial_errors": sum(r["detector_diagnostics"]["face_partial_errors"] for r in status["results"]),
            "largest_waveform_difference": max(r["waveform_max_abs_difference"] for r in status["results"]),
            "minimum_waveform_correlation": min(r["waveform_correlation_with_previous"] for r in status["results"]),
            "maximum_waveform_relative_rmse": max(r["waveform_relative_rmse"] for r in status["results"]),
            "summary_unchanged_count": sum(r["summary_unchanged"] for r in status["results"]),
            "gpu_max_used_mib_after_window": max(r["gpu"]["used_mib"] for r in status["results"]),
            "gpu_max_torch_reserved_mib": max(r["gpu"]["torch_peak_reserved_mib"] for r in status["results"]),
            "dataset_counts": dict(Counter(r["sample_id"].split("_")[0] for r in status["results"]))}
        status["complete"] = True
        status["completed_at"] = now()
        save(STATUS, status)
        (ex.OUT/"재추출결과.txt").write_text("77개 구간 동일 조건 재추출 결과\n\n"+json.dumps(status["summary"], ensure_ascii=False, indent=2)+
            "\n\n기존 결과는 새 결과로 교체했으며 이전 파형 파일은 따로 보관하지 않았습니다.\n상세 기록: configs/reextraction_77_status.json\n", encoding="utf-8")
        print("REEXTRACTION_COMPLETE", json.dumps(status["summary"], ensure_ascii=False), flush=True)
    except BaseException as error:
        status["errors"].append({"time": now(), "type": type(error).__name__, "message": str(error)})
        save(STATUS, status)
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
