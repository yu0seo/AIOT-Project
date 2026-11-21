"""Create a finite waveform + summary-feature convenience subset, without normal labels."""
import numpy as np

from air400_paths import PROJECT

OUT = PROJECT/"06_단일클래스_학습데이터"


def write_subset():
    with np.load(OUT/"model_input_candidates.npz", allow_pickle=False) as data:
        selected = data["extraction_ok"] & data["interval_features_valid"].all(axis=1)
        indices = np.flatnonzero(selected)
        values = {key: data[key][selected] for key in ("waveform", "interval_features", "interval_features_valid",
                  "sample_id", "source_group", "extraction_ok", "training_label")}
        values.update(feature_names=data["feature_names"], source_index=indices)
        assert np.isfinite(values["waveform"]).all() and np.isfinite(values["interval_features"]).all()
        assert np.all(values["training_label"] == "unreviewed")
        target = OUT/"model_input_candidates_computable.npz"
        np.savez_compressed(target, **values)
        with np.load(target, allow_pickle=False) as check:
            np.testing.assert_array_equal(check["sample_id"], data["sample_id"][indices])
            np.testing.assert_array_equal(check["waveform"], data["waveform"][indices])
            np.testing.assert_array_equal(check["interval_features"], data["interval_features"][indices])
        return {"computable_summary_candidates": len(indices), "other_candidates_flagged": int(np.sum(~selected)),
                "computable_subset": target.name, "computable_subset_is_not_confirmed_normal": True}


if __name__ == "__main__":
    print(write_subset())
