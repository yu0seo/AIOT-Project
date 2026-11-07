# IDD 좌표 기반 LSTM 학습과 CCTV 추론

이 프로젝트는 Toyota IDD의 **음주/비음주 실험 조건**을 좌표 기반 네 가지 특징으로 분류한다. 실제 음주운전의 법적 판정이나 위험 운전의 프레임별 정답을 학습하는 모델이 아니다.

## 초기 기준 실험 상태

후속 성능 개선 실험은 [별도 실행 안내](IDD_IMPROVEMENT.md)를 참고한다. 아래 수치는 보존한 초기 LSTM 기준 실험 결과다.

실제 no-video 데이터로 3초, 5초, 10초 모델을 학습·검증·테스트했다. 실험 집단 차이를 줄이기 위해 P 참가자만 사용했고 주의분산 조건을 제외했다. 공식 제외 참가자와 시뮬레이터 이상 주석을 적용한 뒤 **20명, 75개 주행, 150,455개 좌표 행**이 남았다. 선택된 행에는 결측·중복 시각·100ms 간격 이탈·위치 점프가 없었다.

참가자는 train 12명, validation 4명, test 4명으로 분리했다. 모든 길이의 Window 수는 train 8,360개 / validation 2,912개 / test 2,993개다. 어떤 참가자나 시나리오도 분할을 넘지 않는다.

| 입력 길이 | 테스트 ROC-AUC | 테스트 Recall | 테스트 FPR |
|---|---:|---:|---:|
| 3초 | 0.5127 | 6.67% | 10.08% |
| 5초 | 0.5134 | 6.14% | 8.12% |
| 10초 | 0.5211 | 10.10% | 11.77% |

**현재 성능으로 관제에 권장할 수 있는 길이는 없다.** 검증 규칙으로는 10초가 선택되었으며 `best`에 저장했다. 이 파일은 연구용 기준 모델이다. 짧은 CCTV 관측을 고려한 3·5초 모델도 모두 보존했다. 숫자를 개선하기 위해 테스트 결과를 본 뒤 설정이나 임계값을 바꾸지 않았다.

Accuracy, Precision, F1, 혼동행렬, 참가자별 지표, 참가자 군집 신뢰구간은 [실제 결과 보고서](IDD_BASELINE_RESULTS.md)를 확인한다. 이 문서와 보고서의 수치는 실제 측정 결과다. 테스트에서 사용하는 인공 궤적은 소프트웨어 검증용이며 성능 보고서에 섞지 않았다.

## 설치

검증 환경은 Windows 11, Python 3.14.0, CPU이다. 프로젝트 루트 `AIOT_2026`에서 PowerShell로 실행한다. 다른 PC에서는 같은 데이터를 별도로 준비해야 한다.

```powershell
python -m venv .venv-idd
.\.venv-idd\Scripts\python.exe -m pip install -r requirements-idd-lock.txt
```

`requirements-idd-lock.txt`는 실제 실행 환경에서 생성한 전체 버전 목록이다. Python 버전이 달라 해당 고정 버전 설치가 어려우면 Python 3.11 이상에서 `python -m pip install -e .`로 `pyproject.toml`의 호환 범위를 사용할 수 있다. 이 경우 동일 수치 재현을 보장하지 않으며 새 환경을 결과와 함께 기록해야 한다.

직접 사용하는 라이브러리는 네 가지다.

- NumPy: 좌표 연산, 과거 구간 다항식 적합과 미분. 별도의 필터 라이브러리 없이 구현한다.
- pandas: 실제 CSV와 실험 결과 표를 읽고 저장한다.
- PyTorch: LSTM, BCEWithLogitsLoss, AdamW와 모델 가중치 저장에 사용한다.
- scikit-learn: 검증된 분류 지표와 ROC 임계값 계산에 사용한다. SciPy 등은 이 라이브러리의 설치 의존성이다.

테스트는 Python 표준 `unittest`를 사용한다. 별도 테스트 프레임워크는 필요하지 않다.

## 데이터 구조와 라벨 검증

`--data-root`에는 `no-video` 또는 그 안의 `Processed`를 전달한다. 코드에 PC별 절대 경로를 넣지 않는다.

```text
Processed/
  idd_annotation.csv
  Resampled_previous_10/
    Participants/<participant>/scenario_index.csv
  Resampled_previous_10_derived/
    Participants/<participant>/<scenario_path>/ego_tracks.csv
```

실제 인덱스 열은 `scenario_index, scenario_name, scenario_path, round, cognitive_task, start_time, end_time, duration_s, duration_frames`다. 전체 60명 인덱스에서 실제 주행 438개와 ego CSV의 연결을 확인했다. 실험용 로더는 `driving/practice`, 정지 과제, 시선 보정 과제를 사용하지 않는다.

`ego_tracks.csv`에서 읽는 열은 정확히 세 개다.

```text
resampled_epoch_ns
carla_objects_pose_x
carla_objects_pose_y
```

ns 시각은 정수로 파싱해 정밀도를 보존한다. IDD 파일에서는 시나리오 시작 기준 상대 시각이며 CCTV에서는 동일 시간원의 단조 증가 정수 ns를 사용하면 된다. X/Y는 미터 단위다. Toyota가 미리 계산한 yaw, speed, acceleration, jerk는 입력하지 않는다.

라벨은 공식 `DDD2024Dataset`과 같이 **P 참가자의 R2만 1**, P 참가자의 R1과 숫자 ID 참가자는 0으로 생성한다. 모르는 참가자 형식이나 round는 오류로 처리한다. 두 줄 헤더인 `idd_annotation.csv`의 Alcohol 그룹도 교차 확인하며, 공식 규칙과 주석이 다르면 학습을 중단한다. 비음주 실험 조건에 위험 조작이나 충돌이 있어도 음주로 재라벨링하지 않는다.

`configs/idd_lstm.json`의 기본 `cohort=experiment1`, `tasks=["no_task"]`를 사용한다. 숫자 ID 집단을 추가하려면 `cohort=all`로 명시할 수 있지만 이 집단에는 음주 양성이 없으므로 집단 차이가 분류에 영향을 줄 수 있다. 제외 목록은 공식 기본값을 따르며, 초기 80개 no_task 주행 중 이상 주석이 있는 5개를 추가로 제외해 75개가 남았다.

## 특징 정의와 온라인 처리 지연

순서와 단위는 아래와 같이 고정한다. 추가 입력 피처는 없다.

| 순서 | 피처 | 계산식 | 단위 |
|---:|---|---|---|
| 0 | speed | `norm(v)` | m/s |
| 1 | acceleration | `dot(v,a)/norm(v)` | m/s² |
| 2 | jerk | `norm(j)` | m/s³ |
| 3 | turn_rate | `abs(vx*ay-vy*ax)/norm(v)**2` | rad/s |

먼저 관측 사이를 10Hz로 선형 리샘플링한다. 오른쪽 관측이 실제 도착한 뒤에만 그 사이의 격자를 출력한다. 최대 0.2초까지만 기다리므로 이 리샘플링은 **명시적인 제한 지연**이 있다. 관측 사이가 0.2초를 초과하면 연결하지 않는다. CSV 끝을 외삽하거나 이후 관측이 아직 없는 시간을 미리 출력하지 않는다.

최근 11개 좌표, 즉 1초 이력에 3차 최소제곱 다항식을 맞추고 **현재 끝점**에서 v/a/j를 해석적으로 미분한다. 위치 평활화와 미분이 한 연산에 포함된다. 미래 구간을 사용하는 중앙 필터를 쓰지 않으며 오프라인과 온라인이 같은 `FeatureStream.update`를 호출한다. 가속도는 속력의 부호 있는 미분이고 jerk는 2차원 가속도 벡터 미분의 크기다. 경로 방향 미분의 식으로 turn_rate를 계산하므로 차량 yaw를 사용하지 않는다.

거의 정지해 `norm(v)≤1e-8`이면 acceleration을 0으로 처리한다. 방향이 안정적이지 않은 `speed<0.5m/s`에서는 turn_rate를 0으로 처리한다. 이 수치 처리 규칙과 한계값도 모델에 저장한다. 도로 좌표계를 평행 이동하거나 회전해도 이 네 특징의 의미는 유지된다.

3/5/10초는 각각 `(30,4)`, `(50,4)`, `(100,4)`다. 평활화의 초기 이력까지 고려하면 첫 점수는 약 3.9/5.9/10.9초 + 리샘플링 대기 후 나온다. 이 시간을 CCTV의 실제 차량 체류 시간과 비교해야 한다.

오류 처리는 다음과 같다.

- 잘못된 컬럼, 빈 파일, 잘못된 ns 시각, 중복/역순 시각: 학습 중단. 자동 정렬이나 평균으로 숨기지 않는다.
- 좌표 결측/무한대: 그 지점에서 구간 분리. 값을 채워 넣지 않는다.
- 시간 단절 또는 `거리 > 80m/s × dt + 0.5m`인 원시 좌표 점프: 구간 분리 후 평활화와 Window 재수집.
- ByteTrack lost/removed 또는 재사용 ID: `drop_track` 호출. 재검출을 기존 이력과 연결하지 않는다.

물리적 점프 검사는 명백한 오류를 걸러내는 기본값이며 모든 ID 전환이나 스케일 오차를 찾아내는 방법은 아니다.

## 실사·학습·평가 실행

데이터 확인만 먼저 실행하려면 다음과 같다. 결과 폴더는 매번 새로운 이름을 지정하며 기존 파일을 덮어쓰지 않는다.

```powershell
.\.venv-idd\Scripts\python.exe -m idd_classifier inspect --data-root data\IDD\no-video --config configs\idd_lstm.json --output outputs\inspection_01
```

세 길이의 데이터 생성부터 학습·평가·저장까지 한 번에 실행한다.

```powershell
.\.venv-idd\Scripts\python.exe -m idd_classifier train --data-root data\IDD\no-video --config configs\idd_lstm.json --output outputs\idd_lstm_run02 --device cpu
```

설정은 `configs/idd_lstm.json`을 복사해 변경한다. 현재 기준은 단방향 LSTM 1층/hidden 32, 분류기 앞 dropout 0.3, AdamW, BCEWithLogitsLoss, 배치 128, 최대 50 epoch, patience 8이다. 클래스 가중치 `pos_weight=음성 Window 수/양성 Window 수`는 train에서만 계산한다. 최적 체크포인트는 검증 BCE 최소값으로 저장한다.

분할은 참가자가 가진 라벨 집합으로 층화한 뒤 seed 42로 만든다. 정규화 평균/표준편차는 train의 특징 행을 한 번씩만 사용한다. 겹치는 Window가 같은 행을 반복 가중하지 않도록 Window 생성 전에 계산한다. 분산이 거의 0인 특징의 표준편차는 1로 저장한다.

길이를 공정하게 비교하기 위해 **동일한 끝 시각**의 Window를 1초 간격으로 만든다. 초기 100개 특징이 모인 시점부터 세 길이 모두 동일한 개수의 Window를 생성한다. 3초 모델의 실시간 API는 30개만 모이면 판단할 수 있지만, 이 비교 실험은 짧은 추적 구간의 전체 가용률을 측정한 것이 아니다.

임계값은 validation의 정상 Window FPR≤5%인 후보 중 참가자 macro recall을 최대화하도록 선택한다. 동률이면 macro FPR과 Window FPR이 낮고 임계값이 높은 후보를 선택한다. 입력 길이 역시 validation의 macro recall, macro FPR, 짧은 길이 순으로 선택한다. 이후 고정된 모델과 임계값으로 test를 평가한다. 5%는 연구용 기본값으로 운영 보장치가 아니다. 임계값 0.5의 결과도 `metrics.json`에 별도로 저장한다.

## 저장 결과

기존 실측 결과는 `outputs/idd_lstm_seed42`에 있다. 데이터와 큰 생성물은 Git 추적 대상에서 제외했다. 공유할 때 모델 번들과 결과 폴더는 별도로 보관해야 한다.

```text
outputs/idd_lstm_seed42/
  config.json, environment.json, inspection.json
  manifest.csv, data_audit.csv
  splits.json, normalizer.json, selection.json
  comparison.csv, results.json, REPORT.md
  3s/  5s/  10s/
    train_windows.npz, validation_windows.npz, test_windows.npz
    model.pt, metadata.json, history.csv
    validation_predictions.csv, test_predictions.csv, metrics.json
  best/
    model.pt
    metadata.json
```

`metadata.json`에는 피처 순서·정의·단위, 정규화 통계, 10Hz 설정, Window 길이, 다항식 평활화·미분·저속 규칙, 단절/점프 기준, 임계값, LSTM 구조, seed와 참가자 분할을 저장한다. CSV별 SHA-256은 `data_audit.csv`에 있다. 입력 파일을 바꾸면 별도 실험으로 기록해야 한다.

## CCTV 연동 인터페이스

학습과 추론 모두 `features.py`의 공통 추출기를 사용한다. Naver 모델의 출력은 `H_from_px`이며, 이 프로젝트의 피처 자체가 아니다. Naver의 속도 함수는 km/h로 변환하는 부분이 있지만 여기의 공통 피처는 **m/s**다.

```python
from idd_classifier.inference import (
    CoordinateQuality,
    VehiclePredictor,
    homography_to_road,
)

predictor = VehiclePredictor("outputs/idd_lstm_seed42/best")

# 실제 카메라 어댑터에서 받은 값으로 호출한다.
def process_observation(camera_id, track_id, timestamp_ns, x_m, y_m, quality):
    return predictor.update(
        f"{camera_id}:{track_id}", timestamp_ns, x_m, y_m, quality=quality
    )
```

`quality`는 호출자가 실제 측정한 근거로 만든 `CoordinateQuality`다. 기본값은 검증 안 됨이다. `metric_scale_verified=True`, 미터 단위 `control_point_error_m`, `within_road_roi=True`, `tracking_ok=True`, 보정 버전 `calibration_id`가 모두 필요하다. 실측 도로 기준점의 오차가 기본 한계 0.5m를 넘으면 이력을 지우고 점수를 반환하지 않는다. 이 0.5m는 초기 연구 설정이며 실제 좌표 잡음과 특징 민감도 실험으로 조정해야 한다.

H만 보고 미터 스케일의 정확도를 자동으로 알아낼 수는 없다. 도로의 실제 길이/기준점으로 별도 검증해야 하며, 해당 근거가 없으면 `quality`를 임의로 참으로 설정하지 않는다. 보정 ID가 바뀌어도 이력을 초기화한다. `homography_to_road`는 행렬의 유한성/특이성/지평선 근처 투영을 검사하는 수치 도우미다. H의 실제 미터 정확도를 검증하는 함수는 아니다.

원하는 픽셀점에 `homography_to_road(H_from_px, u_px, v_px)`를 적용한 후 결과 X/Y를 전달한다. 차량 마스크나 박스의 어느 점을 사용할지, Naver가 사용하는 투영점 정의와 어떤 차이가 있는지 검증해야 한다. 차량의 높이 때문에 영상 중심점과 실제 도로 접점은 같지 않을 수 있다. ROI 밖, 가림, ID 전환, 끊긴 추적은 품질 플래그나 `drop_track`으로 즉시 전달한다.

정상 처리 결과는 `status="ok"`, `score`(0~1), `suspected`, `threshold`, `feature_timestamp_ns`, `available_at_ns`, `resampling_delay_s`다. 이 점수는 IDD 조건 분류 출력이며 실제 음주 확률로 보정된 값이 아니다. 이력 부족은 `warming_up`, 새 격자 대기는 `waiting_for_sample`, 품질/시각 오류는 `abstain`으로 반환하며 이때 `score`와 `suspected`는 `None`이다. 점수를 0으로 바꿔 정상으로 해석하면 안 된다.

`predictor.drop_track("카메라ID:차량ID")`를 ByteTrack의 lost/removed와 ID 재사용 때 호출한다. 한 predictor에는 동일 시간원의 시각을 전달하고 순차적으로 호출한다. 저장 상태는 기본 최대 512대이며, 다른 관측이 도착할 때 30초 이상 유휴 상태를 만료한다. 화면 밖으로 사라진 즉시 삭제하는 것은 호출자의 책임이다.

실제 ego CSV를 온라인 경로로 재생할 수도 있다.

```powershell
.\.venv-idd\Scripts\python.exe -m idd_classifier replay-idd --bundle outputs\idd_lstm_seed42\best --ego-csv "실제 ego_tracks.csv 경로" --output outputs\replay_01.csv
```

이 명령의 품질 상태는 **미터 단위를 아는 IDD 시뮬레이터 재생 전용**이다. 실제 CCTV 보정이 검증되었다는 뜻이 아니다. 테스트 참가자 P712의 한 실제 CSV에서 세 길이 각각 157개 평가 Window를 온라인으로 재생했고, 배치 평가 점수와의 최대 절대 오차는 약 `6.5e-8` 이하였다. 상세 기록은 `IDD_REPLAY_VALIDATION.json`에 있다.

## 테스트와 프로젝트 구조

```powershell
.\.venv-idd\Scripts\python.exe -m unittest discover -s tests
.\.venv-idd\Scripts\python.exe -m compileall -q idd_classifier tests
```

테스트는 직선 속력, 부호 있는 감속, 벡터 jerk, 원운동 turn_rate, 정지, ns 정밀도, 중복/역순, 결측·단절·위치 점프, 온라인/오프라인 일치, 참가자 분할, train 정규화, FPR 임계값, LSTM 파라미터 갱신, 모델 재로딩, 품질 보류와 전체 저장 흐름을 확인한다.

```text
idd_classifier/
  features.py     공통 특징 정의와 스트림 전처리
  data.py         실제 CSV 로딩, 라벨·주석 검증, 분할, 정규화, Window
  model.py        LSTM과 배치 점수 계산
  metrics.py      지표, 참가자 평가, 검증 임계값, 군집 bootstrap
  experiment.py   학습·평가 실행과 결과 저장
  inference.py    차량별 추론, 품질 검사, H 투영, IDD 재생
  cli.py         명령행 인자와 설정 검사
configs/          데이터 경로를 포함하지 않는 실험 설정
tests/            단위·통합 테스트
docs/             설계 기준, 실행 안내, 실제 결과
```

`code-simplification` 원칙에 따라 이번에 추가한 코드만 검토했고 기존 카메라/검출 코드는 수정하지 않았다. 기능별 작은 함수와 직접 호출을 사용하며 범용 모델 프레임워크를 도입하지 않았다.

## 결과 해석과 다음 연구

Window 단위 지표는 관측 시간이 긴 주행의 영향을 더 받는다. `participant_macro`는 참가자별 지표를 동일 가중치로 평균한다. `participant_condition`은 참가자×음주 조건별 평균 점수를 평가한다. 한 참가자에게 두 라벨이 있으므로 참가자 전체를 하나의 라벨로 합치지 않는다. 신뢰구간은 Window를 독립 추출하지 않고 참가자를 군집으로 재추출한다. 테스트 참가자가 4명뿐이므로 이 구간 역시 정밀한 모집단 추정으로 해석하면 안 된다.

각 참가자의 음주/비음주 주행은 서로 다른 round와 시나리오에 묶여 있다. 전체에서는 8개 시나리오 모두 두 라벨에 존재하지만, 작은 분할에서 시나리오 구성·주행 순서·적응 효과가 결과에 영향을 줄 수 있다. 다음 연구에서는 참가자 교차검증, 시나리오별 성능/구성 분석, 평활화 민감도, 실제 CCTV 좌표 잡음 실험이 필요하다. 새로운 모델을 비교할 때는 현재 테스트를 반복 튜닝에 사용하지 말고 별도 홀드아웃 또는 중첩 교차검증을 설계해야 한다.

3초는 짧은 차량 관측에 유리하지만 패턴이 적고, 10초는 긴 패턴을 볼 수 있지만 관측 실패와 지연이 커진다. 5초는 후속 현장 실험의 공학적 절충 후보일 수 있으나 현재 결과가 5초의 효과를 입증한 것은 아니다. 실제 음주 라벨을 갖춘 현장 검증 전에는 어떤 길이도 관제 모델로 확정할 수 없다. 정상 Window FPR은 차량당·시간당 경보율과 다르므로 후속 단계에서 경보 집계와 중복 경보 정책도 검증해야 한다.

## 공식 근거

- [Toyota DBM 데이터 형식](https://github.com/ToyotaResearchInstitute/DBM/blob/main/data/README.md)
- [Toyota 공식 조건 라벨·제외 설정](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/ddd_2024_dataset.py)
- [Toyota 시뮬레이터 이상 주석 파서](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/parsers/dataset_anomalies.py)
- [Naver 보정 모델 실행 순서](https://github.com/naver/cctv), [H 투영과 속도 단위](https://github.com/naver/cctv/blob/main/tools/speed.py)
- [PyTorch LSTM](https://docs.pytorch.org/docs/2.15/generated/torch.nn.LSTM.html), [BCEWithLogitsLoss와 pos_weight](https://docs.pytorch.org/docs/2.15/generated/torch.nn.BCEWithLogitsLoss.html), [가중치 전용 로딩](https://docs.pytorch.org/docs/2.15/generated/torch.load.html)
- [scikit-learn ROC 임계값](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.roc_curve.html)

학습·추론 코드는 이 프로젝트에서 작성했다. 데이터와 Naver 코드의 사용 조건은 각 원본 라이선스도 확인한다. 원본 데이터와 사전학습 보정 모델을 이 프로젝트 패키지에 재배포하지 않는다.
