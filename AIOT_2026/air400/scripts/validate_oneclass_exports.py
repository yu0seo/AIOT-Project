"""Audit source coverage, time alignment, HDF5 arrays and consolidated candidate inputs."""
from collections import Counter
from datetime import datetime
import json

import h5py
import numpy as np

from air400_paths import DATA, PROJECT
from download_oneclass_sources import save

OUT = PROJECT / "06_단일클래스_학습데이터"


def main():
    index = json.loads((OUT/"index.json").read_text(encoding="utf-8"))
    records = index["samples"]
    identifiers = set()
    flags = Counter()
    protocol = set()
    for r in records:
        identifier = r["sample_id"]
        assert identifier not in identifiers
        identifiers.add(identifier)
        assert (DATA/r["video"]).is_file()
        protocol.add(r["protocol_sha256"])
        with h5py.File(OUT/r["hdf5"], "r") as f:
            assert f.attrs["sample_id"] == identifier
            assert f.attrs["training_label"] == "unreviewed"
            assert f["waveform/filtered"].shape == (300,)
            assert f["waveform/network_output"].shape == (300,)
            assert np.isfinite(f["waveform/filtered"][:]).all()
            np.testing.assert_allclose(f["time/time_sec"][:], np.arange(300)/10, atol=1e-12)
            indices = f["time/source_frame_index"][:]
            error = np.abs(f["time/source_time_sec"][:]-f["time/source_frame_time_sec"][:])
            assert np.all(np.diff(indices) >= 0)
            expected_valid = (error <= .075) & np.r_[True, np.diff(indices) > 0]
            np.testing.assert_array_equal(f["quality/source_sample_valid"][:], expected_valid)
            if not expected_valid.all(): flags["segments_with_timing_or_duplicate_frame_flags"] += 1
            peaks = f["breaths/peak_time_sec"][:]
            np.testing.assert_allclose(f["breaths/interval_sec"][:], np.diff(peaks))
            assert len(f["face/time_sec"]) == 31
            assert int(np.sum(f["face/detection_executed_grid"][:])) == 31
            assert np.isin(f["face/detected"][:], [-1, 0, 1]).all()
            np.testing.assert_array_equal(f["features/summary_valid"][:], np.isfinite(f["features/summary"][:]))
            assert not f["quality/flow_pair_valid"][-1]
            np.testing.assert_array_equal(f["model_inputs/waveform"][:], f["waveform/filtered"][:])
            if np.any(~f["features/summary_valid"][:]): flags["segments_with_unavailable_interval_features"] += 1
        if not r["quality"]["automatic_extraction_ok"]: flags["extraction_quality_flagged"] += 1
        if r["quality"]["body_detection_valid_fraction"] < .5: flags["body_detected_in_under_half_observations_review"] += 1
    assert len(protocol) == 1
    with np.load(OUT/"model_input_candidates.npz", allow_pickle=False) as d:
        assert d["waveform"].shape == (len(records), 300, 1)
        assert d["interval_features"].shape == (len(records), 9)
        assert d["rolling_interval_features"].shape == (len(records), 21, 9)
        np.testing.assert_array_equal(d["rolling_interval_features_valid"], np.isfinite(d["rolling_interval_features"]))
        assert np.all(d["rolling_available_at_sec"] == 30)
        assert d["sample_id"].tolist() == [r["sample_id"] for r in records]
        assert np.isfinite(d["waveform"]).all()
    result = {"checked_at": datetime.now().astimezone().isoformat(), "passed": True, "segments": len(records),
        "waveform_values": len(records)*300, "face_observations": len(records)*31,
        "dataset_segments": dict(Counter(r["dataset"] for r in records)),
        "source_videos": len(set(r["id"] for r in records)), "review_flags": dict(flags),
        "normal_training_labels_assigned": False, "protocol_sha256": next(iter(protocol))}
    save(OUT/"configs/export_validation.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
