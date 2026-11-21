"""Fine-tune one Chest class; checkpoint selection uses validation only."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from air400_paths import AFTER, DATA, FINETUNE, RUNTIME
os.environ["YOLO_CONFIG_DIR"]=str(RUNTIME/"ultralytics")
os.environ["MPLCONFIGDIR"]=str(RUNTIME/"matplotlib")
os.environ["TORCH_HOME"]=str(RUNTIME/"torch")
import torch
from ultralytics import YOLO, settings


def main():
    protocol=json.loads((FINETUNE/"configs/controlled_protocol.json").read_text(encoding="utf-8"))
    cfg=protocol["training"]
    # All artifacts stay local; disable optional external experiment integrations.
    settings.update({k:False for k in ("wandb","mlflow","clearml","comet","dvc","neptune","raytune","tensorboard","sync","hub") if k in settings})
    font=Path("C:/Windows/Fonts/arial.ttf")
    if font.exists():shutil.copy2(font,RUNTIME/"ultralytics/Arial.ttf")
    target=FINETUNE/"models/chest_yolov8m_best.pt"
    if target.exists():
        print("Trained checkpoint already exists; refusing to overwrite",target,flush=True)
        return
    torch.set_num_threads(4)
    model=YOLO(str(DATA/"weights/yolov8m.pt"))
    result=model.train(data=str(FINETUNE/"configs/chest_dataset.yaml"),
        epochs=cfg["epochs_max"],patience=cfg["patience"],imgsz=cfg["imgsz"],batch=cfg["batch"],
        device=0,workers=0,seed=42,deterministic=True,amp=False,cache=False,optimizer="AdamW",
        lr0=.001,lrf=.01,weight_decay=.0005,warmup_epochs=3,
        degrees=30.,translate=.1,scale=.3,fliplr=.5,flipud=.5,mosaic=.5,mixup=0.,close_mosaic=10,
        project=str(FINETUNE/"runs"),name="chest_v1",exist_ok=False,
        pretrained=True,save=True,plots=True,verbose=False)
    run=Path(model.trainer.save_dir)
    checkpoint=run/"weights/best.pt"
    if not checkpoint.is_file():raise RuntimeError("Training did not produce a validation-selected best checkpoint")
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(checkpoint,target)
    (AFTER/"models").mkdir(parents=True,exist_ok=True)
    shutil.copy2(target,AFTER/"models/chest_yolov8m_best.pt")
    # The respiratory network remains exactly unchanged in the after pipeline.
    shutil.copy2(DATA/"weights/DeepPhys_Deep_Body_best.pth",AFTER/"models/DeepPhys_Deep_Body_best.pth")
    provenance={"checkpoint":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
                "base_checkpoint_sha256":hashlib.sha256((DATA/"weights/yolov8m.pt").read_bytes()).hexdigest(),
                "run_directory":str(run),"selection":"Ultralytics validation fitness: 0.1*mAP50 + 0.9*mAP50-95","test_used_for_selection":False,
                "results":getattr(result,"results_dict",{}),"train_args":vars(model.trainer.args)}
    (FINETUNE/"configs/training_result.json").write_text(json.dumps(provenance,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print("Validation-selected model saved",target,flush=True)


if __name__=="__main__":main()
