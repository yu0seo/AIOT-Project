"""Fixed DeepPhys pipeline for the controlled A/B/C Chest experiment."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

from air400_paths import AFTER, BEFORE, DATA, FINETUNE, PRESENTATION, PROJECT, RUNTIME
for key, folder in {"YOLO_CONFIG_DIR":"ultralytics", "MPLCONFIGDIR":"matplotlib", "TORCH_HOME":"torch"}.items():
    os.environ[key]=str(RUNTIME/folder)
import cv2
import h5py
import numpy as np
import torch
import yaml
from scipy import signal

import air400_benchmark as original_runner
import air400_flow_bridge as bridge
from air400_analyze_benchmark import detrend, peaks_csv
from chest_study_prepare import write_image

CONFIG=FINETUNE/"configs"
CONDITION_ROOTS={"A":BEFORE,"B":FINETUNE/"manual_control","C":AFTER}
COLORS={"A":(65,210,90),"B":(40,180,250),"C":(255,130,50)}  # BGR


def save_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+".partial")
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    temporary.replace(path)


def load_manifest():
    return json.loads((CONFIG/"study_manifest.json").read_text(encoding="utf-8"))


def square_box(box):
    x,y,w,h=map(float,box)
    side=min(max(w,h),180.)
    cx,cy=x+w/2,y+h/2
    return [int(round(np.clip(cx-side/2,0,320-side))),int(round(np.clip(cy-side/2,0,180-side))),int(round(side)),int(round(side))]


def iou(a,b):
    ax,ay,aw,ah=map(float,a);bx,by,bw,bh=map(float,b)
    overlap=max(0,min(ax+aw,bx+bw)-max(ax,bx))*max(0,min(ay+ah,by+bh)-max(ay,by))
    return float(overlap/max(aw*ah+bw*bh-overlap,1e-12))


def setup():
    torch.set_num_threads(4);cv2.setNumThreads(4)
    torch.manual_seed(42);np.random.seed(42)
    torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU required for this fixed timing protocol")
    sys.modules["pyflow"]=bridge
    source=DATA/"source/air-400"
    mod=original_runner.load_module("controlled_official_preprocessor",source/"processors/pre_processor.py")
    mod.tqdm=lambda items,**kwargs:items
    config=yaml.safe_load((source/"configs/inference/deepphys_deep_infer.yaml").read_text(encoding="utf-8"))
    cfg=config["TEST"]["DATA"]["PREPROCESS"]
    cfg["INFANT_REGION"]="Chest"
    processor=mod.PreProcessor(cfg,str(DATA/"weights/yolov8m.pt"),str(DATA/"weights/yolov8n-face.pt"))
    model_mod=original_runner.load_module("controlled_deepphys",source/"models/deep_phys.py")
    model=model_mod.DeepPhys(in_channels=3,img_size=96)
    state=torch.load(DATA/"weights/DeepPhys_Deep_Body_best.pth",map_location="cpu",weights_only=True)
    if all(k.startswith("module.") for k in state):state={k[7:]:v for k,v in state.items()}
    model.load_state_dict(state,strict=True);model.eval().to("cuda")
    original_runner.np=np;original_runner.cv2=cv2;original_runner.torch=torch;original_runner.h5py=h5py
    # Warm detectors outside per-clip stage timing.
    processor.detect_body_box(np.zeros((180,320,3),np.uint8));processor.detect_face_box(np.zeros((180,320,3),np.uint8))
    torch.cuda.synchronize()
    return processor,model


def compute_roi(condition,frames,processor,label_box,detector=None):
    started=time.perf_counter();n=len(frames)
    indices=list(range(0,n,10))
    if indices[-1]!=n-1:indices.append(n-1)
    detections=[]
    if condition=="A":
        roi,filled=processor.get_roi_box(frames)
        for idx in indices:
            body,face,chest,body_bad,face_bad,chest_bad=filled[idx]
            detections.append({"frame":idx,"box":list(map(float,chest)),"valid":not chest_bad,
                               "body_valid":not body_bad,"face_valid":not face_bad,"confidence":None})
    elif condition=="B":
        detections=[{"frame":idx,"box":list(label_box),"valid":True,"confidence":None} for idx in indices]
        roi=processor._get_best_box([square_box(label_box) for idx in indices],320,180,square=True)
    else:
        for idx in indices:
            # Same RGB numpy input convention as the released preprocessor.
            result=detector.predict(frames[idx],imgsz=640,conf=.25,device=0,verbose=False)[0]
            best=None
            if len(result.boxes):
                k=int(result.boxes.conf.argmax())
                x1,y1,x2,y2=result.boxes.xyxy[k].detach().cpu().numpy().tolist()
                best={"frame":idx,"box":[x1,y1,x2-x1,y2-y1],"valid":True,"confidence":float(result.boxes.conf[k])}
            detections.append(best or {"frame":idx,"box":[70,0,180,180],"valid":False,"confidence":0.})
        candidates=[square_box(d["box"]) for d in detections if d["valid"]]
        roi=processor._get_best_box(candidates,320,180,square=True)
    torch.cuda.synchronize()
    return list(map(int,roi)),detections,time.perf_counter()-started


def run_condition(condition,item,frames,info,processor,model,label_box,detector=None):
    root=CONDITION_ROOTS[condition]
    summary_path=root/"metrics/control_v1"/(item["id"]+".json")
    signature=hashlib.sha256((CONFIG/"controlled_protocol.json").read_bytes()+(CONFIG/"chest_annotations.json").read_bytes()).hexdigest()
    checkpoint_sha=hashlib.sha256((FINETUNE/"models/chest_yolov8m_best.pt").read_bytes()).hexdigest() if condition=="C" else None
    if summary_path.exists():
        old=json.loads(summary_path.read_text(encoding="utf-8"))
        if old["protocol_annotation_signature"]!=signature:raise RuntimeError("Cached study uses different labels/protocol")
        if condition=="C" and old.get("chest_checkpoint_sha256")!=checkpoint_sha:raise RuntimeError("Cached C output uses a different detector checkpoint")
        print(f"Resume {condition} {item['id']}",flush=True)
        return old
    roi,detections,roi_sec=compute_roi(condition,frames,processor,label_box,detector)
    started=time.perf_counter()
    cropped=processor.crop_infant_boxes(frames,roi)
    cropped,_=processor._resize_frames(cropped,[96,96])
    crop_sec=time.perf_counter()-started
    processor.of_method="deep"
    started=time.perf_counter();flow=processor.run_optical_flow(cropped);flow_sec=time.perf_counter()-started
    motion=np.median(np.sqrt(flow[...,0]**2+flow[...,1]**2),axis=(1,2))
    packed,pack_sec=original_runner.pack_features(processor,cropped,flow)
    original_runner.predict(model,"DeepPhys",packed[:180])
    trials=[original_runner.predict(model,"DeepPhys",packed) for _ in range(3)]
    raw=trials[-1][0];network_sec=float(np.median([t[1] for t in trials]))
    n=len(raw);fps=info["fps"]
    started=time.perf_counter()
    waveform=detrend(np.cumsum(raw))
    bb,aa=signal.butter(1,[.3/(fps/2),1./(fps/2)],btype="bandpass")
    filtered=signal.filtfilt(bb,aa,waveform)
    post_sec=time.perf_counter()-started
    peaks=peaks_csv(DATA/item["annotations"],item["clip"])
    peaks=peaks[peaks<n/fps]
    with h5py.File(DATA/item["reference"],"r") as source:
        ref=source["respiration"][:]
    ref_peak_time=signal.find_peaks(ref,prominence=.1)[0]/10.
    all_peaks=peaks_csv(DATA/item["annotations"],item["clip"])
    timebase_error=max(float(np.min(np.abs(all_peaks-p))) for p in ref_peak_time)
    if timebase_error>.16:raise RuntimeError(f"Reference timebase check failed for {item['id']}: {timebase_error}")
    times=np.arange(n)/fps
    ref=np.interp(times,np.arange(len(ref))/10.,ref)
    ref_dt=detrend(ref)
    output=root/"waveforms/control_v1"/(item["id"]+"_pred.hdf5")
    output.parent.mkdir(parents=True,exist_ok=True)
    with h5py.File(output,"w") as handle:
        for name,values in {"time_sec":times,"respiration":waveform,"respiration_filtered":filtered,"network_output":raw,
                            "motion_level_raw_flow":motion[:n],"reference":ref,"reference_detrended":ref_dt,
                            "annotation_peaks_sec":peaks}.items():
            assert np.isfinite(values).all(),name
            handle.create_dataset(name,data=values,compression="gzip")
        handle.attrs.update(condition=condition,model="DeepPhys",source_video=item["video"],roi=json.dumps(roi),
                            primary_signal="integrated/detrended before bandpass",fine_tuned=condition=="C")
        if checkpoint_sha:handle.attrs["chest_checkpoint_sha256"]=checkpoint_sha
    overlap=[iou(d["box"],label_box) if d["valid"] else 0. for d in detections]
    result={"id":item["id"],"condition":condition,"split":item["split"],"source_group":item["source_group"],
            "protocol_annotation_signature":signature,"chest_checkpoint_sha256":checkpoint_sha,"fps":fps,"frames":len(frames),"valid_frames":n,"retained_sec":n/fps,
            "roi_xywh":roi,"manual_box_xywh":label_box,"flow_input_wh":[96,96],"detections":detections,
            "roi_metrics":{"mean_iou":float(np.mean(overlap)),"iou_0_5_success":float(np.mean(np.array(overlap)>=.5)),
                           "failure_fraction":float(np.mean([not d["valid"] for d in detections])),
                           "crop_iou":iou(roi,square_box(label_box))},
            "timing_sec":{"decode":info["decode_resize_sec"],"roi":roi_sec,"crop":crop_sec,"flow":flow_sec,
                          "pack":pack_sec,"network":network_sec,"postprocess":post_sec},
            "reference_timebase_max_error_sec":timebase_error,"waveform_file":str(output.relative_to(root)).replace("\\","/")}
    result["pipeline_sec"]=sum(result["timing_sec"].values())
    samples=[]
    for idx in (0,len(frames)//2,len(frames)-1):
        image=cv2.cvtColor(frames[idx],cv2.COLOR_RGB2BGR)
        x,y,w,h=roi;cv2.rectangle(image,(x,y),(x+w,y+h),COLORS[condition],2)
        x,y,w,h=map(int,label_box);cv2.rectangle(image,(x,y),(x+w,y+h),(0,220,255),1)
        cv2.putText(image,f"{condition} {item['id']} t={idx/fps:.1f}s",(5,15),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,255,255),1)
        samples.append(image)
    image_path=root/"bounding_boxes/control_v1"/(item["id"]+"_roi.jpg")
    image_path.parent.mkdir(parents=True,exist_ok=True);write_image(image_path,np.concatenate(samples,axis=1))
    save_json(summary_path,result)
    print(f"Finished {condition} {item['id']} | IoU={result['roi_metrics']['mean_iou']:.3f} | processing={result['pipeline_sec']:.1f}s",flush=True)
    return result
