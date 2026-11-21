"""Train AE and Deep SVDD on the same grouped 584/147 assumed-normal split."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import gc
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import subprocess
import time

from air400_paths import PROJECT, RUNTIME
os.environ["MPLCONFIGDIR"] = str(RUNTIME/"matplotlib")
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from download_oneclass_sources import save as atomic_json_save
from oneclass_models import FusionAutoencoder, FusionEncoder, reconstruction_scores, svdd_scores

DATA = PROJECT/"06_단일클래스_학습데이터/model_input_candidates_computable.npz"
RUN = PROJECT/"07_이상탐지_모델비교/normal731_80_20_seed42_v1"
SEED, BATCH, EPOCHS, PATIENCE, PRETRAIN = 42, 32, 100, 20, 20
QUANTILE = .99


def save(path, value):
    # Windows sync/scanning processes can briefly lock a recently replaced file.
    for attempt in range(10):
        try:
            atomic_json_save(path, value)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(.1*(attempt+1))


def save_checkpoint(path, value):
    temporary = path.with_suffix(path.suffix+".partial")
    for attempt in range(10):
        try:
            torch.save(value, temporary)
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(.1*(attempt+1))


def now():
    return datetime.now().astimezone().isoformat()


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def cpu_state(module):
    return {k: v.detach().cpu().clone() for k, v in module.state_dict().items()}


def grouped_split(groups, sample_ids):
    """Choose by counts alone, before observing model losses; never split a source group."""
    names = sorted(set(groups.tolist()))
    sizes = Counter(groups.tolist())
    target = math.ceil(len(groups)*.2)
    overall_air125 = np.mean(np.char.startswith(sample_ids, "air-125_"))
    choices = []
    for count in range(1, len(names)):
        for combination in itertools.combinations(names, count):
            n = sum(sizes[k] for k in combination)
            valid = np.isin(groups, combination)
            fraction = np.mean(np.char.startswith(sample_ids[valid], "air-125_"))
            choices.append(((abs(n-target), abs(fraction-overall_air125), len(combination), combination), valid))
    _, valid = min(choices, key=lambda item: item[0])
    train_i, valid_i = np.flatnonzero(~valid), np.flatnonzero(valid)
    assert len(train_i) == 584 and len(valid_i) == 147
    assert not set(groups[train_i]) & set(groups[valid_i])
    return train_i, valid_i


def setup_data():
    with np.load(DATA, allow_pickle=False) as d:
        wave, features = d["waveform"].copy(), d["interval_features"].copy()
        ids, groups = d["sample_id"].copy(), d["source_group"].copy()
        feature_names = d["feature_names"].tolist()
        original_labels = np.unique(d["training_label"]).tolist()
        assert d["extraction_ok"].all() and d["interval_features_valid"].all()
    assert wave.shape == (731, 300, 1) and features.shape == (731, 9)
    assert np.isfinite(wave).all() and np.isfinite(features).all()
    train_i, valid_i = grouped_split(groups, ids)
    # Global waveform scale preserves between-window amplitude variation.
    wm, ws = float(wave[train_i].astype(np.float64).mean()), float(wave[train_i].astype(np.float64).std())
    fm = features[train_i].astype(np.float64).mean(axis=0)
    fs = features[train_i].astype(np.float64).std(axis=0)
    fs = np.where(fs < 1e-8, 1., fs)
    assert ws > 1e-8
    scaler = {"waveform_mean": wm, "waveform_std": ws, "feature_mean": fm.tolist(), "feature_std": fs.tolist(),
              "fit_partition": "train_only", "waveform_policy": "one global scalar mean/std; no per-window restandardization"}
    split = {"created_at": now(), "seed": SEED, "train_count": len(train_i), "valid_count": len(valid_i),
             "train_fraction": len(train_i)/731, "valid_fraction": len(valid_i)/731,
             "selection_rule": "Enumerate source-group subsets; minimize deviation from ceil(0.2*N), then dataset mixture deviation; no model metric used",
             "group_intersection": [], "group_identity_status": "conservative original-annotation groups; cross-dataset infant identities not independently verified",
             "train_groups": sorted(set(groups[train_i].tolist())), "valid_groups": sorted(set(groups[valid_i].tolist())),
             "train_indices": train_i.tolist(), "valid_indices": valid_i.tolist(),
             "train_sample_ids": ids[train_i].tolist(), "valid_sample_ids": ids[valid_i].tolist(),
             "train_dataset_counts": dict(Counter(s.split("_")[0] for s in ids[train_i])),
             "valid_dataset_counts": dict(Counter(s.split("_")[0] for s in ids[valid_i])),
             "experiment_label": "assumed_normal_by_user", "source_labels_unchanged": original_labels,
             "source_file_sha256": digest(DATA), "feature_names": feature_names}
    save(RUN/"shared/split.json", split)
    save(RUN/"shared/scaler.json", scaler)
    wave = ((wave.astype(np.float64)-wm)/ws).astype(np.float32)
    features = ((features.astype(np.float64)-fm)/fs).astype(np.float32)
    pairs = tuple(torch.from_numpy(x) for x in (wave, features))
    train_set = TensorDataset(pairs[0][train_i], pairs[1][train_i])
    valid_set = TensorDataset(pairs[0][valid_i], pairs[1][valid_i])
    return train_set, valid_set, split, scaler


def loaders(dataset, shuffle=False):
    generator = torch.Generator().manual_seed(SEED)
    return DataLoader(dataset, batch_size=BATCH if shuffle else 128, shuffle=shuffle, generator=generator, num_workers=0)


@torch.no_grad()
def evaluate(model, loader, device, center=None):
    model.eval()
    scores, latents, wave_errors, feature_errors = [], [], [], []
    for wave, features in loader:
        wave, features = wave.to(device), features.to(device)
        if center is None:
            pw, pf, z = model(wave, features)
            score, we, fe = reconstruction_scores(pw, pf, wave, features)
            wave_errors.extend(we.cpu().tolist()); feature_errors.extend(fe.cpu().tolist())
        else:
            z = model(wave, features)
            score = svdd_scores(z, center)
        scores.extend(score.cpu().tolist()); latents.append(z.cpu().numpy())
    scores, latent = np.asarray(scores, np.float64), np.concatenate(latents)
    assert np.isfinite(scores).all() and np.isfinite(latent).all()
    return {"scores": scores, "loss": float(scores.mean()), "latent_std_mean": float(latent.std(axis=0).mean()),
            "score_std": float(scores.std()), "waveform_mae": float(np.mean(wave_errors)) if wave_errors else None,
            "feature_mae": float(np.mean(feature_errors)) if feature_errors else None}


def measured_row(epoch, optimized_loss, training, validation, elapsed, lr):
    threshold = float(np.quantile(training["scores"], QUANTILE))
    accepted = validation["scores"] <= threshold
    return {"epoch": epoch, "optimization_loss": optimized_loss, "train_loss": training["loss"], "valid_loss": validation["loss"],
            "valid_accuracy_normal_only": float(accepted.mean()), "valid_false_positive_rate": float((~accepted).mean()),
            "valid_normal_accepted": int(accepted.sum()), "valid_count": len(accepted),
            "threshold_train_quantile": threshold, "threshold_quantile": QUANTILE,
            "train_latent_std_mean": training["latent_std_mean"], "valid_latent_std_mean": validation["latent_std_mean"],
            "train_score_std": training["score_std"], "valid_score_std": validation["score_std"],
            "valid_waveform_mae": validation["waveform_mae"], "valid_feature_mae": validation["feature_mae"],
            "learning_rate": lr, "epoch_seconds": elapsed}


def train_model(name, model, train_set, valid_set, split, scaler, device, center=None):
    out = RUN/name
    out.mkdir(parents=True, exist_ok=True)
    is_ae = center is None
    lr = 1e-3 if is_ae else 1e-4
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, milestones=[50, 80], gamma=.3)
    train_loader, train_eval, valid_eval = loaders(train_set, True), loaders(train_set), loaders(valid_set)
    history, best, best_row, stale = [], math.inf, None, 0
    best_payload = None
    for epoch in range(1, EPOCHS+1):
        started = time.perf_counter()
        model.train()
        total, count = 0., 0
        for wave, features in train_loader:
            wave, features = wave.to(device), features.to(device)
            optimizer.zero_grad(set_to_none=True)
            if is_ae:
                pw, pf, z = model(wave, features)
                loss = reconstruction_scores(pw, pf, wave, features)[0].mean()
            else:
                loss = svdd_scores(model(wave, features), center).mean()
            if not torch.isfinite(loss):
                raise FloatingPointError(f"{name}: non-finite training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5., error_if_nonfinite=True)
            optimizer.step()
            total += loss.item()*len(wave); count += len(wave)
        tr, va = evaluate(model, train_eval, device, center), evaluate(model, valid_eval, device, center)
        row = measured_row(epoch, total/count, tr, va, time.perf_counter()-started, optimizer.param_groups[0]["lr"])
        history.append(row)
        significant = not math.isfinite(best) or row["valid_loss"] < best-max(1e-8, abs(best)*1e-4)
        # Always save the actual minimum; patience ignores tiny numerical improvements.
        if row["valid_loss"] < best:
            best, best_row = row["valid_loss"], dict(row)
            best_payload = {"format_version": 1, "model_type": name, "model_state_dict": cpu_state(model),
                        "center": center.detach().cpu() if center is not None else None,
                        "threshold": row["threshold_train_quantile"], "threshold_policy": "99th percentile of training scores at this checkpoint",
                        "scaler": scaler, "feature_names": split["feature_names"], "metrics": dict(row),
                        "source_file_sha256": split["source_file_sha256"], "split_sha256": digest(RUN/"shared/split.json"),
                        "normal_label_is_user_assumption": True}
        stale = 0 if significant else stale+1
        if is_ae and epoch == PRETRAIN:
            # A fixed epoch chosen in advance, independent of validation selection.
            save_checkpoint(out/"pretrain_epoch020.pt", {"encoder_state_dict": cpu_state(model.encoder), "epoch": epoch,
                        "purpose": "training-only warm start of the Deep SVDD encoder; no decoder in SVDD inference"})
        scheduler.step()
        if epoch == 1 or epoch % 5 == 0 or stale >= PATIENCE or epoch == EPOCHS:
            save(out/"history.json", {"model": name, "epochs": history})
            save(RUN/"progress.json", {"updated_at": now(), "model": name, "epoch": epoch, "best_epoch": best_row["epoch"],
                                      "latest": row, "complete": False})
        if epoch == 1 or epoch % 5 == 0 or stale >= PATIENCE:
            print(f"{name} epoch {epoch:03d}: train={row['train_loss']:.7f} valid={row['valid_loss']:.7f} normal_acc={row['valid_accuracy_normal_only']:.4%} ({row['valid_normal_accepted']}/147) threshold={row['threshold_train_quantile']:.7g} latent_std={row['valid_latent_std_mean']:.7g}", flush=True)
        if stale >= PATIENCE and (not is_ae or epoch >= PRETRAIN):
            print(f"{name}: early stopping at {epoch}; best epoch {best_row['epoch']}", flush=True)
            break
    assert best_payload is not None
    save_checkpoint(out/"best.pt", best_payload)
    checkpoint = torch.load(out/"best.pt", map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["model_state_dict"])
    valid_result = evaluate(model, valid_eval, device, center)
    np.testing.assert_allclose(valid_result["loss"], best_row["valid_loss"], rtol=1e-6, atol=1e-9)
    predictions = [{"sample_id": sid, "assumed_true_label": "normal", "score": float(score),
                    "threshold": checkpoint["threshold"], "predicted_label": "normal" if score <= checkpoint["threshold"] else "anomaly"}
                   for sid, score in zip(split["valid_sample_ids"], valid_result["scores"])]
    save(out/"valid_predictions.json", {"best_epoch": best_row["epoch"], "samples": predictions})
    result = {"model": name, "epochs_run": len(history), "best_epoch": best_row["epoch"],
              "parameter_count": sum(p.numel() for p in model.parameters()), "best_checkpoint_metrics": best_row,
              "score_definition": "mean waveform absolute error + mean 9-feature absolute error, after train-only scaling" if is_ae else "squared Euclidean distance to fixed nonzero center",
              "pretraining_epochs": 0 if is_ae else PRETRAIN, "checkpoint": str((out/"best.pt").relative_to(RUN)),
              "checkpoint_sha256": digest(out/"best.pt"), "checkpoint_reload_prediction_check": True}
    save(out/"result.json", result)
    return result


def plot_results(results):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = Path("C:/Windows/Fonts/malgun.ttf")
    if font.exists():
        plt.rcParams["font.family"] = FontProperties(fname=str(font)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    colors = {"autoencoder": "#d97706", "deep_svdd": "#2563eb"}
    labels = {"autoencoder": "오토인코더", "deep_svdd": "Deep SVDD"}
    histories = {name: json.loads((RUN/name/"history.json").read_text(encoding="utf-8"))["epochs"] for name in colors}
    fig = plt.figure(figsize=(14, 9), constrained_layout=True)
    grid = fig.add_gridspec(2, 2, height_ratios=[1, 1.05])
    for column, name in enumerate(colors):
        ax = fig.add_subplot(grid[0, column])
        h = histories[name]
        epochs = [r["epoch"] for r in h]
        ax.plot(epochs, [r["train_loss"] for r in h], color="#64748b", ls="--", label="학습 loss (평가 모드)")
        ax.plot(epochs, [r["valid_loss"] for r in h], color=colors[name], lw=2, label="검증 loss")
        best = results[name]["best_checkpoint_metrics"]
        ax.scatter([best["epoch"]], [best["valid_loss"]], color=colors[name], edgecolor="white", s=65, zorder=5, label=f"선택된 epoch {best['epoch']}")
        ax.set_title(labels[name]+(" · 복원 오차 (파형 MAE + 특성 MAE)" if name == "autoencoder" else " · 정상 중심까지의 제곱거리"))
        ax.set_xlabel("본학습 epoch"); ax.set_ylabel("Loss · 각 모델 고유 척도")
        ax.grid(alpha=.2); ax.legend(fontsize=9)
    ax = fig.add_subplot(grid[1, :])
    for name, h in histories.items():
        ax.plot([r["epoch"] for r in h], [100*r["valid_accuracy_normal_only"] for r in h], color=colors[name], lw=2, label=labels[name])
        best = results[name]["best_checkpoint_metrics"]
        ax.scatter([best["epoch"]], [100*best["valid_accuracy_normal_only"]], color=colors[name], s=65, edgecolor="white", zorder=5)
    ax.set_ylim(0, 102); ax.set_xlabel("각 모델의 본학습 epoch (SVDD 복원 사전학습 20 epoch 제외)")
    ax.set_ylabel("정상 검증 정확도 (%)")
    ax.set_title("정상으로 가정한 검증 구간 147개 중 정상 판정 비율 · 기준값은 매 epoch 학습 점수의 99백분위")
    ax.grid(alpha=.2); ax.legend()
    fig.suptitle("동일 8:2 분할 · 학습 584개 / 검증 147개 · 파형 + 호흡 간격 특성\n정상 데이터만 평가: 이상 검출률을 뜻하지 않으며, 두 loss의 숫자를 직접 비교할 수 없음", fontsize=13)
    out = RUN/"graphs"; out.mkdir(exist_ok=True)
    fig.savefig(out/"validation_curves.png", dpi=170)
    fig.savefig(out/"validation_curves.svg")
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), constrained_layout=True)
    for ax, name in zip(axes, colors):
        checkpoint = torch.load(RUN/name/"best.pt", weights_only=True, map_location="cpu")
        records = json.loads((RUN/name/"valid_predictions.json").read_text(encoding="utf-8"))["samples"]
        ax.hist([r["score"] for r in records], bins=20, color=colors[name], alpha=.75)
        ax.axvline(checkpoint["threshold"], color="#dc2626", ls="--", label="학습 점수 99백분위 기준")
        ax.set_title(labels[name]+" · 선택된 모델의 정상 검증 점수")
        ax.set_xlabel("이상점수 (모델별 척도)"); ax.set_ylabel("구간 수"); ax.legend(fontsize=8)
    fig.savefig(out/"validation_score_distributions.png", dpi=160); plt.close(fig)


def final_audit(train_set, valid_set, split, scaler, results, device):
    with np.load(DATA, allow_pickle=False) as original:
        train_i, valid_i = np.array(split["train_indices"]), np.array(split["valid_indices"])
        assert len(set(train_i) | set(valid_i)) == 731 and not set(train_i) & set(valid_i)
        assert not set(original["source_group"][train_i]) & set(original["source_group"][valid_i])
        np.testing.assert_allclose(scaler["feature_mean"], original["interval_features"][train_i].astype(np.float64).mean(axis=0), atol=1e-12)
        assert digest(DATA) == split["source_file_sha256"]
    for name, result in results.items():
        ck = torch.load(RUN/name/"best.pt", map_location="cpu", weights_only=True)
        model = FusionAutoencoder() if name == "autoencoder" else FusionEncoder()
        model.load_state_dict(ck["model_state_dict"], strict=True)
        if name == "deep_svdd":
            assert all(not key.endswith("bias") for key in model.state_dict())
            assert (ck["center"].abs() >= .099999).all()
        cpu_result = evaluate(model, loaders(valid_set), "cpu", ck["center"])
        rows = json.loads((RUN/name/"valid_predictions.json").read_text(encoding="utf-8"))["samples"]
        scores = np.array([r["score"] for r in rows])
        np.testing.assert_allclose(cpu_result["scores"], scores, rtol=2e-4, atol=2e-6)
        history = json.loads((RUN/name/"history.json").read_text(encoding="utf-8"))["epochs"]
        assert len(history) == result["epochs_run"]
        for row in history:
            assert all(np.isfinite(row[key]) for key in ("train_loss", "valid_loss", "threshold_train_quantile", "valid_accuracy_normal_only"))
        best = result["best_checkpoint_metrics"]
        assert sum(r["predicted_label"] == "normal" for r in rows) == best["valid_normal_accepted"]
        assert abs(best["valid_accuracy_normal_only"]-best["valid_normal_accepted"]/147) < 1e-12
        assert best["valid_loss"] == min(r["valid_loss"] for r in history)
    audit = {"checked_at": now(), "passed": True, "all_731_samples_assigned_once": True,
             "source_group_overlap": 0, "scaler_fit_train_only": True, "threshold_uses_train_only": True,
             "validation_not_used_as_threshold_calibration": True, "source_npz_unchanged": True,
             "checkpoints_reload_and_match_saved_predictions": True, "cpu_gpu_score_parity": True,
             "both_models_received_identical_split_and_scaling": True, "abnormal_detection_performance_measured": False}
    save(RUN/"verification.json", audit)


def report(results, split, config):
    save(RUN/"comparison.json", {"completed_at": now(), "split": {k: split[k] for k in ("train_count", "valid_count", "train_groups", "valid_groups", "train_dataset_counts", "valid_dataset_counts")},
                                "accuracy_definition": "Fraction of assumed-normal validation windows with score <= train-score 99th percentile; normal acceptance only",
                                "different_loss_scales_not_directly_comparable": True, "abnormal_detection_performance_measured": False,
                                "models": results})
    lines = ["두 단일 클래스 이상 탐지 모델 학습·검증 결과", "", "입력: 10Hz·30초 파형 300개 + 호흡 간격 요약 특성 9개",
             "데이터: 사용자 결정에 따라 731개를 정상으로 가정. 원본 데이터의 미검토 라벨은 수정하지 않음.",
             "분할: 학습 584개 / 검증 147개 (79.89% / 20.11%)",
             "같은 source_group은 양쪽에 섞이지 않음. 이 그룹은 원본 주석 기반이며 영유아 신원을 독립 검증한 분리는 아님.",
             "학습·검증 데이터셋 구성: "+json.dumps({"train": split["train_dataset_counts"], "valid": split["valid_dataset_counts"]},ensure_ascii=False),
             "검증 그룹: "+", ".join(split["valid_groups"]), "",
             f"배치 {BATCH}, 본학습 최대 {EPOCHS} epoch, 조기 종료 대기 {PATIENCE} epoch, seed {SEED}",
             "공통 encoder: Conv1D 16→32→32, Dense 32 / 특성 MLP 16→8 / 결합 40→16",
             "두 encoder 모두 bias 없음, 마지막 출력 선형. AE에만 입력별 복원층 존재.",
             "AE: AdamW lr=0.001, waveform MAE + feature MAE (각 분기 평균, 가중치 1:1)",
             "Deep SVDD: AdamW lr=0.0001, 고정 비영 중심까지의 제곱거리 평균",
             "SVDD는 AE의 고정된 20번째 epoch encoder로 사전학습 초기화. 해당 epoch는 검증 성능으로 선택하지 않음.",
             "두 optimizer 모두 weight_decay=0.0001, lr은 50/80 epoch 후 0.3배, gradient clip norm=5",
             "최종 checkpoint는 각 모델 자신의 검증 loss 최저 epoch로 선택.", "",
             "정확도 정의: 정상으로 가정한 검증 구간 중 정상 판정한 비율. (1 - 정상 오탐률)",
             "매 epoch 현재 학습 점수의 99백분위를 기준값으로 계산하고 해당 epoch 검증에 적용.",
             "검증 점수로 기준값을 맞추지 않았으므로 정확도가 강제로 99%가 되는 계산은 아님.",
             "각 epoch의 모델/기준값이 함께 갱신되며, 최종 배포 기준값은 선택된 checkpoint에 저장.", ""]
    for name, result in results.items():
        r = result["best_checkpoint_metrics"]
        lines += [name, f"  실행 epoch: {result['epochs_run']} / 선택 epoch: {result['best_epoch']}",
                  f"  파라미터 수: {result['parameter_count']:,}", f"  valid loss: {r['valid_loss']:.9g}",
                  f"  정상 검증 정확도: {100*r['valid_accuracy_normal_only']:.2f}% ({r['valid_normal_accepted']}/147)",
                  f"  정상 오탐률: {100*r['valid_false_positive_rate']:.2f}%",
                  f"  기준값: {r['threshold_train_quantile']:.9g}", ""]
    lines += ["해석의 범위", "  AE loss와 SVDD loss는 정의·척도가 다르므로 작은 숫자로 승자를 정할 수 없음.",
              "  정상 검증 정확도가 높은 모델은 이번 정상 검증군에서 경고를 적게 냈다는 뜻.",
              "  이상을 전혀 알리지 않는 모델도 정상 정확도 100%가 가능하므로 전체 이상 탐지 성능 순위를 정할 수 없음.",
              "  이상 검출률·AUROC·F1·정밀도는 실제 이상 검증 표본이 없어 계산하지 않음.",
              "  무동작 인형 영상과 실제 이상 사례에 대한 민감도·지연 시간은 이번 실험에 포함되지 않음.",
              "  두 corpus의 검증 비중은 그룹 보존 제약 때문에 학습과 차이가 있음.",
              "  새로운 입력의 간격 특성에 NaN이 생기는 경우의 정책은 별도 구현 필요.", "",
              "그래프: graphs/validation_curves.png 및 .svg", "원시 기록: 각 모델 폴더/history.json",
              "검증 구간별 점수·판정: 각 모델 폴더/valid_predictions.json", "검증 검사: verification.json"]
    (RUN/"실험결과.txt").write_text("\n".join(lines)+"\n", encoding="utf-8")


def main():
    if (RUN/"comparison.json").exists():
        raise FileExistsError("Completed experiment exists; use a new run name rather than overwrite it")
    RUN.mkdir(parents=True, exist_ok=True)
    random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)
    torch.set_num_threads(2)
    torch.backends.cudnn.benchmark = False; torch.backends.cudnn.deterministic = True
    torch.backends.cuda.matmul.allow_tf32 = False; torch.backends.cudnn.allow_tf32 = False
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda": torch.cuda.manual_seed_all(SEED)
    train_set, valid_set, split, scaler = setup_data()
    config = {"started_at": now(), "seed": SEED, "device": str(device), "torch_version": str(torch.__version__),
              "gpu": torch.cuda.get_device_name() if device.type == "cuda" else None,
              "batch_size": BATCH, "max_epochs": EPOCHS, "early_stopping_patience": PATIENCE,
              "deep_svdd_pretraining_epochs": PRETRAIN, "threshold_train_quantile": QUANTILE,
              "model_selection": "lowest own validation loss; never lowest cross-model loss",
              "class_assumption": "All 731 windows are assumed normal by explicit user decision; not independently confirmed labels",
              "code_sha256": {name: digest(Path(__file__).with_name(name)) for name in ("oneclass_models.py", "train_oneclass_comparison.py")}}
    save(RUN/"shared/config.json", config)
    print(f"TRAINING_START: train={len(train_set)}, valid={len(valid_set)}, device={device}; valid_groups={split['valid_groups']}", flush=True)
    ae = FusionAutoencoder().to(device)
    results = {"autoencoder": train_model("autoencoder", ae, train_set, valid_set, split, scaler, device)}
    del ae; gc.collect()
    if device.type == "cuda": torch.cuda.empty_cache()
    svdd = FusionEncoder().to(device)
    warm = torch.load(RUN/"autoencoder/pretrain_epoch020.pt", map_location=device, weights_only=True)
    svdd.load_state_dict(warm["encoder_state_dict"])
    with torch.no_grad():
        svdd.eval()
        z = torch.cat([svdd(w.to(device), f.to(device)) for w, f in loaders(train_set)])
        center = z.mean(dim=0)
        center = torch.where(center.abs() < .1, torch.where(center < 0, -.1, .1), center).detach()
        assert torch.isfinite(center).all() and (center.abs() >= .099999).all()
    save(RUN/"deep_svdd/center.json", {"value": center.cpu().tolist(), "initialized_from": "training embeddings only, fixed epoch-20 AE encoder", "fixed_during_training": True, "minimum_absolute_component": .1})
    results["deep_svdd"] = train_model("deep_svdd", svdd, train_set, valid_set, split, scaler, device, center)
    final_audit(train_set, valid_set, split, scaler, results, device)
    plot_results(results)
    report(results, split, config)
    save(RUN/"progress.json", {"updated_at": now(), "complete": True, "models": results})
    print("TRAINING_COMPLETE", json.dumps(results,ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
