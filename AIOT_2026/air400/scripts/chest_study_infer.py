"""Run selected fixed-pipeline Chest conditions with resumable per-video outputs."""
import argparse
import gc
import json
from pathlib import Path

from chest_study_core import *


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conditions",nargs="+",choices=["A","B","C"],default=["A","B"])
    parser.add_argument("--split",choices=["train","val","test","all"],default="all")
    parser.add_argument("--limit",type=int)
    args=parser.parse_args()
    manifest=load_manifest()
    boxes=json.loads((CONFIG/"chest_annotations.json").read_text(encoding="utf-8"))["boxes"]
    processor,model=setup()
    detector=None
    if "C" in args.conditions:
        from ultralytics import YOLO
        detector=YOLO(str(FINETUNE/"models/chest_yolov8m_best.pt"))
        detector.predict(np.zeros((180,320,3),np.uint8),imgsz=640,device=0,verbose=False)
    selected=[s for s in manifest["samples"] if args.split=="all" or s["split"]==args.split]
    if args.limit:selected=selected[:args.limit]
    for item in selected:
        frames,info=original_runner.read_video(DATA/item["video"])
        for condition in args.conditions:
            run_condition(condition,item,frames,info,processor,model,boxes[item["id"]],detector)
            gc.collect()
    print("All requested conditions completed",flush=True)


if __name__=="__main__":main()
