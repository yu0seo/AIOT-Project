"""Report ROI/resize timing and engineering motion-preservation results honestly."""
from __future__ import annotations
from datetime import datetime
import csv
import hashlib
import html
import json
import os
import shutil
from pathlib import Path

from roi_preservation_compare import OUT, CONDITIONS, IDS, PROBE_IDS, START, STOP, CORE, sha
from air400_paths import DATA, PROJECT, RUNTIME
from chest_study_metrics import score_signal
os.environ["MPLCONFIGDIR"]=str(RUNTIME/"matplotlib")
import numpy as np
import h5py
import cv2
import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager
import matplotlib.pyplot as plt

NAMES={"body_official":"Body · 공식 순서","chest_official":"Chest · 공식 순서",
       "body_early96":"Body · 96 선축소","chest_early96":"Chest · 기존 96 선축소"}
COLORS={"body_official":"#245dba","chest_official":"#da7818","body_early96":"#65a3d4","chest_early96":"#9b5b95"}
font=Path("C:/Windows/Fonts/malgun.ttf")
if font.exists():
    font_manager.fontManager.addfont(str(font))
    plt.rcParams["font.family"]=font_manager.FontProperties(fname=str(font)).get_name()
plt.rcParams["axes.unicode_minus"]=False


def read(path):return json.loads(path.read_text(encoding="utf-8"))
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
def fmt(x,n=3):return "—" if x is None else f"{float(x):.{n}f}"


def aggregate(rows,field):
    values=[r[field] for r in rows]
    tp=sum(v["tp"] for v in values);fp=sum(v["fp"] for v in values);fn=sum(v["fn"] for v in values)
    result={"clips":len(values),"tp":tp,"fp":fp,"fn":fn,"f1":2*tp/max(1,2*tp+fp+fn),"recall":tp/max(1,tp+fn)}
    for key in ("wave_abs_r","event_time_mae_sec","interval_mae_sec","bpm_count_abs_error"):
        valid=[v[key] for v in values if v[key] is not None]
        result[key]=float(np.mean(valid)) if valid else None
        result[key+"_valid_clips"]=len(valid)
    return result


def signals(row):
    with h5py.File(OUT/row["waveform"],"r") as f:return {key:f[key][:] for key in f}


def normal_figure(item,rows,calibrated=False):
    fig,axes=plt.subplots(2,2,figsize=(13,7),sharex=True,sharey=True,layout="constrained")
    baseline=signals(next(r for r in rows if r["condition"]=="body_official"))
    scale=max(np.std(baseline["respiration_filtered"]),1e-9)
    for ax,condition in zip(axes.flat,CONDITIONS):
        row=next(r for r in rows if r["condition"]==condition);data=signals(row)
        t=data["time_sec"];reference=data["reference_detrended"]
        ax.plot(t,reference/max(np.std(reference),1e-9),color="#a1a6ae",lw=.9,label="공개 호흡점 기준")
        polarity=row["calibrated_rule"]["polarity"] if calibrated else -1
        ax.plot(t,polarity*data["respiration_filtered"]/scale,color=COLORS[condition],lw=1,label=NAMES[condition])
        m=row["filtered_metrics_calibrated"] if calibrated else row["filtered_metrics_same_reference"]
        idx=np.minimum(len(t)-1,np.rint(np.asarray(m["predicted_peak_times_sec"])*row["fps"]).astype(int))
        ax.scatter(t[idx],polarity*data["respiration_filtered"][idx]/scale,s=10,color=COLORS[condition],zorder=3)
        for peak in data["annotation_peaks_sec"]:ax.axvline(peak,color="#9ca4ae",alpha=.13,lw=.7)
        ax.set_title(f"{NAMES[condition]} | F1 {m['f1']:.3f} | |r| {m['wave_abs_r']:.3f}",fontsize=10,loc="left")
        ax.grid(alpha=.15)
    axes[0,0].legend(fontsize=8,loc="upper right")
    for ax in axes[-1]:ax.set_xlabel("영상 시각 (초)")
    for ax in axes[:,0]:ax.set_ylabel("공통 표시 크기 · 모델 단위")
    fig.suptitle(item+" · 같은 DeepPhys / 공식 필터 / "+("검증에서 부호 고정" if calibrated else "사전 공통 부호 -1")+" / 시간 이동 없음",fontsize=12)
    fig.get_layout_engine().set(rect=(0,.035,1,.95))
    fig.text(.5,.007,"예측은 Body 공식 조건의 같은 표준편차로 표시 · 회색은 실측 변위가 아닌 주석 신호 · 한 클립의 개선만으로 채택하지 않음",ha="center",fontsize=8)
    target=OUT/"plots"/(item+("_calibrated_normal.png" if calibrated else "_normal.png"));target.parent.mkdir(exist_ok=True)
    fig.savefig(target,dpi=145);plt.close(fig)
    return target


def probe_figure(item,probe,normal,edited,current_comparison=False):
    fig,axes=plt.subplots(2,2,figsize=(12.5,7),sharex=True,layout="constrained")
    pair=("body_official","chest_early96") if current_comparison else ("body_official","chest_official")
    for col,condition in enumerate(pair):
        row=next(r for r in edited if r["condition"]==condition)
        baseline_row=next(r for r in normal if r["condition"]==condition)
        baseline=signals(baseline_row);data=signals(row)
        polarity=baseline_row["calibrated_rule"]["polarity"]
        t=data["time_sec"]
        for ax,key in zip(axes[:,col],("respiration","respiration_filtered")):
            scale=max(np.std(baseline[key][(t>=3)&(t<51)]),1e-9)
            ax.plot(t,polarity*baseline[key]/scale,color="#a2a8b0",lw=.8,label="원영상 모델 출력")
            ax.plot(t,polarity*data[key]/scale,color=COLORS[condition],lw=1,label="조작 영상 모델 출력")
            ax.axvspan(START,STOP,color="#ffb94e",alpha=.17,label="프레임 조작 구간")
            ratio=row["probe_metrics"][key]["ratio"]
            title="공식 추세 제거 후 · 필터 전" if key=="respiration" else "공식 대역 필터 후"
            ax.set_title(NAMES[condition]+" / "+title+f"\n22~32초 변동 크기 비율 {fmt(ratio)}",fontsize=9,loc="left")
            ax.grid(alpha=.15)
        axes[-1,col].set_xlabel("영상 시각 (초)")
    axes[0,0].legend(fontsize=8,loc="upper right")
    for ax in axes[:,0]:ax.set_ylabel("원영상 기준 공통 크기")
    label="동일 프레임 반복" if probe=="frozen" else "픽셀 변화량 25% 대조"
    fig.suptitle(item+" · "+label+" · 공학 대조이며 실제 무호흡 아님",fontsize=13)
    fig.get_layout_engine().set(rect=(0,.04,1,.95))
    fig.text(.5,.008,"회색은 원영상의 모델 출력(정답 주석 아님) · 주황 구간은 영상 조작 · ROI 동일 / 재표준화 없음 · 검증에서 고정한 부호 · 실제 호흡량 아님",ha="center",fontsize=8)
    target=OUT/"plots"/(item+"_"+probe+("_current_vs_official.png" if current_comparison else ".png"))
    fig.savefig(target,dpi=145);plt.close(fig)
    return target


def summary_figure(summary,calibrated=False):
    fig,axes=plt.subplots(1,3,figsize=(12.5,4.5),layout="constrained")
    keys=("f1","wave_abs_r","bpm_count_abs_error")
    names=("호흡점 F1 ↑","같은 시각 파형 대응도 ↑","호흡점 개수 기반 BPM 오차 ↓")
    for ax,key,title in zip(axes,keys,names):
        vals=[summary[c]["filtered"][key] for c in CONDITIONS]
        ax.bar(np.arange(4),vals,color=[COLORS[c] for c in CONDITIONS])
        ax.set(xticks=np.arange(4),xticklabels=["Body\n공식","Chest\n공식","Body\n96 선축소","Chest\n96 선축소"],title=title)
        ax.set_ylim(0,max(vals)*1.2+.01);ax.grid(axis="y",alpha=.15)
        for i,v in enumerate(vals):ax.text(i,v,f"{v:.3f}",ha="center",va="bottom",fontsize=9)
    fig.suptitle("검증 S02 부호 고정 후 평가 3클립 · 추가 분석" if calibrated else "원영상 4클립 · 같은 DeepPhys / 공식 필터 · 사전 공통 부호 -1",fontsize=12)
    target=OUT/"plots"/("normal_summary_calibrated.png" if calibrated else "normal_summary.png")
    fig.savefig(target,dpi=150);plt.close(fig)
    return target


def input_video(item,normal_rows):
    row=next(r for r in normal_rows if r["condition"]=="body_official")
    capture=cv2.VideoCapture(str(DATA/item["video"]))
    temp=RUNTIME/"roi_probe_videos"/(item["id"]+"_input_controls.mp4")
    temp.parent.mkdir(exist_ok=True)
    writer=cv2.VideoWriter(str(temp),cv2.VideoWriter_fourcc(*"mp4v"),row["fps"],(960,210))
    assert writer.isOpened()
    anchor=None;count=0
    while count<row["valid_frames"]:
        ok,frame=capture.read()
        if not ok:break
        frame=cv2.resize(frame,(320,180),interpolation=cv2.INTER_AREA)
        current=count/row["fps"]
        active=START<=current<STOP
        if active and anchor is None:anchor=frame.copy()
        frozen=anchor if active else frame
        attenuated=np.rint(anchor.astype(np.float32)+.25*(frame.astype(np.float32)-anchor)).clip(0,255).astype(np.uint8) if active else frame
        panels=[]
        for name,picture in (("Original",frame),("Frozen input",frozen),("Pixel change x0.25",attenuated)):
            header=np.full((30,320,3),25,np.uint8)
            cv2.putText(header,f"{name} | t={current:.1f}s",(6,20),cv2.FONT_HERSHEY_SIMPLEX,.45,(230,230,230),1)
            panels.append(np.concatenate((header,picture),axis=0))
        writer.write(np.concatenate(panels,axis=1));count+=1
    capture.release();writer.release()
    assert count==row["valid_frames"]
    check=cv2.VideoCapture(str(temp));assert int(check.get(cv2.CAP_PROP_FRAME_COUNT))==count;check.release()
    target=OUT/"videos"/temp.name;target.parent.mkdir(exist_ok=True);shutil.copy2(temp,target)
    return target


def probe_summary_figure(motion):
    fig,axes=plt.subplots(1,2,figsize=(13,4.8),layout="constrained")
    keys=("input_pixel_change","flow_mean_magnitude","respiration","respiration_filtered")
    colors=("#a3a9b1","#269d93","#d89723","#376cca")
    labels=("입력 픽셀 변화","정규화 전 흐름","파형 · 필터 전","파형 · 필터 후")
    x=np.arange(4)
    for ax,probe,title in zip(axes,("frozen","attenuated"),("동일 프레임 반복 · 0에 가까운 변동 기대","픽셀 변화 감소 · 실제 변위 25%의 정답은 아님")):
        for i,(key,color,label) in enumerate(zip(keys,colors,labels)):
            vals=[motion[c][probe][key] for c in CONDITIONS]
            pos=x+(i-1.5)*.19
            ax.bar(pos,vals,width=.18,color=color,label=label)
            for p,v in zip(pos,vals):ax.text(p,v,f"{v:.2f}",ha="center",va="bottom",fontsize=7)
        maximum=max(motion[c][probe][key] for c in CONDITIONS for key in keys)
        ax.set(xticks=x,xticklabels=["Body\n공식","Chest\n공식","Body\n96 선축소","Chest\n96 선축소"],ylim=(0,max(.1,maximum*1.3)),title=title)
        ax.set_ylabel("조작 영상 / 원영상 · 2클립 평균")
        ax.grid(axis="y",alpha=.15)
    axes[0].legend(fontsize=8,ncol=2)
    fig.suptitle("움직임 입력 변화에 대한 반응 · 공학 대조 / 실제 호흡량 보존 검증 아님",fontsize=12)
    fig.savefig(OUT/"plots/probe_summary.png",dpi=150);plt.close(fig)


def main():
    protocol=read(OUT/"protocol.json")
    rows=[]
    for item in protocol["samples"]:
        for condition in CONDITIONS:
            rows.append(read(OUT/"runs"/condition/"normal"/(item["id"]+".json")))
        if item["id"] in PROBE_IDS:
            for condition in CONDITIONS:
                for probe in ("frozen","attenuated"):
                    rows.append(read(OUT/"runs"/condition/probe/(item["id"]+".json")))
    normal=[r for r in rows if r["probe"]=="normal"]
    probes=[r for r in rows if r["probe"]!="normal"]
    for row in rows:
        with h5py.File(OUT/row["waveform"],"r+") as handle:
            handle.attrs["synthetic_input_control"]=row["probe"]!="normal"
            handle.attrs["reference_scope"]="original video annotations; invalid as breathing truth inside edited intervals" if row["probe"]!="normal" else "original video annotated breathing peaks; not measured displacement"
            handle.attrs["normal_training_warning"]="Do not mix frozen/attenuated controls into normal waveform training"
    (OUT/"파형_사용안내.txt").write_text("이번 비교는 원영상 4개이며, 4조건 x 원영상/조작 대조의 총 32개 HDF5입니다.\n"
        "runs/body_official/normal: 공식 Body 순서의 원영상 예측\n"
        "runs/chest_official/normal: 공식 Chest 순서의 원영상 예측\n"
        "runs/body_early96/normal, runs/chest_early96/normal: 선축소 비교\n"
        "frozen, attenuated 폴더는 인위적 영상 조작입니다. 정상 학습 데이터에 섞지 마세요.\n"
        "조작 HDF5에 남긴 reference는 원영상 주석으로, 조작 구간의 실제 호흡 정답이 아닙니다.\n\n"
        "time_sec: 영상 기준 초 / network_output: 적분 전 DeepPhys 출력\n"
        "respiration: 공식 적분 및 추세 제거 후, 대역 필터 전 신호\n"
        "respiration_filtered: 공식 0.3~1.0Hz 대역 필터 후 신호\n"
        "flow_mean_magnitude, flow_p90_magnitude: Z-score 정규화 전 광학 흐름 크기의 공간 통계\n"
        "input_pixel_change: 인접 프레임의 평균 픽셀 변화량\n"
        "envelope_primary, envelope_filtered: 파형의 약 1초 RMS\n"
        "reference, reference_detrended, annotation_peaks_sec: 공개 호흡점 기반 주석\n\n"
        "원시 흐름의 절댓값은 FPS, 영상 크기, ROI에 영향을 받으므로 다른 촬영 조건에 같은 문턱값을 쓰면 안 됩니다.\n"
        "파형의 높이는 실제 흉부 변위/호흡량이 아닙니다. 이번 비교만으로 이상 탐지 모델 학습 적합성을 확정하지 않습니다.\n",encoding="utf-8")
    calibration=read(OUT/"validation_polarity.json")
    for row in normal:
        data=signals(row);rule=calibration["conditions"][row["condition"]]["rule"]
        row["calibrated_rule"]=rule
        row["filtered_metrics_calibrated"]=score_signal(data["time_sec"],data["respiration_filtered"],data["reference_detrended"],data["annotation_peaks_sec"],rule)
    evaluation=[r for r in normal if r["id"] in calibration["design"]["evaluation_ids"]]
    calibrated_summary={c:{"filtered":aggregate([r for r in evaluation if r["condition"]==c],"filtered_metrics_calibrated")} for c in CONDITIONS}
    save(OUT/"calibrated_evaluation.json",{"design":calibration["design"],"calibration":calibration,"summaries":calibrated_summary,"clips":evaluation})
    summary={c:{"primary":aggregate([r for r in normal if r["condition"]==c],"primary_metrics"),
                "filtered":aggregate([r for r in normal if r["condition"]==c],"filtered_metrics_same_reference"),
                "fft_bpm_abs_error":float(np.mean([r["fft_bpm_abs_error"] for r in normal if r["condition"]==c]))} for c in CONDITIONS}
    motion={c:{p:{key:float(np.mean([r["probe_metrics"][key]["ratio"] for r in probes if r["condition"]==c and r["probe"]==p and r["probe_metrics"][key]["ratio"] is not None]))
                    for key in ("input_pixel_change","flow_mean_magnitude","respiration","respiration_filtered")}
               for p in ("frozen","attenuated")} for c in CONDITIONS}
    result={"generated_at":datetime.now().astimezone().isoformat(),"protocol":protocol,"normal_summaries":summary,"validation_sign_supplement":calibrated_summary,"probe_ratios":motion,"all_runs":rows,
            "claim_limit":"No clinical winner or apnea sensitivity claim; exploratory timing and edited-input preservation comparison only"}
    save(OUT/"results.json",result)
    with (OUT/"normal_metrics.csv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["id","condition","stage","f1","wave_abs_r","event_time_mae_sec","interval_mae_sec","matched_interval_count","bpm_count_abs_error"]
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in normal:
            for stage,field in (("before_bandpass","primary_metrics"),("official_bandpass","filtered_metrics_same_reference")):
                writer.writerow({"id":r["id"],"condition":r["condition"],"stage":stage,**{k:r[field][k] for k in fields[3:]}})
            if r in evaluation:
                writer.writerow({"id":r["id"],"condition":r["condition"],"stage":"official_bandpass_validation_sign",**{k:r["filtered_metrics_calibrated"][k] for k in fields[3:]}})
    with (OUT/"probe_metrics.csv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["id","condition","probe","signal","ratio","delay_below_20pct_sec"]
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in probes:
            for key,m in r["probe_metrics"].items():
                writer.writerow({"id":r["id"],"condition":r["condition"],"probe":r["probe"],"signal":key,
                                 "ratio":m["ratio"],"delay_below_20pct_sec":m.get("sustained_below_20pct_delay_sec")})
    (OUT/"plots").mkdir(exist_ok=True)
    summary_figure(summary)
    summary_figure(calibrated_summary,calibrated=True)
    probe_summary_figure(motion)
    for item in IDS:
        normal_figure(item,[r for r in normal if r["id"]==item])
        if item in calibration["design"]["evaluation_ids"]:
            normal_figure(item,[r for r in normal if r["id"]==item],calibrated=True)
    for item in PROBE_IDS:
        source=next(s for s in protocol["samples"] if s["id"]==item)
        input_video(source,[r for r in normal if r["id"]==item])
        for p in ("frozen","attenuated"):
            probe_figure(item,p,[r for r in normal if r["id"]==item],[r for r in probes if r["id"]==item and r["probe"]==p])
            probe_figure(item,p,[r for r in normal if r["id"]==item],[r for r in probes if r["id"]==item and r["probe"]==p],current_comparison=True)
    # A numerical ranking is descriptive; choice must jointly consider both goals.
    body=calibrated_summary["body_official"]["filtered"];chest=calibrated_summary["chest_official"]["filtered"]
    timing="Body" if body["f1"]>chest["f1"] else "Chest" if chest["f1"]>body["f1"] else "동률"
    timing_sentence=f"S02 검증 영상에서 부호만 고정한 추가 분석의 평가 3클립에서 호흡점 F1은 {timing} 조건이 높았습니다. Body {body['f1']:.3f}, Chest {chest['f1']:.3f}. 이 값만으로 움직임 소실 보존의 우열을 결정하지 않습니다."
    early_body=calibrated_summary["body_early96"]["filtered"];early_chest=calibrated_summary["chest_early96"]["filtered"]
    body_preferred=body["f1"]>chest["f1"] and early_body["f1"]>early_chest["f1"] and body["event_time_mae_sec"]<chest["event_time_mae_sec"] and early_body["event_time_mae_sec"]<early_chest["event_time_mae_sec"]
    decision=("현재 공개 Body용 가중치와 이번 소규모 호흡 시점 평가에서는 Body ROI를 다음 실험의 기준으로 삼을 근거가 있습니다. 전처리 순서는 일부 지표가 엇갈리므로 공식 순서를 기준선으로 보존하고 96 선축소를 비교 후보로 남깁니다."
                if body_preferred else "현재 소규모 결과만으로 Body 또는 Chest가 일관되게 낫다고 정하기 어렵습니다. 조건별 호흡 시점 지표와 움직임 대조 반응을 함께 확인해야 합니다.")
    frozen_values=[motion[c]["frozen"]["respiration_filtered"] for c in CONDITIONS]
    attenuated_values=[motion[c]["attenuated"]["respiration_filtered"] for c in CONDITIONS]
    motion_statement=(f"화면 전체 정지 대조에서 공식 필터 후 출력 변동은 조건별 평균 원영상의 {100*min(frozen_values):.2f}~{100*max(frozen_values):.2f}%로 줄었습니다. "
        f"픽셀 변화 감소 대조에서는 {100*min(attenuated_values):.1f}~{100*max(attenuated_values):.1f}%가 남았습니다. "
        "이 결과는 인위적 영상 대조이며 실제 흉부 변위 감소의 정답 비율이 아닙니다. 현재 파형 높이를 실제 움직임 강도로 바로 해석할 근거는 부족합니다. 실제 호흡 정지나 흉부만 멈추는 상황은 검증하지 않았습니다.")
    save(OUT/"conclusion.json",{"normal_event_timing":timing_sentence,"motion":motion_statement,"decision":decision,
         "motion_signal_ratios":motion,"final_operational_or_clinical_choice_validated":False})
    (OUT/"결과_설명문.txt").write_text(timing_sentence+"\n\n"+decision+"\n\n"+motion_statement+"\n"
        "4개 원영상 중 S02는 출력 부호 선택용 검증에 사용했고 추가 분석의 평가는 나머지 3클립입니다.\n"
        "원영상 16조건과 조작 영상 16조건의 HDF5·CSV·그래프를 보존합니다.\n"
        "기존 공통 부호 결과와 검증에서 부호만 고정한 추가 분석을 구분해 제시합니다.\n"
        "픽셀 변화 감소는 실제 흉부 변위 감소의 정답이 아닙니다. 실제 카메라와 독립 호흡 주석 검증이 남아 있습니다.\n",encoding="utf-8")
    shutil.copy2(DATA/"source/air-400/configs/inference/deepphys_deep_infer.yaml",OUT/"official_inference_config.yaml")
    save(OUT/"script_hashes.json",{p.name:sha(p) for p in Path(__file__).parent.glob("roi_preservation_*.py")})
    table=[]
    for c in CONDITIONS:
        s=summary[c]["filtered"]
        table.append(f"<tr><th>{NAMES[c]}</th><td>{fmt(s['f1'])}</td><td>{fmt(s['wave_abs_r'])}</td><td>{fmt(s['event_time_mae_sec'])}</td><td>{fmt(s['interval_mae_sec'])} ({s['interval_mae_sec_valid_clips']}/4)</td><td>{fmt(s['bpm_count_abs_error'])}</td><td>{fmt(summary[c]['fft_bpm_abs_error'])}</td></tr>")
    probe_table=[]
    calibrated_table=[]
    for c in CONDITIONS:
        m=calibrated_summary[c]["filtered"]
        calibrated_table.append(f"<tr><th>{NAMES[c]}</th><td>{calibration['conditions'][c]['rule']['polarity']:+d}</td><td>{fmt(m['f1'])}</td><td>{fmt(m['wave_abs_r'])}</td><td>{fmt(m['event_time_mae_sec'])}</td><td>{fmt(m['interval_mae_sec'])} ({m['interval_mae_sec_valid_clips']}/3)</td><td>{fmt(m['bpm_count_abs_error'])}</td></tr>")
    for c in motion:
        for p in motion[c]:
            m=motion[c][p]
            probe_table.append(f"<tr><th>{NAMES[c]}</th><td>{p}</td><td>{fmt(m['input_pixel_change'])}</td><td>{fmt(m['flow_mean_magnitude'])}</td><td>{fmt(m['respiration'])}</td><td>{fmt(m['respiration_filtered'])}</td></tr>")
    cases="".join(f"<details><summary>{item} 원영상 4조건 파형</summary><img src='plots/{item}_normal.png'><p>공식 ROI 화면: Body / Chest</p><img class='roi' src='roi_images/{item}_Body.jpg'><img class='roi' src='roi_images/{item}_Chest.jpg'></details>" for item in IDS)
    calibration_cases="".join(f"<details><summary>{item} · 검증 부호 고정 후 평가 파형</summary><img src='plots/{item}_calibrated_normal.png'></details>" for item in calibration["design"]["evaluation_ids"])
    probe_cases="".join(f"<details><summary>{item} 입력 조작 영상 · 실제 무호흡 아님</summary><video controls preload='metadata' style='max-width:100%' src='videos/{item}_input_controls.mp4'></video></details>" for item in PROBE_IDS)
    probe_cases+="".join(f"<details><summary>{item} · {p}</summary><img src='plots/{item}_{p}.png'></details>" for item in PROBE_IDS for p in ("frozen","attenuated"))
    probe_cases+="".join(f"<details><summary>{item} · {p} · 공식 Body / 기존 Chest 선축소 직접 비교</summary><img src='plots/{item}_{p}_current_vs_official.png'></details>" for item in PROBE_IDS for p in ("frozen","attenuated"))
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>Body·Chest 목표 비교</title><style>
body{font:16px/1.7 system-ui,sans-serif;max-width:1260px;margin:32px auto;padding:0 22px;color:#1c2d43}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}td,th{padding:9px;border-bottom:1px solid #cdd6e0;text-align:left}img{max-width:100%;height:auto}.roi{width:45%;margin-right:3%}.note{background:#fff0cf;padding:17px;border-radius:10px}.result{background:#eaf2ff;padding:17px;border-radius:10px}details{background:#f3f6f9;padding:14px;margin:12px 0}summary{font-weight:650;cursor:pointer}a{color:#235f9f}</style>
<h1>Body·Chest · 호흡 시점과 움직임 감소 보존 비교</h1>
<p class="result">'''+html.escape(timing_sentence)+"<br>"+html.escape(decision)+"<br>"+html.escape(motion_statement)+'''</p>
<p class="note">기존 Chest YOLO 파인튜닝 가중치는 사용하지 않았습니다. 공개 Body용 DeepPhys와 원래 Body/Face 검출기를 고정했습니다. 원영상 4클립, 보수적인 파일명 그룹 4개이며 개인 신원을 확인한 그룹은 아닙니다. 현재 DeepPhys의 원래 학습 데이터와 중복 여부도 알 수 없습니다.</p>
<h2>변수를 나눈 2×2 실험</h2><ul>
<li>공식 Body: 공개 PreProcessor.preprocess를 직접 실행합니다. 원래 ROI 크기에서 DeepFlow → 정규화 → 96×96 입력입니다.</li>
<li>공식 순서 Chest: 위 처리 순서를 유지하고 지원되는 ROI 선택만 Chest로 바꿉니다.</li>
<li>여기서 Chest는 공개 코드가 Body/Face에서 계산한 기하학적 영역입니다. 항상 가슴만 좁게 포함하지 않으며, 수동 해부학적 Chest 영역이나 폐기한 파인튜닝 검출기와 다릅니다. 저장한 실제 박스 화면으로 범위를 확인할 수 있습니다.</li>
<li>Body/Chest 96 선축소: 영역을 자른 직후 96×96으로 줄인 다음 광학 흐름을 계산합니다. 이전 통제 비교 조건의 영향을 분리합니다.</li>
<li>모든 조건에서 공개 PostProcessor를 직접 실행해 필터 전/후 신호를 함께 저장합니다. 가중치, 원본 FPS, 영상 구간, 180프레임 묶음과 공통 호흡점 규칙을 고정했습니다.</li>
</ul><h2>원영상의 호흡 시점 보존</h2>
<img src="plots/normal_summary.png"><table><tr><th>조건</th><th>호흡점 F1 ↑</th><th>파형 |r| ↑</th><th>대응 시각 MAE 초 ↓</th><th>연속 간격 MAE 초 ↓ (유효 클립)</th><th>개수 기반 BPM MAE ↓</th><th>동일 FFT 기반 BPM 오차 ↓</th></tr>'''+"".join(table)+'''</table>
<p>표는 공식 대역 필터 후 결과입니다. F1은 4클립 TP/FP/FN을 합산하고 다른 값은 영상별 평균입니다. 파형 상관은 모든 조건에 같은 필터 전 공개 참조 신호를 사용하며 양 끝 3초를 제외했습니다. 위상·시각 이동을 영상별로 맞추지 않았습니다. 호흡점 규칙은 이전 Chest 검증에서 고정한 공통 값을 유지했으며 Body에 별도 최적화한 규칙은 아닙니다. CSV에는 필터 전 결과도 보존합니다. 회색 기준은 호흡점으로 만든 신호이며 실제 호흡량은 아닙니다.</p>
'''+cases+'''<h2>추가 분석 · 검증 영상에서 부호만 선택한 뒤 다른 3클립 평가</h2>
<p>초기 출력의 부호를 확인하면서 기존 Chest 기반 공통 부호가 Body에 불리할 수 있어 추가한 분석입니다. 최초 사전 계획에는 없었으며 위 결과와 원본 프로토콜을 보존했습니다. 기존 검증 영상 S02_1에서 +1/-1 중 하나를 조건별로 고정하고, 나머지 S01_1·S03_1·S07_01에 적용했습니다. 평가 영상별 부호나 시간 이동, 필터·호흡점 문턱값은 맞추지 않았습니다.</p>
<img src="plots/normal_summary_calibrated.png"><table><tr><th>조건</th><th>검증에서 고정한 부호</th><th>F1 ↑</th><th>|r| ↑</th><th>시각 MAE 초 ↓</th><th>간격 MAE 초 ↓ (유효 클립)</th><th>개수 기반 BPM MAE ↓</th></tr>'''+"".join(calibrated_table)+'''</table>
<p>시각 오차는 ±0.5초 내 일대일 대응에 성공한 호흡점만의 오차입니다. 누락·과잉 호흡점은 F1에 반영합니다. 간격 오차는 양쪽 모두 연속 대응된 호흡쌍만 사용하므로 유효 클립 수와 함께 읽어야 합니다.</p>
'''+calibration_cases+'''<h2>움직임 감소·정지 입력의 보존 · 공학 대조</h2>
<p>IR 10FPS S02_1과 RGB 15FPS S07_01의 18~36초 구간을 조작했습니다. frozen은 한 프레임을 반복합니다. attenuated는 첫 프레임을 기준으로 픽셀 변화량을 25%로 줄입니다. 이는 실제 흉부 변위가 25%라는 뜻이 아닙니다. ROI는 원영상과 같게 고정해 영역 검출 변화와 파형 추출 반응을 분리했습니다.</p>
<p>모델에는 디코딩한 프레임 배열에서 직접 조작을 적용했습니다. 제공하는 MP4는 입력을 보여 주기 위한 재인코딩 예시이며, 그 MP4를 다시 추론하면 압축 때문에 같은 수치가 보장되지는 않습니다.</p>
<p>조작 대조 그래프의 회색 선은 원영상에서 추출한 모델 출력입니다. 위 원영상 비교 그래프의 회색 호흡 주석과 의미가 다릅니다.</p>
<img src="plots/probe_summary.png">
<table><tr><th>조건</th><th>조작</th><th>입력 픽셀 변화 비율</th><th>원시 흐름 크기 비율</th><th>모델 파형 변동 비율 · 필터 전</th><th>모델 파형 변동 비율 · 필터 후</th></tr>'''+"".join(probe_table)+'''</table>
<p>비율은 같은 영상·같은 처리 조건의 22~32초 구간에서 조작 영상/원영상으로 계산합니다. 모델 신호는 표준편차, 입력은 평균 변화량을 사용합니다. frozen은 0에 가까운 출력 변동을 기대합니다. attenuated에서는 원영상보다 줄되 정지와 구분되는 반응인지 봅니다. 둘 다 0이 된다고 더 좋은 결과는 아닙니다. 픽셀 변화와 실제 흉부 변위는 다르므로 모델 출력의 정답 비율을 0.25로 정하지 않았습니다. 원영상의 변동이 작은 경우 비율이 불안정하므로 각 클립의 원값도 JSON에 남겼습니다. 모델 변동 크기를 실제 호흡량으로 해석할 수 없습니다.</p>
<p>CSV의 20% 이하 지속 지연은 원영상이라는 대조 신호가 있어 계산한 공학 지표입니다. 실사용 알림 문턱값이 아니며 실제 아기의 무호흡 판정이나 알림 지연을 뜻하지 않습니다.</p>
'''+probe_cases+'''<p class="note">이 실험은 화면 전체의 인위적 정지·픽셀 변화 감소입니다. 실제 숨을 멈춘 영유아, 흉부만 정지하고 다른 부위가 움직이는 상황, 기도 폐쇄의 검증이 아닙니다. 공개 호흡점만으로 실제 호흡 진폭·정지 시각의 정답을 만들 수 없습니다. 또한 전체 클립 정규화와 양방향 필터를 사용하므로 실시간 알림 지연은 이 결과로 보장되지 않습니다. 실제 라즈베리파이 30FPS 입력은 별도 검증 대상입니다.</p>
<h2>재현·원자료</h2><ul><li><a href="results.json">모든 수치와 실행 결과</a> · <a href="normal_metrics.csv">원영상 필터 전후 CSV</a> · <a href="probe_metrics.csv">조작 대조 CSV와 지연</a></li>
<li><a href="protocol.json">사전 고정 프로토콜과 입력 SHA</a> · <a href="peak_rule.json">고정 호흡점 규칙</a> · <a href="verification.json">원본·출력 검증</a></li>
<li><a href="analysis_addendum.json">추가 분석 도입 시점·사유</a> · <a href="validation_polarity.json">검증 영상으로만 선택한 부호</a> · <a href="calibrated_evaluation.json">추가 분석의 전체 평가 수치</a></li>
<li><a href="결과_설명문.txt">결과 설명문</a> · <a href="official_inference_config.yaml">사용한 공개 추론 설정 원본</a> · <a href="script_hashes.json">실행 코드 SHA</a></li>
<li><a href="파형_사용안내.txt">HDF5 필드와 조작 대조 데이터 구분</a></li>
<li><a href="probe_scope_addendum.json">선축소 조건까지 정지·감소 대조를 포함한 범위 기록</a></li>
<li><a href="https://github.com/michaelwwan/air-400/blob/main/configs/inference/deepphys_deep_infer.yaml">공식 추론 설정</a> · <a href="https://arxiv.org/html/2512.06888v1#S4">공식 논문 방법</a></li>
<li><a href="../../index.html">전체 자료 안내</a></li></ul></html>'''
    (OUT/"index.html").write_text(page,encoding="utf-8")
    save(PROJECT/"goal_comparison_status.json",{"status":"completed_exploratory","normal_clips":4,"probe_clips":2,"report":str((OUT/"index.html").relative_to(PROJECT)).replace("\\","/"),"timing_conclusion":timing_sentence,"motion_conclusion":motion_statement,"clinical_motion_stop_validated":False})
    print(json.dumps({"normal":summary,"probes":motion,"timing":timing_sentence},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
