"""Reproducible 10 Hz / 30 s DeepPhys exports; no anomaly model or normal labels are trained."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import gc
import hashlib
import json
import logging
import msvcrt
import os
from pathlib import Path
import sys
import time

from air400_paths import DATA, PROJECT, RUNTIME
for key, name in {"YOLO_CONFIG_DIR": "ultralytics", "MPLCONFIGDIR": "matplotlib", "TORCH_HOME": "torch"}.items():
    os.environ[key] = str(RUNTIME / name)
import cv2
import h5py
import numpy as np
from scipy import signal
import torch
import yaml

import air400_benchmark as upstream
import air400_flow_bridge as bridge
from download_oneclass_sources import save

OUT = PROJECT / "06_단일클래스_학습데이터"
SOURCE = DATA / "source/air-400"
FS, SECONDS, N = 10, 30, 300
VERSION = "deepphys_body_10hz_30s_v1"
SUMMARY_NAMES = ["peak_count", "interior_interval_count", "ibi_mean_sec", "ibi_std_sec", "ibi_cv", "ibi_rmssd_sec", "ibi_max_sec", "estimated_bpm_from_ibi", "time_since_last_peak_sec"]


class FatalCUDAError(BaseException):
    """Bypass the upstream detector's recoverable-error fallback after CUDA failure."""


@contextmanager
def gpu_slot():
    """Keep CPU flow parallel, but serialize CUDA work and release unused caches."""
    path = RUNTIME/"oneclass_gpu.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0"); handle.flush()
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(.05)
        try:
            torch.cuda.empty_cache()
            yield
        finally:
            try:
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def sources():
    inventory = json.loads((OUT / "configs/source_inventory.json").read_text(encoding="utf-8"))
    items = []
    for r in inventory["samples"]:
        annotations = r.get("csv_annotation_files", [])
        # Conservative grouping: identical original annotation prefix stays together.
        prefix = annotations[0].split("_")[0] if annotations else r["folder"]
        items.append({"dataset": "air-400", "subject": r["folder"], "clip": r["clip"],
                      "id": f"air-400_{r['folder']}_{r['clip']}", "video": r["video_relative_path"],
                      "source_group": "air-400_" + prefix, "group_status": "conservative_annotation_prefix_not_verified_identity"})
    external_path = OUT/"configs/air125_external_download_status.json"
    external = json.loads(external_path.read_text(encoding="utf-8"))["clips"] if external_path.exists() else []
    external_map = {(r["subject"], str(r["clip"])): r for r in external}
    for p in sorted((DATA / "datasets/AIR_125").glob("S*/*.mp4")):
        if not p.stem.isdigit():
            continue
        item = {"dataset": "air-125", "subject": p.parent.name, "clip": p.stem,
                      "id": f"air-125_{p.parent.name}_{p.stem}", "video": str(p.relative_to(DATA)),
                      "source_group": "air-125_" + p.parent.name, "group_status": "released_subject_folder"}
        if (p.parent.name, p.stem) in external_map:
            item["external_source"] = external_map[(p.parent.name, p.stem)]
        items.append(item)
    return items


def decode(path):
    capture = cv2.VideoCapture(str(path))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    size = [int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))]
    frames, pts = [], []
    while True:
        ok, image = capture.read()
        if not ok:
            break
        pts.append(capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.)
        frames.append(cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), (320, 180), interpolation=cv2.INTER_AREA))
    capture.release()
    if not frames or not np.isfinite(fps) or fps <= 0:
        raise ValueError("Video could not be decoded")
    pts = np.asarray(pts, np.float64)
    clock = "decoder_pts"
    if not np.isfinite(pts).all() or np.any(np.diff(pts) <= 0):
        pts = np.arange(len(frames), dtype=np.float64) / fps
        clock = "frame_index_over_container_fps_fallback"
    pts -= pts[0]
    dt = float(np.median(np.diff(pts))) if len(pts) > 1 else 1 / fps
    info = {"native_fps": fps, "native_frames": len(frames), "source_size_wh": size,
            "duration_sec": float(pts[-1] + dt), "last_frame_time_sec": float(pts[-1]), "timebase": clock}
    return np.stack(frames), pts, info


def select_window(frames, pts, start):
    target = start + np.arange(N, dtype=np.float64) / FS
    right = np.clip(np.searchsorted(pts, target), 0, len(pts) - 1)
    left = np.maximum(0, right - 1)
    chosen = np.where(np.abs(pts[left] - target) <= np.abs(pts[right] - target), left, right)
    valid = (np.abs(pts[chosen] - target) <= .075) & np.r_[True, np.diff(chosen) > 0]
    return frames[chosen], chosen, target, valid


class DetectorTap:
    """Observe the released detector calls without changing boxes or ROI selection."""
    def __init__(self, detector):
        self.detector = detector
        self.calls = []

    def __call__(self, *args, **kwargs):
        try:
            result = self.detector(*args, **kwargs)
            self.calls.append(result[0])
            return result
        except Exception as error:
            self.calls.append(None)
            if "CUDA" in str(error) or "out of memory" in str(error).lower():
                raise FatalCUDAError(str(error)) from error
            raise


def rotated_box(xyxy, angle, width, height):
    x1, y1, x2, y2 = map(float, xyxy)
    points = []
    for x, y in ((x1, y1), (x1, y2), (x2, y1), (x2, y2)):
        if angle == 0: points.append((x, y))
        elif angle == 90: points.append((y, height - 1 - x))
        elif angle == 180: points.append((width - 1 - x, height - 1 - y))
        else: points.append((width - 1 - y, x))
    x1 = max(0., min(p[0] for p in points)); y1 = max(0., min(p[1] for p in points))
    x2 = min(float(width), max(p[0] for p in points)); y2 = min(float(height), max(p[1] for p in points))
    return [x1, y1, max(0., x2 - x1), max(0., y2 - y1)]


def detect_roi(processor, frames):
    body_detector, face_detector = processor.body_detector, processor.face_detector
    body_tap, face_tap = DetectorTap(body_detector), DetectorTap(face_detector)
    processor.body_detector, processor.face_detector = body_tap, face_tap
    body_method, face_method = processor.detect_body_box, processor.detect_face_box
    records = []

    def body(image):
        body_tap.calls.clear()
        box = body_method(image)
        records.append({"body_box": box, "body_error": not body_tap.calls or body_tap.calls[0] is None})
        return box

    def face(image):
        face_tap.calls.clear()
        box = face_method(image)
        confidence, area, rotation = -1., -1., -1
        selected = None
        for angle, result in zip((0, 90, 180, 270), face_tap.calls):
            if result is None:
                continue
            for b in result.boxes:
                conf = float(b.conf[0])
                candidate = rotated_box(b.xyxy[0].tolist(), angle, image.shape[1], image.shape[0])
                a = candidate[2] * candidate[3]
                if a > 0 and (conf > confidence or (abs(conf - confidence) < 1e-2 and a > area)):
                    confidence, area, rotation, selected = conf, a, angle, candidate
        if box is not None:
            # Validate exported metadata identifies exactly the released function's selected box.
            assert selected is not None and np.allclose(box, selected, atol=1e-3), (box, selected)
        errors = sum(r is None for r in face_tap.calls)
        records[-1].update(face_box=box, confidence=max(0., confidence), rotation=rotation,
                           execution_valid=errors < 4, partial_error=0 < errors < 4,
                           error_count=errors)
        return box

    processor.detect_body_box, processor.detect_face_box = body, face
    try:
        roi, filled = processor.get_roi_box(frames)
    finally:
        processor.detect_body_box, processor.detect_face_box = body_method, face_method
        processor.body_detector, processor.face_detector = body_detector, face_detector
    indices = list(range(0, len(frames), 10))
    if indices[-1] != len(frames) - 1:
        indices.append(len(frames) - 1)
    assert len(indices) == len(records)
    for index, record in zip(indices, records):
        record.update(frame=index, body_valid=not filled[index][3], face_valid=not filled[index][4])
        b, f = record["body_box"], record["face_box"]
        record["face_center_inside_body"] = bool(b and f and b[0] <= f[0]+f[2]/2 <= b[0]+b[2] and b[1] <= f[1]+f[3]/2 <= b[1]+b[3])
    return list(map(int, roi)), records


def flow_chunk(gray):
    method = cv2.optflow.createOptFlow_DeepFlow()
    return [method.calc(a, b, None) for a, b in zip(gray[:-1], gray[1:])]


def compute_flow(processor, cropped, pool, workers):
    gray = processor.convert_to_grayscale(cropped)[..., 0].astype(np.uint8)
    boundaries = np.linspace(0, len(gray)-1, workers+1, dtype=int)
    chunks = [gray[a:b+1] for a, b in zip(boundaries[:-1], boundaries[1:]) if b > a]
    pairs = [pair for group in pool.map(flow_chunk, chunks) for pair in group]
    uv = np.stack(pairs)
    flow = np.stack((uv[..., 0], uv[..., 1], np.sqrt(np.square(uv).sum(axis=-1)+1e-6)), axis=-1)
    return np.concatenate((flow, np.zeros((1, *flow.shape[1:]), np.float32)), axis=0).astype(np.float32)


def pack(processor, cropped, flow):
    appearance = processor._normalize_frames(cropped.copy())
    motion = processor._normalize_flow(flow.copy())
    appearance, motion = processor._resize_frames(appearance, [96, 96], motion)
    return np.ascontiguousarray(np.concatenate((motion, appearance), axis=-1).transpose(0, 3, 1, 2), dtype=np.float32)


def predict(model, packed, batch=16):
    output = []
    with torch.inference_mode():
        for start in range(0, len(packed), batch):
            output.append(model(torch.from_numpy(packed[start:start+batch]).to("cuda")).flatten().cpu().numpy())
    return np.concatenate(output)


def interval_summary(peaks, left, right):
    interior = peaks[(peaks >= left) & (peaks < right)]
    intervals = np.diff(interior)
    count = len(intervals)
    mean = float(np.mean(intervals)) if count else np.nan
    std = float(np.std(intervals, ddof=1)) if count >= 2 else np.nan
    return np.array([len(interior), count, mean, std, std/mean if count >= 2 and mean > 0 else np.nan,
                     float(np.sqrt(np.mean(np.diff(intervals)**2))) if count >= 2 else np.nan,
                     float(np.max(intervals)) if count else np.nan, 60/mean if count and mean > 0 else np.nan,
                     right-interior[-1] if len(interior) else np.nan], dtype=np.float64)


def breath_features(wave):
    scale = float(np.std(wave))
    peaks = signal.find_peaks(wave, distance=FS, prominence=.25*scale)[0] if scale > 1e-12 else np.empty(0, int)
    peak_times = peaks / FS
    # Preserve all events; edge flags mark filter-boundary-sensitive observations.
    interior = (peak_times >= 2) & (peak_times < SECONDS-2)
    interval_valid = interior[:-1] & interior[1:]
    summary = interval_summary(peak_times, 2, 28)
    # The last-event age uses the actual end of the input window.
    summary[-1] = SECONDS-peak_times[-1] if len(peak_times) else np.nan
    rolling_end = np.arange(10, SECONDS+1, dtype=np.float64)
    rolling = np.stack([interval_summary(peak_times, max(2., end-10), min(28., end)) for end in rolling_end])
    return peaks, peak_times, np.diff(peak_times), interval_valid, summary, rolling_end, rolling


def face_arrays(records, start, state):
    sparse = np.array([r["frame"] for r in records], int)
    detected, duration, censored = [], [], []
    for r in records:
        timestamp = start+r["frame"]/FS
        if not r["execution_valid"]:
            detected.append(-1); duration.append(np.nan); censored.append(True)
            state["missing_start"] = None; state["known_present"] = False
            continue
        value = bool(r["face_valid"])
        if value:
            state["missing_start"] = None; state["known_present"] = True
            d, c = 0., False
        else:
            if state["missing_start"] is None:
                state["missing_start"] = timestamp
                state["left_censored"] = not state["known_present"]
            d, c = timestamp-state["missing_start"], state["left_censored"]
        detected.append(int(value)); duration.append(d); censored.append(c)
    held_index = np.searchsorted(sparse, np.arange(N), side="right")-1
    execution = np.zeros(N, bool); execution[sparse] = True
    held_duration = np.asarray(duration)[held_index].copy()
    held_detected = np.asarray(detected, np.int8)[held_index]
    held_duration += np.where(held_detected == 0, (np.arange(N)-sparse[held_index])/FS, 0)
    return {"frame_index": sparse, "time_sec": sparse/FS, "source_time_sec": start+sparse/FS,
            "detected": np.asarray(detected, np.int8), "confidence": np.array([r["confidence"] for r in records]),
            "bbox_xywh": np.array([r["face_box"] if r["face_box"] is not None else [np.nan]*4 for r in records]),
            "rotation_retry_deg": np.array([r["rotation"] for r in records], np.int16),
            "observation_valid": np.array([r["execution_valid"] for r in records], bool),
            "partial_error": np.array([r["partial_error"] for r in records], bool),
            "body_valid": np.array([r["body_valid"] for r in records], bool),
            "face_center_inside_body": np.array([r["face_center_inside_body"] for r in records], bool),
            "absence_duration_sec": np.asarray(duration), "absence_left_censored": np.asarray(censored, bool),
            "detection_executed_grid": execution, "detected_held_grid": held_detected,
            "absence_duration_held_grid_sec": held_duration}


def setup(workers):
    torch.set_num_threads(2); cv2.setNumThreads(1)
    torch.manual_seed(42); np.random.seed(42)
    torch.backends.cudnn.benchmark = False; torch.backends.cudnn.deterministic = True
    if not torch.cuda.is_available():
        raise RuntimeError("Expected available CUDA GPU")
    sys.modules["pyflow"] = bridge
    mod = upstream.load_module("collection_official_preprocessor", SOURCE / "processors/pre_processor.py")
    mod.tqdm = lambda values, **kwargs: values
    config = yaml.safe_load((SOURCE / "configs/inference/deepphys_deep_infer.yaml").read_text(encoding="utf-8"))
    cfg = config["TEST"]["DATA"]["PREPROCESS"]
    cfg.update(INFANT_REGION="Body", DO_CHUNK=False)
    processor = mod.PreProcessor(cfg, str(DATA/"weights/yolov8m.pt"), str(DATA/"weights/yolov8n-face.pt"))
    net = upstream.load_module("collection_official_deepphys", SOURCE / "models/deep_phys.py")
    model = net.DeepPhys(in_channels=3, img_size=96)
    weights = torch.load(DATA/"weights/DeepPhys_Deep_Body_best.pth", map_location="cpu", weights_only=True)
    if all(k.startswith("module.") for k in weights):
        weights = {k[7:]: v for k, v in weights.items()}
    model.load_state_dict(weights, strict=True); model.eval().to("cuda")
    post = upstream.load_module("collection_official_post", SOURCE/"processors/post_processor.py").PostProcessor()
    protocol = {"version": VERSION, "fps": FS, "window_sec": SECONDS, "frames_per_window": N,
        "model": "DeepPhys_Deep_Body_best.pth", "roi": "Official Body; original public detectors, no Chest fine-tuning",
        "preprocess": "10Hz timestamp-nearest frames -> 320x180 -> official Body crop -> DeepFlow at crop size -> official normalization -> 96x96",
        "postprocess": "Official cumsum, lambda=100 detrend, 0.3-1.0Hz Butterworth filtfilt within each 30s window",
        "face_detection_step_frames": 10, "face_detection_last_frame": True,
        "face_role": "Separate observation/alert metadata, not a respiratory model input",
        "face_association": "Geometric body containment only; infant identity not certified",
        "peak_rule": {"polarity": 1, "minimum_distance_sec": 1., "prominence_in_window_std": .25,
                      "status": "Fixed engineering extraction rule; estimated peaks, not true breath labels"},
        "filter_edge_flag_sec": 2, "rolling_feature_window_sec": 10, "rolling_step_sec": 1,
        "training_selection": "All sources remain unreviewed candidates, not automatically labeled normal",
        "scaling": "No downstream scaler fitted; fit on selected training partition only",
        "reference_labels_as_inputs": False, "drop_180_frame_remainder": False,
        "partial_video_tail": "Document tails shorter than 30 seconds; do not pad or loop video",
        "model_time_context": "Whole 30s normalization and noncausal filtfilt; identical window context required in deployment",
        "weights_sha256": {name: sha(DATA/"weights"/name) for name in ("DeepPhys_Deep_Body_best.pth", "yolov8m.pt", "yolov8n-face.pt")},
        "source_sha256": {str(p.relative_to(SOURCE)): sha(p) for p in (SOURCE/"processors/pre_processor.py", SOURCE/"processors/post_processor.py", SOURCE/"models/deep_phys.py")}}
    protocol_hash = hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()
    protocol["protocol_sha256"] = protocol_hash
    path = OUT / "configs/extraction_protocol_30s_v1.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8"))["protocol_sha256"] != protocol_hash:
        raise ValueError("Existing outputs use another protocol; refuse to mix")
    save(path, protocol)
    logging.getLogger().setLevel(logging.ERROR)
    return processor, model, post, protocol


def write_array(handle, key, values):
    values = np.asarray(values)
    handle.create_dataset(key, data=values, compression="gzip" if values.ndim and values.size else None)


def preview(path, times, wave, peaks, face):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(10, 4.5), sharex=True, gridspec_kw={"height_ratios": [3, 1]}, constrained_layout=True)
    axes[0].plot(times, wave, lw=1, color="#1671c5", label="DeepPhys filtered waveform")
    axes[0].scatter(times[peaks], wave[peaks], s=12, color="#db7525", label="Estimated peaks")
    axes[0].axvspan(0, 2, alpha=.1, color="gray"); axes[0].axvspan(28, 30, alpha=.1, color="gray")
    axes[0].legend(fontsize=8); axes[0].set_ylabel("Model output (arbitrary units)")
    axes[1].step(face["time_sec"], face["detected"], where="post", color="#17804b")
    axes[1].set_yticks([-1, 0, 1], ["error", "missing", "detected"]); axes[1].set_xlabel("Time in this 30s window (s)")
    for ax in axes: ax.grid(alpha=.2)
    fig.suptitle(path.stem)
    path.parent.mkdir(parents=True, exist_ok=True); fig.savefig(path, dpi=130); plt.close(fig)


def export_window(item, frames, native_pts, indices, valid, start, info, processor, model, post, protocol, pool, workers, face_state, verify=False, force=False):
    identifier = f"{item['id']}_{start:03d}-{start+SECONDS:03d}"
    folder = Path(item["dataset"]) / item["subject"]
    path = OUT / "hdf5" / folder / (identifier+".hdf5")
    meta_path = OUT / "metadata" / folder / (identifier+".json")
    if meta_path.exists() and path.exists() and not force:
        previous = json.loads(meta_path.read_text(encoding="utf-8"))
        if previous["protocol_sha256"] != protocol["protocol_sha256"]:
            raise ValueError("Resume protocol mismatch")
        face_state.update(previous["face_state_at_end"])
        return previous
    started = time.perf_counter()
    with gpu_slot():
        roi, records = detect_roi(processor, frames)
    roi_time = time.perf_counter()-started
    cropped = processor.crop_infant_boxes(frames, roi)
    flow_start = time.perf_counter()
    flow = compute_flow(processor, cropped, pool, workers)
    flow_time = time.perf_counter()-flow_start
    verification = None
    if verify:
        direct = processor.run_optical_flow(cropped[:5])
        diff = float(np.max(np.abs(direct[:-1]-flow[:4])))
        if diff > 1e-5:
            raise AssertionError(f"Parallel DeepFlow changed upstream result: {diff}")
        with gpu_slot():
            direct_roi, _ = processor.get_roi_box(frames[:21])
            tapped_roi, _ = detect_roi(processor, frames[:21])
        assert direct_roi == tapped_roi, (direct_roi, tapped_roi)
        verification = {"parallel_vs_official_flow_max_abs": diff, "detector_tap_roi_unchanged": True}
    packed = pack(processor, cropped, flow)
    with gpu_slot():
        raw = predict(model, packed)
        if verify:
            other = predict(model, packed, batch=32)
            difference = float(np.max(np.abs(raw-other)))
            assert difference < 1e-5, difference
            verification["batch16_vs32_max_abs"] = difference
    del packed, cropped, flow
    assert len(raw) == N and np.isfinite(raw).all()
    tensor = torch.from_numpy(raw).unsqueeze(0)
    detrended, _ = post.post_process(tensor, fs=FS, diff_flag=True, infant_flag=True, use_bandpass=False)
    filtered, bpm = post.post_process(tensor, fs=FS, diff_flag=True, infant_flag=True, use_bandpass=True)
    filtered, detrended = np.asarray(filtered).flatten(), np.asarray(detrended).flatten()
    peaks, peak_times, intervals, interval_valid, summary, rolling_end, rolling = breath_features(filtered)
    face = face_arrays(records, start, face_state)
    time_sec = np.arange(N, dtype=np.float64)/FS
    body_fraction = float(np.mean(face["body_valid"]))
    quality = {"sampling_valid_fraction": float(np.mean(valid)), "body_detection_valid_fraction": body_fraction,
               "face_detection_fraction": float(np.mean(face["detected"] == 1)), "training_label": "unreviewed",
               "automatic_extraction_ok": bool(np.all(valid) and body_fraction > 0),
               "not_a_normality_label": True}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".hdf5.partial")
    with h5py.File(temporary, "w") as handle:
        handle.attrs.update(sample_id=identifier, dataset=item["dataset"], subject=item["subject"], source_clip=item["clip"],
                            source_video=item["video"], source_group=item["source_group"], source_video_sha256=info["source_video_sha256"],
                            segment_start_sec=start, segment_end_sec=start+SECONDS, sample_rate_hz=FS, native_fps=info["native_fps"],
                            protocol_sha256=protocol["protocol_sha256"], model=protocol["model"], training_label="unreviewed",
                            pre_bandpass_is_archive_only=True, face_is_separate_alert_metadata=True)
        arrays = {"time/time_sec": time_sec, "time/source_time_sec": start+time_sec,
                  "time/available_at_source_time_sec": np.full(N, start+SECONDS, dtype=np.float64),
                  "time/source_frame_index": indices, "time/source_frame_time_sec": native_pts[indices],
                  "quality/source_sample_valid": valid, "quality/filter_interior_mask": (time_sec >= 2)&(time_sec < 28),
                  "quality/flow_pair_valid": np.r_[np.ones(N-1, bool), False], "roi/body_xywh": roi,
                  "waveform/network_output": raw, "waveform/detrended_archive": detrended, "waveform/filtered": filtered,
                  "breaths/peak_frame_index": peaks, "breaths/peak_time_sec": peak_times,
                  "breaths/peak_source_time_sec": start+peak_times, "breaths/interval_sec": intervals,
                  "breaths/interval_end_time_sec": peak_times[1:], "breaths/interval_valid": interval_valid,
                  "features/summary": summary, "features/summary_valid": np.isfinite(summary),
                  "features/rolling_window_start_sec": np.maximum(2., rolling_end-10),
                  "features/rolling_window_end_sec": np.minimum(28., rolling_end),
                  "features/rolling_reference_end_sec": rolling_end,
                  "features/rolling_available_at_sec": np.full(len(rolling_end), SECONDS, dtype=np.float64), "features/rolling": rolling,
                  "features/rolling_valid": np.isfinite(rolling), **{"face/"+k: v for k, v in face.items()}}
        for key, values in arrays.items(): write_array(handle, key, values)
        handle.create_dataset("features/names", data=np.array(SUMMARY_NAMES, dtype=h5py.string_dtype("utf-8")))
        handle["model_inputs/waveform"] = handle["waveform/filtered"]
        handle["model_inputs/interval_features"] = handle["features/summary"]
        handle["model_inputs/interval_features_valid"] = handle["features/summary_valid"]
    temporary.replace(path)
    meta = {**item, "sample_id": identifier, "segment_start_sec": start, "segment_end_sec": start+SECONDS,
            "protocol_sha256": protocol["protocol_sha256"], "source_video_sha256": info["source_video_sha256"],
            "hdf5": str(path.relative_to(OUT)), "source_info": info, "roi_body_xywh": roi,
            "frames": N, "sample_rate_hz": FS, "face_detector_observations": len(records),
            "summary": {k: float(v) if np.isfinite(v) else None for k, v in zip(SUMMARY_NAMES, summary)},
            "summary_ibi_reference_interval_sec": [2, 28], "estimated_fft_bpm": float(bpm), "quality": quality,
            "face_state_at_end": dict(face_state), "timing_sec": {"roi": roi_time, "flow": flow_time, "total": time.perf_counter()-started},
            "verification": verification}
    save(meta_path, meta)
    # First two clips per subject provide a compact visual audit without generating hundreds of redundant plots.
    if int(item["clip"]) <= 2:
        preview(OUT/"previews"/folder/(identifier+".png"), time_sec, filtered, peaks, face)
    print(f"Extracted {identifier}: {N} waveform points, {len(peaks)} peaks, {len(records)} face observations; {meta['timing_sec']['total']:.1f}s", flush=True)
    return meta


def consolidate():
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((OUT/"metadata").glob("*/*/*.json"))]
    save(OUT/"index.json", {"version": VERSION, "count": len(records), "normal_labels_assigned": False, "samples": records})
    if records:
        waves, features, masks, rolling, rolling_masks = [], [], [], [], []
        for record in records:
            with h5py.File(OUT/record["hdf5"], "r") as handle:
                waves.append(handle["model_inputs/waveform"][:]); features.append(handle["features/summary"][:]); masks.append(handle["features/summary_valid"][:])
                rolling.append(handle["features/rolling"][:]); rolling_masks.append(handle["features/rolling_valid"][:])
        np.savez_compressed(OUT/"model_input_candidates.npz", waveform=np.asarray(waves, np.float32)[..., None],
            interval_features=np.asarray(features, np.float32), interval_features_valid=np.asarray(masks, bool),
            rolling_interval_features=np.asarray(rolling, np.float32), rolling_interval_features_valid=np.asarray(rolling_masks, bool),
            rolling_reference_end_sec=np.arange(10, 31, dtype=np.float32), rolling_available_at_sec=np.full(21, 30, np.float32),
            feature_names=np.asarray(SUMMARY_NAMES), sample_id=np.asarray([r["sample_id"] for r in records]),
            source_group=np.asarray([r["source_group"] for r in records]),
            extraction_ok=np.asarray([r["quality"]["automatic_extraction_ok"] for r in records]),
            training_label=np.full(len(records), "unreviewed"))
    return records


def source_export_complete(item, protocol):
    folder = OUT/"metadata"/item["dataset"]/item["subject"]
    records = [json.loads(p.read_text(encoding="utf-8")) for p in folder.glob(item["id"]+"_*.json")]
    if not records:
        return False
    expected = int(np.floor((records[0]["source_info"]["last_frame_time_sec"]+.15)/SECONDS))
    if len(records) != expected or not expected:
        return False
    digest = sha(DATA/item["video"])
    return (sorted(r["segment_start_sec"] for r in records) == list(range(0, expected*SECONDS, SECONDS))
            and all(r["protocol_sha256"] == protocol["protocol_sha256"] and r["source_video_sha256"] == digest
                    and (OUT/r["hdf5"]).is_file() for r in records))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--dataset", choices=("air-400", "air-125"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--no-consolidate", action="store_true", help="Independent dataset worker; final coordinator writes shared index/NPZ")
    parser.add_argument("--skip-complete-sources", action="store_true", help="Hash-check complete sources without decoding them again")
    args = parser.parse_args()
    processor, model, post, protocol = setup(args.workers)
    items = sources()
    if args.dataset: items = [r for r in items if r["dataset"] == args.dataset]
    if args.ids: items = [r for r in items if r["id"] in args.ids]
    if args.limit: items = items[:args.limit]
    if args.skip_complete_sources: items = [r for r in items if not source_export_complete(r, protocol)]
    status_path = OUT/"configs"/("extraction_status_air-125.json" if args.dataset == "air-125" else "extraction_status.json")
    status = {"started_at": datetime.now().astimezone().isoformat(), "source_count": len(items), "finished_sources": 0,
              "segments": 0, "errors": [], "sources": [], "protocol_sha256": protocol["protocol_sha256"], "complete": False}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for item in items:
            try:
                print("Decoding", item["id"], flush=True)
                frames, pts, info = decode(DATA/item["video"])
                info["source_video_sha256"] = sha(DATA/item["video"])
                if info["native_fps"] < 9.9:
                    raise ValueError(f"Native {info['native_fps']} FPS below target 10Hz; no invented frames")
                count = max(0, int(np.floor((pts[-1]+.15)/SECONDS)))
                if not count: raise ValueError("No complete 30s window")
                state = {"missing_start": None, "known_present": False, "left_censored": True}
                for window in range(count):
                    start = window*SECONDS
                    selected, indices, _, valid = select_window(frames, pts, start)
                    export_window(item, selected, pts, indices, valid, start, info, processor, model, post, protocol,
                                  pool, args.workers, state, verify=args.verify and status["segments"] == 0)
                    status["segments"] += 1
                status["sources"].append({"id": item["id"], "segments": count, "duration_sec": info["duration_sec"],
                                          "tail_sec": max(0., info["duration_sec"]-count*SECONDS), "native_fps": info["native_fps"]})
                del frames; gc.collect()
            except FatalCUDAError as error:
                status["errors"].append({"id": item["id"], "error": str(error)})
                save(status_path, status)
                raise
            except Exception as error:
                import traceback
                traceback.print_exc()
                status["errors"].append({"id": item["id"], "error": str(error)})
                if "CUDA" in str(error) or "out of memory" in str(error).lower():
                    save(status_path, status)
                    raise RuntimeError("CUDA context failed; stop immediately and resume in a fresh process") from error
            status["finished_sources"] += 1
            status["updated_at"] = datetime.now().astimezone().isoformat()
            save(status_path, status)
            if status["finished_sources"] % 10 == 0 and not args.no_consolidate:
                consolidate()
            print(f"Sources {status['finished_sources']}/{len(items)}; segments={status['segments']}; errors={len(status['errors'])}", flush=True)
    all_records = consolidate() if not args.no_consolidate else list((OUT/"metadata").glob("*/*/*.json"))
    status["complete"] = status["finished_sources"] == len(items) and not status["errors"]
    status["all_exported_segments"] = len(all_records)
    save(status_path, status)
    print(json.dumps({k: v for k, v in status.items() if k not in ("sources",)}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
