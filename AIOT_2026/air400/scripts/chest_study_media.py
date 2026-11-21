"""Export real comparison plots and paired videos from fixed study results."""
from pathlib import Path
import os
import shutil

import cv2
import h5py
import numpy as np

from chest_study_core import CONDITION_ROOTS, DATA, PRESENTATION, RUNTIME
from chest_study_prepare import write_image
os.environ["MPLCONFIGDIR"]=str(RUNTIME/"matplotlib")
import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager
import matplotlib.pyplot as plt

font=Path("C:/Windows/Fonts/malgun.ttf")
if font.exists():
    font_manager.fontManager.addfont(str(font))
    plt.rcParams["font.family"]=font_manager.FontProperties(fname=str(font)).get_name()
plt.rcParams["axes.unicode_minus"]=False
COLORS={"A":"#239247","B":"#d69a1c","C":"#2879d0"}
NAMES={"A":"기존 자동 Chest","B":"수동 상체 영역 · 참고","C":"Chest 파인튜닝 후"}


def load_signals(row):
    with h5py.File(CONDITION_ROOTS[row["condition"]]/row["waveform_file"],"r") as f:
        return {name:f[name][:] for name in ("time_sec","respiration","respiration_filtered","reference_detrended","annotation_peaks_sec")}


def waveform_plot(item,rows,rule):
    directory=PRESENTATION/"02_전후파형그래프"
    directory.mkdir(parents=True,exist_ok=True)
    fig,axes=plt.subplots(3,1,figsize=(12,8),sharex=True,layout="constrained")
    for ax,row in zip(axes,rows):
        data=load_signals(row);t=data["time_sec"];wave=data["respiration"]
        predicted=rule["polarity"]*wave/max(np.std(wave),1e-9)
        ref=data["reference_detrended"]/max(np.std(data["reference_detrended"]),1e-9)
        ax.plot(t,ref,color="#a7abb0",lw=1,label="공개 호흡점 기준 신호")
        ax.plot(t,predicted,color=COLORS[row["condition"]],lw=1.15,label=NAMES[row["condition"]])
        for p in data["annotation_peaks_sec"]:ax.axvline(p,color="#9ca3af",alpha=.15,lw=.8)
        stats=row["primary_waveform"]
        idx=np.minimum(len(t)-1,np.rint(np.array(stats["predicted_peak_times_sec"])*row["fps"]).astype(int))
        ax.scatter(t[idx],predicted[idx],s=12,color=COLORS[row["condition"]],zorder=3)
        name=NAMES[row['condition']]+(" · 미검출 대체 영역" if row['roi_metrics']['failure_fraction']>=1 else "")
        ax.set_title(f"{name} | F1={stats['f1']:.3f} | |r|={stats['wave_abs_r']:.3f} | 호흡수 오차={stats['bpm_count_abs_error']:.2f} BPM",fontsize=10,loc="left")
        ax.set_ylabel("표시용 표준화 신호")
        ax.grid(alpha=.15)
    axes[0].legend(fontsize=8,ncol=2,loc="upper right")
    axes[-1].set_xlabel("영상 시각 (초)")
    fig.suptitle(f"{item['id']} · 동일 영상 / 같은 DeepPhys / 96×96 광학 흐름 · {item['split']}")
    fig.get_layout_engine().set(rect=(0,.035,1,.97))
    fig.text(.5,.008,"표시용 크기 조정 / 검증셋에서 고정한 공통 부호 / 시간 이동 없음 · 기준은 실측 호흡량이 아닌 공개 호흡 주석",ha="center",fontsize=8)
    target=directory/(item["id"]+"_ABC_waveforms.png")
    fig.savefig(target,dpi=150);plt.close(fig)
    # A/C raw-value panels preserve absolute stored model output values.
    fig,axes=plt.subplots(2,1,figsize=(12,5),sharex=True,sharey=True,layout="constrained")
    for ax,row in zip(axes,[rows[0],rows[2]]):
        data=load_signals(row)
        ax.plot(data["time_sec"],data["respiration"],color=COLORS[row["condition"]],lw=1)
        for p in data["annotation_peaks_sec"]:ax.axvline(p,color="#888888",alpha=.2,lw=.7)
        name=NAMES[row['condition']]+(" · 미검출 대체 영역" if row['roi_metrics']['failure_fraction']>=1 else "")
        ax.set_title(name,loc="left",fontsize=10);ax.set_ylabel("원본 모델 출력값")
        ax.grid(alpha=.15)
    axes[-1].set_xlabel("영상 시각 (초) · 회색 세로선: 공개 호흡 주석 시각")
    fig.suptitle(item["id"]+" · 전후 파형 원값 / 공통 세로축")
    fig.savefig(directory/(item["id"]+"_AC_raw_values.png"),dpi=140);plt.close(fig)
    for row in (rows[0],rows[2]):
        data=load_signals(row)
        fig,ax=plt.subplots(figsize=(11,3.5),layout="constrained")
        ax.plot(data["time_sec"],data["respiration"],color=COLORS[row["condition"]],lw=1,label="respiration (필터 전)")
        ax.plot(data["time_sec"],data["respiration_filtered"],color="#777777",alpha=.65,lw=.8,label="respiration_filtered")
        ax.set(title=f"{item['id']} · {NAMES[row['condition']]} · 실제 계산값",xlabel="영상 시각 (초)",ylabel="모델 단위")
        ax.legend(fontsize=8);ax.grid(alpha=.15)
        output=CONDITION_ROOTS[row["condition"]]/"waveform_plots/control_v1"
        output.mkdir(parents=True,exist_ok=True)
        fig.savefig(output/(item["id"]+"_waveform.png"),dpi=140);plt.close(fig)
    return target


def paired_video(item,rows):
    target=PRESENTATION/"01_좌우비교영상"/(item["id"]+"_before_after.mp4")
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=RUNTIME/"paired_videos"/(item["id"]+"_before_after.mp4")
    temp.parent.mkdir(exist_ok=True)
    a,c=rows[0],rows[2]
    writer=cv2.VideoWriter(str(temp),cv2.VideoWriter_fourcc(*"mp4v"),a["fps"],(960,310))
    if not writer.isOpened():raise RuntimeError("Cannot initialize video writer")
    capture=cv2.VideoCapture(str(DATA/item["video"]))
    count=0
    while count<a["valid_frames"]:
        ok,frame=capture.read()
        if not ok:break
        frame=cv2.resize(frame,(480,270),interpolation=cv2.INTER_AREA)
        panels=[]
        for row in (a,c):
            image=frame.copy()
            color=(60,205,75) if row["condition"]=="A" else (220,130,40)
            x,y,w,h=row["roi_xywh"]
            cv2.rectangle(image,(round(x*1.5),round(y*1.5)),(round((x+w)*1.5),round((y+h)*1.5)),color,2)
            x,y,w,h=row["manual_box_xywh"]
            cv2.rectangle(image,(round(x*1.5),round(y*1.5)),(round((x+w)*1.5),round((y+h)*1.5)),(0,215,255),1)
            header=np.full((40,480,3),25,np.uint8)
            text="A: Aggregated original Chest" if row["condition"]=="A" else "C: Aggregated fine-tuned Chest"
            if row["condition"]=="C" and row["roi_metrics"]["failure_fraction"]>=1:text="C: Chest FAILED -> center fallback"
            cv2.putText(header,text,(8,17),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1)
            cv2.putText(header,f"{item['id']} | t={count/a['fps']:.1f}s | yellow: assistant reference",(8,33),cv2.FONT_HERSHEY_SIMPLEX,.35,(235,235,235),1)
            panels.append(np.concatenate((header,image),axis=0))
        writer.write(np.concatenate(panels,axis=1));count+=1
    capture.release();writer.release()
    if count!=a["valid_frames"]:raise RuntimeError("Incomplete comparison video")
    verify=cv2.VideoCapture(str(temp));decoded=int(verify.get(cv2.CAP_PROP_FRAME_COUNT));verify.release()
    if decoded!=count:raise RuntimeError("Comparison video failed frame-count check")
    shutil.copy2(temp,target)
    return target


def summary_plot(summaries):
    fig,axes=plt.subplots(1,4,figsize=(15,4.5),layout="constrained")
    panels=[("roi_mean_iou_mean","Chest 박스 겹침 IoU ↑"),("pooled_f1","호흡점 F1 ↑"),
            ("wave_abs_r_mean","파형 대응도 |r| ↑"),("bpm_count_abs_error_mean","호흡수 오차 BPM ↓")]
    for ax,(key,title) in zip(axes,panels):
        vals=[summaries[c][key] for c in "ABC"]
        ax.bar(["A 기존","B 수동","C 학습 후"],vals,color=[COLORS[c] for c in "ABC"])
        for i,v in enumerate(vals):ax.text(i,v,f"{v:.3f}",ha="center",va="bottom",fontsize=9)
        ax.set_title(title,fontsize=11);ax.grid(axis="y",alpha=.15)
        ax.set_ylim(0,max(vals)*1.2+.001)
    fig.suptitle("고정 시험 집합 4클립 · 원본 그룹 1개 · B는 수동 영역 참고 조건\n"
                 +f"C 시험 탐지 실패 {100*summaries['C']['roi_failure_fraction_mean']:.1f}% · C 파형은 대체 영역을 포함",fontsize=12)
    target=PRESENTATION/"03_전체시험성능/test_summary.png"
    target.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(target,dpi=160);plt.close(fig)
    return target


def detection_comparison(item,rows):
    """Show actual sampled detections separately from the aggregated crop video."""
    capture=cv2.VideoCapture(str(DATA/item["video"]))
    panels=[]
    for row in (rows[0],rows[2]):
        pictures=[]
        for requested in (0,row["frames"]//2,row["frames"]-1):
            detection=min(row["detections"],key=lambda d:abs(d["frame"]-requested))
            frame_index=detection["frame"]
            capture.set(cv2.CAP_PROP_POS_FRAMES,frame_index)
            ok,frame=capture.read()
            if not ok:raise RuntimeError(f"Cannot decode sampled detection {item['id']}:{frame_index}")
            frame=cv2.resize(frame,(320,180),interpolation=cv2.INTER_AREA)
            x,y,w,h=map(int,row["manual_box_xywh"])
            cv2.rectangle(frame,(x,y),(x+w,y+h),(0,220,255),1)
            color=(65,210,90) if row["condition"]=="A" else (255,130,50)
            if detection["valid"]:
                x,y,w,h=map(round,detection["box"])
                cv2.rectangle(frame,(x,y),(x+w,y+h),color,2)
            header=np.full((40,320,3),25,np.uint8)
            confidence=detection["confidence"]
            label="valid" if detection["valid"] else "NO DETECTION"
            if confidence is not None:label+=f" conf={confidence:.2f}"
            cv2.putText(header,f"{row['condition']} {item['id']} t={frame_index/row['fps']:.1f}s",(6,15),cv2.FONT_HERSHEY_SIMPLEX,.4,color,1)
            cv2.putText(header,label+" | yellow: reference",(6,32),cv2.FONT_HERSHEY_SIMPLEX,.35,(230,230,230),1)
            pictures.append(np.concatenate((header,frame),axis=0))
        panels.append(np.concatenate(pictures,axis=1))
    capture.release()
    target=PRESENTATION/"04_개선실패사례"/(item["id"]+"_raw_detections.jpg")
    target.parent.mkdir(exist_ok=True)
    write_image(target,np.concatenate(panels,axis=0))
    return target


def split_plot(summaries):
    fig,axes=plt.subplots(1,2,figsize=(10,4.5),layout="constrained")
    positions=np.arange(3)
    for condition,offset in (("A",-.18),("C",.18)):
        for ax,key,title in zip(axes,("roi_mean_iou_mean","roi_failure_fraction_mean"),("Chest 박스 IoU ↑","탐지 실패 비율 ↓")):
            vals=[summaries[s][condition][key] for s in ("train","val","test")]
            ax.bar(positions+offset,vals,width=.34,color=COLORS[condition],label=NAMES[condition])
            for x,v in zip(positions+offset,vals):ax.text(x,v+.015,f"{v:.2f}",ha="center",fontsize=9)
            ax.set(xticks=positions,xticklabels=["학습 14클립","검증 2클립","시험 4클립"],ylim=(0,1.16),title=title)
            ax.grid(axis="y",alpha=.15)
    axes[0].legend(fontsize=9)
    fig.suptitle("학습 환경 밖의 Chest 탐지 · 영상별 평균 / 그룹 분리")
    target=PRESENTATION/"03_전체시험성능/split_generalization.png"
    fig.savefig(target,dpi=150);plt.close(fig)
    return target
