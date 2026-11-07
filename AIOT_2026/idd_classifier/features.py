"""학습/추론 공용: 제한 지연 리샘플링과 과거 좌표의 다항식 미분."""
from collections import Counter, deque
from dataclasses import asdict, dataclass
from itertools import groupby
from numbers import Integral

import numpy as np

FEATURE_NAMES = ("speed", "acceleration", "jerk", "turn_rate")
FEATURE_UNITS = ("m/s", "m/s²", "m/s³", "rad/s")
FEATURE_DEFINITIONS = (
    "평활 궤적 속도 벡터 v의 크기 ||v||",
    "속력의 부호 있는 시간 미분 (v·a)/||v||, 정지 시 0",
    "평활 궤적 가속도 벡터의 시간 미분 크기 ||j||",
    "경로 진행 방향 변화율 절댓값 |vx*ay-vy*ax|/||v||², 저속 시 0",
)


@dataclass(frozen=True)
class FeatureConfig:
    sample_hz: int = 10
    smooth_points: int = 11
    polynomial_degree: int = 3
    max_gap_s: float = 0.2
    max_raw_speed_mps: float = 80.0
    position_slack_m: float = 0.5
    min_turn_speed_mps: float = 0.5

    def __post_init__(self):
        integer_settings = (self.sample_hz, self.smooth_points, self.polynomial_degree)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in integer_settings):
            raise ValueError("주파수, 평활화 점 수, 다항식 차수는 정수여야 합니다.")
        if self.sample_hz <= 0 or 1_000_000_000 % self.sample_hz:
            raise ValueError("샘플링 주파수는 ns 격자로 표현 가능한 양의 정수여야 합니다.")
        if self.polynomial_degree != 3 or self.smooth_points < 4:
            raise ValueError("3차 다항식과 최소 4개의 평활화 점이 필요합니다.")
        vals = [self.max_gap_s, self.max_raw_speed_mps, self.position_slack_m, self.min_turn_speed_mps]
        if not np.isfinite(vals).all() or self.max_gap_s < 1/self.sample_hz or self.max_raw_speed_mps <= 0 or min(vals[2:]) < 0:
            raise ValueError("단절/속도/좌표 허용값 설정이 잘못되었습니다.")

    def metadata(self):
        return {**asdict(self), "resampling": "bracketed_linear_bounded_delay",
                "smoothing": "trailing_polynomial_endpoint", "max_resampling_delay_s": self.max_gap_s,
                "warmup_s": (self.smooth_points-1)/self.sample_hz,
                "derivatives": "동일 다항식의 해석적 1/2/3차 미분", "version": 1}


@dataclass
class FeaturePoint:
    timestamp_ns: int
    available_at_ns: int
    values: np.ndarray
    segment_id: int


@dataclass
class FeatureSegment:
    timestamps_ns: np.ndarray
    values: np.ndarray
    segment_id: int


class FeatureStream:
    """관측 도착 시 호출한다. 미래 데이터 없이 최대 max_gap_s만큼 대기한다.

    오른쪽 관측 도착 이후 두 관측 사이의 격자만 선형 보간한다. 긴 단절,
    결측, 비현실적인 위치 점프는 상태를 초기화하며 그 사이를 연결하지 않는다.
    """
    def __init__(self, config: FeatureConfig):
        self.config = config
        self.period_ns = 1_000_000_000 // config.sample_hz
        self.positions = deque(maxlen=config.smooth_points)
        times = np.arange(1-config.smooth_points, 1, dtype=np.float64)/config.sample_hz
        self.coefficient_weights = np.linalg.pinv(np.vander(times, 4, increasing=True))
        self.audit = Counter(missing_coordinates=0, gaps=0, jumps=0)
        self.last_seen = None
        self.segment_id = 0
        self.previous = None
        self.next_grid = None
        self.reason = "평활화 이력 수집 중"

    def reset(self, reason="추적 상태 초기화"):
        self.positions.clear()
        self.previous = None
        self.next_grid = None
        self.segment_id += 1
        self.reason = reason

    def _on_grid(self, timestamp_ns, xy, available_at_ns):
        self.positions.append(xy.copy())
        if len(self.positions) < self.config.smooth_points:
            return None
        # 큰 절대 좌표 때문에 미분 오차가 커지지 않게 마지막 점을 원점으로 이동한다.
        points = np.asarray(self.positions)
        c = self.coefficient_weights @ (points-points[-1])
        v, a, j = c[1], 2*c[2], 6*c[3]
        speed = float(np.linalg.norm(v))
        acceleration = float(v@a/speed) if speed > 1e-8 else 0.0
        turn = abs(v[0]*a[1]-v[1]*a[0])/speed**2 if speed >= max(1e-8, self.config.min_turn_speed_mps) else 0.0
        values = np.array([speed, acceleration, np.linalg.norm(j), turn], dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError("유효하지 않은 특징이 발생했습니다.")
        self.reason = ""
        return FeaturePoint(timestamp_ns, available_at_ns, values, self.segment_id)

    def update(self, timestamp_ns: int, x_m: float, y_m: float):
        if isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, Integral):
            raise ValueError("타임스탬프는 정수 ns여야 합니다.")
        timestamp_ns = int(timestamp_ns)
        if not 0 <= timestamp_ns <= np.iinfo(np.int64).max:
            raise ValueError("타임스탬프는 0 이상 int64 범위의 ns여야 합니다.")
        if self.last_seen is not None and timestamp_ns <= self.last_seen:
            raise ValueError("중복 또는 역순 타임스탬프입니다. 자동 정렬하지 않습니다.")
        self.last_seen = timestamp_ns
        xy = np.array([x_m, y_m], dtype=np.float64)
        if not np.isfinite(xy).all():
            self.audit["missing_coordinates"] += 1
            self.reset("좌표 결측")
            return []
        if self.previous is not None:
            t0, p0 = self.previous
            delta_s = (timestamp_ns-t0)/1e9
            if timestamp_ns-t0 > round(self.config.max_gap_s*1e9):
                self.audit["gaps"] += 1
                self.reset("관측 단절")
            elif np.linalg.norm(xy-p0) > self.config.max_raw_speed_mps*delta_s+self.config.position_slack_m:
                self.audit["jumps"] += 1
                self.reset("좌표 점프")
        if self.previous is None:
            self.previous = (timestamp_ns, xy)
            self.next_grid = timestamp_ns+self.period_ns
            self._on_grid(timestamp_ns, xy, timestamp_ns)
            return []
        t0, p0 = self.previous
        result = []
        while self.next_grid <= timestamp_ns:
            alpha = (self.next_grid-t0)/(timestamp_ns-t0)
            point = self._on_grid(self.next_grid, p0+alpha*(xy-p0), timestamp_ns)
            if point is not None:
                result.append(point)
            self.next_grid += self.period_ns
        self.previous = (timestamp_ns, xy)
        return result


def extract_segments(timestamps_ns, xy, config: FeatureConfig):
    """오프라인에서도 스트림 함수를 그대로 호출한다. 구간 사이를 잇지 않는다."""
    timestamps_ns, xy = np.asarray(timestamps_ns), np.asarray(xy, dtype=np.float64)
    if timestamps_ns.ndim != 1 or xy.shape != (len(timestamps_ns), 2):
        raise ValueError("시각은 (N,), 좌표는 (N,2)여야 합니다.")
    if timestamps_ns.dtype.kind not in "iu":
        raise ValueError("시각 배열은 정수 ns여야 합니다.")
    stream = FeatureStream(config)
    points = []
    for t, p in zip(timestamps_ns, xy):
        points.extend(stream.update(int(t), p[0], p[1]))
    segments = []
    for segment_id, grouped_points in groupby(points, key=lambda point: point.segment_id):
        group = list(grouped_points)
        segments.append(FeatureSegment(np.array([p.timestamp_ns for p in group], dtype=np.int64),
                                       np.array([p.values for p in group]), segment_id))
    return segments, dict(stream.audit)
