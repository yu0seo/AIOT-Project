# IDD 영상과 피처 같이 확인하기

`inspect_idd.py`는 다운로드된 **sample**의 전방 영상과 같은 시각의 주행 피처를 보여주는 로컬 확인 도구입니다. 원본 데이터는 수정하지 않습니다. 기본 샘플은 `P710/R1/driving/6e-vehicle_run_red_light/nback_task`입니다.

## CMD에서 실행

```cmd
cd /d "C:\Users\dndud\OneDrive\Desktop\coding_folder\AIOT-Project\AIOT_2026"
.venv\Scripts\python.exe pc\inspect_idd.py
```

프로젝트의 `.venv`에 OpenCV가 설치되어 있습니다. 새 환경에서는 먼저 `python -m venv .venv`와 `.venv\Scripts\python.exe -m pip install -r pc\requirements.txt`를 실행하세요. YOLO나 학습 라이브러리는 필요하지 않습니다.

- 시작은 일시정지 상태입니다. **Space**: 재생/일시정지.
- 창 아래 **Frame 슬라이더**: 원하는 시점으로 이동.
- **A / D**: 이전/다음 한 프레임.
- **J / L**: 약 1초 이전/이후.
- **Q / Esc / 창 닫기**: 종료.
- 그래프의 노란 선은 현재 영상 시점입니다. 각 그래프의 세로축 범위는 서로 다릅니다.
- 프레임의 실제 순서를 지키기 위해 뒤로 이동하면 앞부분을 다시 해독합니다. 큰 폭으로 이동하면 잠시 기다릴 수 있습니다. 재생 속도는 PC 성능에 따라 실제 시간보다 느려질 수 있습니다.

35.5초부터 보려면:

```cmd
.venv\Scripts\python.exe pc\inspect_idd.py --seconds 35.5
```

그 시점의 화면을 PNG로 저장하려면 (기존 파일은 덮어쓰지 않습니다):

```cmd
.venv\Scripts\python.exe pc\inspect_idd.py --seconds 35.5 --snapshot data\IDD\inspection\my_35_5s.png
```

## 무엇을 나타내는 피처인가?

IDD는 실제 CCTV에서 수집한 데이터가 아니라 **운전 시뮬레이터 데이터**입니다. `ego`는 화면을 촬영하는 카메라가 달린 실험 차량, 즉 실험 참가자가 운전하는 차량입니다. `ego_tracks.csv`의 값은 화면 앞에 보이는 다른 차량의 속도나 가속도가 아닙니다.

기본 샘플의 상대 경로 `S`는 아래와 같습니다.

```text
Participants/P710/R1/driving/6e-vehicle_run_red_light/nback_task
```

모든 경로의 기준은 `AIOT_2026/data/IDD/sample/Processed`입니다.

| 확인 대상 | 파일 / 열 | 해석 |
|---|---|---|
| 전방 주행 영상 | `Resampled_previous_10/S/cam_front/video.avi` | 실험 차량의 전방 시점 |
| 영상 프레임 시각 | 같은 폴더의 `frame_timing.csv` | `resampled_frame`과 `resampled epoch ns` 연결 |
| 주행 피처 | `Resampled_previous_10_derived/S/ego_tracks.csv` | 실험 차량의 위치 및 파생 주행 피처 |
| 전후 방향 속도 | `longitudinal_speed` | 차량 기준 전후 방향 속도, m/s |
| 좌우 방향 속도 | `lateral_speed` | 차량 기준 횡방향 속도, m/s. 차선 중심에서 벗어난 거리와는 다름 |
| 전후/좌우 가속도 | `longitudinal_acceleration`, `lateral_acceleration` | 각 방향 속도의 변화, m/s² |
| 전후/좌우 저크 | `longitudinal_jerk`, `lateral_jerk` | 각 방향 가속도의 변화율, m/s³ |
| 조작 입력 | `Resampled_previous_10/S/sim_bag/carla_hero_vehicle_status.csv` | `throttle`, `brake`, `steering` 시뮬레이터 값. `steering`을 각도(°)로 해석하지 않음 |
| 전체 객체 위치 | `Resampled_previous_10/S/sim_bag/carla_objects.csv` | 객체 ID별 시뮬레이터 좌표/속도. 화면에 박스를 표시하려면 카메라 투영 정보가 추가로 필요 |
| 시선 | 같은 `sim_bag/experiment_tobii_frame.csv` | 별도 시선 추적 장비의 값. 현재 도구는 시선을 영상에 표시하지 않음 |

예를 들어 기본 샘플의 **35.5초**에는 `longitudinal_speed`가 약 **5.415 m/s**, `lateral_speed`가 약 **0.858 m/s**입니다. 화면의 곡선 주행 장면과 함께 피처 변화를 비교할 수 있습니다. 이 값만으로 차선 이탈이나 음주 여부를 판단할 수는 없습니다. 회전도 횡방향 피처를 변화시킬 수 있습니다.

## 동기화와 해석 시 주의할 점

- 원본 CSV에는 `resampled epoch ns`, 파생 CSV에는 `resampled_epoch_ns`라는 이름이 사용됩니다. 도구는 이름을 정규화하고 **같은 시나리오의 상대 시간(ns)**으로 연결합니다. 초 단위 시간은 이 값을 `1e9`로 나눕니다.
- 영상은 `frame_timing.csv`의 `resampled_frame`에 해당하는 **실제 해독 순서**로 읽습니다. FPS 메타데이터로 시간이나 프레임을 추측하지 않습니다. 현재 샘플은 실제 해독 프레임이 2,080개인데 OpenCV 메타데이터는 600 FPS / 123,820개로 보고합니다. 이 파일에서 `CAP_PROP_POS_FRAMES`를 이용한 직접 탐색은 다른 장면을 선택할 수 있습니다.
- 타임스탬프 연결은 가장 가까운 행을 사용하되 75ms를 넘으면 결측으로 처리합니다. 샘플의 영상 2,080개 시점 모두에 대응하는 ego 행을 확인했습니다.
- 기존 피처는 영상에서 YOLO로 추출한 값이 아닙니다. 공식 코드가 시뮬레이터의 차량 궤적을 차량 방향으로 회전한 뒤, 현재 시점 앞뒤 약 2.5초 구간에 스플라인을 맞춰 속도·가속도·저크를 구한 값입니다. 온라인 CCTV 처리에서는 같은 단위와 좌표 정의를 맞추고, 미래 데이터 없이 계산하는 방법을 별도로 정해야 합니다.
- `nback_task`는 실험 과제 이름입니다. 폴더 이름이나 단일 피처 변화로 음주 라벨을 추정하지 마세요.
- `no-video`에는 대응 영상이 없습니다. 처음 받은 `sample`/`no-video` 구성에서 영상과 피처를 비교할 수 있는 구간은 `sample`에 포함된 구간입니다. 다른 구간을 보려면 같은 참가자·주행·시나리오의 영상과 프레임 시간 파일을 추가로 받아야 합니다. 아래의 음주·충돌 예시는 이 방법으로 추가했습니다.

## 음주 조건과 충돌 주석이 있는 예시

추가 확인용으로 `P710/R2/driving/2-vehicle_pop_out/nback_task`의 전방 영상과 프레임 시간 파일을 `data/IDD/selected/Processed`에 받았습니다(영상 약 199MB). 기존 `no-video`의 대응 ego 피처, 차량 조작 값, 주석 파일을 이 확인용 폴더에 복사했으며 원본 파일은 수정하지 않았습니다.

```cmd
.venv\Scripts\python.exe pc\inspect_idd.py --example impaired-crash --seconds 152
```

152초부터 재생하면 다른 차량이 진입하는 장면과 감속, 충돌 전후의 피처 변화를 확인할 수 있습니다. `idd_annotation.csv`의 이 참가자·시나리오에는 `crash`, `Valid hazard=1`, 충돌 시각 약 `157`초가 기록되어 있습니다. 충돌 시각은 수동 주석의 근사값이며 정확한 충돌 프레임으로 간주하지 않습니다. 빨간 세로선은 이 주석 시각, 노란 세로선은 현재 영상 시각입니다.

### 라벨의 의미

- **음주 여부**: 공식 데이터 로더는 `P`로 시작하는 참가자의 `R2`를 `intoxicated=True`로 정의합니다. `R1`과 숫자로만 된 참가자 ID는 비음주 조건입니다. 선택한 예시의 주석 `Alcohol` 값도 `1`입니다.
- **주의분산 조건**: `scenario_index.csv`의 `cognitive_task`와 폴더의 `no_task`, `nback_task`, `statement_task`로 구분합니다. 선택한 예시는 `nback_task`입니다.
- **충돌/위험 상황 주석**: `idd_annotation.csv`에 시나리오별 위험 상황 결과, 유효 여부, 대략적인 충돌 시각, 일부 경로 이탈 구간 등이 기록되어 있습니다. 파일은 두 줄 헤더이므로 일반적인 단일 헤더 CSV처럼 읽으면 안 됩니다.
- **프레임별 비정상 주행**: 확인한 ego 피처 파일에는 매 시점의 `abnormal=0/1` 정답 열이 없습니다. 음주/주의분산 조건은 주행 구간의 실험 조건이고, 해당 구간의 모든 순간에 위험한 조작이 발생했다는 뜻은 아닙니다. 충돌 역시 음주 때문에 발생했다고 이 주석만으로 단정하지 않습니다.
- **데이터 이상 주석**: 공식 코드의 `DatasetAnomalies`는 공중에 뜬 차량 같은 시뮬레이션/데이터 오류를 다룹니다. 운전자의 비정상 주행 라벨과 구분해야 합니다.

기본 `sample`인 `P710/R1/6e.../nback_task`는 **비음주 + 주의분산 조건**입니다. 이 시나리오에는 `fail - hazard late`, `Valid hazard=0`이 기록되어 있어, 정상/비정상 평가의 대표 사례로 사용하기 전에 제외 여부를 검토해야 합니다.

확인 도구 오른쪽에 `Alcohol`, `Distraction`, `Crash time`, `Hazard`, `Valid hazard`를 표시합니다. 기본 샘플과 추가 예시 모두에 적용됩니다. 조건 정보는 모델의 판별 결과가 아니라 원본 데이터의 조건과 주석입니다.

근거: [공식 조건 라벨 생성 코드](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/ddd_2024_dataset.py), [충돌 주석 해석 코드](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/parsers/crash_counts.py), 다운로드된 `idd_annotation.csv`.

## 데이터 출처

- Toyota Research Institute, [Impaired Driving Dataset](https://toyotaresearchinstitute.github.io/IDD/), CC BY-NC-SA 4.0. 다운로드된 `LICENSE.txt`도 확인하세요.
- [공식 데이터 형식과 프레임 시간 설명](https://github.com/ToyotaResearchInstitute/DBM/blob/main/data/README.md)
- [ego/주변 객체 분리와 주행 피처 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/track_features.py)

프레임 수, 전체 영상 해독, 타임스탬프 연결과 피처 값을 확인하려면:

```cmd
.venv\Scripts\python.exe pc\inspect_idd.py --check
```
