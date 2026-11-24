"""Read-only inspection of the installed AIR-400 artifacts; writes only this audit JSON."""
import csv
import hashlib
import importlib.metadata as packages
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import h5py
import numpy as np
import torch

ROOT = Path(r"C:\Users\OHS\air-400")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "models"))
from air400_detect_v2 import AnomalyV2


def sha(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def overlaps(groups):
    names = sorted(groups)
    return {f"{a}/{b}": sorted(groups[a] & groups[b])
            for i, a in enumerate(names) for b in names[i + 1:]}


report = {"inspected_at": datetime.now().astimezone().isoformat(), "root": str(ROOT)}
report["environment"] = {
    "executable": sys.executable, "python": sys.version,
    "cuda_available": torch.cuda.is_available(),
    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "cv2_import_version": cv2.__version__, "cv2_import_path": cv2.__file__,
    "deepflow_available": hasattr(getattr(cv2, "optflow", None), "createOptFlow_DeepFlow"),
    "ffmpeg_path": shutil.which("ffmpeg"), "ffprobe_path": shutil.which("ffprobe"),
    "packages": {},
}
for name in ("torch", "torchvision", "numpy", "scipy", "h5py", "matplotlib", "PyYAML",
             "ultralytics", "opencv-python", "opencv-contrib-python", "supabase"):
    try:
        report["environment"]["packages"][name] = packages.version(name)
    except packages.PackageNotFoundError:
        report["environment"]["packages"][name] = None

files = ["infer.py", "models/deep_phys.py", "processors/pre_processor.py",
         "processors/post_processor.py", "models/air400_npz_anomaly_v2.py",
         "models/air400_detect_v2.py", "extract_training_waveforms.py",
         "normal_pipeline/inference_adapter.py", "configs/inference/deepphys_deep_infer.yaml",
         "checkpoints/DeepPhys_Deep_Body_best.pth", "detectors/yolov8m.pt",
         "detectors/yolov8n-face.pt", "output/ae_results_v2/air400_ae.pt"]
report["file_sha256"] = {name: sha(ROOT / name) for name in files}
source = Path(r"C:\Users\OHS\Downloads\AIR400_BABYCAM_WORK_HANDOFF.md")
report["handoff"] = {"path": str(source), "sha256": sha(source),
                     "bytes": source.stat().st_size,
                     "lines": len(source.read_text(encoding="utf-8-sig").splitlines())}

checkpoint_path = ROOT / "output/ae_results_v2/air400_ae.pt"
checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
report["checkpoint"] = {key: value for key, value in checkpoint.items() if key != "state_dict"}
report["checkpoint"]["state_dict_tensor_count"] = len(checkpoint["state_dict"])

split_rows = rows(ROOT / "output/ae_results_v2/splits.csv")
stored_groups, namespaced_groups, videos, source_hashes = (defaultdict(set) for _ in range(4))
label_counts, fps_counts = Counter(), Counter()
mapping = defaultdict(set)
for row in split_rows:
    meta = json.loads(row["metadata_json"])
    split = row["split"]
    stored_groups[split].add(row["subject_id"])
    namespaced_groups[split].add(meta.get("subject_id", "MISSING"))
    videos[split].add(row["video_id"])
    source_hashes[split].add(meta.get("source_sha256", "MISSING"))
    mapping[row["subject_id"]].add(meta.get("subject_id", "MISSING"))
    label_counts[meta.get("label_status", "MISSING")] += 1
    fps_counts[str(meta.get("source_fps", "MISSING"))] += 1
report["splits"] = {
    "total_windows": len(split_rows), "window_counts": dict(Counter(r["split"] for r in split_rows)),
    "is_normal_counts": dict(Counter(r["is_normal"] for r in split_rows)),
    "valid_input_counts": dict(Counter(r["valid_input"] for r in split_rows)),
    "label_status_counts": dict(label_counts), "source_fps_counts": dict(fps_counts),
    "stored_subjects": {k: sorted(v) for k, v in stored_groups.items()},
    "namespaced_subjects": {k: sorted(v) for k, v in namespaced_groups.items()},
    "merged_independent_subjects": {k: sorted(v) for k, v in mapping.items() if len(v) > 1},
    "stored_subject_overlap": overlaps(stored_groups),
    "namespaced_subject_overlap": overlaps(namespaced_groups),
    "video_overlap": overlaps(videos), "source_hash_overlap": overlaps(source_hashes),
}

run = json.loads((ROOT / "output/training_30s/run.json").read_text(encoding="utf-8-sig"))
report["extractor_run"] = {
    "signature": run["signature"], "stride_sec": run["stride_sec"],
    "window_sec": run["window_sec"], "output_fs": run["output_fs"],
    "deepphys_checkpoint_matches": run["extractor"]["checkpoint_sha256"] ==
        report["file_sha256"]["checkpoints/DeepPhys_Deep_Body_best.pth"],
    "changed_source_files_since_extraction": [name for name, digest in
        run["extractor"]["source_sha256"].items() if sha(ROOT / name) != digest],
}
torch.set_num_threads(1)
scorer = AnomalyV2(checkpoint_path, torch.device("cpu"))
comparisons = {}
for kind in ("valid", "test"):
    saved = rows(ROOT / f"output/ae_results_v2/{kind}_scores.csv")
    diffs, missing = [], []
    for row in saved:
        path = ROOT / "output/training_30s/windows" / row["npz_file"]
        if not path.is_file():
            missing.append(str(path))
            continue
        with np.load(path, allow_pickle=False) as data:
            score = scorer.score(data["x_10hz"], data["pred_rr_bpm"])
        expected = [float(row[k]) for k in ("wave_mse", "bpm_mse", "anomaly_score")]
        diffs.append(max(abs(a - b) for a, b in zip(score, expected)))
    comparisons[kind] = {"csv_rows": len(saved), "rescored": len(diffs), "missing": missing,
                         "max_absolute_difference": max(diffs, default=None),
                         "all_close_at_2e-6": bool(diffs) and max(diffs) <= 2e-6,
                         "saved_anomaly_count": sum(r["is_anomaly"] == "True" for r in saved)}
    if kind == "valid":
        eligible = [float(r["anomaly_score"]) for r in saved
                    if r["is_normal"] == "True" and r["valid_input"] == "True"]
        comparisons[kind]["q99_higher"] = float(np.quantile(eligible, .99, method="higher"))
report["rescore_existing_evaluation_npz"] = comparisons

sample = ROOT / "output/training_30s/windows" / split_rows[0]["npz_file"]
with np.load(sample, allow_pickle=False) as data:
    report["training_npz_sample"] = {"path": str(sample), "arrays": {
        k: {"shape": list(data[k].shape), "dtype": str(data[k].dtype)}
        for k in data.files if k != "metadata_json"},
        "metadata": json.loads(data["metadata_json"].item())}

prior_dir = ROOT / "output/detect_test_retry2"
prior_rows = rows(prior_dir / "anomaly_scores.csv")
report["existing_video_results"] = {"path": str(prior_dir), "rows": prior_rows,
                                    "rescored": []}
for row in prior_rows:
    if not row["npz_file"]:
        continue
    with np.load(prior_dir / row["npz_file"], allow_pickle=False) as data:
        score = scorer.score(data["x_10hz"], data["pred_rr_bpm"])
        report["existing_video_results"]["rescored"].append({
            "window_index": row["window_index"], "score": score[2],
            "difference": abs(score[2] - float(row["anomaly_score"])),
            "arrays": {k: list(data[k].shape) for k in data.files if k != "metadata_json"}})

inventory = {}
for dataset in ("AIR_125", "AIR_400"):
    directory = ROOT / "data" / dataset
    contents = [p for p in directory.rglob("*") if p.is_file() and not p.name.startswith("._")]
    hdf = [p for p in contents if p.suffix.lower() in (".h5", ".hdf5")]
    item = {"file_suffix_counts": dict(Counter(p.suffix.lower() for p in contents)),
            "subject_directories": sorted(p.name for p in directory.iterdir() if p.is_dir())}
    if hdf:
        item["hdf5_sample"] = {"path": str(hdf[0]), "datasets": {}}
        with h5py.File(hdf[0], "r") as data:
            def visit(name, value):
                if isinstance(value, h5py.Dataset):
                    item["hdf5_sample"]["datasets"][name] = {
                        "shape": list(value.shape), "dtype": str(value.dtype)}
            data.visititems(visit)
    inventory[dataset] = item
report["local_data_inventory"] = inventory
target = OUT / "AIR400_HANDOFF_AUDIT_20261124.json"
target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"report": str(target), "checkpoint": report["checkpoint"],
                  "splits": report["splits"], "rescore": comparisons,
                  "extractor_run": report["extractor_run"], "data": inventory},
                 ensure_ascii=False, indent=2))
