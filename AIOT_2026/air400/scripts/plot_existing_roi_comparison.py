"""Plot the saved automatic/manual ROI pilot; does not rerun video inference."""
import json
import os

from air400_paths import ARCHIVE, PRESENTATION, PROJECT, RUNTIME

os.environ["MPLCONFIGDIR"] = str(RUNTIME / "matplotlib")
import h5py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    settings = [("Automatic Chest ROI (green)", "results", "#239247"),
                ("Manual upper-torso ROI (orange)", "results_manual_chest", "#da961c")]
    rows, curves = [], []
    for label, directory, color in settings:
        folder = ARCHIVE / directory / "S01_1_native"
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        with h5py.File(folder / "DeepPhys_pred.hdf5", "r") as handle:
            t, wave = handle["time_sec"][:], handle["respiration"][:]
        assert np.isfinite(wave).all()
        box = summary["roi_xywh_on_320x180"]
        rows.append({"condition": label, "source_hdf5": (folder / "DeepPhys_pred.hdf5").relative_to(PROJECT).as_posix(),
                     "roi_xywh_on_320x180": box, "flow_input_hw": summary.get("flow_input_size", [box[3], box[2]]),
                     "fps": summary["fps"], "samples": len(wave), "retained_sec": summary["retained_sec"]})
        curves.append((t, wave, color))
    assert np.array_equal(curves[0][0], curves[1][0]), "Cannot compare different time axes"
    fig, axes = plt.subplots(2, 1, figsize=(12, 5.5), sharex=True, sharey=True)
    for ax, row, (t, wave, color) in zip(axes, rows, curves):
        ax.plot(t, wave, color=color, linewidth=1.2)
        ax.set_title(f"{row['condition']} | crop {row['roi_xywh_on_320x180'][2:]} | flow input {row['flow_input_hw']}",
                     fontsize=10, loc="left")
        ax.set_ylabel("Predicted waveform\n(arbitrary model units)")
        ax.grid(alpha=.2)
    axes[-1].set_xlabel("Video time (seconds)")
    fig.suptitle("Existing DeepPhys outputs - same S01/1 video, same pretrained network", fontsize=13)
    fig.text(.5, .015, "Exploratory only: optical-flow input sizes differ. No fine-tuning; no time shifts or amplitude rescaling.",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .045, 1, .94))
    output = PRESENTATION / "90_기존실험참고"
    output.mkdir(parents=True, exist_ok=True)
    png = output / "S01_자동영역_vs_수동영역_기존파형.png"
    fig.savefig(png, dpi=150)
    plt.close(fig)
    metadata = {"scope": "Existing exploratory ROI comparison, not a fine-tuning comparison",
                "confound": "Automatic flow calculated on 180x180 crop; manual crop resized to 96x96 before flow",
                "conditions": rows}
    (output / "S01_자동영역_vs_수동영역_비교조건.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(png)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
