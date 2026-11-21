"""Inspect the official automatic Chest ROI on all ten benchmark videos."""
from __future__ import annotations

import json
import sys

import cv2
import numpy as np
import torch
import yaml

import air400_benchmark as b
import air400_flow_bridge as bridge
from air400_paths import ARCHIVE


def main():
    b.cv2, b.np = cv2, np
    sys.modules["pyflow"] = bridge
    cv2.setNumThreads(4)
    torch.set_num_threads(4)
    module = b.load_module("roi_audit_upstream", b.SOURCE / "processors" / "pre_processor.py")
    module.tqdm = lambda items, **kwargs: items
    config = yaml.safe_load((b.SOURCE / "configs" / "inference" / "efficientphys_coarse2fine_infer.yaml").read_text())
    config = config["TEST"]["DATA"]["PREPROCESS"]
    config["INFANT_REGION"] = "Chest"
    processor = module.PreProcessor(config, str(b.DATA / "weights" / "yolov8m.pt"),
                                    str(b.DATA / "weights" / "yolov8n-face.pt"))
    assets = json.loads((b.DATA / "assets.json").read_text())
    rows, pictures = [], []
    for item in assets["samples"]:
        frames, info = b.read_video(b.DATA / item["video"])
        box, detected = processor.get_roi_box(frames)
        points = detected[::10]
        row = {"subject": item["subject"], "box_xywh": list(map(int,box)),
               "body_detection_fraction": float(np.mean([not x[3] for x in points])),
               "face_detection_fraction": float(np.mean([not x[4] for x in points])),
               "manual_control_box": b.MANUAL_CHEST[item["subject"]],
               "not_anatomical_ground_truth": True}
        rows.append(row)
        pictures_row=[]
        for i in (0, len(frames)//2, len(frames)-1):
            image = frames[i].copy()
            x,y,w,h = map(int,box)
            cv2.rectangle(image,(x,y),(x+w,y+h),(70,235,110),2)
            x,y,w,h = row["manual_control_box"]
            cv2.rectangle(image,(x,y),(x+w,y+h),(255,170,40),1)
            cv2.putText(image,item["subject"]+f" {i/info['fps']:.1f}s",(6,17),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1)
            pictures_row.append(image)
        pictures.append(np.concatenate(pictures_row,axis=1))
        print(json.dumps(row),flush=True)
    output=ARCHIVE/"report"
    b.write_json(output/"roi_audit.json",{"official_chest_green":True,"manual_control_orange":True,"clips":rows})
    cv2.imwrite(str(output/"automatic_roi_audit.jpg"),cv2.cvtColor(np.concatenate(pictures),cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    main()
