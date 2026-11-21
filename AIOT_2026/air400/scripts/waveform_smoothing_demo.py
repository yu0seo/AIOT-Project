"""Illustrate fixed smoothing choices without changing study data or selecting a filter."""
import argparse
from datetime import datetime
import hashlib
import json
import os

from air400_paths import BEFORE, PRESENTATION, RUNTIME
os.environ["MPLCONFIGDIR"]=str(RUNTIME/"matplotlib")
import h5py
import numpy as np
from scipy.signal import savgol_filter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id",default="S03_1")
    args=parser.parse_args()
    if not args.id.replace("_","").isalnum():raise ValueError("Invalid clip ID")
    source=BEFORE/"waveforms/control_v1"/(args.id+"_pred.hdf5")
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    with h5py.File(source,"r") as f:
        t=f["time_sec"][:]
        original=f["respiration"][:]
        official=f["respiration_filtered"][:]
        reference=f["reference_detrended"][:]
    fps=1/float(np.median(np.diff(t)))
    window=max(3,int(round(.5*fps)))
    if window%2==0:window+=1
    smoothed=savgol_filter(original,window_length=window,polyorder=2,mode="interp")
    signals={"original":original,"savgol_0_5sec":smoothed,"official_bandpass":official}
    mask=(t>=3)&(t<t[-1]+1/fps-3)
    def correlation(y):
        return float(abs(np.corrcoef(y[mask],reference[mask])[0,1]))
    out=PRESENTATION/"07_파형후처리검토"
    out.mkdir(parents=True,exist_ok=True)
    artifact=out/(args.id+"_smoothing_demo.hdf5")
    with h5py.File(artifact,"w") as f:
        f.create_dataset("time_sec",data=t)
        f.create_dataset("reference_detrended",data=reference)
        for key,values in signals.items():
            assert len(values)==len(t) and np.isfinite(values).all()
            f.create_dataset(key,data=values,compression="gzip")
        f.attrs.update(source_sha256=source_hash,purpose="Illustration only; no filter selection or accuracy validation",
                       savgol_window_samples=window,savgol_polynomial_order=2)
    font=Path("C:/Windows/Fonts/malgun.ttf")
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"]=font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams["axes.unicode_minus"]=False
    fig,axes=plt.subplots(3,2,figsize=(14,8.5),layout="constrained",sharey=True)
    scale=max(float(np.std(original)),1e-12)
    ref=reference/max(float(np.std(reference)),1e-12)
    titles=["현재 파형 · 적분/추세 제거 후, 대역 필터 전",f"약한 평활화 · Savitzky–Golay {window}샘플 / 2차", "기존 공식 필터 · 0.3~1.0Hz (18~60회/분 대역)"]
    colors=["#239247","#ad6616","#2879d0"]
    for row,((key,values),title,color) in enumerate(zip(signals.items(),titles,colors)):
        for col,ax in enumerate(axes[row]):
            ax.plot(t,ref,color="#a0a4aa",lw=1,label="공개 호흡점 기준 신호")
            ax.plot(t,-values/scale,color=color,lw=1.05,label="DeepPhys 예측")
            ax.set_title(title+f" | |r|={correlation(values):.3f}",fontsize=10,loc="left")
            ax.set_xlim((0,t[-1]) if col==0 else (10,20))
            ax.grid(alpha=.15)
            if col==0:ax.set_ylabel("표시용 크기 조정 신호")
    axes[0,0].legend(fontsize=8,loc="upper right")
    axes[-1,0].set_xlabel("영상 시각 (초) · 전체 구간")
    axes[-1,1].set_xlabel("영상 시각 (초) · 10~20초 확대")
    fig.suptitle(args.id+" · 같은 기존 자동 Chest 파형의 후처리 예시\n회색은 주석 기반 기준 신호 · 회색에 맞춰 필터를 선택하지 않음",fontsize=13)
    fig.get_layout_engine().set(rect=(0,.05,1,.87))
    fig.text(.5,.009,"예측 3개에 같은 원신호 표준편차·같은 부호 적용 / 시간 이동 없음 / 오프라인 예시이며 실시간·이상 보존 성능은 미검증",ha="center",fontsize=9)
    fig.savefig(out/(args.id+"_smoothing_comparison.png"),dpi=150)
    plt.close(fig)
    summary={"generated_at":datetime.now().astimezone().isoformat(),"clip_id":args.id,"source":str(source),
        "source_sha256":source_hash,"fps":fps,"savgol":{"window_samples":window,"nominal_window_sec":window/fps,"polyorder":2},
        "zero_lag_abs_correlation_with_same_reference":{key:correlation(y) for key,y in signals.items()},
        "design":"Fixed illustrative parameters for the user-selected example; not validation-tuned or independent improvement evidence",
        "changes_to_existing_inference_or_training":False,
        "limitations":["Offline centered Savitzky-Golay and forward-backward official filter use future samples",
                       "18-60 breaths/min passband is an engineering parameter, not a normal/abnormal criterion",
                       "No apnea, pause, movement-artifact or anomaly-preservation validation",
                       "Same raw display scale; filtered signals were not independently scaled up"]}
    (out/(args.id+"_smoothing_summary.json")).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"안내.txt").write_text("사용자가 보여준 S03_1의 기존 자동 Chest 파형 후처리 예시입니다.\n"
        "원본·기존 실험 결과·모델 가중치를 수정하지 않았습니다. 공식 필터 값은 기존 HDF5의 저장값입니다.\n"
        "Savitzky–Golay 설정은 예시이며 최적값으로 선정한 것이 아닙니다.\n"
        "매끈한 외형은 정확도·이상 탐지 성능 개선을 보장하지 않습니다.\n"
        "실제 채택 전 검증 집합에서 호흡점/간격 오차와 움직임 감소·정지 보존을 확인해야 합니다.\n"
        "학습과 실제 추론에 동일한 처리 및 지연 조건을 적용해야 합니다.\n",encoding="utf-8")
    assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
