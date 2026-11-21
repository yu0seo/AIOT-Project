"""Generate transparent held-out A/B/C results and PT-ready artifacts."""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import shutil
import statistics
import platform
import importlib.metadata

from chest_study_core import CONFIG, FINETUNE, BEFORE, AFTER, PRESENTATION, PROJECT, save_json, load_manifest
from chest_study_metrics import read_row, pool
from chest_study_media import NAMES, summary_plot, waveform_plot, paired_video, detection_comparison, split_plot
from chest_study_prepare import write_image
import cv2
import numpy as np


def fmt(value, digits=3):
    return "—" if value is None else f"{float(value):.{digits}f}"


def main():
    model=FINETUNE/"models/chest_yolov8m_best.pt"
    if not model.exists():raise RuntimeError("Cannot evaluate a fine-tuned test condition before training is complete")
    manifest=load_manifest()
    rule=json.loads((CONFIG/"peak_rule.json").read_text(encoding="utf-8"))["rule"]
    protocol=json.loads((CONFIG/"controlled_protocol.json").read_text(encoding="utf-8"))
    annotation=json.loads((CONFIG/"chest_annotations.json").read_text(encoding="utf-8"))
    audit=json.loads((CONFIG/"split_audit.json").read_text(encoding="utf-8"))
    training=json.loads((CONFIG/"training_result.json").read_text(encoding="utf-8"))
    with (Path(training["run_directory"])/"results.csv").open(encoding="utf-8-sig",newline="") as handle:
        epoch_rows=list(csv.DictReader(handle))
    best_epoch=max(epoch_rows,key=lambda r:.1*float(r["metrics/mAP50(B)"])+.9*float(r["metrics/mAP50-95(B)"]))
    training["actual_epochs_completed"]=len(epoch_rows)
    training["best_validation_epoch_from_csv"]=int(best_epoch["epoch"])
    if training["selection"]=="best validation mAP50-95":
        training["initial_selection_description"]=training["selection"]
        training["selection"]="Ultralytics validation fitness: 0.1*mAP50 + 0.9*mAP50-95"
        training["selection_clarification"]="Corrected description after inspecting Ultralytics 8.3.96 Metric.fitness; the running training/default selection was not changed and test data were not used."
    save_json(CONFIG/"training_result.json",training)
    rows=[read_row(c,item,rule) for item in manifest["samples"] for c in "ABC"]
    groups={s:{c:pool([r for r in rows if r["split"]==s and r["condition"]==c]) for c in "ABC"} for s in ("train","val","test")}
    test=groups["test"]
    a,c=test["A"],test["C"]
    delta={k:c[k]-a[k] for k in ("roi_mean_iou_mean","pooled_f1","pooled_recall","wave_abs_r_mean","bpm_count_abs_error_mean","pipeline_sec_mean")}
    roi_improved=delta["roi_mean_iou_mean"]>0
    interval_comparable=a["interval_mae_sec_mean"] is not None and c["interval_mae_sec_mean"] is not None
    interval_improved=interval_comparable and c["interval_mae_sec_mean"]<=a["interval_mae_sec_mean"] and c["interval_mae_sec_valid_clips"]>=a["interval_mae_sec_valid_clips"]
    waveform_consistent=(delta["pooled_f1"]>0 and delta["wave_abs_r_mean"]>0 and delta["bpm_count_abs_error_mean"]<=0 and interval_improved)
    roi_sentence="시험 참조 박스와의 겹침은 증가했습니다." if roi_improved else "시험 참조 박스와의 겹침이 개선되지 않았습니다."
    wave_sentence=("파형 F1·대응도·호흡수·간격 오차가 지정한 방향으로 함께 개선됐습니다. 다만 이 소규모 시험 집합에서 관찰된 결과입니다."
                   if waveform_consistent else "파형의 주요 지표가 모두 함께 개선되지는 않았습니다. 전체 파형 성능이 개선됐다고 단정하지 않습니다.")
    if c["roi_failure_fraction_mean"]>=1-1e-12:
        wave_sentence="시험의 모든 Chest 탐지 시도가 실패해 C 파형은 중앙 대체 영역에서 추출됐습니다. 파형 수치의 변화를 Chest 파인튜닝의 성공으로 해석할 수 없습니다."
    recommendation=("이번 파인튜닝 가중치를 기존 ROI 모듈의 대체 모델로 채택할 근거가 부족합니다."
                    if not(roi_improved and waveform_consistent and c["roi_failure_fraction_mean"]<=a["roi_failure_fraction_mean"])
                    else "소규모 비교에서 가능성을 확인했습니다. 다양한 독립 촬영 대상과 실제 카메라 영상으로 다음 검증을 진행해야 합니다.")
    output=PRESENTATION/"03_전체시험성능"
    output.mkdir(parents=True,exist_ok=True)
    analysis={"generated_at":datetime.now().astimezone().isoformat(),"protocol":protocol,"split_audit":audit,
              "frozen_peak_rule":rule,"training_checkpoint_sha256":hashlib.sha256(model.read_bytes()).hexdigest(),
              "summaries":groups,"test_delta_C_minus_A":delta,"conclusion":{"roi":roi_sentence,"waveform":wave_sentence,"recommendation":recommendation},"clips":rows}
    save_json(output/"controlled_comparison.json",analysis)
    columns=["id","split","source_group","condition","roi_iou","roi_failure_fraction","wave_abs_r","f1","precision","recall",
             "tp","fp","fn","interval_mae_sec","matched_interval_count","bpm_count_abs_error","processing_sec"]
    with (output/"per_clip_metrics.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for row in rows:
            m=row["primary_waveform"]
            writer.writerow({"id":row["id"],"split":row["split"],"source_group":row["source_group"],"condition":row["condition"],
                "roi_iou":row["roi_metrics"]["mean_iou"],"roi_failure_fraction":row["roi_metrics"]["failure_fraction"],
                **{k:m[k] for k in ("wave_abs_r","f1","precision","recall","tp","fp","fn","interval_mae_sec","matched_interval_count","bpm_count_abs_error")},
                "processing_sec":row["pipeline_sec"]})
    summary_plot(test)
    split_plot(groups)
    media=[]
    for item in manifest["samples"]:
        if item["split"]!="test":continue
        selected=[next(r for r in rows if r["id"]==item["id"] and r["condition"]==condition) for condition in "ABC"]
        graph=waveform_plot(item,selected,rule)
        video=paired_video(item,selected)
        detection_comparison(item,selected)
        media.append({"id":item["id"],"graph":graph.relative_to(PRESENTATION).as_posix(),"video":video.relative_to(PRESENTATION).as_posix(),
                      "f1_delta":selected[2]["primary_waveform"]["f1"]-selected[0]["primary_waveform"]["f1"],
                      "correlation_delta":selected[2]["primary_waveform"]["wave_abs_r"]-selected[0]["primary_waveform"]["wave_abs_r"]})
    case_dir=PRESENTATION/"04_개선실패사례"
    case_dir.mkdir(exist_ok=True)
    for item in manifest["samples"]:
        if item["split"]!="test":continue
        pictures=[]
        for condition in ("A","C"):
            from chest_study_core import CONDITION_ROOTS
            path=CONDITION_ROOTS[condition]/"bounding_boxes/control_v1"/(item["id"]+"_roi.jpg")
            pictures.append(cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR))
        write_image(case_dir/(item["id"]+"_roi_before_after.jpg"),np.concatenate(pictures,axis=0))
    ranked=sorted(media,key=lambda r:r["f1_delta"],reverse=True)
    save_json(case_dir/"all_test_cases_ranked.json",{"ranking":"C-A F1; every held-out clip included, not used for model selection","cases":ranked})
    label_dir=PRESENTATION/"06_라벨링데이터샘플"
    label_samples=[]
    for item in manifest["samples"]:
        destination=label_dir/item["split"]
        destination.mkdir(parents=True,exist_ok=True)
        shutil.copy2(FINETUNE/"labeling_samples"/(item["id"]+"_label_sample.jpg"),destination/(item["id"]+"_label_sample.jpg"))
        record=[r for r in annotation["images"] if r["id"]==item["id"]][14]
        shutil.copy2(FINETUNE/record["label"],destination/(item["id"]+"_yolo_label.txt"))
        label_samples.append({"id":item["id"],"split":item["split"],"sample_image":record["image"],"sample_label":record["label"],"image_sha256":record["image_sha256"]})
    save_json(label_dir/"label_provenance.json",{"annotator":annotation["annotator"],"temporal_method":annotation["temporal_method"],
               "definition":annotation["definition"],"split_audit":audit,
               "samples":label_samples,"note":"Only train/ examples were used to update YOLO weights; val/test samples are explicitly separated."})
    sample_ids=("S01_1","S05_1","S07_01","S10_1")
    label_pictures=[]
    for sample_id in sample_ids:
        assert next(s for s in manifest["samples"] if s["id"]==sample_id)["split"]=="train"
        path=label_dir/"train"/(sample_id+"_label_sample.jpg")
        label_pictures.append(cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR))
    write_image(label_dir/"training_label_samples.jpg",np.concatenate([np.concatenate(label_pictures[:2],axis=1),np.concatenate(label_pictures[2:],axis=1)],axis=0))
    overview=PRESENTATION/"05_실험개요"
    overview.mkdir(exist_ok=True)
    (overview/"PT_설명문.txt").write_text(f'''발표에 사용할 수 있는 설명

AIR-400 공개 영상에서 Chest 영역 추출을 개선하면 DeepPhys 파형도 개선되는지 확인했습니다.
20클립의 600개 프레임에 AI 보조 상체 라벨을 만들고 촬영 원본 그룹을 나눴습니다.
학습 14클립, 검증 2클립, 시험 4클립을 사용했습니다.
같은 DeepPhys 가중치와 전처리를 유지하고 기존 자동 영역 A, 수동 참조 영역 B,
Chest 전용 YOLO 파인튜닝 C를 비교했습니다. B는 학습된 검출 모델이 아닙니다.

시험 결과 (A -> C)
Chest 박스 IoU: {a['roi_mean_iou_mean']:.3f} -> {c['roi_mean_iou_mean']:.3f}
ROI 실패 비율: {100*a['roi_failure_fraction_mean']:.1f}% -> {100*c['roi_failure_fraction_mean']:.1f}%
호흡점 F1: {a['pooled_f1']:.3f} -> {c['pooled_f1']:.3f}
파형 대응도 |r|: {a['wave_abs_r_mean']:.3f} -> {c['wave_abs_r_mean']:.3f}
호흡수 MAE: {a['bpm_count_abs_error_mean']:.2f} -> {c['bpm_count_abs_error_mean']:.2f} BPM
연속 대응 호흡 간격 MAE: {fmt(a['interval_mae_sec_mean'])} -> {fmt(c['interval_mae_sec_mean'])} 초

허용되는 결론
{roi_sentence}
{wave_sentence}
{recommendation}

해석 범위
실제 시험 집합은 4클립, 보수적으로 묶은 원본 그룹 1개입니다.
독립 전문가가 검수한 해부학적 정답이나 실제 기도 폐쇄 사건 라벨은 없습니다.
따라서 이 결과를 영유아 전체의 무호흡 검출률, 질식 예방 성능,
정상/비정상 알림 정확도로 발표하면 안 됩니다.
실제 라즈베리파이 30FPS 입력과 실시간 지연은 별도 검증 대상입니다.

자료 선택
01: 동일 영상 좌우 비교. 굵은 박스는 실제 파형 추출에 사용한 고정 영역.
02: 공개 호흡 주석과 A/B/C 파형, A/C 실제 출력값 공통 세로축.
03: 시험 전체 요약 그래프와 모든 클립의 원시 지표 표.
04: 집계 전 실제 검출 박스와 모든 시험 사례. 좋은 사례만 골라 제시하지 않음.
06: 실제 이미지·YOLO 라벨 예시. train/val/test를 구분해 표시.
''',encoding="utf-8")
    import torch
    save_json(overview/"environment.json",{"python":platform.python_version(),"platform":platform.platform(),
        "packages":{name:importlib.metadata.version(name) for name in ("torch","torchvision","ultralytics","numpy","scipy","h5py","matplotlib","opencv-contrib-python-headless")},
        "cuda_runtime":torch.version.cuda,"gpu":torch.cuda.get_device_name(0),
        "training_amp":False,"inference_flow_backend":"OpenCV DeepFlow","study_seed":42})
    (overview/"파형파일_사용안내.txt").write_text('''통제 비교(control_v1) 파형 파일 안내

A: 01_파인튜닝전/waveforms/control_v1/
B: 02_Chest_파인튜닝/manual_control/waveforms/control_v1/ (수동 참조)
C: 03_파인튜닝후/waveforms/control_v1/
각 조건 20개 HDF5. 동일 영상에는 동일 파일명, 시간축, 공개 주석을 사용합니다.

time_sec: 영상 시작 기준 초. 각 파일의 원본 FPS를 사용합니다.
network_output: 적분 전 DeepPhys 네트워크 출력.
respiration: network_output 누적합 후 추세 제거, 대역 필터 적용 전 주지표 신호.
respiration_filtered: respiration에 공식 0.3~1.0Hz 필터 적용한 보조 신호.
motion_level_raw_flow: 정규화 전 광학 흐름 크기의 프레임별 중앙값.
reference / reference_detrended: 공개 호흡점 주석 기반 기준 신호, 실측 호흡량 아님.
annotation_peaks_sec: 공개 CSV 호흡점 시각. 신호 배열과 길이가 다릅니다.

180프레임 단위 추론이므로 끝의 남는 프레임은 제외합니다.
기존 파일럿 S01_1_pilot_pred.hdf5의 respiration은 필터 적용 후 값입니다.
파일럿과 control_v1을 자동으로 섞어서 학습하지 마세요.
동일 시간축 그래프의 표준화는 표시용이며 HDF5에는 실제 계산값을 보존했습니다.
모델 출력 크기는 호흡량이나 생리학적 절대 단위로 해석할 수 없습니다.

읽는 예:
import h5py
with h5py.File("S03_1_pred.hdf5", "r") as f:
    time_sec = f["time_sec"][:]
    waveform = f["respiration"][:]

이번 시험은 ROI 및 파형 비교입니다. 단일 클래스 이상 탐지 모델을 학습하거나
정상/비정상 임계값, 실시간 무호흡 알림 성능을 검증한 결과는 아닙니다.
''',encoding="utf-8")
    for name in ("controlled_protocol.json","study_manifest.json","split_audit.json","peak_rule.json","training_result.json","annotation_review.json","selection_clarification.json","training_amendment.json","training_result_chest_v1.json","training_result_chest_frozen_v2.json"):
        if not (CONFIG/name).exists():continue
        shutil.copy2(CONFIG/name,overview/name)
    for root in (BEFORE,AFTER):
        for name in ("controlled_protocol.json","study_manifest.json","peak_rule.json"):
            shutil.copy2(CONFIG/name,root/"configs"/name)
    shutil.copy2(CONFIG/"training_result.json",AFTER/"configs/training_result.json")
    for source_name,target_name in (("results.png","yolo_training_curve.png"),("results.csv","yolo_training_results.csv")):
        source=Path(training["run_directory"])/source_name
        if source.exists():shutil.copy2(source,overview/target_name)
    save_json(overview/"script_hashes.json",{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("chest_study_*.py")})
    table=[]
    for condition in "ABC":
        s=test[condition]
        table.append(f"<tr><th>{condition} {NAMES[condition]}</th><td>{fmt(s['roi_mean_iou_mean'])}</td><td>{100*s['roi_failure_fraction_mean']:.1f}%</td><td>{fmt(s['pooled_f1'])}</td><td>{fmt(s['pooled_recall'])}</td><td>{fmt(s['wave_abs_r_mean'])}</td><td>{fmt(s['bpm_count_abs_error_mean'],2)}</td><td>{fmt(s['interval_mae_sec_mean'])} ({s['interval_mae_sec_valid_clips']}/4)</td><td>{fmt(s['pipeline_sec_mean'],1)}</td></tr>")
    details=[]
    for m in media:
        item=next(s for s in manifest["samples"] if s["id"]==m["id"])
        details.append(f"<details><summary>{m['id']} · F1 변화 {m['f1_delta']:+.3f} / |r| 변화 {m['correlation_delta']:+.3f}</summary><video controls preload='metadata' src='../{m['video']}'></video><p><a href='../{m['video']}'>좌우 비교 영상 파일</a> · 영상의 굵은 박스는 클립 집계 후 실제 파형 추출에 사용한 고정 영역입니다.</p><p>아래는 집계 전 실제 프레임별 검출 박스입니다. 위 A / 아래 C · 노랑은 AI 보조 참조 라벨.</p><img src='../04_개선실패사례/{m['id']}_raw_detections.jpg'><img src='../{m['graph']}'><img src='../02_전후파형그래프/{m['id']}_AC_raw_values.png'></details>")
    validation_ap=training.get("results",{}).get("metrics/mAP50-95(B)")
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>Chest 파인튜닝 전후 검증</title>
<style>body{font:16px/1.65 system-ui,sans-serif;color:#192b42;max-width:1280px;margin:36px auto;padding:0 22px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:10px;border-bottom:1px solid #d4dce6;text-align:left}img,video{max-width:100%;height:auto}.note{padding:16px;background:#fff0cf;border-radius:8px}.result{padding:18px;background:#eaf3ff;border-radius:8px}details{padding:14px;margin:14px 0;background:#f4f7fa}summary{font-weight:650;cursor:pointer}a{color:#1d68ab}code{background:#eef2f6;padding:2px 5px}</style>
<h1>Chest 파인튜닝 전후 · 통제 비교 결과</h1>
'''+f"<p class='result'>{roi_sentence}<br>{wave_sentence}<br>{recommendation}</p>"+'''
<p class="note">이 시험은 Chest 영역 추출 모듈의 비교입니다. 실제 무호흡·기도 폐쇄 라벨을 사용한 검출 성능이 아닙니다. Chest 박스는 AI 보조 시각 주석이며 독립적인 전문가 검수는 없습니다. 시험 4클립은 보수적으로 묶은 원본 그룹 1개에 속합니다. 영상 수·프레임 수를 독립적인 영유아 수로 해석하지 마세요.</p>
<h2>고정 시험 집합 결과</h2><img src="../03_전체시험성능/test_summary.png">
<table><tr><th>조건</th><th>박스 IoU ↑</th><th>ROI 실패 ↓</th><th>호흡점 F1 ↑</th><th>재현율 ↑</th><th>파형 |r| ↑</th><th>호흡수 MAE ↓</th><th>간격 MAE 초 ↓ (유효 클립)</th><th>처리 초/클립</th></tr>'''+''.join(table)+'''</table>
<p>F1·재현율은 시험 전체 호흡점 TP/FP/FN을 합산했습니다. IoU·|r|·호흡수 오차·처리 시간은 영상별 값의 평균입니다. 간격 오차는 양쪽 모두 연속으로 대응된 호흡쌍만 평가하므로 유효 클립 수를 함께 표시합니다. 실패 영상도 표에서 제외하지 않았습니다.</p>
<p>ROI 실패는 10프레임 간격 탐지 시도의 실패 비율입니다. C는 confidence 0.25를 사용하며, 클립 전체에서 검출이 없으면 기존 집계 함수의 중앙 180×180 영역으로 대체합니다. 이때 생성된 파형은 Chest 검출 성공의 증거가 아닙니다. 실패를 숨기지 않고 IoU는 0으로 평가했습니다.</p>
<h2>무엇을 바꾸고 무엇을 고정했나</h2><ul>
<li>A: 기존 YOLO Body·Face 검출 → 계산식 Chest. B: 검수한 수동 상체 영역. C: YOLOv8m을 Chest 1클래스로 파인튜닝해 직접 검출.</li>
<li>세 조건 모두 영상과 구간·FPS, 광학 흐름 입력 96×96, DeepFlow, DeepPhys 가중치, 정규화, 180프레임 묶음, 추세 제거를 고정했습니다. B는 수동 참조 조건이며 운영 모델이 아닙니다.</li>
<li>박스는 같은 중앙값 중심/75백분위 크기 집계 원칙으로 클립당 고정해 잘라냅니다. 단, A/C는 다른 ROI 모듈이므로 가중치 하나만 교체한 실험은 아닙니다.</li>
<li>주지표 파형은 네트워크 출력 적분 + λ=100 추세 제거 후 대역 필터 전 신호입니다. 공식 18~60BPM 필터 출력도 HDF5에 따로 보존했습니다.</li>
<li>CSV 호흡점의 실제 시각을 사용합니다. HDF5 기준 신호의 10Hz 시간축은 CSV 피크와 대조해 확인했습니다. 기준 신호는 호흡점 주석이며 실측 가슴 변위·호흡량이 아닙니다.</li>
<li>호흡점 추출 부호·prominence·최소 간격은 A/B 검증 영상으로만 선택한 하나의 공통 규칙입니다. 시험 영상별 위상·시간 이동 맞춤은 하지 않았습니다. 양 끝 3초를 제외하고 ±0.5초 안에서 일대일 대응을 평가했습니다.</li>
<li>고정된 호흡점 최소 간격은 1초입니다. 이 규칙으로 빠른 호흡을 평가하는 데 한계가 있으며 일반적인 영유아 호흡 범위의 성능을 보장하지 않습니다. |r|은 0지연 상관의 절댓값으로 신호의 부호 반전을 허용하므로 실제 흡기·호기 방향의 정확도를 뜻하지 않습니다.</li>
<li>호흡수는 예측과 주석 모두 같은 평가 구간의 호흡점 개수/구간 길이로 계산했습니다. 그림의 표준화는 표시용이며 원값 그림도 함께 제공합니다.</li>
</ul>
<h2>데이터·학습·한계</h2>
<img src="../03_전체시험성능/split_generalization.png">
'''+f"<p>20클립 / 이미지 600장: 학습 {audit['images']['train']}장(14클립), 검증 {audit['images']['val']}장(2클립), 시험 {audit['images']['test']}장(4클립). 원본 그룹: {html.escape(str(audit['groups']))}. 동일 이미지 해시 겹침은 없습니다.</p><p>YOLO 검증 mAP50-95: {fmt(validation_ap)}. 이는 검증 집합의 지표이며 위 시험 성능과 다릅니다. 실제 체크포인트·조기 종료 선택은 Ultralytics 기본 검증 fitness(0.1×mAP50 + 0.9×mAP50-95)를 사용합니다. 사전 문서의 ‘mAP50-95’라는 설명을 구현의 정확한 계산식으로 명확히 했으며, 실행 중 선택 규칙을 변경하거나 시험 집합을 사용하지 않았습니다.</p>"+'''
<p>초기 전체 학습에서 검증 성능이 무너져, 시험 C 추론 전에 backbone 10개 층 고정·학습률 0.0003 설정을 한 번 추가했습니다. 두 실행의 최고 검증 fitness로 최종 모델을 선택했습니다. 두 실행 기록과 변경 시점을 보존했으며 시험 결과로 재학습하지 않았습니다.</p>
<p>라벨은 정적인 클립의 상체 사각형을 샘플 프레임에 전파하고 접촉표로 확인한 AI 보조 주석입니다. 독립 사람 검수와 다양한 대상 추가 검증이 필요합니다. DeepPhys의 원래 학습 데이터와 이번 영상의 중복 여부는 알 수 없습니다. 실제 라즈베리파이 30FPS 검증도 포함하지 않습니다.</p>
<p>처리 시간은 RTX 4060에서 영상 디코딩·영역·광학 흐름·패킹·추론·후처리 단계의 합계입니다. 네트워크는 준비 실행 제외 3회 중앙값, 광학 흐름은 1회입니다. 다운로드·첫 모델 로딩·DB 전송은 제외했습니다. B는 자동 탐지 시간이 없습니다.</p>
<p>전체 클립 정규화와 양방향 필터를 쓰는 배치 실험입니다. 실시간 인과 추론·알림 지연을 검증한 결과는 아닙니다.</p>
<h2>시험 영상별 결과 · 모두 공개</h2>'''+''.join(details)+'''
<h2>실제 학습 라벨 샘플</h2><p>아래 노란 박스는 학습 이미지에 사용한 AI 보조 상체 라벨입니다. 검출 모델의 예측 박스가 아닙니다. 이 네 예시는 train 분할에 속하며 검증·시험 예시는 별도 폴더에 보존했습니다.</p>
<img src="../06_라벨링데이터샘플/training_label_samples.jpg">
<h2>파일과 재현 정보</h2><ul>
<li><a href="../03_전체시험성능/controlled_comparison.json">전체 JSON 지표 · 학습/검증/시험 모두</a></li>
<li><a href="../03_전체시험성능/per_clip_metrics.csv">영상별 CSV · Excel용 UTF-8 BOM</a></li>
<li><a href="controlled_protocol.json">사전 고정 비교 조건</a> · <a href="study_manifest.json">영상 선택·분리 목록</a> · <a href="split_audit.json">누수 확인</a></li>
<li><a href="peak_rule.json">검증셋에서 고정한 호흡점 규칙</a> · <a href="training_result.json">YOLO 학습·체크포인트 정보</a></li>
<li><a href="training_amendment.json">검증 성능에 따른 추가 학습 설정</a> · <a href="training_result_chest_v1.json">첫 학습 기록</a> · <a href="training_result_chest_frozen_v2.json">일부 층 고정 학습 기록</a></li>
<li><a href="yolo_training_curve.png">YOLO 학습 곡선</a> · <a href="yolo_training_results.csv">에포크별 실제 학습 기록</a> · <a href="annotation_review.json">라벨 접촉표 확인 기록</a></li>
<li><a href="파형파일_사용안내.txt">HDF5 저장 필드와 읽는 방법</a></li>
<li><a href="PT_설명문.txt">수치와 범위를 포함한 발표 설명문</a></li>
<li><a href="../06_라벨링데이터샘플/label_provenance.json">실제 라벨 샘플 출처</a> · <a href="script_hashes.json">실행 코드 SHA256</a></li>
<li><a href="environment.json">실행 라이브러리·GPU 환경</a></li>
<li><a href="../../index.html">프로젝트 폴더 안내</a></li>
</ul></html>'''
    (overview/"index.html").write_text(page,encoding="utf-8")
    # Clear the initial placeholders now that real artifacts exist.
    for folder in [PRESENTATION/x for x in ("01_좌우비교영상","02_전후파형그래프","03_전체시험성능","04_개선실패사례","05_실험개요","06_라벨링데이터샘플")]:
        (folder/"상태.txt").write_text("자료 생성 완료. 05_실험개요/index.html에서 결과와 범위를 확인하세요.\n",encoding="utf-8")
    save_json(PROJECT/"comparison_status.json",{"status":"completed_exploratory","clips":20,"test_clips":4,"test_source_groups":1,
             "report":str((overview/"index.html").relative_to(PROJECT)).replace("\\","/"),"conclusion":analysis["conclusion"]})
    print(json.dumps({"test":test,"delta":delta,"conclusion":analysis["conclusion"]},ensure_ascii=False,indent=2),flush=True)


if __name__=="__main__":main()
