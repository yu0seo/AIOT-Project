"""One validation-only recovery candidate; never select using test outputs."""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
import shutil

from air400_paths import AFTER, DATA, FINETUNE, RUNTIME
for key, name in (("YOLO_CONFIG_DIR","ultralytics"),("MPLCONFIGDIR","matplotlib"),("TORCH_HOME","torch")):
    os.environ[key]=str(RUNTIME/name)
import torch
from ultralytics import YOLO, settings


def main():
    config=FINETUNE/"configs"
    original=config/"training_result.json"
    if not original.exists():raise RuntimeError("Wait for the first training run")
    if list((AFTER/"metrics/control_v1").glob("*.json")):
        raise RuntimeError("Recovery must be fixed before any fine-tuned test evaluation")
    first=json.loads(original.read_text(encoding="utf-8"))
    first_record=config/"training_result_chest_v1.json"
    if not first_record.exists():shutil.copy2(original,first_record)
    amendment={"recorded_at":datetime.now().astimezone().isoformat(),
        "reason":"First candidate validation mAP collapsed while training loss decreased; inspect a lower-learning-rate frozen-backbone candidate before any C/test inference.",
        "test_used":False,"additional_candidates_max":1,"selection":"0.1*mAP50 + 0.9*mAP50-95 on validation only across both runs",
        "candidate":{"name":"chest_frozen_v2","freeze":10,"lr0":.0003,"epochs":40,"patience":12,
                     "degrees":20.,"mosaic":.25,"all_other_parameters":"same as chest_v1"},
        "original_protocol_preserved":True}
    amendment_file=config/"training_amendment.json"
    if not amendment_file.exists():amendment_file.write_text(json.dumps(amendment,ensure_ascii=False,indent=2),encoding="utf-8")
    second_record=config/"training_result_chest_frozen_v2.json"
    if second_record.exists():
        second=json.loads(second_record.read_text(encoding="utf-8"))
    else:
        settings.update({k:False for k in ("wandb","mlflow","clearml","comet","dvc","neptune","raytune","tensorboard","sync","hub") if k in settings})
        torch.set_num_threads(4)
        model=YOLO(str(DATA/"weights/yolov8m.pt"))
        result=model.train(data=str(config/"chest_dataset.yaml"),epochs=40,patience=12,imgsz=640,batch=4,
            device=0,workers=0,seed=42,deterministic=True,amp=False,cache=False,optimizer="AdamW",
            lr0=.0003,lrf=.01,weight_decay=.0005,warmup_epochs=3,freeze=10,
            degrees=20.,translate=.1,scale=.3,fliplr=.5,flipud=.5,mosaic=.25,mixup=0.,close_mosaic=10,
            project=str(FINETUNE/"runs"),name="chest_frozen_v2",exist_ok=False,
            pretrained=True,save=True,plots=True,verbose=False)
        run=Path(model.trainer.save_dir)
        second={"checkpoint":str(run/"weights/best.pt"),"run_directory":str(run),
                "selection":amendment["selection"],"test_used_for_selection":False,
                "results":getattr(result,"results_dict",{}),"train_args":vars(model.trainer.args)}
        second_record.write_text(json.dumps(second,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    def fitness(record):
        metrics=record["results"]
        return .1*metrics["metrics/mAP50(B)"]+.9*metrics["metrics/mAP50-95(B)"]
    selected=max([first,second],key=fitness)
    # The first copied checkpoint may be overwritten; the actual run checkpoint is immutable.
    source=Path(selected["run_directory"])/"weights/best.pt"
    target=FINETUNE/"models/chest_yolov8m_best.pt"
    shutil.copy2(source,target)
    shutil.copy2(source,AFTER/"models/chest_yolov8m_best.pt")
    selected={**selected,"checkpoint":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
        "base_checkpoint_sha256":hashlib.sha256((DATA/"weights/yolov8m.pt").read_bytes()).hexdigest(),
        "selection":amendment["selection"],"test_used_for_selection":False,
        "candidate_fitness":{Path(r["run_directory"]).name:fitness(r) for r in (first,second)},
        "training_amendment":"training_amendment.json"}
    original.write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"selected":selected["run_directory"],"candidate_fitness":selected["candidate_fitness"]},indent=2),flush=True)


if __name__=="__main__":main()
