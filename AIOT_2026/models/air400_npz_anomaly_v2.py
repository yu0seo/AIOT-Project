"""AIR-400 windows/**/*.npz -> 영아 단위 train/valid/test -> 1D CNN Denoising Autoencoder."""

import argparse
import csv
import json
import re
from pathlib import Path
from zipfile import BadZipFile

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

BPM_WEIGHT = 0.2
NOISE_STD = 0.05  # 표준화된 파형에 학습할 때만 넣는 노이즈
SEED = 42


class Autoencoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv1d(1, 16, 9, stride=2, padding=4), nn.SiLU(),   # 300 -> 150
            nn.Conv1d(16, 24, 9, stride=3, padding=4), nn.SiLU(),  # 150 -> 50
            nn.Conv1d(24, 2, 5, padding=2),                       # (B, 2, 50)
        )
        self.decoder = nn.Sequential(
            nn.Conv1d(3, 24, 5, padding=2), nn.SiLU(),
            nn.Upsample(scale_factor=3, mode="linear", align_corners=False),
            nn.Conv1d(24, 16, 7, padding=3), nn.SiLU(),
            nn.Upsample(scale_factor=2, mode="linear", align_corners=False),
            nn.Conv1d(16, 1, 9, padding=4),                        # (B, 1, 300)
        )
        self.bpm_head = nn.Sequential(nn.Linear(10, 32), nn.SiLU(), nn.Linear(32, 1))

    def forward(self, wave, bpm):
        z = self.encoder(wave)
        # 파형 복원에만 입력 BPM을 쓴다. BPM은 잠재 파형의 반복 패턴에서 재추정한다.
        bpm_context = bpm.unsqueeze(-1).expand(-1, -1, z.size(-1))
        wave_hat = self.decoder(torch.cat((z, bpm_context), dim=1))
        centered = z - z.mean(dim=-1, keepdim=True)
        unit = centered / (centered.square().mean(dim=-1, keepdim=True) + 1e-5).sqrt()
        lags = torch.cat([(unit[..., lag:] * unit[..., :-lag]).mean(dim=-1)
                          for lag in range(1, 6)], dim=1)
        return wave_hat, self.bpm_head(lags)


def read_metadata(data, required):
    try:
        info = json.loads(data["metadata_json"].item())
        if not isinstance(info, dict):
            raise ValueError("JSON 객체가 아닙니다")
        return info
    except (KeyError, TypeError, ValueError) as exc:
        if required:
            raise ValueError(f"metadata_json을 읽을 수 없습니다: {exc}") from exc
        return None  # 기본 모드의 영아 ID는 폴더명에서 읽는다.


def metadata_value(info, key):
    value = info.get(key)
    if not isinstance(value, (str, int, float, bool)) or not str(value).strip():
        raise ValueError(f"metadata_json에 유효한 '{key}' 값이 없습니다. 키: {list(info)}")
    return str(value).strip()


def load_windows(args):
    paths = sorted(args.windows_dir.rglob("*.npz"))
    if not paths:
        raise ValueError(f"NPZ 파일을 찾지 못했습니다: {args.windows_dir}")
    waves, bpms, rows = [], [], []
    subjects_by_video = {}
    for path in paths:
        rel = path.relative_to(args.windows_dir)
        try:
            if len(rel.parts) < 2:
                raise ValueError("windows 폴더 아래 영상별 하위 폴더에 NPZ가 있어야 합니다.")
            video = rel.parts[0]
            with np.load(path, allow_pickle=False) as data:
                wave = np.asarray(data["x_10hz"], dtype=np.float32)
                bpm = np.asarray(data["pred_rr_bpm"], dtype=np.float32).item()
                info = read_metadata(data, bool(args.subject_key or args.normal_key))
            if wave.shape != (300,):
                raise ValueError(f"x_10hz shape은 (300,)이어야 합니다. 현재: {wave.shape}")
            if args.subject_key:
                subject = metadata_value(info, args.subject_key)
                if subjects_by_video.setdefault(video, subject) != subject:
                    raise ValueError("같은 영상 폴더에 서로 다른 영아 ID가 있습니다.")
            else:
                match = re.search(r"(?:^|_)S(\d+)(?=_|$)", video, flags=re.IGNORECASE)
                if not match:
                    raise ValueError("영상 폴더명에서 S번호를 찾지 못했습니다. --subject-key를 지정하세요.")
                subject = f"S{int(match.group(1)):02d}"
            is_normal = args.all_normal or (
                metadata_value(info, args.normal_key).casefold() == args.normal_value.strip().casefold()
            )
        except (BadZipFile, EOFError, KeyError, OSError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}: {exc}") from exc
        waves.append(wave)
        bpms.append(bpm)
        rows.append({
            "npz_file": rel.as_posix(), "video_id": video, "subject_id": subject,
            "pred_rr_bpm": bpm if np.isfinite(bpm) else "", "is_normal": is_normal,
            "valid_input": bool(np.isfinite(wave).all() and np.isfinite(bpm) and bpm > 0),
            "metadata_json": json.dumps(info, ensure_ascii=False) if info is not None else "",
        })
    return np.stack(waves)[:, None, :], np.asarray(bpms, dtype=np.float32)[:, None], rows


def split_by_subject(groups, usable_normal):
    ids = np.random.default_rng(SEED).permutation(np.unique(groups))
    if len(ids) < 3:
        raise ValueError("train/valid/test를 영아 단위로 나누려면 영아가 최소 3명 필요합니다.")
    normal_ids = set(groups[usable_normal])
    if len(normal_ids) < 2:
        raise ValueError("학습과 임계값 보정에 유효한 정상 구간이 있는 영아가 최소 2명 필요합니다.")
    # train과 valid에 각각 정상 영아 그룹이 들어가도록 먼저 한 그룹씩 배정한다.
    train_anchor, valid_anchor = [g for g in ids if g in normal_ids][:2]
    rest = [g for g in ids if g not in (train_anchor, valid_anchor)]
    n_train = min(len(ids) - 2, max(1, round(0.70 * len(ids))))
    n_valid = min(len(ids) - n_train - 1, max(1, round(0.15 * len(ids))))
    cut = n_train - 1
    train_ids = [train_anchor] + rest[:cut]
    valid_ids = [valid_anchor] + rest[cut:cut + n_valid - 1]
    return np.select([np.isin(groups, train_ids), np.isin(groups, valid_ids)],
                     ["train", "valid"], default="test")


def make_loader(wave, bpm, idx, stats, shuffle=False):
    x = (wave[idx] - stats["wave_mean"]) / stats["wave_std"]
    b = (bpm[idx] - stats["bpm_mean"]) / stats["bpm_std"]
    return DataLoader(TensorDataset(torch.from_numpy(x), torch.from_numpy(b)),
                      batch_size=64, shuffle=shuffle)


def errors(model, wave, bpm, *, training=False):
    wave_input = wave + NOISE_STD * torch.randn_like(wave) if training else wave
    wave_hat, bpm_hat = model(wave_input, bpm)  # 목표 파형 wave는 그대로 둔다.
    wave_mse = (wave_hat - wave).square().mean(dim=(1, 2))
    bpm_mse = (bpm_hat - bpm).square().mean(dim=1)
    return torch.stack((wave_mse, bpm_mse, wave_mse + BPM_WEIGHT * bpm_mse), dim=1)


def fit(model, train_loader, val_loader, device, epochs, patience=2):
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=1e-3)
    best_loss = float("inf")
    best_epoch = 0
    best_state = None
    stale_epochs = 0

    for epoch in range(1, epochs + 1):
        model.train()
        total = 0.0
        for wave, bpm in train_loader:
            optimizer.zero_grad()
            loss = errors(model, wave.to(device), bpm.to(device), training=True)[:, 2].mean()
            value = loss.item()
            if not np.isfinite(value):
                raise RuntimeError("학습 손실이 NaN 또는 Inf입니다. 파형과 BPM 범위를 확인하세요.")
            loss.backward()
            optimizer.step()
            total += value * len(wave)
        train_loss = total / len(train_loader.dataset)
        val_loss = float(score(model, val_loader, device)[:, 2].mean(dtype=np.float64))
        if val_loss < best_loss:
            best_loss, best_epoch = val_loss, epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
        if epoch == 1 or epoch % 10 == 0 or epoch == epochs or stale_epochs:
            print(f"epoch {epoch:>4}/{epochs}: train_loss={train_loss:.6f} | val_loss={val_loss:.6f}")
        if stale_epochs >= patience:
            print(f"조기 종료: epoch {epoch} (검증 손실 {patience}회 연속 미개선)")
            break

    model.load_state_dict(best_state)
    print(f"최적 모델 복원: epoch {best_epoch} | val_loss={best_loss:.6f}")
    return best_epoch, best_loss


@torch.inference_mode()
def score(model, loader, device):
    model.eval()
    batches = [errors(model, x.to(device), b.to(device)).cpu().numpy() for x, b in loader]
    result = np.concatenate(batches) if batches else np.empty((0, 3), dtype=np.float32)
    if not np.isfinite(result).all():
        raise RuntimeError("복원 오차에 NaN 또는 Inf가 있습니다. 입력 값의 범위를 확인하세요.")
    return result


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def scored_rows(rows, indices, usable_indices, scores, threshold):
    by_index = dict(zip(usable_indices, scores))
    result = []
    for i in indices:
        if i in by_index:
            wave_mse, bpm_mse, anomaly_score = map(float, by_index[i])
            flag = anomaly_score > threshold
        else:
            wave_mse = bpm_mse = anomaly_score = flag = ""  # 판정 불가
        result.append({**rows[i], "wave_mse": wave_mse, "bpm_mse": bpm_mse,
                       "anomaly_score": anomaly_score, "is_anomaly": flag})
    return result


def run(args):
    torch.manual_seed(SEED)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    wave, bpm, rows = load_windows(args)
    groups = np.array([r["subject_id"] for r in rows])
    valid_input = np.array([r["valid_input"] for r in rows], dtype=bool)
    usable_normal = valid_input & np.array([r["is_normal"] for r in rows], dtype=bool)
    splits = split_by_subject(groups, usable_normal)
    for row, split in zip(rows, splits):
        row["split"] = split
    for split in ("train", "valid", "test"):
        mask = splits == split
        print(f"{split}: 영아 {len(np.unique(groups[mask]))}명, 구간 {mask.sum()}개")
    missing_meta = sum(not row["metadata_json"] for row in rows)
    if missing_meta:
        print(f"metadata_json을 읽지 못한 {missing_meta}개 구간은 폴더명으로 식별했습니다.")

    train_idx = np.flatnonzero((splits == "train") & usable_normal)
    valid_idx = np.flatnonzero((splits == "valid") & usable_normal)
    test_idx = np.flatnonzero(splits == "test")
    test_ok = test_idx[valid_input[test_idx]]
    print(f"학습 정상 {len(train_idx)}개 / 임계값 보정 정상 {len(valid_idx)}개 / 테스트 유효 {len(test_ok)}개")
    x_train, b_train = wave[train_idx], bpm[train_idx]
    stats = {
        "wave_mean": float(x_train.mean(dtype=np.float64)),
        "wave_std": float(x_train.std(dtype=np.float64)),
        "bpm_mean": float(b_train.mean(dtype=np.float64)),
        "bpm_std": max(float(b_train.std(dtype=np.float64)), 1.0),
    }
    if stats["wave_std"] == 0.0:
        raise ValueError("학습용 정상 파형 전체에 변동이 없습니다.")

    model = Autoencoder().to(device)
    train_loader = make_loader(wave, bpm, train_idx, stats, shuffle=True)
    val_loader = make_loader(wave, bpm, valid_idx, stats)
    best_epoch, best_val_loss = fit(model, train_loader, val_loader, device, args.epochs, args.patience)
    # 최적 에포크의 정상 검증 점수로 임계값을 계산한다.
    val_scores = score(model, val_loader, device)
    threshold = float(np.quantile(val_scores[:, 2], 0.99, method="higher"))
    wave_mean, bpm_mean = val_scores[:, :2].mean(axis=0, dtype=np.float64)
    print(f"최적 모델 검증 손실 구성: wave_mse={wave_mean:.6f} | "
          f"0.2*bpm_mse={BPM_WEIGHT * bpm_mean:.6f}")
    if len(valid_idx) < 100 or len(np.unique(groups[valid_idx])) == 1:
        print("주의: 정상 보정 구간 또는 영아가 적어 임계값이 불안정할 수 있습니다.")

    test_scores = score(model, make_loader(wave, bpm, test_ok, stats), device)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"model_version": 2, "state_dict": model.cpu().state_dict(), "stats": stats,
                "bpm_weight": BPM_WEIGHT, "threshold": threshold,
                "best_epoch": best_epoch, "best_val_loss": best_val_loss},
               args.out_dir / "air400_ae.pt")
    write_csv(args.out_dir / "splits.csv", rows)
    write_csv(args.out_dir / "valid_scores.csv", scored_rows(rows, valid_idx, valid_idx, val_scores, threshold))
    write_csv(args.out_dir / "test_scores.csv", scored_rows(rows, test_idx, test_ok, test_scores, threshold))
    print(f"임계값: {threshold:.6f} | 테스트 이상 후보 {(test_scores[:, 2].astype(np.float64) > threshold).sum()}개")
    print(f"저장 위치: {args.out_dir.resolve()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("windows_dir", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("ae_results_v2"))
    parser.add_argument("--epochs", type=int, default=1000, help="최대 학습 에포크 (기본값: %(default)s)")
    parser.add_argument("--patience", type=int, default=2, help="조기 종료 인내 에포크 (기본값: %(default)s)")
    parser.add_argument("--subject-key", help="폴더명 S번호 대신 사용할 metadata_json의 영아 ID 키")
    normal = parser.add_mutually_exclusive_group(required=True)
    normal.add_argument("--all-normal", action="store_true", help="모든 유효 구간을 정상으로 취급")
    normal.add_argument("--normal-key", help="정상 라벨이 들어 있는 metadata_json 키")
    parser.add_argument("--normal-value", default="normal", help="--normal-key에서 정상으로 볼 값")
    args = parser.parse_args()
    if args.epochs < 1 or args.patience < 1:
        parser.error("--epochs와 --patience는 1 이상이어야 합니다.")
    try:
        run(args)
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
