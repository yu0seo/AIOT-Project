"""Window 지표, 참가자 일반화 지표, 검증 데이터 전용 임계값 선택."""
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score, roc_curve)

METRIC_NAMES = ("accuracy", "precision", "recall", "f1", "roc_auc", "fpr")


def participant_macro_auc(labels, scores, participants):
    labels, scores, participants = np.asarray(labels), np.asarray(scores), np.asarray(participants)
    aucs = []
    for participant in np.unique(participants):
        mask = participants == participant
        if len(np.unique(labels[mask])) == 2:
            aucs.append(roc_auc_score(labels[mask], scores[mask]))
    if not aucs:
        raise ValueError("두 클래스를 가진 검증 참가자가 필요합니다.")
    return float(np.mean(aucs))


def select_balanced_threshold(validation):
    """보조 분류용 임계값. 기본 저오탐 임계값과 구분해 저장한다."""
    counts = validation.groupby(["participant", "label"])["score"].transform("size")
    fpr, tpr, thresholds = roc_curve(validation.label, validation.score,
                                    sample_weight=1/counts.to_numpy(), drop_intermediate=False)
    best = max(range(len(thresholds)), key=lambda i: (tpr[i]-fpr[i], -fpr[i]))
    threshold = thresholds[best]
    if not np.isfinite(threshold):
        threshold = np.nextafter(float(validation.score.max()), np.inf)
    return {"threshold": float(threshold), "validation_macro_balanced_accuracy": float((1+tpr[best]-fpr[best])/2),
            "rule": "보조 분석: validation 참가자 macro balanced accuracy 최대"}


def binary_metrics(labels, scores, threshold):
    labels, scores = np.asarray(labels, dtype=int), np.asarray(scores, dtype=float)
    if not len(labels) or labels.shape != scores.shape or not np.isfinite(scores).all():
        raise ValueError("비어 있거나 유효하지 않은 평가 입력입니다.")
    if not set(labels).issubset({0, 1}) or np.any((scores < 0) | (scores > 1)):
        raise ValueError("라벨은 0/1, 점수는 0~1이어야 합니다.")
    predicted = scores >= threshold
    matrix = confusion_matrix(labels, predicted, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()
    return {"n": len(labels), "positive_n": int(labels.sum()),
            "accuracy": float(accuracy_score(labels, predicted)),
            "precision": float(precision_score(labels, predicted, zero_division=0)),
            "recall": float(recall_score(labels, predicted, zero_division=0)) if tp+fn else None,
            "f1": float(f1_score(labels, predicted, zero_division=0)),
            "roc_auc": float(roc_auc_score(labels, scores)) if len(set(labels)) == 2 else None,
            "fpr": float(fp/(fp+tn)) if fp+tn else None,
            "confusion_matrix": matrix.tolist()}


def select_threshold(validation, max_fpr):
    """Window FPR 제한 아래 참가자 macro recall 최대. 테스트 입력은 받지 않는다."""
    if not 0 <= max_fpr < 1 or set(validation["label"]) != {0, 1}:
        raise ValueError("임계값 선택에는 두 라벨과 올바른 FPR 제한이 필요합니다.")
    counts = validation.groupby(["participant", "label"])["score"].transform("size")
    weights = 1/counts.to_numpy()
    fpr, _, thresholds = roc_curve(validation.label, validation.score, drop_intermediate=False)
    macro_fpr, macro_recall, weighted_thresholds = roc_curve(
        validation.label, validation.score, sample_weight=weights, drop_intermediate=False)
    if not np.array_equal(thresholds, weighted_thresholds):
        raise ValueError("임계값 후보가 일치하지 않습니다.")
    feasible = np.flatnonzero(fpr <= max_fpr+1e-12)
    best = max(feasible, key=lambda i: (macro_recall[i], -macro_fpr[i], -fpr[i], thresholds[i]))
    threshold = thresholds[best]
    if not np.isfinite(threshold):
        threshold = np.nextafter(float(validation.score.max()), np.inf)
    return {"threshold": float(threshold), "max_validation_fpr": max_fpr,
            "validation_fpr": float(fpr[best]), "validation_macro_recall": float(macro_recall[best]),
            "rule": "검증 Window FPR 제한 안에서 참가자 macro recall 최대, 동률이면 낮은 macro FPR"}


def evaluate_predictions(frame, threshold, bootstrap_repeats=500, seed=42):
    window = binary_metrics(frame.label, frame.score, threshold)
    per_participant = []
    for participant, group in frame.groupby("participant", sort=True):
        per_participant.append({"participant": participant, **binary_metrics(group.label, group.score, threshold)})
    macro = {}
    for name in METRIC_NAMES:
        values = [row[name] for row in per_participant if row[name] is not None]
        macro[name] = float(np.mean(values)) if values else None
    # 한 참가자가 정상/음주 두 조건을 가지므로 참가자×조건으로 나누어 평균한다.
    condition = frame.groupby(["participant", "label"], as_index=False)["score"].mean()
    rng = np.random.default_rng(seed)
    groups = [group for _, group in frame.groupby("participant", sort=True)]
    samples = {name: [] for name in METRIC_NAMES}
    for _ in range(bootstrap_repeats):
        resampled = pd.concat([groups[i] for i in rng.integers(0, len(groups), len(groups))], ignore_index=True)
        metrics = binary_metrics(resampled.label, resampled.score, threshold)
        for name in METRIC_NAMES:
            if metrics[name] is not None:
                samples[name].append(metrics[name])
    intervals = {name: np.quantile(values, [.025, .975]).tolist() if values else None
                 for name, values in samples.items()}
    return {"window": window, "participant_macro": macro, "per_participant": per_participant,
            "participant_condition": binary_metrics(condition.label, condition.score, threshold),
            "participant_condition_scores": condition.to_dict("records"),
            "window_cluster_bootstrap_95ci": intervals,
            "bootstrap": {"unit": "참가자", "repeats": bootstrap_repeats, "participants": len(groups)}}
