"""Independent annotation-based analysis of the saved four-model experiment.

The official infant bandpass can exclude annotated slow breaths. Consequently
rate error is also checked against CSV annotation intervals, and correspondence
is evaluated before the bandpass. No normal/abnormal diagnosis is inferred.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path

import h5py
import numpy as np
from scipy import signal, sparse
from scipy.sparse.linalg import spsolve

from air400_paths import ROOT, DATA, ARCHIVE
NAMES = ["DeepPhys", "TSCAN", "EfficientPhys", "VIRENet"]
COLORS = ["#1874d1", "#d67715", "#16816b", "#9854b7"]


def detrend(y):
    """Same smoothing-prior equation as upstream, solved as a sparse system."""
    y = np.asarray(y, dtype=float).reshape(-1)
    n = len(y)
    d = sparse.diags([np.ones(n-2), -2*np.ones(n-2), np.ones(n-2)],
                     [0, 1, 2], shape=(n-2, n), format="csc")
    return y - spsolve(sparse.eye(n, format="csc") + 100**2 * (d.T @ d), y)


def corr(a, b):
    return float(abs(np.corrcoef(a, b)[0, 1])) if min(np.std(a), np.std(b)) > 1e-10 else 0.


def peaks_csv(path, clip):
    values = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 5 or row[0].startswith("#"):
                continue
            files = json.loads(row[1])
            if any(int(Path(x).stem) == int(clip) for x in files):
                values.append(float(row[2]))
    return np.asarray(sorted(set(values)))


def analyze_folder(folder, item):
    result = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    fs, n = result["fps"], result["valid_frames"]
    with h5py.File(DATA / item["reference"], "r") as f:
        reference = f["respiration"][:]
    original_reference = reference.copy()
    native_count = result.get("source_native_frames", result["frames"])
    reference = np.interp(np.linspace(1, len(reference), native_count),
                          np.arange(1, len(reference)+1), reference)
    if "control_source_frames" in result:
        indices = np.floor(np.arange(result["frames"]) * result["source_native_fps"] / fs).astype(int)
        reference = reference[indices]
    reference = reference[:n]
    reference_dt = detrend(reference)
    peaks = peaks_csv(DATA / item["annotations"], item["clip"])
    reference_peaks = signal.find_peaks(original_reference, prominence=.1)[0] / 10.
    errors = [float(np.min(np.abs(peaks - x))) for x in reference_peaks]
    # Independently check time units against the CSV timestamps. This is an
    # observed timebase inference, not an HDF5 sampling-rate attribute.
    if max(errors) > .16:
        raise AssertionError(f"10Hz reference timebase not supported for {item['subject']}: {max(errors)}")
    reference_csv_time = detrend(np.interp(np.arange(n)/fs,
                                         np.arange(len(original_reference))/10., original_reference))
    peaks = peaks[peaks < n / fs]
    rate = float(60 / np.mean(np.diff(peaks)))
    result["annotation_interval_bpm"] = rate
    result["annotation_peak_times_sec"] = peaks.tolist()
    result["reference_detrended_unbandpassed"] = reference_dt.tolist()
    result["reference_detrended_unbandpassed_csv_time"] = reference_csv_time.tolist()
    result["inferred_reference_fs"] = {"hz": 10., "mean_nearest_csv_peak_error_sec": float(np.mean(errors)),
                                       "max_nearest_csv_peak_error_sec": float(max(errors))}
    result["annotation_rate_below_official_18_bpm_band"] = rate < 18
    for name in NAMES:
        with h5py.File(folder / f"{name}_pred.hdf5", "r") as f:
            raw, wave = f["network_output"][:], f["respiration"][:]
        dt = detrend(np.cumsum(raw))
        edge = int(3 * fs)
        metric = result["models"][name]
        metric["bpm_error_vs_csv_intervals"] = abs(metric["bpm"] - rate)
        metric["wave_abs_r_unbandpassed"] = corr(dt[edge:-edge], reference_dt[edge:-edge])
        metric["wave_abs_r_unbandpassed_csv_time"] = corr(dt[edge:-edge], reference_csv_time[edge:-edge])
        f, power = signal.periodogram(dt, fs, nfft=2**(n-1).bit_length())
        region = (f >= .08) & (f <= 1.)
        metric["unbandpassed_dominant_bpm_5_60"] = float(f[region][np.argmax(power[region])] * 60)
        metric["unbandpassed_bpm_error_vs_csv"] = abs(metric["unbandpassed_dominant_bpm_5_60"] - rate)
        frozen_path = folder / f"{name}_freeze_probe.hdf5"
        if frozen_path.is_file():
            with h5py.File(frozen_path, "r") as f:
                frozen_raw = f["network_output"][:]
            frozen_dt = detrend(np.cumsum(frozen_raw))
            sl = slice(int(25 * fs), int(29 * fs))
            metric["freeze_unbandpassed_rms_ratio"] = float(np.sqrt(np.mean(frozen_dt[sl]**2)) /
                                                           max(np.sqrt(np.mean(dt[sl]**2)), 1e-10))
    return result


def summarize(rows):
    keys = ["bpm_error_vs_csv_intervals", "bpm_abs_error", "wave_abs_r_zero_lag",
            "wave_abs_r_unbandpassed", "wave_abs_r_unbandpassed_csv_time", "local_18s_bpm_mae", "pipeline_time_sec",
            "network_time_sec", "flow_time_sec", "pipeline_realtime_factor",
            "freeze_24_30s_rms_ratio", "freeze_unbandpassed_rms_ratio",
            "unbandpassed_bpm_error_vs_csv"]
    summary = {}
    for name in NAMES:
        values = [x["models"][name] for x in rows]
        summary[name] = {"n": len(rows)}
        for key in keys:
            nums = [x[key] for x in values if key in x]
            if nums:
                summary[name][key+"_mean"] = float(np.mean(nums))
                summary[name][key+"_median"] = float(np.median(nums))
        summary[name]["rate_within_3_bpm_count"] = sum(x["bpm_error_vs_csv_intervals"] <= 3 for x in values)
    return summary


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    assets = json.loads((DATA / "assets.json").read_text(encoding="utf-8"))
    groups = {}
    for label, directory in [("manual_chest", "results_manual_chest"), ("automatic_chest", "results")]:
        rows = []
        for item in assets["samples"]:
            folder = ARCHIVE / directory / f"{item['subject']}_{item['clip']}_native"
            if (folder / "summary.json").is_file():
                row = analyze_folder(folder, item)
                row["folder"] = str(folder.relative_to(ARCHIVE)).replace("\\", "/")
                rows.append(row)
        if rows:
            groups[label] = {"summary": summarize(rows), "clips": rows}
    controls = []
    for item in assets["samples"][:1]:
        folder = ARCHIVE / "results_manual_chest" / f"{item['subject']}_{item['clip']}_30fps_duplicate_control"
        if (folder / "summary.json").is_file():
            controls.append(analyze_folder(folder, item))
    report = ARCHIVE / "report"
    report.mkdir(exist_ok=True)
    analysis = {"groups": groups, "duplicated_frame_30fps_controls": controls,
                "primary_rate_reference": "CSV breathing-peak start-time intervals; 60 / mean interval",
                "reference_waveform": "Gaussian-smoothed manual peaks, not measured tidal volume",
                "scope": "Exploratory transferred Body checkpoints; training overlap unknown; no apnea labels"}
    (report / "analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    protocol = {"primary_selection": "First numbered video in every S01-S10 folder, before predictions",
                "automatic_roi_full_pipeline_subset": ["S01"],
                "automatic_roi_detection_audit": "All ten selected clips, without repeating neural comparisons on known mixed regions",
                "selection_reason": "S01 discovered ROI fallback; all-video ROI audit separates cropping reliability from network comparison",
                "model_selection_priority": ["waveform correspondence", "before-bandpass respiration rate agreement",
                                             "zero-motion residual", "whole-pipeline processing time"],
                "no_clinical_normal_abnormal_labels": True,
                "held_out_checkpoint_training_membership_unknown": True,
                "measured_flow_repetitions": 1, "network_repetitions_after_warmup": 3,
                "scripts_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in Path(__file__).parent.glob("air400_*.py")}}
    (report / "protocol.json").write_text(json.dumps(protocol, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v["summary"] for k,v in groups.items()}, indent=2))
    for group, info in groups.items():
        s = info["summary"]
        fig, axes = plt.subplots(1, 4, figsize=(15, 4), layout="constrained")
        panels = [("bpm_error_vs_csv_intervals_mean", "Rate MAE vs manual intervals (BPM)"),
                  ("wave_abs_r_unbandpassed_csv_time_median", "Before-bandpass |r|, CSV-checked timebase"),
                  ("pipeline_time_sec_median", "Full processing seconds / clip (median)"),
                  ("freeze_24_30s_rms_ratio_median", "Frozen-image output RMS ratio (median)")]
        for ax, (key, title) in zip(axes, panels):
            vals = [s[x][key] for x in NAMES]
            ax.bar(NAMES, vals, color=COLORS)
            for i,v in enumerate(vals):
                ax.text(i,v,f"{v:.2f}",ha="center",va="bottom",fontsize=9)
            ax.tick_params(axis="x",rotation=28)
            ax.set_title(title,fontsize=9)
            ax.grid(axis="y",alpha=.15)
            ax.set_ylim(0,max(vals)*1.18+1e-6)
        fig.suptitle(f"{group.replace('_', ' ')} | {len(info['clips'])} clips | released model + matching flow")
        fig.savefig(report / f"{group}_comparison.png",dpi=160)
        plt.close(fig)
        for row in info["clips"]:
            folder = ARCHIVE / row["folder"]
            fig,axes=plt.subplots(4,1,figsize=(13,8),sharex=True,layout="constrained")
            for ax,name,color in zip(axes,NAMES,COLORS):
                with h5py.File(folder/f"{name}_pred.hdf5","r") as f:
                    t,raw,ref=f["time_sec"][:],f["network_output"][:],f["reference_filtered"][:]
                ref=np.asarray(row["reference_detrended_unbandpassed_csv_time"])
                wave=detrend(np.cumsum(raw))
                # Do not choose a fitted time lag. Only polarity and scale for visualization.
                polarity=1 if np.corrcoef(wave,ref)[0,1]>=0 else -1
                ax.plot(t,ref/max(np.std(ref),1e-9),color="#999999",label="detrended manual-peak reference, before bandpass")
                ax.plot(t,polarity*wave/max(np.std(wave),1e-9),color=color,lw=1,label="integrated/detrended, before bandpass")
                with h5py.File(folder/f"{name}_freeze_probe.hdf5","r") as f:
                    frozen=detrend(np.cumsum(f["network_output"][:]))
                ax.plot(t,polarity*frozen/max(np.std(wave),1e-9),color="#df4164",lw=1,alpha=.75,label="24-30s frozen-image control")
                ax.axvspan(24,30,color="#ffbe55",alpha=.15)
                ax.set_ylabel(name)
                ax.grid(alpha=.15)
            axes[0].legend(fontsize=7,ncol=3)
            axes[-1].set_xlabel("Seconds; visualization scale/polarity only, no time alignment fit")
            fig.suptitle(f"{row['subject']} / {group}: engineering signal correspondence, not apnea validation")
            fig.savefig(folder/"waveform_before_bandpass.png",dpi=130)
            plt.close(fig)
    # A self-contained navigable report, with local images linked relatively.
    blocks=[]
    for label, info in groups.items():
        tr=[]
        for name in NAMES:
            s=info["summary"][name]
            tr.append(f"<tr><th>{name}</th><td>{s['bpm_error_vs_csv_intervals_mean']:.2f}</td><td>{s['unbandpassed_bpm_error_vs_csv_mean']:.2f}</td><td>{s['wave_abs_r_unbandpassed_csv_time_median']:.3f}</td><td>{s['pipeline_time_sec_median']:.2f}</td><td>{s['network_time_sec_median']:.3f}</td><td>{s['freeze_24_30s_rms_ratio_median']:.3f}</td></tr>")
        details=[]
        for r in info["clips"]:
            folder=r["folder"]
            details.append(f"<details><summary>{r['subject']} / {r['fps']:g} FPS / {r['retained_sec']:g} s / manual rate {r['annotation_interval_bpm']:.2f} BPM</summary><p>ROI xywh={r['roi_xywh_on_320x180']}; quality={html.escape(str(r['quality']))}</p><img src='../{folder}/roi.jpg'><img src='../{folder}/waveform_comparison.png'><img src='../{folder}/waveform_before_bandpass.png'><a href='../{folder}/summary.json'>Runtime and original metrics</a></details>")
        blocks.append(f"<h2>{label}: {len(info['clips'])} clips</h2><img src='{label}_comparison.png'><table><tr><th>Model</th><th>Official-output rate MAE vs CSV (BPM)</th><th>Before-bandpass rate MAE vs CSV (BPM)</th><th>Before-bandpass |r| median</th><th>Total s/clip median</th><th>Network s/clip median</th><th>Freeze RMS ratio median</th></tr>{''.join(tr)}</table>{''.join(details)}")
    control_block = ""
    if controls:
        native = next(x for x in groups["manual_chest"]["clips"] if x["subject"] == "S01")
        pairs=[]
        for name in NAMES:
            a,b=native["models"][name],controls[0]["models"][name]
            pairs.append(f"<tr><th>{name}</th><td>{a['bpm_error_vs_csv_intervals']:.2f} → {b['bpm_error_vs_csv_intervals']:.2f}</td><td>{a['wave_abs_r_unbandpassed_csv_time']:.3f} → {b['wave_abs_r_unbandpassed_csv_time']:.3f}</td><td>{a['pipeline_time_sec']:.2f} → {b['pipeline_time_sec']:.2f}</td></tr>")
        control_block="<h2>S01 10 → 30 FPS 중복 프레임 민감도 대조</h2><p>동일한 첫 54초 프레임을 반복한 결과입니다. 실제 30 FPS 영상은 아닙니다. 같은 180프레임 묶음의 시간 길이가 18초에서 6초로 달라집니다. 10 FPS 원본의 정규화에는 버려지는 뒤쪽 약 7초도 포함되어 이 표는 FPS 하나만 분리한 인과 실험이 아닙니다. 영상의 시간 정보·노출·잡음·압축이 실제 카메라와 같다는 뜻도 아닙니다.</p><table><tr><th>모델</th><th>CSV 기준 BPM 오차</th><th>필터 전 |r|</th><th>전체 처리 초</th></tr>"+''.join(pairs)+"</table>"
    audit_block = ""
    if (report/"roi_audit.json").is_file():
        audit_block="<h2>전체 10개 영상의 자동 Chest 영역 확인</h2><p>초록: 공식 자동 Chest. 주황: 수동 상체 대조. 수동 영역도 해부학적 정답 라벨은 아닙니다. 자동 영역이 넓어지거나 상체를 벗어난 사례가 있으므로 파형 모델 비교와 영역 검출 품질을 구분해야 합니다.</p><a href='roi_audit.json'>전체 검출 상태</a><img src='automatic_roi_audit.jpg'>"
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>AIR-400 four-model comparison</title>
<style>body{font:16px/1.6 system-ui,sans-serif;max-width:1250px;margin:40px auto;padding:0 24px;color:#182538}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:10px;border-bottom:1px solid #ccd3dc;text-align:left}img{max-width:100%;height:auto}details{margin:16px 0;padding:12px;background:#f5f7fa}summary{cursor:pointer;font-weight:650}a{color:#1766b1}.note{padding:16px;background:#fff3d9}</style>
<h1>AIR-400 네 모델 비교 실험</h1>
<p>S01~S10의 첫 번째 번호 영상을 예측 전 선택했습니다. 공개 Body 가중치를 Chest 영역에 적용하는 탐색 실험입니다. 학습 데이터와 겹치는지는 확인할 수 없어 독립 검증 성능을 뜻하지 않습니다.</p>
<h2>추천: DeepPhys + DeepFlow를 Chest 프로토타입의 첫 후보로</h2>
<p>수동 상체 대조 10개 영상에서 DeepPhys의 대역 필터 전 파형 대응도 중앙값 |r|는 0.319로 가장 높았고, 필터 전 호흡수 오차도 평균 2.35 BPM으로 가장 작았습니다. TSCAN은 전체 처리 시간이 더 짧지만 파형 대응도가 낮았습니다. EfficientPhys는 정지 출력 억제가 가장 좋았지만 파형 대응도와 필터 전 호흡수 오차에서 불리했습니다. VIRENet은 공식 후처리 호흡수 오차 3.11 BPM으로 DeepPhys 3.14 BPM과 비슷했고, 짧은 구간 호흡수 오차는 더 작았지만 파형 대응도와 정지 잔류에서는 DeepPhys가 유리했습니다.</p>
<p>이 추천은 파형 자체를 후속 이상 탐지 모델에 넣겠다는 목적에 따른 선택입니다. DeepPhys도 10개 중 4개 영상에서 대역 필터 전 |r|가 0.2 미만이므로 충실한 파형 복원이 검증됐다고 볼 수 없습니다. 자동 Chest 영역 검증, 느린 호흡·정지를 보존하는 후처리, 실제 라즈베리파이 영상 검증이 필요합니다.</p>
<p class="note">실제 호흡 정지·이상 라벨이 없습니다. 24~30초 프레임 고정은 움직임이 없을 때의 출력 잔류를 보는 공학적 대조 실험이며 실제 무호흡 검출률이 아닙니다. 수면 중 변동·기도 폐쇄를 구별하는 능력은 이 실험으로 결정할 수 없습니다.</p>
<h2>조건과 해석</h2><ul>
<li>DeepPhys+DeepFlow, TSCAN+PCAFlow, EfficientPhys 및 VIRENet+원본 Coarse2Fine. 가중치에 맞는 흐름 방식을 유지했습니다. 모든 모델은 FP32, 96×96 입력, 180프레임 묶음이며 4회 중 첫 준비 실행을 제외한 3회 네트워크 시간 중앙값입니다.</li>
<li>RTX 4060 8GB; CPU 광학 흐름: OpenCV 4스레드, Coarse2Fine 4프로세스. 전체 시간은 영상 읽기·영역·흐름·정규화·GPU 추론·후처리 합계입니다. 다운로드·첫 모델 로딩·추가 정지 대조 실험 시간은 제외했습니다. DB 전송 시간도 제외했습니다.</li>
<li>자동 Chest가 크게 잡히는 현상을 발견해 수동 상체 영역 대조를 추가했습니다. 수동 대조는 320×180 영상의 상체 사각형을 모든 모델에 동일 적용하고 흐름 계산 전 96×96으로 확대했습니다. 40픽셀 PCAFlow에서 프로세스가 종료되는 현상을 피하기 위한 동일 처리입니다. 자동 실험은 공식 영역과 흐름 해상도를 유지했습니다. 수동 총 시간에는 자동 검출 시간이 없습니다.</li>
<li>HDF5 기준 파형은 수동 호흡점의 Gaussian 평활 신호입니다. 호흡량·공기 흐름의 실측 신호가 아닙니다. CSV 시작 시각 간격으로 별도 호흡수 기준을 계산했습니다.</li>
<li>HDF5의 600개 샘플을 10Hz로 해석했을 때 호흡 피크 시각이 CSV와 약 0.04~0.06초 평균 차이로 일치했습니다. 이에 근거한 시간축으로 대역 필터 전 대응도를 계산했습니다. 이는 HDF5 속성에 명시된 샘플링률이 아니라 주석과의 대조로 추론한 값입니다. 공식 로더처럼 전체 프레임 수에 단순 보간한 결과도 JSON에 별도로 보존했습니다.</li>
<li>공식 0.3~1Hz(18~60 BPM) 후처리는 느린 호흡의 기본 주파수를 제외할 수 있습니다. 따라서 공식 HDF 기준의 오차와 별도로 CSV 간격 대비 호흡수 오차 및 대역 필터 전 대응도를 함께 계산했습니다. |r|는 3초씩 양 끝을 제외하고 위상 이동을 맞추지 않은 절댓값입니다. 부호는 학습 신호의 방향 차이를 허용합니다. 높을수록 좋지만 파형 정확도 전체를 보증하지 않습니다.</li>
<li>대역 필터 전 호흡수 진단은 적분·추세 제거를 한 신호의 FFT에서 0.08~1Hz(약 5~60 BPM)를 검색했습니다. 고정 대역 필터를 적용한 출력과는 다른 진단 지표입니다. 원본 추세 제거의 λ=100도 고정 샘플 단위 설정이어서 FPS에 따라 물리적 시간 효과가 달라집니다. 모든 모델에 같은 진단 방식을 적용했습니다.</li>
<li>원본은 10 FPS 9개, 15 FPS 1개입니다. 180프레임 단위에 맞춰 10 FPS는 54초, 15 FPS는 60초를 평가했습니다. S01의 같은 첫 54초를 중복 프레임으로 30 FPS로 만든 실험은 시간 해상도를 추가하지 않는 민감도 대조이며 실제 라즈베리파이 30 FPS 검증이 아닙니다.</li>
<li>Freeze RMS 비율은 24~30초 프레임 고정 후 25~29초 출력 RMS / 같은 구간 원본 출력 RMS입니다. 0에 가까울수록 정지 시 출력 감소가 큽니다. 필터 잔향, 전체 정규화, 경계 변화의 영향도 포함하므로 진단 지표로 사용할 수 없습니다.</li>
</ul>
<p><a href="analysis.json">모든 분석 수치(JSON)</a> · <a href="protocol.json">실험 범위·코드 SHA256</a> · <a href="../../00_공통자료/assets.json">출처·파일 SHA256</a> · <a href="../results_manual_chest/environment.json">실행 환경</a> · <a href="../results_manual_chest/model_details.json">가중치·설정</a> · <a href="validation.json">구현 일치 검증</a></p>
'''+''.join(blocks)+control_block+audit_block+"</html>"
    (report/"index.html").write_text(page,encoding="utf-8")


if __name__ == "__main__":
    main()
