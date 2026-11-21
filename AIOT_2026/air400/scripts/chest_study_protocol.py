"""Freeze controlled-study settings before training or waveform comparison."""
from datetime import datetime
import hashlib
import json
from air400_paths import DATA, FINETUNE


def main():
    target=FINETUNE/"configs"/"controlled_protocol.json"
    protocol={"version":"controlled_chest_v1","created_at":datetime.now().astimezone().isoformat(),
              "conditions":{"A":"Original Body/Face-derived Chest ROI","B":"Assistant-reviewed manual upper-thorax ROI",
                            "C":"Fine-tuned YOLOv8m direct Chest detector"},
              "frozen_deepphys_sha256":hashlib.sha256((DATA/"weights/DeepPhys_Deep_Body_best.pth").read_bytes()).hexdigest(),
              "same_for_all":{"native_fps":True,"decode_resize_wh":[320,180],"optical_flow_input_wh":[96,96],
                              "cnn_input_wh":[96,96],"optical_flow":"OpenCV DeepFlow","frame_chunk":180,
                              "normalization":"upstream clip-wide Standardized raw/flow","fp32":True,
                              "roi_aggregation":"same median center / 75th percentile square size, fixed per clip",
                              "roi_detector_frame_step":10,"crop_margin_fraction":0.,
                              "waveform_primary":"integrate network output; smoothing-prior detrend lambda=100; no bandpass",
                              "waveform_secondary":"same signal plus upstream 0.3-1.0Hz first-order zero-phase filter"},
              "training":{"base":"yolov8m.pt","classes":["chest"],"epochs_max":60,"patience":15,
                          "imgsz":640,"batch":4,"workers":0,"seed":42,"amp":False,"device":0,
                          "checkpoint_selection":"best validation mAP50-95; test never used for selection"},
              "metrics":{"primary":["zero-lag absolute waveform correlation","one-to-one annotated-breath F1",
                                    "matched consecutive-breath interval MAE"],
                         "peak_rule_selection":"common polarity/prominence/min-distance chosen on validation A/B only, then frozen for A/B/C test",
                         "peak_match_tolerance_sec":0.5,"edge_trim_sec":3.,
                         "rate":"same peak-count / duration method for prediction and annotation",
                         "roi":["mean IoU incl. zero on failure","IoU>=0.5 success fraction","failure fraction"],
                         "no_test_time_shift_fit":True,"failures_not_dropped":True},
              "limitations":["Assistant labels without independent expert review","Only one conservative source group in held-out test",
                             "Unknown overlap with original DeepPhys training","No abnormal-respiration labels; no clinical event sensitivity claim",
                             "A/C compares ROI modules, not only a weight change","Repeated frames are not independent subjects"]}
    if target.exists():
        old=json.loads(target.read_text(encoding="utf-8"))
        assert old["version"]==protocol["version"],"Protocol exists; use a new study version"
        print("Existing protocol retained",target)
    else:
        target.write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding="utf-8")
        print("Frozen",target)


if __name__=="__main__":
    main()
