"""Compare the four released AIR-400 pipelines on identical Chest crops.

Uses matched published weights/flow algorithms, original normalization, 180-frame
chunks, float32 inference, and the original postprocessor. The frozen-image probe
is an engineering negative control, not an apnea example or clinical evaluation.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import gc
import importlib.util
import json
import logging
import multiprocessing
import os
from pathlib import Path
import platform
import sys
import time

from air400_paths import ROOT, DATA, ARCHIVE, RUNTIME
SOURCE = DATA / "source" / "air-400"
OUT = ARCHIVE / "results"
ROI_MODE = "auto"
# Upper-torso controls selected from video snapshots before model comparisons.
# These rectangles are an engineering ROI control, not clinical annotations.
MANUAL_CHEST = {
    "S01": [133, 68, 40, 40], "S02": [178, 80, 48, 48],
    "S03": [161, 79, 44, 44], "S04": [200, 73, 44, 44],
    "S05": [185, 68, 60, 60], "S06": [185, 78, 60, 60],
    "S07": [165, 82, 60, 60], "S08": [160, 90, 60, 60],
    "S09": [185, 78, 60, 60], "S10": [180, 62, 60, 60],
}
for key, directory in {"YOLO_CONFIG_DIR": "ultralytics", "MPLCONFIGDIR": "matplotlib",
                       "TORCH_HOME": "torch"}.items():
    os.environ[key] = str(RUNTIME / directory)

SPECS = {
    "DeepPhys": ("deep_phys", "deep", "deepphys_deep_infer.yaml"),
    "TSCAN": ("ts_can", "pca", "tscan_pca_infer.yaml"),
    "EfficientPhys": ("efficient_phys", "coarse2fine", "efficientphys_coarse2fine_infer.yaml"),
    "VIRENet": ("vire_net", "coarse2fine", "virenet_coarse2fine_infer.yaml"),
}
COLORS = {"DeepPhys": "#1874d1", "TSCAN": "#d67715", "EfficientPhys": "#16816b", "VIRENet": "#9854b7"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def annotation_peaks(path, clip):
    peaks = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 5 or row[0].startswith("#"):
                continue
            try:
                files = json.loads(row[1])
                if any(int(Path(x).stem) == int(clip) for x in files):
                    peaks.append(float(row[2]))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
    return sorted(set(peaks))


def read_video(path):
    started = time.perf_counter()
    capture = cv2.VideoCapture(str(path))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    size = [int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))]
    frames, timestamps = [], []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        timestamps.append(float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000)
        frames.append(cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (320, 180), interpolation=cv2.INTER_AREA))
    capture.release()
    if not frames or fps <= 0:
        raise ValueError(f"Video decode failed: {path}")
    return np.stack(frames), {"fps": fps, "frames": len(frames), "source_size": size,
                              "duration_sec": len(frames) / fps,
                              "decode_resize_sec": time.perf_counter() - started,
                              "first_pts_sec": timestamps[0], "last_pts_sec": timestamps[-1]}


def make_flow(preprocessor, images, method, pool):
    started = time.perf_counter()
    if method == "coarse2fine":
        params = (.012, .75, 20, 7, 1, 30, 0)
        values = [np.clip(x / 255., 0, 1).astype(np.float64) for x in images]
        inputs = ((values[i], values[i + 1], params) for i in range(len(values) - 1))
        pairs = list(pool.map(flow_bridge.pair_worker, inputs, chunksize=8))
        uv = np.stack(pairs)
        flow = np.stack((uv[..., 0], uv[..., 1], np.sqrt(np.square(uv).sum(axis=-1) + 1e-6)), axis=-1)
        flow = np.concatenate((flow, np.zeros((1, *flow.shape[1:]))), axis=0).astype(np.float32)
    else:
        preprocessor.of_method = method
        flow = preprocessor.run_optical_flow(images)
    return flow, time.perf_counter() - started


def freeze_flow(preprocessor, images, flow, method, start, stop):
    """Exact identical-frame flow is zero; only the exit pair needs recomputing."""
    frozen = images.copy()
    frozen[start:stop] = images[start]
    changed = flow.copy()
    changed[start:stop - 1, ..., :2] = 0
    # Original implementation adds 1e-6 under sqrt for non-padding magnitude.
    changed[start:stop - 1, ..., 2] = .001
    if method == "coarse2fine":
        first = np.ascontiguousarray(images[start] / 255., dtype=np.float64)
        last = np.ascontiguousarray(images[stop] / 255., dtype=np.float64)
        u, v, _ = flow_bridge.coarse2fine_flow(first, last, .012, .75, 20, 7, 1, 30, 0)
        changed[stop - 1] = np.stack((u, v, np.sqrt(u*u + v*v + 1e-6)), axis=-1)
    else:
        preprocessor.of_method = method
        exit_flow = preprocessor.run_optical_flow(np.stack((images[start], images[stop])))
        changed[stop - 1] = exit_flow[0]
    return frozen, changed


def pack_features(preprocessor, images, flow):
    started = time.perf_counter()
    raw = preprocessor._normalize_frames(images.copy())
    normalized_flow = preprocessor._normalize_flow(flow.copy())
    raw, normalized_flow = preprocessor._resize_frames(raw, [96, 96], normalized_flow)
    packed = np.concatenate((normalized_flow, raw), axis=-1).astype(np.float32)
    valid = len(packed) // 180 * 180
    return np.ascontiguousarray(packed[:valid].transpose(0, 3, 1, 2)), time.perf_counter() - started


def predict(model, name, features, timed=True):
    torch.cuda.synchronize()
    started = time.perf_counter()
    predictions = []
    with torch.inference_mode():
        for offset in range(0, len(features), 180):
            batch = torch.from_numpy(features[offset:offset + 180]).to("cuda")
            if name not in ("DeepPhys", "TSCAN"):
                batch = batch[:, :3]
            if name == "EfficientPhys":
                batch = torch.cat((batch, batch[-1:]), dim=0)
            predictions.append(model(batch).reshape(-1))
        torch.cuda.synchronize()
        result = torch.cat(predictions).cpu().numpy()
    if len(result) != len(features) or not np.isfinite(result).all():
        raise ValueError(f"Invalid {name} output: {len(result)} vs {len(features)}")
    return result, time.perf_counter() - started


def postprocess(postprocessor, raw, fs, diff=True):
    started = time.perf_counter()
    processed, bpm = postprocessor.post_process(torch.from_numpy(raw).unsqueeze(0), fs=int(round(fs)),
                                               diff_flag=diff, infant_flag=True,
                                               use_bandpass=True, eval_method="FFT")
    return np.asarray(processed).reshape(-1), float(bpm), time.perf_counter() - started


def correlation(a, b):
    if min(np.std(a), np.std(b)) < 1e-9:
        return 0.
    return float(np.corrcoef(a, b)[0, 1])


def metrics(prediction, reference, fs, pred_bpm, reference_bpm, times):
    # Use interior samples to avoid zero-phase filter boundary artifacts.
    edge = int(round(3 * fs))
    a, b = prediction[edge:-edge], reference[edge:-edge]
    signed = correlation(a, b)
    best = (abs(signed), 0, 1 if signed >= 0 else -1)
    for lag in range(-int(fs), int(fs) + 1):
        aa, bb = (a[lag:], b[:-lag]) if lag > 0 else ((a[:lag], b[-lag:]) if lag < 0 else (a, b))
        r = correlation(aa, bb)
        if abs(r) > best[0]:
            best = (abs(r), lag, 1 if r >= 0 else -1)
    local_errors = []
    for left in np.arange(0, len(prediction) / fs - 17.99, 18):
        i, j = int(round(left * fs)), int(round((left + 18) * fs))
        pr = PostProcessor._calculate_fft_rr(prediction[i:j], int(round(fs)), .3, 1.)
        rr = PostProcessor._calculate_fft_rr(reference[i:j], int(round(fs)), .3, 1.)
        local_errors.append(abs(float(pr) - float(rr)))
    intervals = np.diff(times)
    return {"bpm": pred_bpm, "reference_bpm": reference_bpm,
            "bpm_abs_error": abs(pred_bpm - reference_bpm),
            "wave_abs_r_zero_lag": abs(signed),
            "wave_abs_r_best_lag_1s": best[0], "best_lag_sec": best[1] / fs,
            "polarity_for_visualization": best[2],
            "local_18s_bpm_mae": float(np.mean(local_errors)),
            "manual_annotation_count": len(times),
            "manual_interval_cv": float(np.std(intervals) / np.mean(intervals)) if len(intervals) else None,
            "manual_max_interval_sec": float(intervals.max()) if len(intervals) else None}


def save_hdf(path, raw, wave, reference, fs, metadata):
    with h5py.File(path, "w") as f:
        for name, data in {"time_sec": np.arange(len(wave)) / fs, "respiration": wave,
                           "network_output": raw, "reference_filtered": reference}.items():
            f.create_dataset(name, data=data, compression="gzip")
        for key, value in metadata.items():
            f.attrs[key] = json.dumps(value, ensure_ascii=False) if not isinstance(value, (str, int, float)) else value


def evaluate_clip(item, models, config, processor, postprocessor, pool, freeze=True, tag="native"):
    subject, clip = item["subject"], item["clip"]
    folder = OUT / f"{subject}_{clip}_{tag}"
    summary_path = folder / "summary.json"
    if summary_path.is_file():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    folder.mkdir(parents=True, exist_ok=True)
    frames, info = read_video(DATA / item["video"])
    original_fs = info["fps"]
    native_frame_count = len(frames)
    native_indices = None
    if tag == "30fps_duplicate_control":
        source_count = len(frames) // 180 * 180
        frames = frames[:source_count]
        info["control_source_frames"] = source_count
        info["source_native_frames"] = native_frame_count
        info["source_native_duration_sec"] = info["duration_sec"]
        indices = np.floor(np.arange(int(len(frames) / original_fs * 30)) * original_fs / 30).astype(int)
        frames = frames[np.minimum(indices, len(frames) - 1)]
        native_indices = indices
        info["fps"] = 30.
        info["frames"] = len(frames)
        info["duration_sec"] = len(frames) / 30
        info["last_pts_sec"] = (len(frames)-1) / 30
        info["source_native_fps"] = original_fs
        info["new_temporal_information"] = False
    fs = info["fps"]
    started = time.perf_counter()
    if ROI_MODE == "manual":
        roi, detections = MANUAL_CHEST[subject], []
    else:
        roi, detections = processor.get_roi_box(frames)
    torch.cuda.synchronize()
    roi_time = time.perf_counter() - started
    images = processor.crop_infant_boxes(frames, roi)
    flow_resize_time = 0.
    if ROI_MODE == "manual":
        # PCAFlow crashes on the 40px control in this OpenCV build. Apply the
        # same 96x96 flow-input size to all four manual-control pipelines.
        started = time.perf_counter()
        images, _ = processor._resize_frames(images, [96, 96])
        flow_resize_time = time.perf_counter() - started
    samples = [0, len(frames) // 2, len(frames) - 1]
    montage = []
    for index in samples:
        picture = frames[index].copy()
        x, y, w, h = map(int, roi)
        cv2.rectangle(picture, (x, y), (x + w, y + h), (60, 230, 120), 2)
        cv2.putText(picture, f"{subject}/{clip} t={index/fs:.1f}s", (7, 17), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
        montage.append(picture)
    cv2.imwrite(str(folder / "roi.jpg"), cv2.cvtColor(np.concatenate(montage, axis=1), cv2.COLOR_RGB2BGR))
    with h5py.File(DATA / item["reference"], "r") as f:
        target = np.asarray(f["respiration"][:], dtype=np.float64)
    # Match the original official loader's sample-index interpolation exactly.
    reference_full = np.interp(np.linspace(1, len(target), native_frame_count), np.arange(1, len(target) + 1), target)
    if native_indices is not None:
        reference_full = reference_full[native_indices]
    valid = len(frames) // 180 * 180
    reference, reference_bpm, _ = postprocess(postprocessor, reference_full[:valid], fs, diff=False)
    peaks = annotation_peaks(DATA / item["annotations"], clip)
    peaks = [x for x in peaks if x < valid / fs]
    detection_points = detections[::10]
    quality = {"body_detection_fraction": float(np.mean([not x[3] for x in detection_points])) if detection_points else None,
               "face_detection_fraction": float(np.mean([not x[4] for x in detection_points])) if detection_points else None}
    result = {"subject": subject, "clip": clip, "tag": tag, "video": item["video"],
              "roi_mode": ROI_MODE,
              **info, "valid_frames": valid, "retained_sec": valid / fs,
              "dropped_tail_sec": (len(frames) - valid) / fs,
              "roi_xywh_on_320x180": list(map(int, roi)), "roi_time_sec": roi_time,
              "flow_input_size": list(images.shape[1:3]), "flow_input_resize_sec": flow_resize_time,
              "quality": quality, "models": {}}
    write_json(folder / "preprocessing.json", result)
    flows = {}
    for method in ("deep", "pca", "coarse2fine"):
        print(f"{subject}/{clip} {tag}: {method} flow ({len(images)} frames, crop {images.shape[1:3]})", flush=True)
        flows[method] = make_flow(processor, images, method, pool)
    for name in SPECS:
        model = models[name]
        flow, flow_time = flows[SPECS[name][1]]
        features, packing_time = pack_features(processor, images, flow)
        # Warm-up is excluded from the measured network stage.
        predict(model, name, features[:180])
        trials = [predict(model, name, features) for _ in range(3)]
        raw = trials[-1][0]
        network_time = float(np.median([x[1] for x in trials]))
        wave, bpm, post_time = postprocess(postprocessor, raw, fs)
        stats = metrics(wave, reference, fs, bpm, reference_bpm, peaks)
        stats.update({"flow": SPECS[name][1], "flow_time_sec": flow_time,
                      "packing_time_sec": packing_time, "network_time_sec": network_time,
                      "postprocess_time_sec": post_time,
                      "pipeline_time_sec": info["decode_resize_sec"] + roi_time + flow_resize_time + flow_time + packing_time + network_time + post_time,
                      "network_timing_trials_sec": [x[1] for x in trials]})
        stats["pipeline_realtime_factor"] = stats["pipeline_time_sec"] / (valid / fs)
        save_hdf(folder / f"{name}_pred.hdf5", raw, wave, reference, fs,
                 {"roi": "Chest", "model": name, "flow": stats["flow"], "synthetic_freeze": False})
        if freeze:
            left, right = int(round(24 * fs)), int(round(30 * fs))
            frozen_images, frozen_flow = freeze_flow(processor, images, flow, SPECS[name][1], left, right)
            frozen_features, _ = pack_features(processor, frozen_images, frozen_flow)
            frozen_raw, _ = predict(model, name, frozen_features)
            frozen_wave, frozen_bpm, _ = postprocess(postprocessor, frozen_raw, fs)
            interior = slice(int(25 * fs), int(29 * fs))
            baseline_rms = float(np.sqrt(np.mean(wave[interior] ** 2)))
            frozen_rms = float(np.sqrt(np.mean(frozen_wave[interior] ** 2)))
            stats["freeze_24_30s_rms_ratio"] = frozen_rms / max(baseline_rms, 1e-10)
            stats["freeze_rms_baseline"] = baseline_rms
            stats["freeze_rms_probe"] = frozen_rms
            stats["freeze_bpm"] = frozen_bpm
            save_hdf(folder / f"{name}_freeze_probe.hdf5", frozen_raw, frozen_wave, reference, fs,
                     {"synthetic_freeze": True, "freeze_start_sec": 24, "freeze_stop_sec": 30,
                      "not_a_clinical_apnea_sample": True})
            del frozen_images, frozen_flow, frozen_features
        result["models"][name] = stats
        print(f"  {name}: BPM error={stats['bpm_abs_error']:.2f}, |r|={stats['wave_abs_r_zero_lag']:.3f}, total={stats['pipeline_time_sec']:.2f}s", flush=True)
        write_json(folder / "partial.json", result)
        del features
        gc.collect()
    write_json(summary_path, result)
    return result


def aggregate(results):
    native = [x for x in results if x["tag"] == "native"]
    summaries = {}
    for name in SPECS:
        rows = [x["models"][name] for x in native]
        summaries[name] = {"clips": len(rows)}
        for key in ("bpm_abs_error", "wave_abs_r_zero_lag", "wave_abs_r_best_lag_1s", "local_18s_bpm_mae",
                    "pipeline_time_sec", "network_time_sec", "flow_time_sec", "pipeline_realtime_factor",
                    "freeze_24_30s_rms_ratio"):
            values = [r[key] for r in rows if key in r]
            if values:
                summaries[name][key + "_mean"] = float(np.mean(values))
                summaries[name][key + "_median"] = float(np.median(values))
        summaries[name]["bpm_error_per_clip"] = [r["bpm_abs_error"] for r in rows]
    write_json(OUT / "aggregate.json", {"scope": "exploratory released-checkpoint Chest transfer, not held-out clinical validation",
                                       "models": summaries, "clips": native})
    return summaries


def plots(results, summaries):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    native = [r for r in results if r["tag"] == "native"]
    sheet = np.concatenate([cv2.cvtColor(cv2.imread(str(OUT / f"{r['subject']}_{r['clip']}_native" / 'roi.jpg')), cv2.COLOR_BGR2RGB) for r in native])
    cv2.imwrite(str(OUT / "chest_roi_contact_sheet.jpg"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))
    for r in results:
        folder = OUT / f"{r['subject']}_{r['clip']}_{r['tag']}"
        fig, axes = plt.subplots(4, 1, figsize=(13, 8), sharex=True, constrained_layout=True)
        for ax, name in zip(axes, SPECS):
            with h5py.File(folder / f"{name}_pred.hdf5", "r") as f:
                t, wave, ref = f["time_sec"][:], f["respiration"][:], f["reference_filtered"][:]
            polarity = r["models"][name]["polarity_for_visualization"]
            scale = max(float(np.std(wave)), 1e-9)
            ax.plot(t, ref / max(float(np.std(ref)), 1e-9), color="#a6aab3", lw=1.1, label="manual reference (filtered)")
            ax.plot(t, polarity * wave / scale, color=COLORS[name], lw=1.1, label=name)
            if (folder / f"{name}_freeze_probe.hdf5").is_file():
                with h5py.File(folder / f"{name}_freeze_probe.hdf5", "r") as f:
                    frozen = f["respiration"][:]
                ax.plot(t, polarity * frozen / scale, color="#de3956", lw=1, alpha=.8, label="24-30 s frozen-image probe")
                ax.axvspan(24, 30, color="#ffbe55", alpha=.18)
            m = r["models"][name]
            ax.set_ylabel(name)
            ax.set_title(f"BPM error {m['bpm_abs_error']:.2f} | zero-lag |r| {m['wave_abs_r_zero_lag']:.2f} | lag-fit |r| {m['wave_abs_r_best_lag_1s']:.2f}", fontsize=9, loc="left")
            ax.grid(alpha=.18)
        axes[0].legend(loc="upper right", fontsize=8, ncol=3)
        axes[-1].set_xlabel("Time (s); polarity/std adjusted only for visualization, no lag correction")
        fig.suptitle(f"{r['subject']}/{r['clip']} | Chest | {r['fps']:g} fps | {r['tag']}")
        fig.savefig(folder / "waveform_comparison.png", dpi=140)
        plt.close(fig)
    names = list(SPECS)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    panels = [("bpm_abs_error_mean", "Mean respiration-rate error (BPM)", False),
              ("pipeline_time_sec_mean", "Mean full processing time (s/video)", False),
              ("freeze_24_30s_rms_ratio_median", "Frozen-image residual RMS ratio (median)", True)]
    for ax, (key, title, percent) in zip(axes, panels):
        vals = [summaries[n].get(key, 0) for n in names]
        ax.bar(names, vals, color=[COLORS[n] for n in names])
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="x", rotation=25)
        ax.grid(axis="y", alpha=.2)
        for i, v in enumerate(vals):
            ax.text(i, v, f"{v:.2f}", ha="center", va="bottom", fontsize=9)
    fig.suptitle(f"AIR-400 released checkpoints / Chest / {len(native)} clips — exploratory comparison")
    fig.savefig(OUT / "comparison_summary.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--subjects", nargs="+", help="Subset of the ten preselected folders")
    parser.add_argument("--roi-mode", choices=("auto", "manual"), default="auto")
    parser.add_argument("--no-freeze", action="store_true")
    parser.add_argument("--fps-control", action="store_true", help="Additional duplicated-frame 30fps control on S01; not native 30fps")
    args = parser.parse_args()
    global np, cv2, torch, h5py, PostProcessor, flow_bridge, OUT, ROI_MODE
    ROI_MODE = args.roi_mode
    OUT = ARCHIVE / ("results_manual_chest" if ROI_MODE == "manual" else "results")
    import numpy as np
    import cv2
    import torch
    import h5py
    import yaml
    import air400_flow_bridge as flow_bridge
    sys.modules["pyflow"] = flow_bridge
    OUT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING)
    torch.set_num_threads(4)
    cv2.setNumThreads(4)
    torch.manual_seed(42)
    np.random.seed(42)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    if not torch.cuda.is_available():
        raise RuntimeError("This comparison protocol requires the detected NVIDIA GPU")
    pp_module = load_module("air400_official_preprocessor", SOURCE / "processors" / "pre_processor.py")
    pp_module.tqdm = lambda iterable, **kwargs: iterable
    PostProcessor = load_module("air400_official_postprocessor", SOURCE / "processors" / "post_processor.py").PostProcessor
    assets = json.loads((DATA / "assets.json").read_text(encoding="utf-8"))
    configurations = {}
    models = {}
    model_details = {}
    for name, (module_name, flow, filename) in SPECS.items():
        config = yaml.safe_load((SOURCE / "configs" / "inference" / filename).read_text(encoding="utf-8"))
        split = config["TEST"]["DATA"]
        if isinstance(split, list):
            split = split[0]
        config["TEST"]["DATA"] = split
        split["PREPROCESS"]["INFANT_REGION"] = "Chest"
        config["INFERENCE"]["BATCH_SIZE"] = 1
        configurations[name] = config
        module = load_module("air400_" + module_name, SOURCE / "models" / (module_name + ".py"))
        klass = getattr(module, name)
        kwargs = {"in_channels": 3, "img_size": 96}
        if name != "DeepPhys":
            kwargs["frame_depth"] = 10
        model = klass(**kwargs)
        state = torch.load(DATA / "weights" / assets["models"][name], map_location="cpu", weights_only=True)
        if all(k.startswith("module.") for k in state):
            state = {k.removeprefix("module."): v for k, v in state.items()}
        model.load_state_dict(state, strict=True)
        model.eval().to("cuda")
        models[name] = model
        model_details[name] = {"parameters": sum(p.numel() for p in model.parameters()),
                               "weight_file": assets["models"][name], "flow": flow,
                               "strict_weight_load": True, "configuration": config}
        print(f"Loaded {name}: {model_details[name]['parameters']:,} parameters", flush=True)
    config = configurations["EfficientPhys"]
    processor = pp_module.PreProcessor(config["TEST"]["DATA"]["PREPROCESS"],
                                      str(DATA / "weights" / "yolov8m.pt"), str(DATA / "weights" / "yolov8n-face.pt"))
    if processor.body_detector is None or processor.face_detector is None:
        raise RuntimeError("Official ROI detectors failed to load")
    # Warm GPU detectors once, outside per-video steady-state timing.
    blank = np.zeros((180, 320, 3), dtype=np.uint8)
    processor.detect_body_box(blank)
    processor.detect_face_box(blank)
    torch.cuda.synchronize()
    hardware = {"platform": platform.platform(), "python": sys.version,
                "torch": torch.__version__, "torchvision": __import__("torchvision").__version__,
                "opencv": cv2.__version__, "gpu": torch.cuda.get_device_name(0),
                "gpu_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
                "cpu": os.environ.get("PROCESSOR_IDENTIFIER"), "logical_cpus": os.cpu_count(),
                "torch_threads": 4, "opencv_threads": 4, "coarse2fine_processes": 4,
                "model_batch_frames": 180, "fp32": True,
                "native_source_commit": assets["repositories"][0]["commit"],
                "coarse2fine_source_commit": assets["repositories"][1]["commit"]}
    write_json(OUT / "environment.json", hardware)
    write_json(OUT / "model_details.json", model_details)
    print("Coarse2Fine binding smoke test: " + json.dumps(flow_bridge.smoke_test()), flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn")) as pool:
        samples = [x for x in assets["samples"] if not args.subjects or x["subject"] in args.subjects][:args.limit]
        for item in samples:
            results.append(evaluate_clip(item, models, config, processor, PostProcessor(), pool, not args.no_freeze))
            aggregate(results)
        if args.fps_control:
            results.append(evaluate_clip(assets["samples"][0], models, config, processor, PostProcessor(), pool,
                                         not args.no_freeze, "30fps_duplicate_control"))
    summaries = aggregate(results)
    plots(results, summaries)
    write_json(OUT / "run_results.json", results)
    print(json.dumps(summaries, indent=2), flush=True)


if __name__ == "__main__":
    main()
