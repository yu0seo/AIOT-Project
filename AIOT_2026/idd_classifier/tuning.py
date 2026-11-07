"""기존 학습 참가자 내부에서 수행하는 제한된 모델 탐색."""
import copy
import json
import random
import re
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from .data import build_manifest, fit_normalizer, make_windows, normalize, prepare_tracks, transform_features
from .experiment import prediction_frame, train_model, write_json
from .features import FeatureConfig
from .metrics import evaluate_predictions, select_threshold
from .model import create_model, model_architecture, predict_scores


def participant_folds(participants, folds, seed):
    if len(participants) != len(set(participants)):
        raise ValueError("참가자 목록에 중복이 있습니다.")
    participants = sorted(participants)
    if folds < 2 or len(participants) < folds*2:
        raise ValueError("fold마다 최소 두 참가자가 필요합니다.")
    random.Random(seed).shuffle(participants)
    result = []
    for index in range(folds):
        validation = sorted(participants[index::folds])
        train = sorted(set(participants)-set(validation))
        result.append({"train": train, "validation": validation})
    return result


def validate_search_config(base, search):
    for key in ("folds", "epochs", "patience"):
        if not isinstance(search[key], int) or search[key] < 1:
            raise ValueError(f"{key}는 양의 정수여야 합니다.")
    stride = search["stride_seconds"]*base["feature"]["sample_hz"]
    if not np.isfinite(stride) or stride < 1 or not float(stride).is_integer():
        raise ValueError("탐색 stride는 양의 정수 샘플에 대응해야 합니다.")
    if search["checkpoint_metric"] not in ("loss", "macro_auc"):
        raise ValueError("알 수 없는 체크포인트 선택 기준입니다.")
    names = set()
    for candidate in search["candidates"]:
        name = candidate["name"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or name in names:
            raise ValueError("후보 이름은 중복 없는 영문/숫자/밑줄/하이픈이어야 합니다.")
        names.add(name)
        config = candidate_config(base, candidate, search, 0)
        FeatureConfig(**config["feature"])
        transform_features(np.zeros((1, 4)), candidate["transform"])
        create_model(candidate["model_type"], model_architecture(config))
    if not names:
        raise ValueError("최소 하나의 탐색 후보가 필요합니다.")
    comparison_warmup_points(search)


def comparison_warmup_points(search):
    """평활화 설정을 바꾸지 않고 실험 사이의 Window 끝 시각을 맞춘다."""
    required = max(candidate["smooth_points"] for candidate in search["candidates"])
    points = search.get("comparison_warmup_points", required)
    if isinstance(points, bool) or not isinstance(points, int) or points < required:
        raise ValueError("비교용 초기 이력은 모든 평활화 점 수 이상의 정수여야 합니다.")
    return points


def candidate_config(base, candidate, search, fold):
    config = copy.deepcopy(base)
    config.update({key: value for key, value in candidate.items()
                   if key not in ("name", "smooth_points")})
    config["feature"]["smooth_points"] = candidate["smooth_points"]
    config.update(epochs=search["epochs"], patience=search["patience"],
                  checkpoint_metric=search["checkpoint_metric"], seed=base["seed"]+fold,
                  quiet_epochs=True)
    return config


def normalized_subset(raw, participants, normalizer):
    selected = np.isin(raw["participant"], participants)
    windows = {key: values[selected] for key, values in raw.items()}
    if set(windows["y"]) != {0, 1} or set(windows["participant"]) != set(participants):
        raise ValueError("처리 후 참가자 또는 클래스가 사라졌습니다.")
    windows["x"] = normalize(windows["x"], normalizer)
    return windows


def run_search(data_root, base, search, reference_run, output):
    """기존 train 12명만 읽고 3-fold 탐색한다. test 점수는 열지 않는다."""
    output, reference_run = Path(output), Path(reference_run)
    validate_search_config(base, search)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(base["cpu_threads"])
    splits = json.loads((reference_run/"splits.json").read_text(encoding="utf-8"))
    development = splits["train"]
    if set(development) & (set(splits["validation"]) | set(splits["test"])):
        raise ValueError("참조 분할에 참가자 누출이 있습니다.")
    folds = participant_folds(development, search["folds"], search["seed"])
    write_json(output/"folds.json", folds)
    write_json(output/"search_config.json", search)
    write_json(output/"base_config.json", base)
    write_json(output/"reference_splits.json", splits)
    root, manifest = build_manifest(data_root, base)
    manifest["included"] &= manifest.participant.isin(development)
    manifest.to_csv(output/"search_manifest.csv", index=False, encoding="utf-8-sig")
    feature_base = FeatureConfig(**base["feature"])
    smoothers = sorted({candidate["smooth_points"] for candidate in search["candidates"]})
    common_warmup = comparison_warmup_points(search)
    stride = round(search["stride_seconds"]*feature_base.sample_hz)
    reference_audit = pd.read_csv(reference_run/"data_audit.csv").set_index("scenario_id")
    prepared = {}
    for points in smoothers:
        feature_config = replace(feature_base, smooth_points=points)
        tracks, audit = prepare_tracks(root, manifest, feature_config)
        for row in audit.to_dict("records"):
            if row["sha256"] != reference_audit.loc[row["scenario_id"], "sha256"]:
                raise ValueError("원본 데이터가 기준 실험 후 변경되었습니다.")
        audit.to_csv(output/f"search_audit_smooth{points}.csv", index=False)
        anchor = max(base["window_seconds"])*feature_base.sample_hz+common_warmup-points
        prepared[points] = {"tracks": tracks, "windows": {
            seconds: make_windows(tracks, development, seconds*feature_base.sample_hz, stride, anchor)
            for seconds in base["window_seconds"]}}
    rows = []
    started = time.perf_counter()
    for candidate in search["candidates"]:
        prepared_data = prepared[candidate["smooth_points"]]
        for seconds in base["window_seconds"]:
            for fold_index, split in enumerate(folds):
                directory = output/"cv"/candidate["name"]/f"{seconds}s"/f"fold{fold_index}"
                directory.mkdir(parents=True)
                config = candidate_config(base, candidate, search, fold_index)
                normalizer = fit_normalizer(prepared_data["tracks"], split["train"], candidate["transform"])
                raw = prepared_data["windows"][seconds]
                train = normalized_subset(raw, split["train"], normalizer)
                validation = normalized_subset(raw, split["validation"], normalizer)
                model, training = train_model(train, validation, config, directory, "cpu")
                frame = prediction_frame(validation, predict_scores(model, validation["x"]))
                point = select_threshold(frame, base["max_validation_fpr"])
                metrics = evaluate_predictions(frame, point["threshold"], 0)
                row = {"candidate": candidate["name"], "seconds": seconds, "fold": fold_index,
                       "macro_auc": metrics["participant_macro"]["roc_auc"],
                       "macro_recall": metrics["participant_macro"]["recall"],
                       "window_auc": metrics["window"]["roc_auc"], "fpr": metrics["window"]["fpr"],
                       "best_epoch": training["best_epoch"], "parameters": sum(p.numel() for p in model.parameters())}
                rows.append(row)
                pd.DataFrame(rows).to_csv(output/"cv_results.csv", index=False)
                frame.to_csv(directory/"validation_predictions.csv", index=False)
                write_json(directory/"fit.json", {"config": config, "normalizer": normalizer,
                                                  "training": training, "operating_point": point})
                print(f"CV {len(rows)}/{len(search['candidates'])*len(base['window_seconds'])*len(folds)} | {candidate['name']} {seconds}초 fold{fold_index} | macro AUC {row['macro_auc']:.4f}", flush=True)
    table = pd.DataFrame(rows)
    ranking = table.groupby(["candidate", "seconds"], as_index=False).agg(
        mean_macro_auc=("macro_auc", "mean"), std_macro_auc=("macro_auc", "std"),
        mean_macro_recall=("macro_recall", "mean"), parameters=("parameters", "first"))
    ranking = ranking.sort_values(["seconds", "mean_macro_auc", "mean_macro_recall", "parameters"],
                                  ascending=[True, False, False, True])
    ranking.to_csv(output/"cv_ranking.csv", index=False)
    winners = ranking.groupby("seconds", sort=True).head(1).to_dict("records")
    selection = {"winners": winners, "common_warmup_points": common_warmup,
                 "selection_rule": "학습 참가자 내부 3-fold mean macro AUC → macro recall → 적은 파라미터",
                 "test_accessed": False, "elapsed_seconds": time.perf_counter()-started}
    write_json(output/"cv_selection.json", selection)
    print(json.dumps(selection, ensure_ascii=False, indent=2), flush=True)
    return selection
