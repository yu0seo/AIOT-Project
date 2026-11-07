"""차량별 도로 좌표 → 점수. 검증할 수 없는 좌표에서는 판단을 보류한다."""
import json
from collections import deque
from dataclasses import dataclass
from numbers import Integral, Real
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from .data import load_track, normalize
from .features import FEATURE_NAMES, FeatureConfig, FeatureStream
from .model import create_model, predict_scores


@dataclass(frozen=True)
class CoordinateQuality:
    """호출자가 실측 기준점·ROI·추적기로 확인한 근거. XY만으로 스케일을 알 수 없다."""
    metric_scale_verified: bool = False
    control_point_error_m: float | None = None
    within_road_roi: bool = False
    tracking_ok: bool = False
    calibration_id: str = ""

    def rejection_reason(self, max_error_m):
        if self.metric_scale_verified is not True:
            return "미터 스케일 검증 필요"
        if not isinstance(self.control_point_error_m, Real) or not np.isfinite(self.control_point_error_m):
            return "도로 기준점 오차 측정 필요"
        if not 0 <= self.control_point_error_m <= max_error_m:
            return "도로 기준점 오차 초과"
        if self.within_road_roi is not True:
            return "검증된 도로 ROI 밖"
        if self.tracking_ok is not True:
            return "추적 품질 불량"
        if not self.calibration_id:
            return "보정 버전 식별자 필요"
        return ""


@dataclass
class TrackState:
    stream: FeatureStream
    window: deque
    calibration_id: str
    last_timestamp_ns: int
    segment_id: int = 0


class VehiclePredictor:
    def __init__(self, bundle, device="cpu", max_tracks=512, idle_timeout_s=30):
        bundle = Path(bundle)
        self.metadata = json.loads((bundle/"metadata.json").read_text(encoding="utf-8"))
        meta = self.metadata
        if meta["format_version"] != 1 or meta["feature_order"] != list(FEATURE_NAMES):
            raise ValueError("지원하지 않는 모델/특징 순서입니다.")
        self.config = FeatureConfig(**meta["feature_config"])
        self.steps = meta["timesteps"]
        if self.steps != round(meta["window_seconds"]*self.config.sample_hz) or meta["sample_hz"] != self.config.sample_hz:
            raise ValueError("모델과 전처리의 시간축 설정이 다릅니다.")
        normalize(np.zeros((1, 4)), meta["normalizer"])
        self.threshold = float(meta["threshold"])
        if not np.isfinite(self.threshold) or not 0 <= self.threshold <= np.nextafter(1., np.inf):
            raise ValueError("유효하지 않은 분류 임계값입니다.")
        self.max_error_m = float(meta["coordinate_quality"]["max_control_point_error_m"])
        if not np.isfinite(self.max_error_m) or self.max_error_m < 0:
            raise ValueError("기준점 오차 한계가 잘못되었습니다.")
        if max_tracks < 1 or idle_timeout_s <= self.config.max_gap_s:
            raise ValueError("추적 저장 한도/만료 시간을 확인하세요.")
        self.model = create_model(meta["model_type"], meta["architecture"]).to(device)
        self.model.load_state_dict(torch.load(bundle/"model.pt", map_location=device, weights_only=True))
        self.model.eval()
        self.device = device
        self.max_tracks = max_tracks
        self.idle_timeout_ns = round(idle_timeout_s*1e9)
        self.tracks: dict[str, TrackState] = {}

    def drop_track(self, vehicle_id):
        """ByteTrack의 lost/removed, ID 재사용, 카메라 변경 시 호출한다."""
        self.tracks.pop(vehicle_id, None)

    def update(self, vehicle_id, timestamp_ns, x_m, y_m, *, quality=None):
        result = {"vehicle_id": vehicle_id, "status": "abstain", "score": None, "suspected": None,
                  "reason": "", "threshold": self.threshold}
        if not isinstance(vehicle_id, str) or not vehicle_id:
            return {**result, "reason": "비어 있지 않은 차량 ID 문자열이 필요합니다."}
        reason = quality.rejection_reason(self.max_error_m) if isinstance(quality, CoordinateQuality) else "좌표 품질 검증 필요"
        if isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, Integral):
            reason = "정수 ns 시각이 필요합니다."
        if reason:
            self.drop_track(vehicle_id)
            return {**result, "reason": reason}
        timestamp_ns = int(timestamp_ns)
        expired = [key for key, state in self.tracks.items()
                   if timestamp_ns-state.last_timestamp_ns > self.idle_timeout_ns]
        for key in expired:
            self.drop_track(key)
        state = self.tracks.get(vehicle_id)
        if state is None or state.calibration_id != quality.calibration_id:
            if state is None and len(self.tracks) >= self.max_tracks:
                oldest = min(self.tracks, key=lambda key: self.tracks[key].last_timestamp_ns)
                self.drop_track(oldest)
            state = TrackState(FeatureStream(self.config), deque(maxlen=self.steps), quality.calibration_id, timestamp_ns)
            self.tracks[vehicle_id] = state
        try:
            points = state.stream.update(timestamp_ns, x_m, y_m)
        except (ValueError, TypeError, OverflowError) as error:
            self.drop_track(vehicle_id)
            return {**result, "reason": str(error)}
        state.last_timestamp_ns = timestamp_ns
        if state.stream.segment_id != state.segment_id:
            state.window.clear()
            state.segment_id = state.stream.segment_id
        for point in points:
            state.window.append(point.values)
        if len(state.window) < self.steps:
            return {**result, "status": "warming_up", "reason": state.stream.reason or "Window 이력 수집 중",
                    "valid_feature_points": len(state.window), "required_feature_points": self.steps}
        if not points:
            return {**result, "status": "waiting_for_sample", "reason": "새 10Hz 특징을 기다리는 중"}
        values = normalize(np.asarray(state.window)[None], self.metadata["normalizer"])
        score = float(predict_scores(self.model, values, device=self.device)[0])
        return {**result, "status": "ok", "score": score, "suspected": score >= self.threshold,
                "feature_timestamp_ns": points[-1].timestamp_ns,
                "available_at_ns": points[-1].available_at_ns,
                "resampling_delay_s": (points[-1].available_at_ns-points[-1].timestamp_ns)/1e9}


def homography_to_road(homography, u_px, v_px):
    """검증된 pixel→meter H에 대한 수치 검사. 실제 미터 정확도를 보장하지 않는다."""
    matrix = np.asarray(homography, dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all() or np.linalg.cond(matrix) > 1e12:
        raise ValueError("유효하지 않거나 특이한 Homography입니다.")
    point = matrix @ np.array([u_px, v_px, 1.], dtype=float)
    if not np.isfinite(point).all() or abs(point[2]) < 1e-10*np.linalg.norm(matrix):
        raise ValueError("투영점이 지평선에 가깝거나 유효하지 않습니다.")
    return tuple(point[:2]/point[2])


def replay_idd(bundle, ego_csv, output):
    """시뮬레이터 좌표의 온라인 경로 확인용. CCTV 품질을 확인한 것으로 간주하지 않는다."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"기존 결과를 덮어쓰지 않습니다: {output}")
    times, xy, _ = load_track(ego_csv)
    predictor = VehiclePredictor(bundle)
    torch.set_num_threads(2)
    quality = CoordinateQuality(True, 0., True, True, "IDD-simulator-replay-only")
    rows = []
    for stamp, point in zip(times, xy):
        rows.append({"input_timestamp_ns": int(stamp), **predictor.update("IDD-ego", int(stamp), *point, quality=quality)})
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output, index=False, encoding="utf-8-sig")
    print(f"IDD 온라인 재생 결과 저장: {output}")
