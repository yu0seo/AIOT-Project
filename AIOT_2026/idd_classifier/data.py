"""실사한 IDD CSV 구조의 명시적 로딩, 품질 검사와 참가자 분할."""
import csv
import hashlib
import random
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd

from .features import FeatureConfig, FeatureSegment, extract_segments

COORDINATE_COLUMNS = ("resampled_epoch_ns", "carla_objects_pose_x", "carla_objects_pose_y")
SCENARIO_CODES = ("1a", "2", "2b", "3c", "5", "6e", "7a", "8a")
INDEX_COLUMNS = {"scenario_index", "scenario_name", "scenario_path", "round", "cognitive_task",
                 "start_time", "end_time", "duration_s", "duration_frames"}


def processed_root(root):
    root = Path(root).expanduser().resolve()
    if (root/"Processed").is_dir():
        root = root/"Processed"
    if not (root/"Resampled_previous_10"/"Participants").is_dir():
        raise FileNotFoundError(f"IDD 10Hz 참가자 인덱스가 없습니다: {root}")
    return root


def label_for(participant, round_name):
    """공식 DDD2024Dataset 규칙. 알 수 없는 ID/round는 추정하지 않는다."""
    if not re.fullmatch(r"P\d+|\d+", participant) or round_name not in ("R1", "R2"):
        raise ValueError(f"검증되지 않은 참가자/round: {participant}/{round_name}")
    return int(participant.startswith("P") and round_name == "R2")


def read_annotations(root):
    path = root/"idd_annotation.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    if len(rows) < 2 or len(rows[0]) < 65 or len(rows[1]) < 65 or rows[0][57] != "Alcohol":
        raise ValueError("실사한 IDD 주석의 Alcohol 그룹 위치와 다릅니다.")
    for start in (1, 57):
        if tuple(rows[1][start:start+8]) != SCENARIO_CODES:
            raise ValueError("IDD 주석의 두 줄 헤더 구조가 변경되었습니다.")
    result = {}
    for row in rows[2:]:
        if not row or not re.fullmatch(r"P\d+|\d+", row[0]):
            continue
        if len(row) < 65 or row[0] in result:
            raise ValueError("잘못되거나 중복된 IDD 주석 행입니다.")
        result[row[0]] = {code: {"anomaly": row[1+i].strip(), "alcohol": row[57+i].strip()}
                          for i, code in enumerate(SCENARIO_CODES)}
    return result


def build_manifest(root, config):
    """모든 실제 인덱스를 검사하고 각 주행의 포함/제외 이유를 기록한다."""
    root = processed_root(root)
    annotations = read_annotations(root)
    rows = []
    index_files = sorted((root/"Resampled_previous_10"/"Participants").glob("*/scenario_index.csv"))
    if config["cohort"] not in ("experiment1", "all"):
        raise ValueError("cohort는 experiment1 또는 all이어야 합니다.")
    for index_path in index_files:
        participant = index_path.parent.name
        table = pd.read_csv(index_path, dtype=str, keep_default_na=False)
        if not INDEX_COLUMNS.issubset(table.columns) or table["scenario_path"].duplicated().any():
            raise ValueError(f"잘못된 인덱스 컬럼 또는 중복 시나리오: {index_path}")
        for row in table.to_dict("records"):
            if not row["scenario_name"].startswith("driving/") or row["scenario_name"] == "driving/practice":
                continue
            path = PurePosixPath(row["scenario_path"])
            expected = (row["round"], *row["scenario_name"].split("/"), row["cognitive_task"])
            if path.is_absolute() or path.parts != expected or ".." in path.parts or "\\" in str(path):
                raise ValueError(f"인덱스 메타데이터와 경로가 다릅니다: {participant}/{path}")
            label = label_for(participant, row["round"])
            code = path.parts[2].split("-")[0]
            if code not in SCENARIO_CODES:
                raise ValueError(f"검증되지 않은 실험 시나리오: {code}")
            reasons = []
            if participant in config["exclude_participants"]:
                reasons.append("공식 제외 참가자")
            if config["cohort"] == "experiment1" and not participant.startswith("P"):
                reasons.append("다른 실험 집단")
            if row["cognitive_task"] not in config["tasks"]:
                reasons.append("주의분산 조건 제외")
            annotation = annotations.get(participant, {}).get(code)
            if annotation and config["exclude_annotated_anomalies"] and annotation["anomaly"]:
                reasons.append("시뮬레이터 이상 주석")
            if not reasons and annotation is None:
                raise ValueError(f"선택된 참가자에 검증용 주석이 없습니다: {participant}")
            if annotation is not None:
                alcohol = annotation["alcohol"]
                if alcohol not in ("", "0", "1"):
                    raise ValueError(f"알 수 없는 Alcohol 주석: {participant}/{code}")
                if not reasons and int(alcohol == "1") != label:
                    raise ValueError(f"공식 라벨과 Alcohol 주석 불일치: {participant}/{code}")
            relative = Path("Resampled_previous_10_derived")/"Participants"/participant/Path(*path.parts)/"ego_tracks.csv"
            exists = (root/relative).is_file()
            if not reasons and not exists:
                raise FileNotFoundError(f"선택된 ego CSV 누락: {root/relative}")
            rows.append({"participant": participant, "round": row["round"], "label": label,
                         "task": row["cognitive_task"], "scenario_name": row["scenario_name"],
                         "scenario_id": f"{participant}/{path}", "relative_path": relative.as_posix(),
                         "exists": exists, "included": not reasons, "exclusion_reason": "; ".join(reasons)})
    manifest = pd.DataFrame(rows)
    if manifest.empty or manifest["scenario_id"].duplicated().any():
        raise ValueError("주행 인덱스가 없거나 중복되었습니다.")
    return root, manifest


def load_track(path):
    """ns 정밀도를 보존한다. 역순/중복을 정렬로 숨기지 않는다."""
    path = Path(path)
    table = pd.read_csv(path, usecols=list(COORDINATE_COLUMNS), dtype={"resampled_epoch_ns": "string"})
    raw_times = table["resampled_epoch_ns"]
    if table.empty or raw_times.isna().any() or not raw_times.str.fullmatch(r"\d+").all():
        raise ValueError(f"비어 있거나 정수 ns가 아닌 타임스탬프: {path}")
    times = raw_times.to_numpy(dtype=np.int64)
    if np.any(times[1:] <= times[:-1]):
        raise ValueError(f"중복/역순 타임스탬프: {path}")
    xy = table[list(COORDINATE_COLUMNS[1:])].apply(pd.to_numeric, errors="raise").to_numpy(dtype=np.float64)
    steps = np.diff(times)
    audit = {"rows": len(table), "missing_rows": int(np.sum(~np.isfinite(xy).all(axis=1))),
             "median_dt_s": float(np.median(steps)/1e9) if len(steps) else None,
             "non_100ms_intervals": int(np.sum(steps != 100_000_000)),
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return times, xy, audit


@dataclass
class Track:
    participant: str
    scenario_id: str
    label: int
    segments: list[FeatureSegment]


def prepare_tracks(root, manifest, feature_config: FeatureConfig):
    tracks, audits = [], []
    for row in manifest[manifest["included"]].to_dict("records"):
        times, xy, audit = load_track(root/row["relative_path"])
        segments, feature_audit = extract_segments(times, xy, feature_config)
        tracks.append(Track(row["participant"], row["scenario_id"], row["label"], segments))
        audits.append({"scenario_id": row["scenario_id"], **audit, **feature_audit,
                       "feature_segments": len(segments), "feature_rows": sum(len(s.values) for s in segments)})
    if not tracks:
        raise ValueError("선택 조건에 해당하는 주행이 없습니다.")
    return tracks, pd.DataFrame(audits)


def split_participants(manifest, seed, validation_fraction, test_fraction):
    """참가자가 가진 라벨 집합으로 층화하고 Window 생성 전에 분할한다."""
    if min(validation_fraction, test_fraction) <= 0 or validation_fraction+test_fraction >= 1:
        raise ValueError("train/validation/test 비율이 잘못되었습니다.")
    groups = {}
    for participant, rows in manifest.groupby("participant", sort=True):
        profile = tuple(sorted(rows["label"].unique()))
        groups.setdefault(profile, []).append(participant)
    rng = random.Random(seed)
    splits = {"train": [], "validation": [], "test": []}
    for participants in groups.values():
        if len(participants) < 3:
            raise ValueError("라벨 집합별 참가자가 3명 미만입니다. 누출 없이 세 분할을 만들 수 없습니다.")
        rng.shuffle(participants)
        nv = max(1, round(len(participants)*validation_fraction))
        nt = max(1, round(len(participants)*test_fraction))
        if nv+nt >= len(participants):
            raise ValueError("분할에 필요한 참가자가 부족합니다.")
        splits["validation"].extend(participants[:nv])
        splits["test"].extend(participants[nv:nv+nt])
        splits["train"].extend(participants[nv+nt:])
    for name, participants in splits.items():
        participants.sort()
        if set(manifest.loc[manifest["participant"].isin(participants), "label"]) != {0, 1}:
            raise ValueError(f"{name} 분할에 두 라벨이 모두 필요합니다.")
    return splits


def transform_features(values, transform="identity"):
    """원시 물리 피처 뒤에 적용하는 정규화 변환. 피처 추가나 clipping은 없다."""
    values = np.asarray(values)
    if transform == "identity":
        return values
    if transform == "signed_log1p":
        return np.sign(values)*np.log1p(np.abs(values))
    raise ValueError(f"지원하지 않는 정규화 변환: {transform}")


def fit_normalizer(tracks, train_participants, transform="identity"):
    # 겹친 Window의 반복 행으로 가중하지 않고 train의 특징 행을 한 번씩 사용한다.
    rows = [s.values for t in tracks if t.participant in train_participants for s in t.segments]
    if not rows:
        raise ValueError("정규화할 train 특징이 없습니다.")
    values = transform_features(np.concatenate(rows), transform)
    std = values.std(axis=0)
    std[std < 1e-8] = 1.0
    return {"mean": values.mean(axis=0).tolist(), "std": std.tolist(), "rows": len(values), "transform": transform}


def normalize(values, normalizer):
    """학습과 추론이 공유하는 train 기준 표준화. 추가 clipping은 하지 않는다."""
    mean = np.asarray(normalizer["mean"], dtype=np.float32)
    std = np.asarray(normalizer["std"], dtype=np.float32)
    if mean.shape != (4,) or std.shape != (4,) or not np.isfinite([mean, std]).all() or np.any(std <= 0):
        raise ValueError("정규화 평균/표준편차는 유한한 4개 값이며 표준편차는 양수여야 합니다.")
    transformed = transform_features(np.asarray(values, dtype=np.float32), normalizer.get("transform", "identity"))
    return ((transformed-mean)/std).astype(np.float32)


def make_windows(tracks, participants, steps, stride, anchor_steps):
    """길이 비교의 끝 시각을 공통 anchor에 맞춘다. 구간 경계는 넘지 않는다."""
    if steps <= 0 or stride <= 0 or anchor_steps < steps:
        raise ValueError("Window/stride/anchor 설정이 잘못되었습니다.")
    windows, labels, owners, scenarios, ends = [], [], [], [], []
    for track in tracks:
        if track.participant not in participants:
            continue
        for segment in track.segments:
            for end in range(anchor_steps-1, len(segment.values), stride):
                windows.append(segment.values[end+1-steps:end+1])
                labels.append(track.label)
                owners.append(track.participant)
                scenarios.append(track.scenario_id)
                ends.append(segment.timestamps_ns[end])
    if not windows:
        raise ValueError("해당 분할에 유효한 Window가 없습니다.")
    return {"x": np.asarray(windows, dtype=np.float32), "y": np.asarray(labels, dtype=np.float32),
            "participant": np.asarray(owners), "scenario_id": np.asarray(scenarios),
            "end_ns": np.asarray(ends, dtype=np.int64)}
