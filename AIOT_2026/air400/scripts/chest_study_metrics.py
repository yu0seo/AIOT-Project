"""Timing-preserving waveform metrics; calibrate one common peak rule on val only."""
from __future__ import annotations
import argparse
import itertools
import json

import h5py
import numpy as np
from scipy import signal

from chest_study_core import CONFIG, CONDITION_ROOTS, load_manifest, save_json


def match_events(predicted, reference, tolerance=.5):
    """Order-preserving max-cardinality matching; min error breaks ties."""
    a,b=np.asarray(predicted),np.asarray(reference)
    n,m=len(a),len(b)
    counts=np.zeros((n+1,m+1),dtype=int)
    errors=np.zeros((n+1,m+1),dtype=float)
    decisions=np.zeros((n+1,m+1),dtype=np.int8)
    for i in range(1,n+1):
        for j in range(1,m+1):
            choices=[(counts[i-1,j],-errors[i-1,j],1),(counts[i,j-1],-errors[i,j-1],2)]
            delta=abs(a[i-1]-b[j-1])
            if delta<=tolerance:
                choices.append((counts[i-1,j-1]+1,-errors[i-1,j-1]-delta,3))
            best=max(choices,key=lambda x:(x[0],x[1],x[2]))
            counts[i,j],errors[i,j],decisions[i,j]=best[0],-best[1],best[2]
    pairs=[];i,j=n,m
    while i and j:
        choice=decisions[i,j]
        if choice==3:pairs.append((i-1,j-1));i-=1;j-=1
        elif choice==1:i-=1
        else:j-=1
    return list(reversed(pairs))


def score_signal(times,wave,ref_wave,reference_peaks,rule):
    fs=1/float(np.median(np.diff(times)))
    left,right=3.,len(times)/fs-3.
    valid=(times>=left)&(times<right)
    reference_peaks=np.asarray(reference_peaks)
    true=reference_peaks[(reference_peaks>=left)&(reference_peaks<right)]
    scale=float(np.std(wave[valid]))
    if scale<1e-9:
        predicted=np.array([])
    else:
        indices,_=signal.find_peaks(rule["polarity"]*wave,
            distance=max(1,int(round(rule["minimum_distance_sec"]*fs))),prominence=rule["prominence_std"]*scale)
        predicted=times[indices]
        predicted=predicted[(predicted>=left)&(predicted<right)]
    pairs=match_events(predicted,true,.5)
    tp=len(pairs);fp=len(predicted)-tp;fn=len(true)-tp
    precision=tp/max(1,tp+fp);recall=tp/max(1,tp+fn)
    intervals=[]
    for (i,j),(k,l) in zip(pairs,pairs[1:]):
        if k==i+1 and l==j+1:
            intervals.append(abs((predicted[k]-predicted[i])-(true[l]-true[j])))
    correlation=float(np.corrcoef(wave[valid],ref_wave[valid])[0,1]) if min(np.std(wave[valid]),np.std(ref_wave[valid]))>1e-9 else 0.
    duration=right-left
    return {"tp":tp,"fp":fp,"fn":fn,"precision":precision,"recall":recall,
            "f1":2*tp/max(1,2*tp+fp+fn),"wave_abs_r":abs(correlation),"wave_signed_r":correlation,
            "event_time_mae_sec":float(np.mean([abs(predicted[i]-true[j]) for i,j in pairs])) if pairs else None,
            "interval_mae_sec":float(np.mean(intervals)) if intervals else None,"matched_interval_count":len(intervals),
            "predicted_count":len(predicted),"reference_count":len(true),
            "predicted_bpm_count":len(predicted)/duration*60,"reference_bpm_count":len(true)/duration*60,
            "bpm_count_abs_error":abs(len(predicted)-len(true))/duration*60,
            "predicted_peak_times_sec":predicted.tolist(),"reference_peak_times_sec":true.tolist(),
            "matched_indices":pairs,"evaluation_duration_sec":duration}


def read_row(condition,item,rule):
    root=CONDITION_ROOTS[condition]
    summary_path=root/"metrics/control_v1"/(item["id"]+".json")
    summary=json.loads(summary_path.read_text(encoding="utf-8"))
    with h5py.File(root/summary["waveform_file"],"r") as f:
        time,wave,ref,peaks=f["time_sec"][:],f["respiration"][:],f["reference_detrended"][:],f["annotation_peaks_sec"][:]
        filtered=f["respiration_filtered"][:]
    primary=score_signal(time,wave,ref,peaks,rule)
    bb,aa=signal.butter(1,[.3/(summary["fps"]/2),1./(summary["fps"]/2)],btype="bandpass")
    ref_filtered=signal.filtfilt(bb,aa,ref)
    secondary=score_signal(time,filtered,ref_filtered,peaks,rule)
    return {**summary,"primary_waveform":primary,"secondary_filtered":secondary}


def pool(rows):
    vals=[r["primary_waveform"] for r in rows]
    tp=sum(v["tp"] for v in vals);fp=sum(v["fp"] for v in vals);fn=sum(v["fn"] for v in vals)
    result={"clips":len(rows),"source_groups":sorted({r["source_group"] for r in rows}),"tp":tp,"fp":fp,"fn":fn,
            "pooled_f1":2*tp/max(1,2*tp+fp+fn),"pooled_precision":tp/max(1,tp+fp),"pooled_recall":tp/max(1,tp+fn)}
    for key in ("wave_abs_r","f1","bpm_count_abs_error","event_time_mae_sec","interval_mae_sec"):
        nums=[v[key] for v in vals if v[key] is not None]
        result[key+"_mean"]=float(np.mean(nums)) if nums else None
        result[key+"_median"]=float(np.median(nums)) if nums else None
        result[key+"_valid_clips"]=len(nums)
    for key in ("mean_iou","iou_0_5_success","failure_fraction","crop_iou"):
        result["roi_"+key+"_mean"]=float(np.mean([r["roi_metrics"][key] for r in rows]))
    result["pipeline_sec_mean"]=float(np.mean([r["pipeline_sec"] for r in rows]))
    return result


def calibrate():
    target=CONFIG/"peak_rule.json"
    if target.exists():
        print("Frozen validation peak rule exists",target)
        return
    validation=[s for s in load_manifest()["samples"] if s["split"]=="val"]
    candidates=[]
    for polarity,prominence,distance in itertools.product([1,-1],[.25,.5,.75,1.],[.5,.8,1.]):
        rule={"polarity":polarity,"prominence_std":prominence,"minimum_distance_sec":distance}
        rows=[read_row(c,s,rule) for c in ("A","B") for s in validation]
        stats=pool(rows)
        candidates.append({"rule":rule,"validation":stats})
    best=max(candidates,key=lambda x:(x["validation"]["pooled_f1"],-x["validation"]["bpm_count_abs_error_mean"]))
    save_json(target,{"selection":"A/B validation only; one common rule for all A/B/C test clips",**best,"candidates":candidates})
    print(json.dumps(best,ensure_ascii=False,indent=2))


def verify():
    assert match_events([1.1,2.1,3.1],[1,2,3])==[(0,0),(1,1),(2,2)]
    assert len(match_events([1.1,2.1,2.2,5.1],[1,2,3,5]))==3
    assert match_events([],[])==[]
    assert match_events([1],[2],.5)==[]
    times=np.arange(0,12,.1)
    truth=np.array([3.,5.,7.])
    wave=sum(np.exp(-.5*((times-t)/.15)**2) for t in truth)
    rule={"polarity":1,"minimum_distance_sec":1.,"prominence_std":.25}
    ideal=score_signal(times,wave,wave,truth,rule)
    assert ideal["tp"]==3 and ideal["fp"]==0 and ideal["fn"]==0 and ideal["f1"]==1,ideal
    flat=score_signal(times,np.zeros_like(times),wave,truth,rule)
    assert flat["tp"]==0 and flat["fn"]==3 and flat["f1"]==0 and flat["interval_mae_sec"] is None,flat
    print("Event matcher checks passed")


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--calibrate",action="store_true");p.add_argument("--verify",action="store_true")
    args=p.parse_args()
    if args.verify:verify()
    if args.calibrate:calibrate()
