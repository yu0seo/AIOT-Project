"""Compare official Body/Chest order and early resizing; probe edited-frame response."""
from __future__ import annotations
import argparse
from datetime import datetime
import gc
import hashlib
import json
import time

from chest_study_core import (DATA, BEFORE, CONFIG, PRESENTATION, RUNTIME,
    original_runner, setup, save_json, load_manifest, torch, np, cv2, h5py)
from chest_study_metrics import score_signal
from air400_analyze_benchmark import detrend, peaks_csv
from chest_study_prepare import write_image
from scipy.ndimage import uniform_filter1d

OUT=PRESENTATION/"08_Body_Chest_목표비교"
CONDITIONS={"body_official":("Body",False),"chest_official":("Chest",False),
            "body_early96":("Body",True),"chest_early96":("Chest",True)}
IDS=("S01_1","S02_1","S03_1","S07_01")
PROBE_IDS=("S02_1","S07_01")
START,STOP=18.,36.
CORE=(22.,32.)


def sha(path):
    with path.open("rb") as handle:return hashlib.file_digest(handle,"sha256").hexdigest()


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/"protocol.json"
    if path.exists():return json.loads(path.read_text(encoding="utf-8"))
    samples=[s for s in load_manifest()["samples"] if s["id"] in IDS]
    source=DATA/"source/air-400"
    protocol={"created_at":datetime.now().astimezone().isoformat(),"version":"roi_preservation_v1",
        "samples":samples,"selection":"One first numbered clip per conservative source-prefix group; S07 adds RGB/15fps; before new inference",
        "conditions":{k:{"roi":r,"early_resize_96":early} for k,(r,early) in CONDITIONS.items()},
        "probe_ids":list(PROBE_IDS),"probe_interval_sec":[START,STOP],"probe_core_sec":list(CORE),
        "probe_types":{"frozen":"Repeat the interval's first decoded frame", "attenuated":"anchor + 0.25*(frame-anchor), uint8 rounding; pixel-change proxy, not 25% physical displacement"},
        "same_for_all":["original DeepPhys Body weights", "native fps", "official PreProcessor.preprocess and packing", "OpenCV DeepFlow", "180-frame chunks", "same normal-video ROI held for probes", "both official pre-bandpass and bandpass PostProcessor outputs"],
        "metrics":{"normal":"Common previously frozen peak rule; zero-lag correlation against the same unfiltered annotation reference; no per-clip lag/polarity fit",
                   "probe":"RMS/std in 22-32s relative to same pipeline original clip; no independent normalization for plotting",
                   "reduction_threshold":"0.2 of same-time baseline RMS, held >=1s; engineering illustration, not an alarm threshold"},
        "source_hashes":{str(p.relative_to(DATA)):sha(p) for p in [source/"processors/pre_processor.py",source/"processors/post_processor.py",source/"models/deep_phys.py",DATA/"weights/DeepPhys_Deep_Body_best.pth"]},
        "video_hashes":{s["id"]:sha(DATA/s["video"]) for s in samples},
        "limits":["4 clips / 4 conservative filename groups; not verified individual identities", "Unknown overlap with original DeepPhys training", "No real apnea or annotated motion-amplitude ground truth", "Edited input is not physiological apnea or airway obstruction", "Whole-clip standardization and forward-backward postprocessing are offline", "Body-trained checkpoint may favor Body", "No retraining or threshold tuning on these outputs"]}
    save_json(path,protocol)
    save_json(OUT/"peak_rule.json",json.loads((CONFIG/"peak_rule.json").read_text(encoding="utf-8")))
    return protocol


def edit_frames(frames,fps,probe):
    if probe=="normal":return frames
    changed=frames.copy();a,b=round(START*fps),round(STOP*fps)
    anchor=frames[a].astype(np.float32)
    if probe=="frozen":changed[a:b]=frames[a]
    elif probe=="attenuated":changed[a:b]=np.rint(anchor+.25*(frames[a:b].astype(np.float32)-anchor)).clip(0,255).astype(np.uint8)
    else:raise ValueError(probe)
    return changed


def envelope(y,fps):
    return np.sqrt(np.maximum(0,uniform_filter1d(np.square(y),size=max(1,round(fps)),mode="nearest")))


def make_reference(item,t):
    peaks=peaks_csv(DATA/item["annotations"],item["clip"])
    with h5py.File(DATA/item["reference"],"r") as handle:reference=handle["respiration"][:]
    reference=np.interp(t,np.arange(len(reference))/10.,reference)
    return reference,detrend(reference),peaks[peaks<(t[-1]+1/(item["fps"]))]


def run_one(item,condition,probe,frames,info,roi,filled,processor,model,post,protocol):
    root=OUT/"runs"/condition/probe
    meta_path=root/(item["id"]+".json")
    protocol_sha=sha(OUT/"protocol.json")
    if meta_path.exists():
        result=json.loads(meta_path.read_text(encoding="utf-8"))
        assert result["protocol_sha256"]==protocol_sha
        print("Resume",item["id"],condition,probe,flush=True);return
    fps=info["fps"];input_frames=edit_frames(frames,fps,probe)
    _,early=CONDITIONS[condition]
    original_roi=processor.get_roi_box;original_crop=processor.crop_infant_boxes;original_flow=processor.run_optical_flow
    captures={}
    def crop_capture(images,box):
        images=original_crop(images,box)
        if early:images,_=processor._resize_frames(images,[96,96])
        captures["flow_size_wh"]=[images.shape[2],images.shape[1]]
        diffs=np.abs(np.diff(images.astype(np.float32),axis=0)).mean(axis=(1,2,3))
        captures["input_pixel_change"]=np.r_[diffs,0.]
        return images
    def flow_capture(images):
        started=time.perf_counter();flow=original_flow(images)
        captures["flow_sec"]=time.perf_counter()-started
        mag=np.sqrt(flow[...,0]**2+flow[...,1]**2)
        captures["flow_mean_magnitude"]=mag.mean(axis=(1,2))
        captures["flow_p90_magnitude"]=np.percentile(mag,90,axis=(1,2))
        return flow
    # Exact released preprocessing implementation. Only ROI reuse and the named
    # early-resize ablation are injected; normal ROI was computed by released code.
    processor.get_roi_box=lambda images:(roi,filled)
    processor.crop_infant_boxes=crop_capture
    processor.run_optical_flow=flow_capture
    try:
        started=time.perf_counter()
        chunks,_=processor.preprocess(input_frames,np.zeros(len(frames),np.float32),int(round(fps)))
        preprocess_sec=time.perf_counter()-started
    finally:
        processor.get_roi_box=original_roi;processor.crop_infant_boxes=original_crop;processor.run_optical_flow=original_flow
    features=np.ascontiguousarray(chunks.reshape(-1,96,96,6).transpose(0,3,1,2),dtype=np.float32)
    del chunks,input_frames
    original_runner.predict(model,"DeepPhys",features[:180])
    raw,network_sec=original_runner.predict(model,"DeepPhys",features)
    del features
    tensor=torch.from_numpy(raw).unsqueeze(0)
    primary,_=post.post_process(tensor,fs=int(round(fps)),diff_flag=True,infant_flag=True,use_bandpass=False,eval_method="FFT")
    filtered,bpm=post.post_process(tensor,fs=int(round(fps)),diff_flag=True,infant_flag=True,use_bandpass=True,eval_method="FFT")
    primary=np.asarray(primary).reshape(-1);filtered=np.asarray(filtered).reshape(-1)
    n=len(raw);times=np.arange(n)/fps
    reference,reference_dt,peaks=make_reference(item,times)
    root.mkdir(parents=True,exist_ok=True)
    target=root/(item["id"]+".hdf5")
    arrays={"time_sec":times,"network_output":raw,"respiration":primary,"respiration_filtered":filtered,
            "reference":reference,"reference_detrended":reference_dt,"annotation_peaks_sec":peaks,
            **{k:captures[k][:n] for k in ("input_pixel_change","flow_mean_magnitude","flow_p90_magnitude")},
            "envelope_primary":envelope(primary,fps),"envelope_filtered":envelope(filtered,fps)}
    with h5py.File(target,"w") as handle:
        for key,values in arrays.items():
            assert np.isfinite(values).all(),key
            handle.create_dataset(key,data=values,compression="gzip")
        handle.attrs.update(condition=condition,probe=probe,protocol_sha256=protocol_sha,source_video=item["video"])
    meta={"id":item["id"],"source_group":item["source_group"],"condition":condition,"probe":probe,
          "fps":fps,"source_frames":len(frames),"valid_frames":n,"retained_sec":n/fps,
          "roi_xywh":roi,"flow_size_wh":captures["flow_size_wh"],"protocol_sha256":protocol_sha,
          "timing_sec":{"preprocess":preprocess_sec,"flow_included_in_preprocess":captures["flow_sec"],"network":network_sec},
          "official_fft_bpm":float(bpm),"waveform":str(target.relative_to(OUT)).replace("\\","/")}
    if probe=="normal":
        rule=json.loads((OUT/"peak_rule.json").read_text(encoding="utf-8"))["rule"]
        meta["primary_metrics"]=score_signal(times,primary,reference_dt,peaks,rule)
        meta["filtered_metrics_same_reference"]=score_signal(times,filtered,reference_dt,peaks,rule)
        ref_tensor=torch.from_numpy(reference).unsqueeze(0)
        _,ref_bpm=post.post_process(ref_tensor,fs=int(round(fps)),diff_flag=False,infant_flag=True,use_bandpass=True,eval_method="FFT")
        meta["reference_fft_bpm"]=float(ref_bpm);meta["fft_bpm_abs_error"]=abs(float(bpm)-float(ref_bpm))
        if condition=="chest_early96":
            old=BEFORE/"waveforms/control_v1"/(item["id"]+"_pred.hdf5")
            with h5py.File(old,"r") as handle:
                diff=float(np.max(np.abs(raw-handle["network_output"][:])))
            meta["previous_pipeline_network_max_abs_difference"]=diff
            assert diff<1e-5,("Early96 reproduction mismatch",item["id"],diff)
    else:
        with h5py.File(OUT/"runs"/condition/"normal"/(item["id"]+".hdf5"),"r") as handle:
            baseline={k:handle[k][:] for k in arrays if k not in ("annotation_peaks_sec",)}
        core=(times>=CORE[0])&(times<CORE[1])
        stats={}
        for key in ("input_pixel_change","flow_mean_magnitude","network_output","respiration","respiration_filtered"):
            a,b=arrays[key][core],baseline[key][core]
            # Network has arbitrary DC offset; evaluate varying output, not its bias.
            if key in ("network_output","respiration","respiration_filtered"):
                rms_a=float(np.std(a));rms_b=float(np.std(b))
            else:rms_a=float(np.mean(a));rms_b=float(np.mean(b))
            stats[key]={"edited_level":rms_a,"original_level":rms_b,"ratio":rms_a/rms_b if rms_b>1e-10 else None}
        for signal_key,env_key in (("respiration","envelope_primary"),("respiration_filtered","envelope_filtered")):
            level=float(np.sqrt(np.mean(baseline[signal_key][core]**2)))
            event=(times>=START)&(times<STOP)
            low=(arrays[env_key][event]<.2*level).astype(int)
            count=round(fps)
            sustained=np.flatnonzero(np.convolve(low,np.ones(count,dtype=int),mode="valid")>=count)
            stats[signal_key]["sustained_below_20pct_delay_sec"]=float(sustained[0]/fps) if len(sustained) else None
            pre=(times>=14)&(times<16)
            stats[signal_key]["pre_event_change_rms"]=float(np.sqrt(np.mean((arrays[signal_key][pre]-baseline[signal_key][pre])**2)))
        meta["probe_metrics"]=stats
    save_json(meta_path,meta)
    print(f"Finished {item['id']} {condition} {probe} | flow {captures['flow_size_wh']} | {preprocess_sec+network_sec:.1f}s",flush=True)
    gc.collect()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase",choices=("normal","probes","all"),default="all")
    parser.add_argument("--ids",nargs="+")
    args=parser.parse_args()
    protocol=prepare();processor,model=setup()
    source=DATA/"source/air-400"
    post=original_runner.load_module("roi_preservation_official_post",source/"processors/post_processor.py").PostProcessor()
    selected=[s for s in protocol["samples"] if not args.ids or s["id"] in args.ids]
    for item in selected:
        print("Decoding",item["id"],flush=True)
        frames,info=original_runner.read_video(DATA/item["video"])
        for roi_mode in ("Body","Chest"):
            processor.infant_region=roi_mode
            roi,filled=processor.get_roi_box(frames)
            roi=list(map(int,roi))
            preview=cv2.cvtColor(frames[len(frames)//2],cv2.COLOR_RGB2BGR)
            x,y,w,h=roi;cv2.rectangle(preview,(x,y),(x+w,y+h),(50,210,70) if roi_mode=="Body" else (230,150,40),2)
            images=OUT/"roi_images";images.mkdir(exist_ok=True)
            write_image(images/(item["id"]+"_"+roi_mode+".jpg"),preview)
            modes=[c for c,(r,e) in CONDITIONS.items() if r==roi_mode]
            for condition in modes:
                if args.phase in ("normal","all"):
                    run_one(item,condition,"normal",frames,info,roi,filled,processor,model,post,protocol)
                if args.phase in ("probes","all") and item["id"] in PROBE_IDS:
                    for probe in ("frozen","attenuated"):
                        run_one(item,condition,probe,frames,info,roi,filled,processor,model,post,protocol)
        del frames;gc.collect()
    print("Requested ROI comparison phase complete",flush=True)


if __name__=="__main__":main()
