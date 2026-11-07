"""누출을 막은 3/5/10초 LSTM 학습, 검증 선택과 고정 테스트 평가."""
import json
import platform
import random
import shutil
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .data import (build_manifest, fit_normalizer, make_windows, normalize, prepare_tracks,
                   split_participants)
from .features import FEATURE_DEFINITIONS, FEATURE_NAMES, FEATURE_UNITS, FeatureConfig
from .metrics import METRIC_NAMES, evaluate_predictions, participant_macro_auc, select_threshold
from .model import create_model, model_architecture, predict_scores


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def prediction_frame(windows, scores):
    return pd.DataFrame({"participant": windows["participant"], "scenario_id": windows["scenario_id"],
                         "end_ns": windows["end_ns"], "label": windows["y"].astype(int), "score": scores})


def bundle_metadata(config, feature_config, normalizer, seconds, training, splits, operating_point, anchor, stride):
    """학습 실행 방식과 무관하게 동일한 추론 계약을 저장한다."""
    return {"format_version": 1, "model_type": config.get("model_type", "LSTM"),
            "window_seconds": seconds, "timesteps": seconds*feature_config.sample_hz,
            "sample_hz": feature_config.sample_hz, "feature_order": list(FEATURE_NAMES),
            "feature_units": list(FEATURE_UNITS), "feature_definitions": list(FEATURE_DEFINITIONS),
            "feature_config": asdict(feature_config), "preprocessing": feature_config.metadata(),
            "normalizer": normalizer, "architecture": model_architecture(config),
            "threshold": operating_point["threshold"], "operating_point": operating_point,
            "training": training, "seed": config["seed"], "splits": splits,
            "comparison_anchor_steps": anchor, "stride_steps": stride,
            "limitations": ["IDD 실험 조건 분류이며 CCTV 탐지 성능이 아님", "round와 시나리오 구성의 교란",
                            "검증 FPR 제한은 실제 CCTV FPR을 보장하지 않음"],
            "coordinate_quality": {"max_control_point_error_m": 0.5, "metric_scale_verification_required": True}}


def train_model(train, validation, config, directory, device):
    """train만 클래스 가중치를 계산한다. 검증 BCE로 early stopping한다."""
    seed = config["seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    model = create_model(config.get("model_type", "LSTM"), model_architecture(config)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"])
    positives = float(train["y"].sum())
    pos_weight = (len(train["y"])-positives)/positives
    loss_function = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight, device=device))
    dataset = TensorDataset(torch.from_numpy(train["x"]), torch.from_numpy(train["y"]))
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(dataset, batch_size=config["batch_size"], shuffle=True, num_workers=0, generator=generator)
    validation_loader = DataLoader(TensorDataset(torch.from_numpy(validation["x"]), torch.from_numpy(validation["y"])),
                                   batch_size=config["batch_size"], num_workers=0)
    best_loss, best_epoch, stale = float("inf"), 0, 0
    best_auc = 0.0
    best_metric = -float("inf")
    monitor = config.get("checkpoint_metric", "loss")
    if monitor not in ("loss", "macro_auc"):
        raise ValueError("checkpoint_metric은 loss 또는 macro_auc여야 합니다.")
    history = []
    for epoch in range(1, config["epochs"]+1):
        started = time.perf_counter()
        model.train()
        total_loss = 0.0
        for features, labels in loader:
            features, labels = features.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(features), labels)
            if not torch.isfinite(loss):
                raise ValueError("학습 손실이 유한하지 않습니다.")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0, error_if_nonfinite=True)
            optimizer.step()
            total_loss += float(loss.detach())*len(labels)
        model.eval()
        validation_loss = 0.0
        validation_scores = []
        with torch.inference_mode():
            for features, labels in validation_loader:
                logits = model(features.to(device))
                validation_loss += float(nn.functional.binary_cross_entropy_with_logits(
                    logits, labels.to(device), reduction="sum"))
                validation_scores.extend(torch.sigmoid(logits).cpu().tolist())
        validation_loss /= len(validation["y"])
        if not np.isfinite(validation_loss):
            raise ValueError("검증 손실이 유한하지 않습니다.")
        validation_auc = participant_macro_auc(validation["y"], validation_scores, validation["participant"])
        history.append({"epoch": epoch, "train_loss": total_loss/len(dataset),
                        "validation_loss": validation_loss, "validation_macro_auc": validation_auc,
                        "seconds": time.perf_counter()-started})
        pd.DataFrame(history).to_csv(directory/"history.csv", index=False)
        seconds = train['x'].shape[1]/config['feature']['sample_hz']
        if not config.get("quiet_epochs", False):
            print(f"{seconds:g}초 | epoch {epoch:02d} | train {history[-1]['train_loss']:.4f} | validation {validation_loss:.4f} | macro AUC {validation_auc:.4f}", flush=True)
        current_metric = validation_auc if monitor == "macro_auc" else -validation_loss
        if current_metric > best_metric+1e-4:
            best_loss, best_epoch, stale = validation_loss, epoch, 0
            best_auc, best_metric = validation_auc, current_metric
            weights = {name: value.detach().cpu() for name, value in model.state_dict().items()}
            torch.save(weights, directory/"model.pt")
        else:
            stale += 1
            if stale >= config["patience"]:
                break
    model.load_state_dict(torch.load(directory/"model.pt", map_location=device, weights_only=True))
    return model, {"best_epoch": best_epoch, "best_validation_loss": best_loss,
                   "best_validation_macro_auc": best_auc, "checkpoint_metric": monitor,
                   "epochs_run": len(history), "train_pos_weight": pos_weight}


def inspect_dataset(data_root, config, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    root, manifest = build_manifest(data_root, config)
    manifest.to_csv(output/"manifest.csv", index=False, encoding="utf-8-sig")
    tracks, audit = prepare_tracks(root, manifest, FeatureConfig(**config["feature"]))
    audit.to_csv(output/"data_audit.csv", index=False, encoding="utf-8-sig")
    selected = manifest[manifest.included]
    summary = {"processed_root": str(root), "indexed_driving_scenarios": len(manifest),
               "selected_scenarios": len(selected), "participants": selected.participant.nunique(),
               "raw_rows": int(audit.rows.sum()),
               "labels": {str(k): int(v) for k, v in selected.label.value_counts().items()},
               "missing_rows": int(audit.missing_rows.sum()), "gaps": int(audit.gaps.sum()),
               "jumps": int(audit.jumps.sum()), "non_100ms_intervals": int(audit.non_100ms_intervals.sum())}
    write_json(output/"inspection.json", summary)
    write_json(output/"config.json", config)
    return tracks, selected, summary


def run_experiment(data_root, config, output, device="cpu"):
    started = time.perf_counter()
    torch.set_num_threads(config["cpu_threads"])
    output = Path(output)
    tracks, manifest, inspection = inspect_dataset(data_root, config, output)
    feature_config = FeatureConfig(**config["feature"])
    splits = split_participants(manifest, config["seed"], config["validation_fraction"], config["test_fraction"])
    write_json(output/"splits.json", splits)
    normalizer = fit_normalizer(tracks, splits["train"], config.get("transform", "identity"))
    write_json(output/"normalizer.json", normalizer)
    environment = {"python": platform.python_version(), "platform": platform.platform(),
                   "packages": {name: version(name) for name in ("numpy", "pandas", "scikit-learn", "torch")},
                   "device": device, "cpu_threads": config["cpu_threads"]}
    write_json(output/"environment.json", environment)
    models, results, test_sets = {}, [], {}
    hz = feature_config.sample_hz
    anchor = round(max(config["window_seconds"])*hz)
    stride = round(config["stride_seconds"]*hz)
    for seconds in config["window_seconds"]:
        steps = round(seconds*hz)
        directory = output/f"{seconds}s"
        directory.mkdir()
        windows = {}
        for name, participants in splits.items():
            raw = make_windows(tracks, participants, steps, stride, anchor)
            if set(raw["y"]) != {0, 1} or set(raw["participant"]) != set(participants):
                raise ValueError(f"{name}: 특징 처리 후 참가자/클래스가 사라졌습니다. 분할을 재검토하세요.")
            np.savez_compressed(directory/f"{name}_windows.npz", **raw)
            windows[name] = {**raw, "x": normalize(raw["x"], normalizer)}
        model, training = train_model(windows["train"], windows["validation"], config, directory, device)
        validation_scores = predict_scores(model, windows["validation"]["x"], device=device)
        validation_frame = prediction_frame(windows["validation"], validation_scores)
        operating_point = select_threshold(validation_frame, config["max_validation_fpr"])
        validation_frame.to_csv(directory/"validation_predictions.csv", index=False)
        validation_result = evaluate_predictions(validation_frame, operating_point["threshold"], 0)
        metadata = bundle_metadata(config, feature_config, normalizer, seconds, training, splits,
                                   operating_point, anchor, stride)
        write_json(directory/"metadata.json", metadata)
        results.append({"window_seconds": seconds, "threshold": metadata["threshold"],
                        "training": training, "validation": validation_result,
                        "window_counts": {name: len(w["y"]) for name, w in windows.items()}})
        models[seconds] = model
        test_sets[seconds] = windows["test"]
    # 이 선택까지 test 점수나 지표에 접근하지 않는다.
    selected = max(results, key=lambda r: (r["validation"]["participant_macro"]["recall"],
                                          -r["validation"]["participant_macro"]["fpr"], -r["window_seconds"]))
    selected_seconds = selected["window_seconds"]
    write_json(output/"selection.json", {"selected_seconds": selected_seconds,
               "basis": "검증 FPR 제한 아래 참가자 macro recall, macro FPR, 짧은 길이 순; test 미사용"})
    for result in results:
        seconds = result["window_seconds"]
        frame = prediction_frame(test_sets[seconds], predict_scores(models[seconds], test_sets[seconds]["x"], device=device))
        frame["prediction"] = (frame.score >= result["threshold"]).astype(int)
        frame.to_csv(output/f"{seconds}s"/"test_predictions.csv", index=False)
        result["test"] = evaluate_predictions(frame, result["threshold"], config["bootstrap_repeats"], config["seed"])
        result["test_at_0_5"] = evaluate_predictions(frame, .5, 0)["window"]
        write_json(output/f"{seconds}s"/"metrics.json", result)
    best = output/"best"
    best.mkdir()
    for name in ("model.pt", "metadata.json"):
        shutil.copyfile(output/f"{selected_seconds}s"/name, best/name)
    table = [{"window_seconds": r["window_seconds"], "selected_by_validation": r["window_seconds"] == selected_seconds,
              "threshold": r["threshold"], **{k: r["test"]["window"][k] for k in METRIC_NAMES},
              "participant_macro_recall": r["test"]["participant_macro"]["recall"],
              "participant_macro_fpr": r["test"]["participant_macro"]["fpr"]} for r in results]
    pd.DataFrame(table).to_csv(output/"comparison.csv", index=False)
    report = {"inspection": inspection, "selection_seconds": selected_seconds, "results": results,
              "elapsed_seconds": time.perf_counter()-started, "environment": environment}
    write_json(output/"results.json", report)
    write_report(output/"REPORT.md", report, splits)
    return report


def write_report(path, report, splits):
    lines = ["# IDD 시계열 분류 실제 측정 결과", "", "이 문서의 지표는 로컬 CSV를 사용해 실제 측정한 값이다. CCTV 탐지 정확도를 뜻하지 않는다.", "",
             f"선택 데이터: 참가자 {report['inspection']['participants']}명, 주행 {report['inspection']['selected_scenarios']}개.",
             f"참가자 분할: train {len(splits['train'])}명 / validation {len(splits['validation'])}명 / test {len(splits['test'])}명.", "",
             "동일한 구간 끝 시각에서 3/5/10초를 비교했다. 겹친 Window는 독립 표본이 아니며, 참가자 군집 bootstrap을 사용했다.", "",
             "| 길이 | 임계값 | Accuracy | Precision | Recall | F1 | ROC-AUC | FPR |", "|---|---|---|---|---|---|---|---|"]
    for result in report["results"]:
        metrics = result["test"]["window"]
        values = [f"{metrics[k]:.4f}" if metrics[k] is not None else "정의 불가" for k in METRIC_NAMES]
        lines.append(f"| {result['window_seconds']}초 | {result['threshold']:.4f} | " + " | ".join(values) + " |")
    for result in report["results"]:
        metrics = result["test"]
        lines += ["", f"## {result['window_seconds']}초", "",
                  f"Window 수: {result['window_counts']}. 최적 epoch: {result['training']['best_epoch']}.",
                  f"Confusion matrix [[TN, FP], [FN, TP]]: {metrics['window']['confusion_matrix']}.",
                  f"참가자 macro recall: {metrics['participant_macro']['recall']:.4f}, macro FPR: {metrics['participant_macro']['fpr']:.4f}.",
                  f"참가자×조건 평균점수 지표: {json.dumps(metrics['participant_condition'], ensure_ascii=False)}.",
                  f"Window 지표의 참가자 군집 95% 구간: {json.dumps(metrics['window_cluster_bootstrap_95ci'], ensure_ascii=False)}."]
    lines += ["", "## 입력 길이 선택과 해석", "",
              f"검증 데이터로 선택한 길이는 **{report['selection_seconds']}초**다. 결과를 보고 test가 좋은 길이로 바꾸지 않았다.",
              "이 선택은 비교한 기준 모델 사이의 연구용 선택이다. 현재 성능으로 실제 CCTV 관제에 권장할 수 있는 입력 길이는 없다.",
              "3초는 짧은 관측에 적합하지만 변화 패턴이 적고, 5초는 관측 시간과 정보량의 절충이며, 10초는 긴 패턴을 보지만 차량 추적 성공률이 낮아진다.",
              "첫 특징 전 1초 이력이 필요해 첫 판단은 약 3.9/5.9/10.9초 후 가능하다. 리샘플링 대기는 최대 0.2초다.",
              "검증 FPR≤5%는 경험적 임계값 선택 기준이다. test 또는 CCTV에서 5%를 보장하지 않는다.", "",
              "## 한계", "",
              "정상 라벨은 비음주 실험 조건이며 안전 운전을 뜻하지 않는다. 음주 라벨도 모든 Window에서 위험 행동이 있었다는 뜻이 아니다.",
              "각 P 참가자의 두 round에는 서로 다른 시나리오가 배정된다. 전체에서는 각 시나리오가 두 라벨 모두에 존재하지만, 참가자 분리만으로 순서·학습 효과와 시나리오 불균형을 제거할 수는 없다.",
              "참가자 수가 적어 불확실성이 크다. Window 수를 독립 참가자 수처럼 해석하지 않아야 한다. 참가자별 상세 지표는 metrics.json을 확인한다.",
              "실제 CCTV는 미터 스케일, 위치 오차, 프레임 누락, 관측 시점, 차종, 도로 구조가 다르다. 현장 라벨 데이터로 외부 검증하기 전 운영 모델로 확정할 수 없다.",
              "FPR은 정상 Window 중 양성 비율이다. 차량당 또는 시간당 관제 경보율이 아니며 연속 경보 집계 정책은 후속 검증 대상이다."]
    Path(path).write_text("\n".join(lines)+"\n", encoding="utf-8")
