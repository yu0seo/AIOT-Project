"""교차검증으로 고정한 후보 재학습과 기존 홀드아웃의 짝지은 비교."""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from .data import build_manifest, fit_normalizer, make_windows, prepare_tracks
from .experiment import bundle_metadata, prediction_frame, train_model, write_json
from .features import FeatureConfig
from .metrics import binary_metrics, evaluate_predictions, select_balanced_threshold, select_threshold
from .model import predict_scores
from .tuning import candidate_config, normalized_subset


def paired_bootstrap(frame, candidate_threshold, baseline_threshold, repeats, seed):
    """같은 참가자를 함께 재추출해 두 모델 지표 차이의 구간을 계산한다."""
    rng = np.random.default_rng(seed)
    groups = [group for _, group in frame.groupby("participant", sort=True)]
    differences = {key: [] for key in ("roc_auc", "accuracy", "recall", "fpr")}
    for _ in range(repeats):
        sample = pd.concat([groups[i] for i in rng.integers(0, len(groups), len(groups))], ignore_index=True)
        improved = binary_metrics(sample.label, sample.score, candidate_threshold)
        baseline = binary_metrics(sample.label, sample.baseline_score, baseline_threshold)
        for key in differences:
            differences[key].append(improved[key]-baseline[key])
    return {key: np.quantile(values, [.025, .975]).tolist() if values else None
            for key, values in differences.items()}


def finalize_search(data_root, search_run, reference_run):
    search_run, reference_run = Path(search_run), Path(reference_run)
    output = search_run/"final"
    output.mkdir(exist_ok=False)
    base = json.loads((search_run/"base_config.json").read_text(encoding="utf-8"))
    search = json.loads((search_run/"search_config.json").read_text(encoding="utf-8"))
    selection = json.loads((search_run/"cv_selection.json").read_text(encoding="utf-8"))
    splits = json.loads((search_run/"reference_splits.json").read_text(encoding="utf-8"))
    if splits != json.loads((reference_run/"splits.json").read_text(encoding="utf-8")):
        raise ValueError("탐색에 사용한 참조 분할과 최종 비교 대상이 다릅니다.")
    torch.set_num_threads(base["cpu_threads"])
    root, manifest = build_manifest(data_root, base)
    development = splits["train"]+splits["validation"]
    selected = max(selection["winners"], key=lambda row: (row["mean_macro_auc"], row["mean_macro_recall"], -row["seconds"]))
    write_json(output/"selection_before_test.json", {"selected_seconds": selected["seconds"],
               "winners": selection["winners"], "source": "기존 train 참가자 내부 CV", "test_accessed": False})
    models, metadata, results = {}, {}, []
    for winner in selection["winners"]:
        seconds = int(winner["seconds"])
        candidate = next(row for row in search["candidates"] if row["name"] == winner["candidate"])
        config = candidate_config(base, candidate, search, 0)
        config.update(epochs=base["epochs"], patience=base["patience"], quiet_epochs=False)
        feature_config = FeatureConfig(**config["feature"])
        chosen_manifest = manifest.copy()
        chosen_manifest["included"] &= chosen_manifest.participant.isin(development)
        tracks, audit = prepare_tracks(root, chosen_manifest, feature_config)
        directory = output/f"{seconds}s"
        directory.mkdir()
        audit.to_csv(directory/"development_audit.csv", index=False)
        normalizer = fit_normalizer(tracks, splits["train"], candidate["transform"])
        anchor = max(base["window_seconds"])*feature_config.sample_hz+selection["common_warmup_points"]-candidate["smooth_points"]
        raw = make_windows(tracks, development, seconds*feature_config.sample_hz, feature_config.sample_hz, anchor)
        train = normalized_subset(raw, splits["train"], normalizer)
        validation = normalized_subset(raw, splits["validation"], normalizer)
        model, training = train_model(train, validation, config, directory, "cpu")
        frame = prediction_frame(validation, predict_scores(model, validation["x"]))
        operating_point = select_threshold(frame, base["max_validation_fpr"])
        auxiliary_point = select_balanced_threshold(frame)
        meta = bundle_metadata(config, feature_config, normalizer, seconds, training, splits,
                               operating_point, anchor, feature_config.sample_hz)
        meta.update(candidate=candidate, cv=winner, auxiliary_balanced_operating_point=auxiliary_point)
        write_json(directory/"metadata.json", meta)
        frame.to_csv(directory/"validation_predictions.csv", index=False)
        write_json(directory/"training_config.json", config)
        models[seconds], metadata[seconds] = model, meta
        results.append({"seconds": seconds, "candidate": candidate, "cv": winner,
                        "validation": evaluate_predictions(frame, operating_point["threshold"], 0),
                        "auxiliary_balanced_threshold": auxiliary_point,
                        "train_window_n": len(train["y"]), "validation_window_n": len(validation["y"])})
    # 후보와 모든 임계값을 저장한 뒤에만 test 좌표와 기존 test 예측을 연다.
    for result in results:
        seconds = result["seconds"]
        meta = metadata[seconds]
        feature_config = FeatureConfig(**meta["feature_config"])
        test_manifest = manifest.copy()
        test_manifest["included"] &= test_manifest.participant.isin(splits["test"])
        tracks, audit = prepare_tracks(root, test_manifest, feature_config)
        directory = output/f"{seconds}s"
        audit.to_csv(directory/"test_audit.csv", index=False)
        raw = make_windows(tracks, splits["test"], meta["timesteps"], meta["stride_steps"], meta["comparison_anchor_steps"])
        test = normalized_subset(raw, splits["test"], meta["normalizer"])
        frame = prediction_frame(test, predict_scores(models[seconds], test["x"]))
        frame["prediction"] = (frame.score >= meta["threshold"]).astype(int)
        frame.to_csv(directory/"test_predictions.csv", index=False)
        result["test"] = evaluate_predictions(frame, meta["threshold"], base["bootstrap_repeats"], base["seed"])
        result["test_at_0_5"] = binary_metrics(frame.label, frame.score, .5)
        result["test_at_balanced_threshold"] = evaluate_predictions(
            frame, result["auxiliary_balanced_threshold"]["threshold"], 0)
        previous = pd.read_csv(reference_run/f"{seconds}s"/"test_predictions.csv")
        paired = frame.merge(previous[["participant", "scenario_id", "end_ns", "label", "score"]],
                             on=["participant", "scenario_id", "end_ns"], suffixes=("", "_baseline"), validate="one_to_one")
        if len(paired) != len(frame) or not np.array_equal(paired.label, paired.label_baseline):
            raise ValueError("기준 모델과 같은 끝 시각의 테스트 Window를 연결할 수 없습니다.")
        paired = paired.rename(columns={"score_baseline": "baseline_score"})
        previous_meta = json.loads((reference_run/f"{seconds}s"/"metadata.json").read_text(encoding="utf-8"))
        result["baseline_on_same_windows"] = binary_metrics(paired.label, paired.baseline_score, previous_meta["threshold"])
        result["paired_difference_95ci"] = paired_bootstrap(
            paired, meta["threshold"], previous_meta["threshold"], base["bootstrap_repeats"], base["seed"])
        paired.to_csv(directory/"paired_predictions.csv", index=False)
        write_json(directory/"metrics.json", result)
    best = output/"best"
    best.mkdir()
    for name in ("model.pt", "metadata.json"):
        shutil.copyfile(output/f"{selected['seconds']}s"/name, best/name)
    report = {"selected_seconds": selected["seconds"], "selection": selection, "results": results,
              "evaluation_limit": "기존 test 결과를 본 뒤 수행한 후속 연구. 새로운 외부 검증이 필요함."}
    write_json(output/"results.json", report)
    write_improvement_report(output/"REPORT.md", report)
    print(json.dumps({"selected_seconds": selected["seconds"], "output": str(output)}, ensure_ascii=False), flush=True)
    return report


def write_improvement_report(path, report):
    selected_result = next(row for row in report["results"] if row["seconds"] == report["selected_seconds"])
    interval = selected_result["paired_difference_95ci"]["roc_auc"]
    conclusion = "선택 후보의 AUC 개선을 확인했다. 실제 CCTV 외부 검증은 별도로 필요하다."
    if interval is None or interval[0] <= 0:
        conclusion = "현재 실험에서는 일반화 성능의 의미 있는 개선을 확인하지 못했다. 기존 best를 교체하지 않는다."
    lines = ["# IDD 성능 개선 실제 측정 결과", "", f"**{conclusion}**", "", report["evaluation_limit"], "",
             "같은 테스트 참가자·시나리오·끝 시각에서 기존 가중치와 비교했다. 입력은 네 피처 그대로다.", "",
             "| 길이 | 선택 후보 | 기존 AUC | 후보 AUC | 기본 임계값 Accuracy | Recall | FPR | 보조 Accuracy | 보조 FPR |", "|---|---|---|---|---|---|---|---|---|"]
    for row in report["results"]:
        metrics = row["test"]["window"]
        auxiliary = row["test_at_balanced_threshold"]["window"]
        lines.append(f"| {row['seconds']}초 | {row['candidate']['name']} | {row['baseline_on_same_windows']['roc_auc']:.4f} | {metrics['roc_auc']:.4f} | {metrics['accuracy']:.4f} | {metrics['recall']:.4f} | {metrics['fpr']:.4f} | {auxiliary['accuracy']:.4f} | {auxiliary['fpr']:.4f} |")
    lines += ["", f"CV로 미리 선택한 길이: **{report['selected_seconds']}초**. test가 가장 좋은 길이로 재선택하지 않았다.",
              "저오탐 임계값은 validation FPR≤5% 기준이다. 보조 임계값은 validation 참가자 macro balanced accuracy 최대 기준이며 기본 관제 임계값과 다르다."]
    for row in report["results"]:
        lines += ["", f"## {row['seconds']}초", "", f"후보 설정: {json.dumps(row['candidate'], ensure_ascii=False)}",
                  f"CV 선택용 macro AUC: {row['cv']['mean_macro_auc']:.4f} ± {row['cv']['std_macro_auc']:.4f}",
                  f"저오탐 Window 지표: {json.dumps(row['test']['window'], ensure_ascii=False)}",
                  f"참가자 macro 지표: {json.dumps(row['test']['participant_macro'], ensure_ascii=False)}",
                  f"보조 분류 임계값의 Window 지표: {json.dumps(row['test_at_balanced_threshold']['window'], ensure_ascii=False)}",
                  f"동일 참가자 군집 재추출, 개선−기존 차이 95% 구간: {json.dumps(row['paired_difference_95ci'], ensure_ascii=False)}"]
    lines += ["", "## 해석 범위", "", "탐색은 train 참가자 12명 내부에서 진행했고, 기존 validation 4명으로 최종 체크포인트와 임계값을 정했다. test 참가자는 4명이다.",
              "CV 점수는 여러 후보 중 선택에 사용한 값이므로 비편향 최종 성능으로 해석하지 않는다. 겹친 Window는 독립 표본이 아니다.",
              "기존 test 점수가 이미 알려진 후속 실험이며 새로운 참가자 또는 실제 CCTV의 외부 검증을 대체하지 않는다. test 결과를 보고 후보를 변경하지 않았다.",
              "보조 Accuracy가 높아져도 FPR이 관제에 적합한지 따로 확인해야 한다. 실험 조건 분류 성능을 실제 음주운전 판별 정확도로 해석하지 않는다."]
    Path(path).write_text("\n".join(lines)+"\n", encoding="utf-8")
