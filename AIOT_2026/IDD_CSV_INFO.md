# IDD CSV 파일 및 전체 컬럼 설명

작성일: 2026-11-06

**프로젝트 폴더에 있는 모든 CSV를 조사한 데이터 사전이다.** CCTV 모델에 사용할 파일만 선정한 문서가 아니라, 시선·보정·운전 조작·차량 궤적·영상 시간표·실험 주석까지 포함한다.

## 조사 범위와 읽는 방법

- 조사 루트: `C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026`
- 발견한 CSV: **13,042개**. 모두 data/IDD 아래에 있으며 Sample과 no-video를 모두 포함한다.
- 파일명 기준 **26종**, 헤더 구성 기준 **32종**이다.
- 모든 파일의 실제 헤더와 처음 최대 3개 레코드를 읽어 같은 파일명을 헤더별로 묶었다. 주석의 두 번째 헤더와 대표 파일의 일부 값도 별도로 확인했다.
- 참가자·시나리오마다 반복되는 같은 형식은 설명을 반복하지 않고 해당 종류의 설명을 공통 적용한다. 각 절에 파일 수·처리 버전별 분포·대표 원본 경로를 적었다.
- 전체 행의 결측률·물리적 정확성까지 검사한 문서는 아니다. 단위나 생성 정의가 확인되지 않은 항목은 미확인 또는 추정으로 표시한다.
- 기존 CSV 및 IDD_CCTV_COLUMN_REVIEW.md는 수정하지 않았다.

‘특성’에는 모델 입력 후보뿐 아니라 ID, 시간, 장치 상태, 측정 유효성, 실험조건, 사건 결과와 집계도 포함된다. 조건·결과·관리 컬럼을 모두 예측 입력으로 쓰라는 의미는 아니다.

### 공통 용어·시간·폴더

- ego/hero: 실험 참가자가 운전하는 차량. ado: ego 이외 주변 객체. hazard: 위험 시나리오의 대상으로 선정된 객체.
- Resampled_previous_10 / 60: 각각 10Hz / 60Hz 시간축에 맞춘 데이터. derived는 추가 계산한 파생 데이터다.
- resampled_epoch_ns와 resampled epoch ns는 시나리오 기준 상대 ns다. 원본 파일의 공백·밑줄 차이를 아래 표에 그대로 보존했다.
- log time류의 절대 시각, Tobii 장치/시스템 시계, 시나리오 상대 시각은 서로 다른 시간 표현이다.
- 빈칸, NaN, -1, 0의 의미는 컬럼마다 다르다. 특히 시선 미측정을 0좌표나 정상 상태로 해석하지 않는다.
- participant/round/scenario/task 경로는 CSV 행과 함께 관리해야 한다. 다른 시나리오의 같은 ID·상대시각을 무조건 연결하면 안 된다.

참고: [공식 데이터 형식](https://github.com/ToyotaResearchInstitute/DBM/blob/main/data/README.md).

## 파일 종류 전체 목록

| CSV 파일명 | 실제 파일 수 | 헤더 형식 수 | 형식별 컬럼 수 | 의미 |
| --- | --- | --- | --- | --- |
| [scenario_index.csv](#csv-01) | 60 | 1 | 9 | 실험 목록·조건 |
| [idd_annotation.csv](#csv-02) | 2 | 1 | 114 | 수동 주석·조건·결과 |
| [carla_actor_list.csv](#csv-03) | 616 | 1 | 7 | 객체 목록 |
| [carla_objects.csv](#csv-04) | 616 | 1 | 18 | 전체 객체 상태 |
| [carla_hero_vehicle_status.csv](#csv-05) | 616 | 1 | 11 | 참가자 차량 제어·자세 |
| [ic_speedometer.csv](#csv-06) | 616 | 1 | 5 | 계기판 속도계 |
| [telemetry_velocity.csv](#csv-07) | 616 | 1 | 5 | 차량 속력 계측 |
| [telemetry_vehicleodometer.csv](#csv-08) | 616 | 1 | 5 | 주행거리계 |
| [telemetry_roadwheel_angle.csv](#csv-09) | 616 | 1 | 5 | 바퀴 조향각 |
| [usercontrols_status_brake_pedal.csv](#csv-10) | 573 | 1 | 5 | 운전자 브레이크 입력 |
| [usercontrols_status_throttle_pedal.csv](#csv-11) | 616 | 1 | 5 | 운전자 가속 페달 입력 |
| [usercontrols_status_steeringwheel_angle.csv](#csv-12) | 616 | 1 | 5 | 운전자 핸들 입력 |
| [experiment_tobii_frame.csv](#csv-13) | 2362 | 1 | 36 | 시선 추적 측정 |
| [experiment_tobii_calib_data.csv](#csv-14) | 110 | 1 | 13 | 시선 추적 보정 절차 |
| [ego_tracks.csv](#csv-15) | 439 | 1 | 24 | 참가자 차량 파생 궤적 |
| [ado_tracks.csv](#csv-16) | 364 | 1 | 18 | 주변 객체 파생 궤적 |
| [hazard_tracks.csv](#csv-17) | 364 | 1 | 17 | 선정된 위험 객체 궤적 |
| [ado_removal_stats.csv](#csv-18) | 364 | 1 | 6 | 주변 객체 기록 종료 분석 |
| [relevant_trajectories.csv](#csv-19) | 372 | 1 | 20 | 거리·방향을 추가한 객체 궤적 |
| [steering_reversals.csv](#csv-20) | 439 | 1 | 3 | 조향 반전 시점 |
| [gaze_depth.csv](#csv-21) | 431 | 2 | 3 / 2 | 시선 위치의 장면 깊이 |
| [gaze_semantics.csv](#csv-22) | 431 | 2 | 3 / 3 | 시선 위치의 장면 종류 |
| [gaze_entropy.csv](#csv-23) | 439 | 2 | 5 / 3 | 시선 분포·전이 엔트로피 |
| [gaze_pitch_yaw.csv](#csv-24) | 372 | 1 | 5 | 시선 방향각 |
| [gaze_fixation_saccade.csv](#csv-25) | 372 | 1 | 9 | 시선 고정·급속 이동 |
| [frame_timing.csv](#csv-26) | 4 | 4 | 8 / 8 / 8 / 9 | 영상 프레임 시간표 |

## 동일 파일명 안에서 확인한 형식 차이

| 파일 | 형식 | 파일 수 | 주의할 점 |
| --- | --- | --- | --- |
| gaze_depth.csv | 상대시각 + 좌안/우안 깊이 | 372 | 3컬럼 |
| gaze_depth.csv | 상대시각 + gaze_depth | 59 | 2컬럼. 눈 선택·양안 통합 규칙 미확인 |
| gaze_entropy.csv | 상대시각 + 좌우 눈별 엔트로피 4개 | 372 | 5컬럼 |
| gaze_entropy.csv | 상대시각 + 좌우 구분 없는 엔트로피 2개 | 67 | 3컬럼 |
| gaze_semantics.csv | 상대시각 + 좌안/우안 분류 | 372 | 3컬럼 |
| gaze_semantics.csv | 상대시각 + cam_seg + gaze_semantics | 59 | 3컬럼이지만 위와 의미가 다름 |
| frame_timing.csv | 깊이·전방·분할·축소 전방 각 1개 | 4 | 각각 8/8/8/9컬럼 |

여러 파일을 합칠 때 이름만 보고 동일한 열로 가정하면 안 된다. 아래에서 모든 형식의 모든 컬럼을 따로 설명한다.

<a id="csv-01"></a>

## 1. scenario_index.csv

**파일 의미:** 참가자별 실험 구간 목록과 경로, 라운드, 인지 과제, 시작·종료 시각을 연결하는 인덱스.

**한 행의 의미:** 한 행 = 참가자 한 명의 실험 구간 하나. 주행뿐 아니라 시선 보정·정지 과제도 포함한다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| no-video | Resampled_previous_10 | 60 |

**해석할 때 확인할 점:** start_time/end_time은 이 파일에서 ns이다. actor list의 동명 컬럼은 s이다. round=R2만 보고 음주라고 판단하지 않는다. 공식 음주 조건은 참가자 ID가 P로 시작하고 R2인 경우다.

참고: [공식 실험조건 생성 코드](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/ddd_2024_dataset.py), [공식 데이터 형식](https://github.com/ToyotaResearchInstitute/DBM/blob/main/data/README.md).

### 형식 1: 9개 컬럼, 60개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/scenario_index.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/scenario_index.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `scenario_index` | 참가자별 시나리오 목록 안의 행 번호. 전역 고유 ID가 아니며 예측 입력에서 제외한다. | 정수 | — |
| 2 | `scenario_name` | 실험 종류 및 시나리오 이름. driving/6e-vehicle_run_red_light처럼 구성되며 주행 구간 선택, 시나리오 코드 추출, 평가 층화에 사용한다. 특정 시나리오 암기를 막기 위해 기본 예측 입력에서 제외한다. | 문자열 | — |
| 3 | `scenario_path` | 참가자 폴더 기준 데이터 경로. 회차/시나리오/과제 폴더를 연결하며 파일을 찾는 데 사용한다. | 상대 경로 | — |
| 4 | `round` | 실험 라운드. 음주 조건 생성에 참가자 이름과 함께 사용한다. 숫자 참가자 ID의 R2는 음주 조건이 아니다. | R1/R2 | — |
| 5 | `cognitive_task` | no_task, nback_task, statement_task 중 하나. 인지적 주의분산 조건의 목표/층화용이며 실제 위험 행동의 순간별 라벨은 아니다. | 범주 | — |
| 6 | `start_time` | 시나리오 시작 절대 시각. 시간 정렬용이며 파일의 resampled_epoch_ns=0에 해당하는 기준점으로 사용한다. 예측 입력에서 제외한다. | 절대 로그 시각 ns | — |
| 7 | `end_time` | 시나리오 종료 절대 시각. 구간 잘라내기·검증용이다. 미래 종료 시각을 온라인 모델 입력으로 사용하지 않는다. | 절대 로그 시각 ns | — |
| 8 | `duration_s` | 시나리오 길이. 실제 start_time/end_time 차이를 1e9로 나눈 값과 대응하며 주석 범위·윈도 길이 확인에 사용한다. | 초 | — |
| 9 | `duration_frames` | 해당 리샘플링 시간축의 프레임/샘플 수. 검사한 10Hz 인덱스의 P710 R1 6e는 2080이다. 각 센서의 유효 검출 개수나 모든 영상 파일의 디코드 수를 무조건 보증하는 값은 아니다. | 개 | — |

<a id="csv-02"></a>

## 2. idd_annotation.csv

**파일 의미:** 참가자별 8개 위험 시나리오의 오류, 위험 상황 결과, 충돌, 인지 과제·음주 조건, 경로 이탈과 집계를 담은 표.

**한 행의 의미:** 헤더 2줄 뒤 한 행 = 참가자 한 명. 시나리오별 정보가 가로 방향으로 반복된다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Processed 바로 아래 | 1 |
| no-video | Processed 바로 아래 | 1 |

참고: [공식 실험조건 생성 코드](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/ddd_2024_dataset.py), [공식 충돌 주석 해석](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/parsers/crash_counts.py), [공식 물리 오류 주석 해석](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/parsers/dataset_anomalies.py).

### 형식 1: 114개 컬럼, 2개 파일

대표 원본: [data/IDD/no-video/Processed/idd_annotation.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/idd_annotation.csv)

첫 줄에는 그룹명 외에 통계·메모가 섞여 있어 빈칸을 앞의 값으로 채우는 방식으로 그룹을 만들면 안 된다. 아래 정리 이름은 설명용이며 원본 헤더를 변경한 것이 아니다. 물리 열 번호는 1부터 센다.

8개 시나리오 코드 순서는 1a, 2, 2b, 3c, 5, 6e, 7a, 8a다. 음주·인지 과제 조건은 주행 결과와 다르며, 모든 순간의 위험 운전 정답도 아니다.

| 열 | 원본 헤더 1 | 원본 헤더 2 | 설명용 그룹/항목 | 설명 | 단위·값 |
| --- | --- | --- | --- | --- | --- |
| 1 | ∅ | ID | ID / ID | 참가자 ID. 경로의 참가자 이름과 연결하며 학습/검증 분할을 참가자 단위로 묶는 데 사용한다. 예측 입력에서 제외한다. | 문자열 |
| 2 | was there a floating car or some other wierd physics to cut out? (start and end clip time in sec) | 1a | was there a floating car or some other wierd physics to cut out? (start and end clip time in sec) / 1a | 차량 부유 등 시뮬레이션/물리 오류 구간. 예: 17-32 또는 여러 구간의 쉼표 목록. 해당 구간을 제거하는 품질 필터이며 위험 운전 정답이 아니다. | 시나리오 시작 기준 초 구간 |
| 3 | ∅ | 2 | was there a floating car or some other wierd physics to cut out? (start and end clip time in sec) / 2 | 차량 부유 등 시뮬레이션/물리 오류 구간. 예: 17-32 또는 여러 구간의 쉼표 목록. 해당 구간을 제거하는 품질 필터이며 위험 운전 정답이 아니다. | 시나리오 시작 기준 초 구간 |
| 4 | ∅ | 2b | was there a floating car or some other wierd physics to cut out? (start and end clip time in sec) / 2b | 차량 부유 등 시뮬레이션/물리 오류 구간. 예: 17-32 또는 여러 구간의 쉼표 목록. 해당 구간을 제거하는 품질 필터이며 위험 운전 정답이 아니다. | 시나리오 시작 기준 초 구간 |
| 5 | ∅ | 3c | was there a floating car or some other wierd physics to cut out? (start and end clip time in sec) / 3c | 차량 부유 등 시뮬레이션/물리 오류 구간. 예: 17-32 또는 여러 구간의 쉼표 목록. 해당 구간을 제거하는 품질 필터이며 위험 운전 정답이 아니다. | 시나리오 시작 기준 초 구간 |
| 6 | ∅ | 5 | was there a floating car or some other wierd physics to cut out? (start and end clip time in sec) / 5 | 차량 부유 등 시뮬레이션/물리 오류 구간. 예: 17-32 또는 여러 구간의 쉼표 목록. 해당 구간을 제거하는 품질 필터이며 위험 운전 정답이 아니다. | 시나리오 시작 기준 초 구간 |
| 7 | ∅ | 6e | was there a floating car or some other wierd physics to cut out? (start and end clip time in sec) / 6e | 차량 부유 등 시뮬레이션/물리 오류 구간. 예: 17-32 또는 여러 구간의 쉼표 목록. 해당 구간을 제거하는 품질 필터이며 위험 운전 정답이 아니다. | 시나리오 시작 기준 초 구간 |
| 8 | ∅ | 7a | was there a floating car or some other wierd physics to cut out? (start and end clip time in sec) / 7a | 차량 부유 등 시뮬레이션/물리 오류 구간. 예: 17-32 또는 여러 구간의 쉼표 목록. 해당 구간을 제거하는 품질 필터이며 위험 운전 정답이 아니다. | 시나리오 시작 기준 초 구간 |
| 9 | ∅ | 8a | was there a floating car or some other wierd physics to cut out? (start and end clip time in sec) / 8a | 차량 부유 등 시뮬레이션/물리 오류 구간. 예: 17-32 또는 여러 구간의 쉼표 목록. 해당 구간을 제거하는 품질 필터이며 위험 운전 정답이 아니다. | 시나리오 시작 기준 초 구간 |
| 10 | hazard - did driver deal with it ok / did it execute ok? | 1a | hazard - did driver deal with it ok / did it execute ok? / 1a | 위험 상황 결과와 실행 이상 메모. ok, near, crash, fail 등이 혼재한다. 공식 파서는 fail 포함 시 -1(유효한 위험충돌 결과 아님), 그 외 crash 포함 시 1, 나머지는 0으로 처리한다. near를 정밀한 위험도 등급으로 바로 간주하지 않는다. | 문자열 |
| 11 | ∅ | 2 | hazard - did driver deal with it ok / did it execute ok? / 2 | 위험 상황 결과와 실행 이상 메모. ok, near, crash, fail 등이 혼재한다. 공식 파서는 fail 포함 시 -1(유효한 위험충돌 결과 아님), 그 외 crash 포함 시 1, 나머지는 0으로 처리한다. near를 정밀한 위험도 등급으로 바로 간주하지 않는다. | 문자열 |
| 12 | ∅ | 2b | hazard - did driver deal with it ok / did it execute ok? / 2b | 위험 상황 결과와 실행 이상 메모. ok, near, crash, fail 등이 혼재한다. 공식 파서는 fail 포함 시 -1(유효한 위험충돌 결과 아님), 그 외 crash 포함 시 1, 나머지는 0으로 처리한다. near를 정밀한 위험도 등급으로 바로 간주하지 않는다. | 문자열 |
| 13 | ∅ | 3c | hazard - did driver deal with it ok / did it execute ok? / 3c | 위험 상황 결과와 실행 이상 메모. ok, near, crash, fail 등이 혼재한다. 공식 파서는 fail 포함 시 -1(유효한 위험충돌 결과 아님), 그 외 crash 포함 시 1, 나머지는 0으로 처리한다. near를 정밀한 위험도 등급으로 바로 간주하지 않는다. | 문자열 |
| 14 | ∅ | 5 | hazard - did driver deal with it ok / did it execute ok? / 5 | 위험 상황 결과와 실행 이상 메모. ok, near, crash, fail 등이 혼재한다. 공식 파서는 fail 포함 시 -1(유효한 위험충돌 결과 아님), 그 외 crash 포함 시 1, 나머지는 0으로 처리한다. near를 정밀한 위험도 등급으로 바로 간주하지 않는다. | 문자열 |
| 15 | 416 | 6e | hazard - did driver deal with it ok / did it execute ok? / 6e | 위험 상황 결과와 실행 이상 메모. ok, near, crash, fail 등이 혼재한다. 공식 파서는 fail 포함 시 -1(유효한 위험충돌 결과 아님), 그 외 crash 포함 시 1, 나머지는 0으로 처리한다. near를 정밀한 위험도 등급으로 바로 간주하지 않는다. | 문자열 |
| 16 | 416 | 7a | hazard - did driver deal with it ok / did it execute ok? / 7a | 위험 상황 결과와 실행 이상 메모. ok, near, crash, fail 등이 혼재한다. 공식 파서는 fail 포함 시 -1(유효한 위험충돌 결과 아님), 그 외 crash 포함 시 1, 나머지는 0으로 처리한다. near를 정밀한 위험도 등급으로 바로 간주하지 않는다. | 문자열 |
| 17 | 0.05288461538 | 8a | hazard - did driver deal with it ok / did it execute ok? / 8a | 위험 상황 결과와 실행 이상 메모. ok, near, crash, fail 등이 혼재한다. 공식 파서는 fail 포함 시 -1(유효한 위험충돌 결과 아님), 그 외 crash 포함 시 1, 나머지는 0으로 처리한다. near를 정밀한 위험도 등급으로 바로 간주하지 않는다. | 문자열 |
| 18 | crash (approx impact time in sec) | 1a | crash (approx impact time in sec) / 1a | 대략적인 충돌 시각. 복수 충돌은 쉼표로 구분한다. 정확한 프레임 정답이 아니다. 공란은 공식 충돌 카운트에서 0회로 해석하지만 모든 순간의 정상 주행을 보증하지 않는다. | 시나리오 시작 기준 초 |
| 19 | ∅ | 2 | crash (approx impact time in sec) / 2 | 대략적인 충돌 시각. 복수 충돌은 쉼표로 구분한다. 정확한 프레임 정답이 아니다. 공란은 공식 충돌 카운트에서 0회로 해석하지만 모든 순간의 정상 주행을 보증하지 않는다. | 시나리오 시작 기준 초 |
| 20 | ∅ | 2b | crash (approx impact time in sec) / 2b | 대략적인 충돌 시각. 복수 충돌은 쉼표로 구분한다. 정확한 프레임 정답이 아니다. 공란은 공식 충돌 카운트에서 0회로 해석하지만 모든 순간의 정상 주행을 보증하지 않는다. | 시나리오 시작 기준 초 |
| 21 | sober | 3c | crash (approx impact time in sec) / 3c | 대략적인 충돌 시각. 복수 충돌은 쉼표로 구분한다. 정확한 프레임 정답이 아니다. 공란은 공식 충돌 카운트에서 0회로 해석하지만 모든 순간의 정상 주행을 보증하지 않는다. | 시나리오 시작 기준 초 |
| 22 | statement | 5 | crash (approx impact time in sec) / 5 | 대략적인 충돌 시각. 복수 충돌은 쉼표로 구분한다. 정확한 프레임 정답이 아니다. 공란은 공식 충돌 카운트에서 0회로 해석하지만 모든 순간의 정상 주행을 보증하지 않는다. | 시나리오 시작 기준 초 |
| 23 | nback | 6e | crash (approx impact time in sec) / 6e | 대략적인 충돌 시각. 복수 충돌은 쉼표로 구분한다. 정확한 프레임 정답이 아니다. 공란은 공식 충돌 카운트에서 0회로 해석하지만 모든 순간의 정상 주행을 보증하지 않는다. | 시나리오 시작 기준 초 |
| 24 | ∅ | 7a | crash (approx impact time in sec) / 7a | 대략적인 충돌 시각. 복수 충돌은 쉼표로 구분한다. 정확한 프레임 정답이 아니다. 공란은 공식 충돌 카운트에서 0회로 해석하지만 모든 순간의 정상 주행을 보증하지 않는다. | 시나리오 시작 기준 초 |
| 25 | ∅ | 8a | crash (approx impact time in sec) / 8a | 대략적인 충돌 시각. 복수 충돌은 쉼표로 구분한다. 정확한 프레임 정답이 아니다. 공란은 공식 충돌 카운트에서 0회로 해석하지만 모든 순간의 정상 주행을 보증하지 않는다. | 시나리오 시작 기준 초 |
| 26 | Valid hazard | 1a | Valid hazard / 1a | 위험 시나리오 실행 유효 여부. 1은 유효, 0은 무효. 특히 위험 대응/충돌 성능 평가의 필터로 사용한다. 무효가 곧 위험 운전자라는 뜻은 아니다. | 0/1 |
| 27 | ∅ | 2 | Valid hazard / 2 | 위험 시나리오 실행 유효 여부. 1은 유효, 0은 무효. 특히 위험 대응/충돌 성능 평가의 필터로 사용한다. 무효가 곧 위험 운전자라는 뜻은 아니다. | 0/1 |
| 28 | 1 = valid | 2b | Valid hazard / 2b | 위험 시나리오 실행 유효 여부. 1은 유효, 0은 무효. 특히 위험 대응/충돌 성능 평가의 필터로 사용한다. 무효가 곧 위험 운전자라는 뜻은 아니다. | 0/1 |
| 29 | ∅ | 3c | Valid hazard / 3c | 위험 시나리오 실행 유효 여부. 1은 유효, 0은 무효. 특히 위험 대응/충돌 성능 평가의 필터로 사용한다. 무효가 곧 위험 운전자라는 뜻은 아니다. | 0/1 |
| 30 | 416 | 5 | Valid hazard / 5 | 위험 시나리오 실행 유효 여부. 1은 유효, 0은 무효. 특히 위험 대응/충돌 성능 평가의 필터로 사용한다. 무효가 곧 위험 운전자라는 뜻은 아니다. | 0/1 |
| 31 | 395 | 6e | Valid hazard / 6e | 위험 시나리오 실행 유효 여부. 1은 유효, 0은 무효. 특히 위험 대응/충돌 성능 평가의 필터로 사용한다. 무효가 곧 위험 운전자라는 뜻은 아니다. | 0/1 |
| 32 | ∅ | 7a | Valid hazard / 7a | 위험 시나리오 실행 유효 여부. 1은 유효, 0은 무효. 특히 위험 대응/충돌 성능 평가의 필터로 사용한다. 무효가 곧 위험 운전자라는 뜻은 아니다. | 0/1 |
| 33 | ∅ | 8a | Valid hazard / 8a | 위험 시나리오 실행 유효 여부. 1은 유효, 0은 무효. 특히 위험 대응/충돌 성능 평가의 필터로 사용한다. 무효가 곧 위험 운전자라는 뜻은 아니다. | 0/1 |
| 34 | Count of hazard crashes | 1a | Count of hazard crashes / 1a | 설정된 위험 객체/사건과 관련된 충돌 집계. 실제 값은 0 또는 1이다. fail 시나리오의 0을 정상 음성으로 쓰지 않도록 Valid hazard와 원문 hazard를 함께 확인한다. | 횟수 |
| 35 | ∅ | 2 | Count of hazard crashes / 2 | 설정된 위험 객체/사건과 관련된 충돌 집계. 실제 값은 0 또는 1이다. fail 시나리오의 0을 정상 음성으로 쓰지 않도록 Valid hazard와 원문 hazard를 함께 확인한다. | 횟수 |
| 36 | ∅ | 2b | Count of hazard crashes / 2b | 설정된 위험 객체/사건과 관련된 충돌 집계. 실제 값은 0 또는 1이다. fail 시나리오의 0을 정상 음성으로 쓰지 않도록 Valid hazard와 원문 hazard를 함께 확인한다. | 횟수 |
| 37 | ∅ | 3c | Count of hazard crashes / 3c | 설정된 위험 객체/사건과 관련된 충돌 집계. 실제 값은 0 또는 1이다. fail 시나리오의 0을 정상 음성으로 쓰지 않도록 Valid hazard와 원문 hazard를 함께 확인한다. | 횟수 |
| 38 | ∅ | 5 | Count of hazard crashes / 5 | 설정된 위험 객체/사건과 관련된 충돌 집계. 실제 값은 0 또는 1이다. fail 시나리오의 0을 정상 음성으로 쓰지 않도록 Valid hazard와 원문 hazard를 함께 확인한다. | 횟수 |
| 39 | ∅ | 6e | Count of hazard crashes / 6e | 설정된 위험 객체/사건과 관련된 충돌 집계. 실제 값은 0 또는 1이다. fail 시나리오의 0을 정상 음성으로 쓰지 않도록 Valid hazard와 원문 hazard를 함께 확인한다. | 횟수 |
| 40 | ∅ | 7a | Count of hazard crashes / 7a | 설정된 위험 객체/사건과 관련된 충돌 집계. 실제 값은 0 또는 1이다. fail 시나리오의 0을 정상 음성으로 쓰지 않도록 Valid hazard와 원문 hazard를 함께 확인한다. | 횟수 |
| 41 | ∅ | 8a | Count of hazard crashes / 8a | 설정된 위험 객체/사건과 관련된 충돌 집계. 실제 값은 0 또는 1이다. fail 시나리오의 0을 정상 음성으로 쓰지 않도록 Valid hazard와 원문 hazard를 함께 확인한다. | 횟수 |
| 42 | Count of crashes | 1a | Count of crashes / 1a | 해당 시나리오의 전체 충돌 횟수 집계. 공란 또는 양의 정수가 기록되어 있다. 공식 로더는 이 집계열 대신 충돌 시각 목록을 세어 전체 충돌 수를 생성한다. | 횟수 |
| 43 | ∅ | 2 | Count of crashes / 2 | 해당 시나리오의 전체 충돌 횟수 집계. 공란 또는 양의 정수가 기록되어 있다. 공식 로더는 이 집계열 대신 충돌 시각 목록을 세어 전체 충돌 수를 생성한다. | 횟수 |
| 44 | ∅ | 2b | Count of crashes / 2b | 해당 시나리오의 전체 충돌 횟수 집계. 공란 또는 양의 정수가 기록되어 있다. 공식 로더는 이 집계열 대신 충돌 시각 목록을 세어 전체 충돌 수를 생성한다. | 횟수 |
| 45 | ∅ | 3c | Count of crashes / 3c | 해당 시나리오의 전체 충돌 횟수 집계. 공란 또는 양의 정수가 기록되어 있다. 공식 로더는 이 집계열 대신 충돌 시각 목록을 세어 전체 충돌 수를 생성한다. | 횟수 |
| 46 | ∅ | 5 | Count of crashes / 5 | 해당 시나리오의 전체 충돌 횟수 집계. 공란 또는 양의 정수가 기록되어 있다. 공식 로더는 이 집계열 대신 충돌 시각 목록을 세어 전체 충돌 수를 생성한다. | 횟수 |
| 47 | ∅ | 6e | Count of crashes / 6e | 해당 시나리오의 전체 충돌 횟수 집계. 공란 또는 양의 정수가 기록되어 있다. 공식 로더는 이 집계열 대신 충돌 시각 목록을 세어 전체 충돌 수를 생성한다. | 횟수 |
| 48 | ∅ | 7a | Count of crashes / 7a | 해당 시나리오의 전체 충돌 횟수 집계. 공란 또는 양의 정수가 기록되어 있다. 공식 로더는 이 집계열 대신 충돌 시각 목록을 세어 전체 충돌 수를 생성한다. | 횟수 |
| 49 | ∅ | 8a | Count of crashes / 8a | 해당 시나리오의 전체 충돌 횟수 집계. 공란 또는 양의 정수가 기록되어 있다. 공식 로더는 이 집계열 대신 충돌 시각 목록을 세어 전체 충돌 수를 생성한다. | 횟수 |
| 50 | CD type | 1a | CD type / 1a | 인지적 주의분산 조건. 1=statement_task, 2=nback_task. 이번 416개 시나리오에서 공란은 scenario_index의 no_task와 일치했다. 조건 분류의 목표/층화용이며 행동 모델 예측 입력으로 쓰지 않는다. | 1/2/공란 |
| 51 | 1=statement | 2 | CD type / 2 | 인지적 주의분산 조건. 1=statement_task, 2=nback_task. 이번 416개 시나리오에서 공란은 scenario_index의 no_task와 일치했다. 조건 분류의 목표/층화용이며 행동 모델 예측 입력으로 쓰지 않는다. | 1/2/공란 |
| 52 | 2=nback | 2b | CD type / 2b | 인지적 주의분산 조건. 1=statement_task, 2=nback_task. 이번 416개 시나리오에서 공란은 scenario_index의 no_task와 일치했다. 조건 분류의 목표/층화용이며 행동 모델 예측 입력으로 쓰지 않는다. | 1/2/공란 |
| 53 | ∅ | 3c | CD type / 3c | 인지적 주의분산 조건. 1=statement_task, 2=nback_task. 이번 416개 시나리오에서 공란은 scenario_index의 no_task와 일치했다. 조건 분류의 목표/층화용이며 행동 모델 예측 입력으로 쓰지 않는다. | 1/2/공란 |
| 54 | I should've just done this in python lol | 5 | CD type / 5 | 인지적 주의분산 조건. 1=statement_task, 2=nback_task. 이번 416개 시나리오에서 공란은 scenario_index의 no_task와 일치했다. 조건 분류의 목표/층화용이며 행동 모델 예측 입력으로 쓰지 않는다. | 1/2/공란 |
| 55 | ∅ | 6e | CD type / 6e | 인지적 주의분산 조건. 1=statement_task, 2=nback_task. 이번 416개 시나리오에서 공란은 scenario_index의 no_task와 일치했다. 조건 분류의 목표/층화용이며 행동 모델 예측 입력으로 쓰지 않는다. | 1/2/공란 |
| 56 | ∅ | 7a | CD type / 7a | 인지적 주의분산 조건. 1=statement_task, 2=nback_task. 이번 416개 시나리오에서 공란은 scenario_index의 no_task와 일치했다. 조건 분류의 목표/층화용이며 행동 모델 예측 입력으로 쓰지 않는다. | 1/2/공란 |
| 57 | ∅ | 8a | CD type / 8a | 인지적 주의분산 조건. 1=statement_task, 2=nback_task. 이번 416개 시나리오에서 공란은 scenario_index의 no_task와 일치했다. 조건 분류의 목표/층화용이며 행동 모델 예측 입력으로 쓰지 않는다. | 1/2/공란 |
| 58 | Alcohol | 1a | Alcohol / 1a | 음주 실험 조건 주석. 1=음주. 이번 416개 시나리오에서 공란은 비음주와 일치했다. 공식 규칙인 참가자 ID가 P로 시작하고 round=R2일 때만 intoxicated=True를 우선 사용하고 이 열로 교차 검증한다. | 1/공란 |
| 59 | 1=drunk | 2 | Alcohol / 2 | 음주 실험 조건 주석. 1=음주. 이번 416개 시나리오에서 공란은 비음주와 일치했다. 공식 규칙인 참가자 ID가 P로 시작하고 round=R2일 때만 intoxicated=True를 우선 사용하고 이 열로 교차 검증한다. | 1/공란 |
| 60 | ∅ | 2b | Alcohol / 2b | 음주 실험 조건 주석. 1=음주. 이번 416개 시나리오에서 공란은 비음주와 일치했다. 공식 규칙인 참가자 ID가 P로 시작하고 round=R2일 때만 intoxicated=True를 우선 사용하고 이 열로 교차 검증한다. | 1/공란 |
| 61 | ∅ | 3c | Alcohol / 3c | 음주 실험 조건 주석. 1=음주. 이번 416개 시나리오에서 공란은 비음주와 일치했다. 공식 규칙인 참가자 ID가 P로 시작하고 round=R2일 때만 intoxicated=True를 우선 사용하고 이 열로 교차 검증한다. | 1/공란 |
| 62 | ∅ | 5 | Alcohol / 5 | 음주 실험 조건 주석. 1=음주. 이번 416개 시나리오에서 공란은 비음주와 일치했다. 공식 규칙인 참가자 ID가 P로 시작하고 round=R2일 때만 intoxicated=True를 우선 사용하고 이 열로 교차 검증한다. | 1/공란 |
| 63 | ∅ | 6e | Alcohol / 6e | 음주 실험 조건 주석. 1=음주. 이번 416개 시나리오에서 공란은 비음주와 일치했다. 공식 규칙인 참가자 ID가 P로 시작하고 round=R2일 때만 intoxicated=True를 우선 사용하고 이 열로 교차 검증한다. | 1/공란 |
| 64 | ∅ | 7a | Alcohol / 7a | 음주 실험 조건 주석. 1=음주. 이번 416개 시나리오에서 공란은 비음주와 일치했다. 공식 규칙인 참가자 ID가 P로 시작하고 round=R2일 때만 intoxicated=True를 우선 사용하고 이 열로 교차 검증한다. | 1/공란 |
| 65 | ∅ | 8a | Alcohol / 8a | 음주 실험 조건 주석. 1=음주. 이번 416개 시나리오에서 공란은 비음주와 일치했다. 공식 규칙인 참가자 ID가 P로 시작하고 round=R2일 때만 intoxicated=True를 우선 사용하고 이 열로 교차 검증한다. | 1/공란 |
| 66 | Sober, no CD | 1a | Sober, no CD / 1a | 해당 시나리오가 비음주·인지 과제 없음 조건이면 1인 조건 표시. Alcohol/CD type의 중복 정보로 조건별 집계·검증에만 사용한다. | 0/1 |
| 67 | ∅ | 2 | Sober, no CD / 2 | 해당 시나리오가 비음주·인지 과제 없음 조건이면 1인 조건 표시. Alcohol/CD type의 중복 정보로 조건별 집계·검증에만 사용한다. | 0/1 |
| 68 | ∅ | 2b | Sober, no CD / 2b | 해당 시나리오가 비음주·인지 과제 없음 조건이면 1인 조건 표시. Alcohol/CD type의 중복 정보로 조건별 집계·검증에만 사용한다. | 0/1 |
| 69 | ∅ | 3c | Sober, no CD / 3c | 해당 시나리오가 비음주·인지 과제 없음 조건이면 1인 조건 표시. Alcohol/CD type의 중복 정보로 조건별 집계·검증에만 사용한다. | 0/1 |
| 70 | ∅ | 5 | Sober, no CD / 5 | 해당 시나리오가 비음주·인지 과제 없음 조건이면 1인 조건 표시. Alcohol/CD type의 중복 정보로 조건별 집계·검증에만 사용한다. | 0/1 |
| 71 | ∅ | 6e | Sober, no CD / 6e | 해당 시나리오가 비음주·인지 과제 없음 조건이면 1인 조건 표시. Alcohol/CD type의 중복 정보로 조건별 집계·검증에만 사용한다. | 0/1 |
| 72 | ∅ | 7a | Sober, no CD / 7a | 해당 시나리오가 비음주·인지 과제 없음 조건이면 1인 조건 표시. Alcohol/CD type의 중복 정보로 조건별 집계·검증에만 사용한다. | 0/1 |
| 73 | ∅ | 8a | Sober, no CD / 8a | 해당 시나리오가 비음주·인지 과제 없음 조건이면 1인 조건 표시. Alcohol/CD type의 중복 정보로 조건별 집계·검증에만 사용한다. | 0/1 |
| 74 | Sober, CD | 1a | Sober, CD / 1a | 해당 시나리오가 비음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 75 | ∅ | 2 | Sober, CD / 2 | 해당 시나리오가 비음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 76 | ∅ | 2b | Sober, CD / 2b | 해당 시나리오가 비음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 77 | ∅ | 3c | Sober, CD / 3c | 해당 시나리오가 비음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 78 | ∅ | 5 | Sober, CD / 5 | 해당 시나리오가 비음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 79 | ∅ | 6e | Sober, CD / 6e | 해당 시나리오가 비음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 80 | ∅ | 7a | Sober, CD / 7a | 해당 시나리오가 비음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 81 | ∅ | 8a | Sober, CD / 8a | 해당 시나리오가 비음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 82 | Drunk, no CD | 1a | Drunk, no CD / 1a | 해당 시나리오가 음주·인지 과제 없음 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 83 | ∅ | 2 | Drunk, no CD / 2 | 해당 시나리오가 음주·인지 과제 없음 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 84 | ∅ | 2b | Drunk, no CD / 2b | 해당 시나리오가 음주·인지 과제 없음 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 85 | ∅ | 3c | Drunk, no CD / 3c | 해당 시나리오가 음주·인지 과제 없음 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 86 | ∅ | 5 | Drunk, no CD / 5 | 해당 시나리오가 음주·인지 과제 없음 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 87 | ∅ | 6e | Drunk, no CD / 6e | 해당 시나리오가 음주·인지 과제 없음 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 88 | ∅ | 7a | Drunk, no CD / 7a | 해당 시나리오가 음주·인지 과제 없음 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 89 | ∅ | 8a | Drunk, no CD / 8a | 해당 시나리오가 음주·인지 과제 없음 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 90 | Drunk, CD | 1a | Drunk, CD / 1a | 해당 시나리오가 음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 91 | ∅ | 2 | Drunk, CD / 2 | 해당 시나리오가 음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 92 | ∅ | 2b | Drunk, CD / 2b | 해당 시나리오가 음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 93 | ∅ | 3c | Drunk, CD / 3c | 해당 시나리오가 음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 94 | ∅ | 5 | Drunk, CD / 5 | 해당 시나리오가 음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 95 | ∅ | 6e | Drunk, CD / 6e | 해당 시나리오가 음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 96 | ∅ | 7a | Drunk, CD / 7a | 해당 시나리오가 음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 97 | ∅ | 8a | Drunk, CD / 8a | 해당 시나리오가 음주·인지 과제 수행 조건이면 1인 조건 표시. 조건별 집계·검증용이며 예측 입력에서 제외한다. | 0/1 |
| 98 | Total | ∅ | Total /  | 참가자별 조건 표시 합계로 해석되는 시나리오 수 집계. 52명 모두 8이며 입력 정보가 없다. 통계 검증 외에는 제외한다. | 개 |
| 99 | Sober hazard crashes | No CD | Sober hazard crashes / No CD | 참가자의 비음주 조건에서 발생한 위험 관련 충돌을 인지 과제 없음/있음으로 나눈 집계. 사후 결과 통계이며 차량 시점별 예측 입력에서 제외한다. | 횟수 |
| 100 | ∅ | CD | Sober hazard crashes / CD | 참가자의 비음주 조건에서 발생한 위험 관련 충돌을 인지 과제 없음/있음으로 나눈 집계. 사후 결과 통계이며 차량 시점별 예측 입력에서 제외한다. | 횟수 |
| 101 | Drunk hazard crashes | No CD | Drunk hazard crashes / No CD | 참가자의 음주 조건에서 발생한 위험 관련 충돌을 인지 과제 없음/있음으로 나눈 집계. 사후 결과 통계이며 예측 입력에서 제외한다. | 횟수 |
| 102 | ∅ | CD | Drunk hazard crashes / CD | 참가자의 음주 조건에서 발생한 위험 관련 충돌을 인지 과제 없음/있음으로 나눈 집계. 사후 결과 통계이며 예측 입력에서 제외한다. | 횟수 |
| 103 | Sober total crashes | No CD | Sober total crashes / No CD | 참가자의 비음주 조건 전체 충돌을 인지 과제 없음/있음으로 나눈 집계. 사후 결과 통계이며 예측 입력에서 제외한다. | 횟수 |
| 104 | ∅ | CD | Sober total crashes / CD | 참가자의 비음주 조건 전체 충돌을 인지 과제 없음/있음으로 나눈 집계. 사후 결과 통계이며 예측 입력에서 제외한다. | 횟수 |
| 105 | Drunk total crashes | No CD | Drunk total crashes / No CD | 참가자의 음주 조건 전체 충돌을 인지 과제 없음/있음으로 나눈 집계. 사후 결과 통계이며 예측 입력에서 제외한다. | 횟수 |
| 106 | ∅ | CD | Drunk total crashes / CD | 참가자의 음주 조건 전체 충돌을 인지 과제 없음/있음으로 나눈 집계. 사후 결과 통계이며 예측 입력에서 제외한다. | 횟수 |
| 107 | off_course (start and end clip time in sec) | 1a | off_course (start and end clip time in sec) / 1a | 주행 경로 이탈로 주석된 시작·끝 구간. 차선 중심으로부터의 거리 측정값이나 완전한 프레임별 차선 이탈 정답이 아니다. 빈칸은 미주석과 구별이 어렵다. 끝값 1000 등의 관측값은 시나리오 길이와 대조하여 확인해야 한다. | 시나리오 시작 기준 초 구간 |
| 108 | ∅ | 2 | off_course (start and end clip time in sec) / 2 | 주행 경로 이탈로 주석된 시작·끝 구간. 차선 중심으로부터의 거리 측정값이나 완전한 프레임별 차선 이탈 정답이 아니다. 빈칸은 미주석과 구별이 어렵다. 끝값 1000 등의 관측값은 시나리오 길이와 대조하여 확인해야 한다. | 시나리오 시작 기준 초 구간 |
| 109 | ∅ | 2b | off_course (start and end clip time in sec) / 2b | 주행 경로 이탈로 주석된 시작·끝 구간. 차선 중심으로부터의 거리 측정값이나 완전한 프레임별 차선 이탈 정답이 아니다. 빈칸은 미주석과 구별이 어렵다. 끝값 1000 등의 관측값은 시나리오 길이와 대조하여 확인해야 한다. | 시나리오 시작 기준 초 구간 |
| 110 | ∅ | 3c | off_course (start and end clip time in sec) / 3c | 주행 경로 이탈로 주석된 시작·끝 구간. 차선 중심으로부터의 거리 측정값이나 완전한 프레임별 차선 이탈 정답이 아니다. 빈칸은 미주석과 구별이 어렵다. 끝값 1000 등의 관측값은 시나리오 길이와 대조하여 확인해야 한다. | 시나리오 시작 기준 초 구간 |
| 111 | ∅ | 5 | off_course (start and end clip time in sec) / 5 | 주행 경로 이탈로 주석된 시작·끝 구간. 차선 중심으로부터의 거리 측정값이나 완전한 프레임별 차선 이탈 정답이 아니다. 빈칸은 미주석과 구별이 어렵다. 끝값 1000 등의 관측값은 시나리오 길이와 대조하여 확인해야 한다. | 시나리오 시작 기준 초 구간 |
| 112 | ∅ | 6e | off_course (start and end clip time in sec) / 6e | 주행 경로 이탈로 주석된 시작·끝 구간. 차선 중심으로부터의 거리 측정값이나 완전한 프레임별 차선 이탈 정답이 아니다. 빈칸은 미주석과 구별이 어렵다. 끝값 1000 등의 관측값은 시나리오 길이와 대조하여 확인해야 한다. | 시나리오 시작 기준 초 구간 |
| 113 | ∅ | 7a | off_course (start and end clip time in sec) / 7a | 주행 경로 이탈로 주석된 시작·끝 구간. 차선 중심으로부터의 거리 측정값이나 완전한 프레임별 차선 이탈 정답이 아니다. 빈칸은 미주석과 구별이 어렵다. 끝값 1000 등의 관측값은 시나리오 길이와 대조하여 확인해야 한다. | 시나리오 시작 기준 초 구간 |
| 114 | ∅ | 8a | off_course (start and end clip time in sec) / 8a | 주행 경로 이탈로 주석된 시작·끝 구간. 차선 중심으로부터의 거리 측정값이나 완전한 프레임별 차선 이탈 정답이 아니다. 빈칸은 미주석과 구별이 어렵다. 끝값 1000 등의 관측값은 시나리오 길이와 대조하여 확인해야 한다. | 시나리오 시작 기준 초 구간 |

<a id="csv-03"></a>

## 3. carla_actor_list.csv

**파일 의미:** 시뮬레이션에 기록된 객체의 ID, 종류·모델, 역할과 기록 구간.

**한 행의 의미:** 한 행 = 객체 하나. 시점마다 반복되는 움직임 표가 아니다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 614 |

**해석할 때 확인할 점:** hero는 참가자 차량 역할이고 autopilot은 자동 주행 객체 역할이다. 정상/비정상 정답 컬럼이 아니다. 기록 시작·종료가 객체 생성·소멸의 실제 순간과 완전히 같다고 단정하지 않는다.

참고: [공식 차량 피처 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/track_features.py), [공식 데이터 형식](https://github.com/ToyotaResearchInstitute/DBM/blob/main/data/README.md).

### 형식 1: 7개 컬럼, 616개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/carla_actor_list.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/carla_actor_list.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `carla_actor_id` | 객체 식별 번호. carla_objects_id와 연결한다. | ID | — |
| 2 | `carla_actor_type` | 시뮬레이터 객체 종류·모델 이름. 예: vehicle.audi.tt. | 문자열 | — |
| 3 | `carla_actor_rolename` | 실험 내 객체 역할. hero는 참가자 차량, autopilot은 자동 주행 객체 역할이다. | 문자열 | — |
| 4 | `start_epoch_ns` | 시나리오에서 해당 객체가 기록되기 시작한 상대 시각. | ns | — |
| 5 | `end_epoch_ns` | 시나리오에서 해당 객체 기록이 끝난 상대 시각. | ns | — |
| 6 | `start_time` | 해당 객체 기록 시작의 절대 로그 시각. | s | — |
| 7 | `end_time` | 해당 객체 기록 종료의 절대 로그 시각. | s | — |

<a id="csv-04"></a>

## 4. carla_objects.csv

**파일 의미:** 참가자 차량을 포함한 여러 객체의 위치·자세·속도·크기를 시점별로 기록한 시뮬레이터 로그.

**한 행의 의미:** 한 행 = 한 시점의 객체 하나. 같은 시각에 여러 행이 있을 수 있다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 614 |

**해석할 때 확인할 점:** 좌표는 지도 기준이다. bbox는 픽셀 박스가 아니다. CARLA native extent는 반크기지만 ROS objects는 그 두 배를 내보낸다. IDD 내보내기까지 직접 확인하지 못했으므로 전체 크기 해석은 ROS 구현과 샘플값에 근거한다.

참고: [공식 데이터 형식](https://github.com/ToyotaResearchInstitute/DBM/blob/main/data/README.md), [CARLA ROS 객체 변환](https://github.com/carla-simulator/ros-bridge/blob/master/carla_ros_bridge/src/carla_ros_bridge/traffic_participant.py).

### 형식 1: 18개 컬럼, 616개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/carla_objects.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/carla_objects.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `carla_objects log time` | 객체 메시지가 원래 로그에 기록된 시각. | 절대 시각 s | — |
| 2 | `carla_objects_id` | 한 시뮬레이션 구간의 객체 식별 번호. | ID | — |
| 3 | `carla_objects_pose_x` | 지도 좌표계의 객체 x 위치. 차량의 전방 축이나 영상의 가로 픽셀값이 아니다. | m | — |
| 4 | `carla_objects_pose_y` | 지도 좌표계의 객체 y 위치. 차량의 횡방향 축이나 영상의 세로 픽셀값이 아니다. | m | — |
| 5 | `carla_objects_pose_z` | 지도 좌표계의 객체 z 위치·높이. | m | — |
| 6 | `carla_objects_pose_orientation_x` | 차체 자세를 나타내는 quaternion의 x 성분. x축 회전각 자체는 아니다. | 무차원 | — |
| 7 | `carla_objects_pose_orientation_y` | 차체 자세 quaternion의 y 성분. y축 회전각 자체는 아니다. | 무차원 | — |
| 8 | `carla_objects_pose_orientation_z` | 차체 자세 quaternion의 z 성분. z축 회전각 자체는 아니다. | 무차원 | — |
| 9 | `carla_objects_pose_orientation_w` | 차체 자세 quaternion의 스칼라 성분. 다른 세 성분과 함께 하나의 자세를 표현한다. | 무차원 | — |
| 10 | `carla_objects_twist_linear_vx` | 지도 좌표계 x 방향의 선속도. 차량 기준 종속도와 다르다. | m/s | — |
| 11 | `carla_objects_twist_linear_vy` | 지도 좌표계 y 방향의 선속도. 차량 기준 횡속도와 다르다. | m/s | — |
| 12 | `carla_objects_twist_linear_vz` | 지도 좌표계 z 방향의 선속도. | m/s | — |
| 13 | `carla_objects_bbox_x` | 객체 3D 바운딩박스의 x축 크기. 영상의 박스 x 좌표가 아니다. | m | — |
| 14 | `carla_objects_bbox_y` | 객체 3D 바운딩박스의 y축 크기. 영상의 박스 y 좌표가 아니다. | m | — |
| 15 | `carla_objects_bbox_z` | 객체 3D 바운딩박스의 z축 크기. | m | — |
| 16 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 17 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 18 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-05"></a>

## 5. carla_hero_vehicle_status.csv

**파일 의미:** 참가자 차량(hero)에 적용된 가속·브레이크·조향 제어값과 차체 자세를 기록한 표.

**한 행의 의미:** 한 행 = 참가자 차량의 한 재샘플링 시점.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 614 |

**해석할 때 확인할 점:** 이 표의 제어값과 usercontrols_status_*의 장치 입력은 출처가 다르다. 제어 입력, 실제 움직임, 운전자의 페달·핸들 입력을 구분한다.

### 형식 1: 11개 컬럼, 616개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/carla_hero_vehicle_status.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/carla_hero_vehicle_status.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `throttle` | 참가자 차량에 적용된 가속 제어 입력. | 제어값 | 가속도 측정값이 아니다. CARLA 표준 입력은 0~1이며 IDD의 내보내기 스케일은 별도 확인 대상이다. |
| 2 | `brake` | 참가자 차량에 적용된 제동 제어 입력. | 제어값 | 충돌 여부나 감속도와 다르다. CARLA 표준 입력은 0~1이다. |
| 3 | `steering` | 참가자 차량에 적용된 조향 제어 입력. | 제어값 | 핸들 각도(°)로 해석하지 않는다. CARLA 표준 steer는 -1~1이나 IDD의 부호 대응은 확인해야 한다. |
| 4 | `carla_hero_status log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 5 | `orientation_x` | 참가자 차량 자세 quaternion의 x 성분. | 무차원 | x/y/z/w 네 성분을 함께 해석하며 개별 회전각이 아니다. |
| 6 | `orientation_y` | 참가자 차량 자세 quaternion의 y 성분. | 무차원 | x/y/z/w 네 성분을 함께 해석하며 개별 회전각이 아니다. |
| 7 | `orientation_z` | 참가자 차량 자세 quaternion의 z 성분. | 무차원 | x/y/z/w 네 성분을 함께 해석하며 개별 회전각이 아니다. |
| 8 | `orientation_w` | 참가자 차량 자세 quaternion의 w 성분. | 무차원 | x/y/z/w 네 성분을 함께 해석하며 개별 회전각이 아니다. |
| 9 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 10 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 11 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-06"></a>

## 6. ic_speedometer.csv

**파일 의미:** 차량 계기판 속도계의 표시값을 시간순으로 기록한 표.

**한 행의 의미:** 한 행 = 한 재샘플링 시점의 속도계 신호.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 614 |

### 형식 1: 5개 컬럼, 616개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/ic_speedometer.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/ic_speedometer.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `ic_speedometer log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `ic_speedometer_data` | 계기판에 표시되는 속도값. | 표시 단위 미확인 | 원자료에서 mph/km/h 여부를 확인하지 못했다. m/s로 단정하거나 임의로 변환하지 않는다. |
| 3 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 4 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 5 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-07"></a>

## 7. telemetry_velocity.csv

**파일 의미:** 차량의 속력 관련 텔레메트리 신호.

**한 행의 의미:** 한 행 = 한 재샘플링 시점의 수치 신호.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 614 |

### 형식 1: 5개 컬럼, 616개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/telemetry_velocity.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/telemetry_velocity.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `telemetry_velocity log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `telemetry_velocity_data` | 차량의 속력 관련 텔레메트리 값. | m/s로 해석되나 장치 규격 미확인 | 샘플은 객체 속도 크기와 비슷하다. 공식 신호 단위 명세는 확보하지 못했다. |
| 3 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 4 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 5 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-08"></a>

## 8. telemetry_vehicleodometer.csv

**파일 의미:** 차량의 누적 주행거리계 신호.

**한 행의 의미:** 한 행 = 한 재샘플링 시점. 현재 시나리오 시작에서 0으로 초기화된 거리라고 가정하지 않는다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 614 |

### 형식 1: 5개 컬럼, 616개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/telemetry_vehicleodometer.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/telemetry_vehicleodometer.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `telemetry_vehicleodometer log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `telemetry_vehicleodometer_data` | 차량의 누적 주행거리계 값. | 원신호 거리 단위 미확인 | 시나리오 내 이동거리를 원하면 시간에 따른 차이를 사용하되 단위를 먼저 확인한다. |
| 3 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 4 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 5 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-09"></a>

## 9. telemetry_roadwheel_angle.csv

**파일 의미:** 도로에 접하는 차량 바퀴의 조향각 관련 텔레메트리.

**한 행의 의미:** 한 행 = 한 재샘플링 시점의 조향 신호. 운전자의 핸들 각도와 구분한다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 614 |

참고: [공식 조향 반전 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/generate_derived_steering_features.py).

### 형식 1: 5개 컬럼, 616개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/telemetry_roadwheel_angle.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/telemetry_roadwheel_angle.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `telemetry_roadwheel_angle log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `telemetry_roadwheel_angle_data` | 차량 바퀴의 조향각 관련 값. | 각도 단위 미확인 | 핸들 각도 및 차체 yaw와 다르다. 공식 반전 코드의 0.5/2.5는 이 신호와 같은 단위다. |
| 3 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 4 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 5 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-10"></a>

## 10. usercontrols_status_brake_pedal.csv

**파일 의미:** 운전 장치에서 읽은 브레이크 페달 입력 상태.

**한 행의 의미:** 한 행 = 한 재샘플링 시점의 입력 신호.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 571 |

### 형식 1: 5개 컬럼, 573개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/usercontrols_status_brake_pedal.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/usercontrols_status_brake_pedal.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `usercontrols_status_brake_pedal log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `usercontrols_status_brake_pedal_data` | 운전자가 밟은 브레이크 페달 입력값. | 원장치 입력값 | 샘플에는 0 같은 값이 있다. 장치 정규화·보정 범위는 미확인. 차량 brake 제어값과 구분한다. |
| 3 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 4 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 5 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-11"></a>

## 11. usercontrols_status_throttle_pedal.csv

**파일 의미:** 운전 장치에서 읽은 가속 페달 입력 상태.

**한 행의 의미:** 한 행 = 한 재샘플링 시점의 입력 신호.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 614 |

### 형식 1: 5개 컬럼, 616개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/usercontrols_status_throttle_pedal.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/usercontrols_status_throttle_pedal.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `usercontrols_status_throttle_pedal log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `usercontrols_status_throttle_pedal_data` | 운전자가 밟은 가속 페달 입력값. | 원장치 입력값 | 가속도나 속도가 아니다. 장치 정규화·보정 범위는 미확인. |
| 3 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 4 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 5 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-12"></a>

## 12. usercontrols_status_steeringwheel_angle.csv

**파일 의미:** 운전자가 돌린 핸들의 각도 관련 입력 신호.

**한 행의 의미:** 한 행 = 한 재샘플링 시점. 차량 차체 방향이나 바퀴 조향각과는 다른 신호다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 614 |

### 형식 1: 5개 컬럼, 616개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/usercontrols_status_steeringwheel_angle.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/usercontrols_status_steeringwheel_angle.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `usercontrols_status_steeringwheel_angle log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `usercontrols_status_steeringwheel_angle_data` | 운전자가 돌린 핸들의 각도 관련 입력값. | 각도 단위 미확인 | 바퀴 각도나 정규화 steering과 직접 같은 값으로 비교하지 않는다. |
| 3 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 4 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 5 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-13"></a>

## 13. experiment_tobii_frame.csv

**파일 의미:** Tobii 장비에서 측정한 좌우 눈 위치, 시선이 향하는 점, 동공 크기, 측정 유효성 및 시계 정보.

**한 행의 의미:** 한 행 = 한 재샘플링 시점의 좌우 눈 측정값.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 1 |
| Sample | Resampled_previous_60 | 1 |
| no-video | Resampled_previous_10 | 1180 |
| no-video | Resampled_previous_60 | 1180 |

**해석할 때 확인할 점:** 좌우는 운전자의 왼쪽·오른쪽 눈이다. user 좌표는 Tobii 기기 전면 중앙을 원점으로 한 mm 좌표이고, display 좌표는 화면 좌상단 0,0·우하단 1,1 기준이다. validity가 False인 측정값은 그대로 정상값으로 사용하지 않는다.

참고: [Tobii 좌표계](https://developer.tobiipro.com/commonconcepts/coordinatesystems.html), [Tobii SDK 시계](https://developer.tobiipro.com/tobii.research/python/reference/2.0.0.9-alpha-g01eb0bc5/namespacetobii__research.html), [공식 시선 고정·도약·엔트로피 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/gaze_features.py).

### 형식 1: 36개 컬럼, 2,362개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/experiment_tobii_frame.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/sim_bag/experiment_tobii_frame.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `tobii log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `tobii_left_eye_gaze_origin_in_trackbox_x` | 왼쪽 눈 눈 위치의 트래킹 가능 공간(track box) 기준 x 성분. | 상대·정규화 좌표로 해석 | user 좌표의 mm와 다르다. IDD 수집기의 정확한 축 정규화는 미확인. |
| 3 | `tobii_left_eye_gaze_origin_in_trackbox_y` | 왼쪽 눈 눈 위치의 트래킹 가능 공간(track box) 기준 y 성분. | 상대·정규화 좌표로 해석 | user 좌표의 mm와 다르다. IDD 수집기의 정확한 축 정규화는 미확인. |
| 4 | `tobii_left_eye_gaze_origin_in_trackbox_z` | 왼쪽 눈 눈 위치의 트래킹 가능 공간(track box) 기준 z 성분. | 상대·정규화 좌표로 해석 | user 좌표의 mm와 다르다. IDD 수집기의 정확한 축 정규화는 미확인. |
| 5 | `tobii_left_eye_gaze_origin_in_user_x` | 왼쪽 눈 시선 출발점인 눈 위치의 사용자 좌표계 x 성분. | mm | 원점은 시선 추적기 전면 중앙. 실제 도로 위치가 아니다. |
| 6 | `tobii_left_eye_gaze_origin_in_user_y` | 왼쪽 눈 시선 출발점인 눈 위치의 사용자 좌표계 y 성분. | mm | 원점은 시선 추적기 전면 중앙. 실제 도로 위치가 아니다. |
| 7 | `tobii_left_eye_gaze_origin_in_user_z` | 왼쪽 눈 시선 출발점인 눈 위치의 사용자 좌표계 z 성분. | mm | 원점은 시선 추적기 전면 중앙. 실제 도로 위치가 아니다. |
| 8 | `tobii_left_eye_gaze_origin_validity` | 왼쪽 눈 눈 위치 측정의 유효 여부. | Boolean | True는 유효, False는 무효. 해당 좌표·크기와 함께 확인한다. |
| 9 | `tobii_left_eye_gaze_pt_in_user_x` | 왼쪽 눈 시선이 향하는 점의 사용자 좌표계 x 성분. | mm | 시선 출발점과 시선 도착점을 구분한다. |
| 10 | `tobii_left_eye_gaze_pt_in_user_y` | 왼쪽 눈 시선이 향하는 점의 사용자 좌표계 y 성분. | mm | 시선 출발점과 시선 도착점을 구분한다. |
| 11 | `tobii_left_eye_gaze_pt_in_user_z` | 왼쪽 눈 시선이 향하는 점의 사용자 좌표계 z 성분. | mm | 시선 출발점과 시선 도착점을 구분한다. |
| 12 | `tobii_left_eye_gaze_pt_in_display_x` | 왼쪽 눈 화면상 시선점의 x 좌표. | 정규화 좌표 | (0,0)은 화면 좌상단, (1,1)은 우하단. 픽셀 좌표가 아니며 화면 밖 값도 처리해야 한다. |
| 13 | `tobii_left_eye_gaze_pt_in_display_y` | 왼쪽 눈 화면상 시선점의 y 좌표. | 정규화 좌표 | (0,0)은 화면 좌상단, (1,1)은 우하단. 픽셀 좌표가 아니며 화면 밖 값도 처리해야 한다. |
| 14 | `tobii_left_eye_gaze_pt_validity` | 왼쪽 눈 시선점 측정의 유효 여부. | Boolean | True는 유효, False는 무효. 해당 좌표·크기와 함께 확인한다. |
| 15 | `tobii_left_eye_pupil_diameter` | 왼쪽 눈 동공 지름. | mm (SDK 정의) | pupil_validity가 유효한지 함께 확인한다. |
| 16 | `tobii_left_eye_pupil_validity` | 왼쪽 눈 동공 측정의 유효 여부. | Boolean | True는 유효, False는 무효. 해당 좌표·크기와 함께 확인한다. |
| 17 | `tobii_right_eye_gaze_origin_in_trackbox_x` | 오른쪽 눈 눈 위치의 트래킹 가능 공간(track box) 기준 x 성분. | 상대·정규화 좌표로 해석 | user 좌표의 mm와 다르다. IDD 수집기의 정확한 축 정규화는 미확인. |
| 18 | `tobii_right_eye_gaze_origin_in_trackbox_y` | 오른쪽 눈 눈 위치의 트래킹 가능 공간(track box) 기준 y 성분. | 상대·정규화 좌표로 해석 | user 좌표의 mm와 다르다. IDD 수집기의 정확한 축 정규화는 미확인. |
| 19 | `tobii_right_eye_gaze_origin_in_trackbox_z` | 오른쪽 눈 눈 위치의 트래킹 가능 공간(track box) 기준 z 성분. | 상대·정규화 좌표로 해석 | user 좌표의 mm와 다르다. IDD 수집기의 정확한 축 정규화는 미확인. |
| 20 | `tobii_right_eye_gaze_origin_in_user_x` | 오른쪽 눈 시선 출발점인 눈 위치의 사용자 좌표계 x 성분. | mm | 원점은 시선 추적기 전면 중앙. 실제 도로 위치가 아니다. |
| 21 | `tobii_right_eye_gaze_origin_in_user_y` | 오른쪽 눈 시선 출발점인 눈 위치의 사용자 좌표계 y 성분. | mm | 원점은 시선 추적기 전면 중앙. 실제 도로 위치가 아니다. |
| 22 | `tobii_right_eye_gaze_origin_in_user_z` | 오른쪽 눈 시선 출발점인 눈 위치의 사용자 좌표계 z 성분. | mm | 원점은 시선 추적기 전면 중앙. 실제 도로 위치가 아니다. |
| 23 | `tobii_right_eye_gaze_origin_validity` | 오른쪽 눈 눈 위치 측정의 유효 여부. | Boolean | True는 유효, False는 무효. 해당 좌표·크기와 함께 확인한다. |
| 24 | `tobii_right_eye_gaze_pt_in_user_x` | 오른쪽 눈 시선이 향하는 점의 사용자 좌표계 x 성분. | mm | 시선 출발점과 시선 도착점을 구분한다. |
| 25 | `tobii_right_eye_gaze_pt_in_user_y` | 오른쪽 눈 시선이 향하는 점의 사용자 좌표계 y 성분. | mm | 시선 출발점과 시선 도착점을 구분한다. |
| 26 | `tobii_right_eye_gaze_pt_in_user_z` | 오른쪽 눈 시선이 향하는 점의 사용자 좌표계 z 성분. | mm | 시선 출발점과 시선 도착점을 구분한다. |
| 27 | `tobii_right_eye_gaze_pt_in_display_x` | 오른쪽 눈 화면상 시선점의 x 좌표. | 정규화 좌표 | (0,0)은 화면 좌상단, (1,1)은 우하단. 픽셀 좌표가 아니며 화면 밖 값도 처리해야 한다. |
| 28 | `tobii_right_eye_gaze_pt_in_display_y` | 오른쪽 눈 화면상 시선점의 y 좌표. | 정규화 좌표 | (0,0)은 화면 좌상단, (1,1)은 우하단. 픽셀 좌표가 아니며 화면 밖 값도 처리해야 한다. |
| 29 | `tobii_right_eye_gaze_pt_validity` | 오른쪽 눈 시선점 측정의 유효 여부. | Boolean | True는 유효, False는 무효. 해당 좌표·크기와 함께 확인한다. |
| 30 | `tobii_right_eye_pupil_diameter` | 오른쪽 눈 동공 지름. | mm (SDK 정의) | pupil_validity가 유효한지 함께 확인한다. |
| 31 | `tobii_right_eye_pupil_validity` | 오른쪽 눈 동공 측정의 유효 여부. | Boolean | True는 유효, False는 무효. 해당 좌표·크기와 함께 확인한다. |
| 32 | `tobii_device_time_stamp` | Tobii 장치 자체 시계 기준 타임스탬프. | SDK 기준 µs | Unix 절대 로그 초나 resampled 상대 ns와 직접 같게 비교하지 않는다. IDD 수집기의 추가 변환 여부는 미확인. |
| 33 | `tobii_system_time_stamp` | Tobii 호스트 시스템 시계 기준 타임스탬프. | SDK 기준 µs | Unix 절대 로그 초나 resampled 상대 ns와 직접 같게 비교하지 않는다. IDD 수집기의 추가 변환 여부는 미확인. |
| 34 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 35 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 36 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-14"></a>

## 14. experiment_tobii_calib_data.csv

**파일 의미:** 시선 추적기를 보정·시험하는 동안 표시한 목표점, 화면 상태, 진행 단계와 횟수를 기록한 표.

**한 행의 의미:** 한 행 = 보정 절차의 한 시점. 운전 중 위험 행동의 라벨이 아니다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| no-video | Resampled_previous_10 | 110 |

**해석할 때 확인할 점:** 목표점 좌표와 단계는 수집 프로그램의 보정 UI 상태를 뜻한다. num_calib/num_test의 정확한 증가 규칙은 미확인이다. 대표 파일에는 보정 실패·재시도·시험 성공 등 여러 상태가 있다.

참고: [Tobii 좌표계](https://developer.tobiipro.com/commonconcepts/coordinatesystems.html), [Tobii SDK 시계](https://developer.tobiipro.com/tobii.research/python/reference/2.0.0.9-alpha-g01eb0bc5/namespacetobii__research.html).

### 형식 1: 13개 컬럼, 110개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/tobii_calibration/sim_bag/experiment_tobii_calib_data.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10/Participants/7201/R1/tobii_calibration/sim_bag/experiment_tobii_calib_data.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `tobii_calib_device_time_stamp` | Tobii 장치 자체 시계 기준 타임스탬프. | SDK 기준 µs | Unix 절대 로그 초나 resampled 상대 ns와 직접 같게 비교하지 않는다. IDD 수집기의 추가 변환 여부는 미확인. |
| 2 | `tobii_calib_system_time_stamp` | Tobii 호스트 시스템 시계 기준 타임스탬프. | SDK 기준 µs | Unix 절대 로그 초나 resampled 상대 ns와 직접 같게 비교하지 않는다. IDD 수집기의 추가 변환 여부는 미확인. |
| 3 | `tobii_calib_mode` | 시선 보정·시험 화면 또는 절차의 현재 상태. | 문자열 | 대표값: WelcomeWidget, CalibrationWidget, TestWidget, TestFailedWidget 등. |
| 4 | `tobii_calib_shown_target_point_x` | 보정·시험 때 화면에 제시한 목표점의 x 좌표. | 정규화 화면 좌표로 해석 | 대표 파일에 0.1, 0.5, 0.9 등이 기록된다. 시선 측정점이 아니라 제시한 목표점이다. |
| 5 | `tobii_calib_shown_target_point_y` | 보정·시험 때 화면에 제시한 목표점의 y 좌표. | 정규화 화면 좌표로 해석 | 단계에 따라 공란이다. 목표를 제시하지 않는 상태일 수 있다. |
| 6 | `tobii_calib_shown_target_idx` | 현재 제시된 보정·시험 목표점의 인덱스. | 정수 | 점의 순번. 좌표나 정확도 점수가 아니다. |
| 7 | `tobii_calib_animation_step` | 목표점 표시 애니메이션의 진행 단계. | 정수 단계 | 구체적인 단계별 의미는 수집 프로그램 코드 미확인. |
| 8 | `tobii_calib_num_calib` | 보정 시행과 관련된 횟수 카운터. | 정수 | 대표 파일은 0~3. 성공 횟수인지 총 시도 횟수인지는 확정하지 않는다. |
| 9 | `tobii_calib_num_test` | 보정 검증 시험과 관련된 횟수 카운터. | 정수 | 대표 파일은 0~2. 정확한 증가 규칙은 수집 코드 미확인. |
| 10 | `tobii_calib log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 11 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 12 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 13 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-15"></a>

## 15. ego_tracks.csv

**파일 의미:** 전체 객체 로그에서 참가자 차량을 분리하고 방향·종횡 속도·가속도·저크를 추가한 표.

**한 행의 의미:** 한 행 = 참가자 차량의 한 시점. 객체 ID는 별도 컬럼으로 들어 있지 않다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10_derived | 1 |
| no-video | Resampled_previous_10_derived | 438 |

**해석할 때 확인할 점:** 기존 6개 종·횡방향 피처는 현재 시점의 차체 방향으로 회전한 위치 곡선에 앞뒤 약 2.5초 구간의 스플라인을 적합해 계산한다. 실시간 과거 데이터만으로 계산한 값과 같은 처리라고 볼 수 없다.

참고: [공식 차량 피처 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/track_features.py), [공식 차체 방향 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/utils/carla.py).

### 형식 1: 24개 컬럼, 439개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/ego_tracks.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/ego_tracks.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `carla_objects_log_time` | 객체 메시지가 원래 로그에 기록된 시각. | 절대 시각 s | — |
| 3 | `carla_objects_pose_x` | 지도 좌표계의 객체 x 위치. 차량의 전방 축이나 영상의 가로 픽셀값이 아니다. | m | — |
| 4 | `carla_objects_pose_y` | 지도 좌표계의 객체 y 위치. 차량의 횡방향 축이나 영상의 세로 픽셀값이 아니다. | m | — |
| 5 | `carla_objects_pose_z` | 지도 좌표계의 객체 z 위치·높이. | m | — |
| 6 | `carla_objects_pose_orientation_x` | 차체 자세를 나타내는 quaternion의 x 성분. x축 회전각 자체는 아니다. | 무차원 | — |
| 7 | `carla_objects_pose_orientation_y` | 차체 자세 quaternion의 y 성분. y축 회전각 자체는 아니다. | 무차원 | — |
| 8 | `carla_objects_pose_orientation_z` | 차체 자세 quaternion의 z 성분. z축 회전각 자체는 아니다. | 무차원 | — |
| 9 | `carla_objects_pose_orientation_w` | 차체 자세 quaternion의 스칼라 성분. 다른 세 성분과 함께 하나의 자세를 표현한다. | 무차원 | — |
| 10 | `carla_objects_twist_linear_vx` | 지도 좌표계 x 방향의 선속도. 차량 기준 종속도와 다르다. | m/s | — |
| 11 | `carla_objects_twist_linear_vy` | 지도 좌표계 y 방향의 선속도. 차량 기준 횡속도와 다르다. | m/s | — |
| 12 | `carla_objects_twist_linear_vz` | 지도 좌표계 z 방향의 선속도. | m/s | — |
| 13 | `carla_objects_bbox_x` | 객체 3D 바운딩박스의 x축 크기. 영상의 박스 x 좌표가 아니다. | m | — |
| 14 | `carla_objects_bbox_y` | 객체 3D 바운딩박스의 y축 크기. 영상의 박스 y 좌표가 아니다. | m | — |
| 15 | `carla_objects_bbox_z` | 객체 3D 바운딩박스의 z축 크기. | m | — |
| 16 | `resampled_log_time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 17 | `smoothed_log_time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |
| 18 | `yaw` | 객체 quaternion의 Euler z 회전각에서 90°를 뺀 수평 방향각. | 도(°) | 차체 방향이며 궤적 접선이나 나침반 방위각과 같다고 가정하지 않는다. |
| 19 | `lateral_speed` | 현재 차체 방향을 기준으로 한 횡방향 속도. 차선 중심 이탈거리와 다르다. | m/s | — |
| 20 | `longitudinal_speed` | 현재 차체 방향을 기준으로 한 전후 방향 속도. | m/s | — |
| 21 | `lateral_acceleration` | 현재 차체 방향 기준 횡가속도. 현재 방향으로 회전시킨 위치 곡선의 2차 미분이다. | m/s² | — |
| 22 | `longitudinal_acceleration` | 현재 차체 방향 기준 종가속도. 현재 방향으로 회전시킨 위치 곡선의 2차 미분이다. | m/s² | — |
| 23 | `lateral_jerk` | 현재 차체 방향 기준 횡방향 저크. 위치 곡선의 3차 미분이다. | m/s³ | — |
| 24 | `longitudinal_jerk` | 현재 차체 방향 기준 종방향 저크. 위치 곡선의 3차 미분이다. | m/s³ | — |

<a id="csv-16"></a>

## 16. ado_tracks.csv

**파일 의미:** 참가자 차량을 제외한 주변 객체들의 궤적. ado는 이 데이터 처리에서 ego 이외 객체를 가리킨다.

**한 행의 의미:** 한 행 = 한 시점의 주변 객체 하나. object_id로 시계열을 묶는다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| no-video | Resampled_previous_10_derived | 364 |

**해석할 때 확인할 점:** 현재 공개 track_features.py는 ego를 뺀 객체가 10개 미만이면 ado 출력 단계에서 반환한다. 파일이 없는 구간을 주변 객체가 전혀 없는 구간으로 해석하지 않는다.

참고: [공식 차량 피처 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/track_features.py).

### 형식 1: 18개 컬럼, 364개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/ado_tracks.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/ado_tracks.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `object_id` | 파생 파일에서 사용하는 객체 ID. 같은 시나리오의 carla_actor_id와 연결한다. | ID | 시나리오 경로와 함께 식별해야 한다. |
| 3 | `carla_objects_log_time` | 객체 메시지가 원래 로그에 기록된 시각. | 절대 시각 s | — |
| 4 | `carla_objects_pose_x` | 지도 좌표계의 객체 x 위치. 차량의 전방 축이나 영상의 가로 픽셀값이 아니다. | m | — |
| 5 | `carla_objects_pose_y` | 지도 좌표계의 객체 y 위치. 차량의 횡방향 축이나 영상의 세로 픽셀값이 아니다. | m | — |
| 6 | `carla_objects_pose_z` | 지도 좌표계의 객체 z 위치·높이. | m | — |
| 7 | `carla_objects_pose_orientation_x` | 차체 자세를 나타내는 quaternion의 x 성분. x축 회전각 자체는 아니다. | 무차원 | — |
| 8 | `carla_objects_pose_orientation_y` | 차체 자세 quaternion의 y 성분. y축 회전각 자체는 아니다. | 무차원 | — |
| 9 | `carla_objects_pose_orientation_z` | 차체 자세 quaternion의 z 성분. z축 회전각 자체는 아니다. | 무차원 | — |
| 10 | `carla_objects_pose_orientation_w` | 차체 자세 quaternion의 스칼라 성분. 다른 세 성분과 함께 하나의 자세를 표현한다. | 무차원 | — |
| 11 | `carla_objects_twist_linear_vx` | 지도 좌표계 x 방향의 선속도. 차량 기준 종속도와 다르다. | m/s | — |
| 12 | `carla_objects_twist_linear_vy` | 지도 좌표계 y 방향의 선속도. 차량 기준 횡속도와 다르다. | m/s | — |
| 13 | `carla_objects_twist_linear_vz` | 지도 좌표계 z 방향의 선속도. | m/s | — |
| 14 | `carla_objects_bbox_x` | 객체 3D 바운딩박스의 x축 크기. 영상의 박스 x 좌표가 아니다. | m | — |
| 15 | `carla_objects_bbox_y` | 객체 3D 바운딩박스의 y축 크기. 영상의 박스 y 좌표가 아니다. | m | — |
| 16 | `carla_objects_bbox_z` | 객체 3D 바운딩박스의 z축 크기. | m | — |
| 17 | `resampled_log_time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 18 | `smoothed_log_time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-17"></a>

## 17. hazard_tracks.csv

**파일 의미:** 공식 처리 코드가 위험 객체로 선정한 차량 또는 보행자 한 객체의 궤적.

**한 행의 의미:** 한 행 = 선정된 객체의 한 시점. 충돌 발생 여부를 기록한 정답 표가 아니다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| no-video | Resampled_previous_10_derived | 364 |

**해석할 때 확인할 점:** 현재 공개 코드는 보행자를 우선 선정하거나, 존재 구간·거리·차종 조건으로 위험 차량 후보를 고른다. 사람의 확정 주석이 아니라 코드의 선정 결과이므로 대상 객체의 타당성을 확인해야 한다.

참고: [공식 차량 피처 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/track_features.py).

### 형식 1: 17개 컬럼, 364개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/hazard_tracks.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/hazard_tracks.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `carla_objects_log_time` | 객체 메시지가 원래 로그에 기록된 시각. | 절대 시각 s | — |
| 3 | `carla_objects_pose_x` | 지도 좌표계의 객체 x 위치. 차량의 전방 축이나 영상의 가로 픽셀값이 아니다. | m | — |
| 4 | `carla_objects_pose_y` | 지도 좌표계의 객체 y 위치. 차량의 횡방향 축이나 영상의 세로 픽셀값이 아니다. | m | — |
| 5 | `carla_objects_pose_z` | 지도 좌표계의 객체 z 위치·높이. | m | — |
| 6 | `carla_objects_pose_orientation_x` | 차체 자세를 나타내는 quaternion의 x 성분. x축 회전각 자체는 아니다. | 무차원 | — |
| 7 | `carla_objects_pose_orientation_y` | 차체 자세 quaternion의 y 성분. y축 회전각 자체는 아니다. | 무차원 | — |
| 8 | `carla_objects_pose_orientation_z` | 차체 자세 quaternion의 z 성분. z축 회전각 자체는 아니다. | 무차원 | — |
| 9 | `carla_objects_pose_orientation_w` | 차체 자세 quaternion의 스칼라 성분. 다른 세 성분과 함께 하나의 자세를 표현한다. | 무차원 | — |
| 10 | `carla_objects_twist_linear_vx` | 지도 좌표계 x 방향의 선속도. 차량 기준 종속도와 다르다. | m/s | — |
| 11 | `carla_objects_twist_linear_vy` | 지도 좌표계 y 방향의 선속도. 차량 기준 횡속도와 다르다. | m/s | — |
| 12 | `carla_objects_twist_linear_vz` | 지도 좌표계 z 방향의 선속도. | m/s | — |
| 13 | `carla_objects_bbox_x` | 객체 3D 바운딩박스의 x축 크기. 영상의 박스 x 좌표가 아니다. | m | — |
| 14 | `carla_objects_bbox_y` | 객체 3D 바운딩박스의 y축 크기. 영상의 박스 y 좌표가 아니다. | m | — |
| 15 | `carla_objects_bbox_z` | 객체 3D 바운딩박스의 z축 크기. | m | — |
| 16 | `resampled_log_time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 17 | `smoothed_log_time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |

<a id="csv-18"></a>

## 18. ado_removal_stats.csv

**파일 의미:** 주변 객체의 마지막 기록 시점과 ego와의 거리·방향, 종료 사유를 코드의 규칙으로 추정한 표.

**한 행의 의미:** 한 행 = 주변 객체 하나의 기록 종료 요약.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| no-video | Resampled_previous_10_derived | 364 |

참고: [공식 차량 피처 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/track_features.py).

### 형식 1: 6개 컬럼, 364개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/ado_removal_stats.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/ado_removal_stats.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `object_id` | 파생 파일에서 사용하는 객체 ID. 같은 시나리오의 carla_actor_id와 연결한다. | ID | 시나리오 경로와 함께 식별해야 한다. |
| 2 | `time_ns` | 주변 객체가 마지막으로 기록된 시나리오 상대 시각. | ns | ado_removal_stats의 기록 종료 시점. |
| 3 | `distance_from_ego` | 마지막 기록 시점에서 해당 객체와 참가자 차량 사이의 3D 직선거리. | m | 지도 좌표 x/y/z 차이로 계산. |
| 4 | `direction_from_ego_deg` | 마지막 기록 시점에 객체가 ego에 대해 놓인 상대 방향각. | 도(°) | 공식 코드에서 위치 방향과 ego yaw를 조합. 0°를 무조건 정면이라고 해석하지 않는다. |
| 5 | `on_screen` | 마지막 기록 시점에서 화면 안에 있을 법한지를 거리·방향으로 추정한 값. | Boolean | 공식 조건은 거리 100m 미만, 상대각 45~135°. 영상에서 실제 보임을 검증한 값이 아니다. |
| 6 | `cause` | 주변 객체 기록이 종료된 이유를 규칙으로 분류한 코드. | 범주 | end, far, still, hazard, previous, unknown. 아래 코드표 참조. |

### cause 코드의 의미

| 코드 | 현재 공개 코드의 해석 |
| --- | --- |
| end | 객체 기록이 참가자 주행 구간 끝까지 이어짐. |
| far | 마지막 ego 거리 250m 이상으로 멀어진 경우. |
| still | 약 7초 전과의 위치 변화가 0.5m 이하인 경우. 과거 시점이 없는 경우의 처리까지 포함된 휴리스틱이므로 실제 정지 판정으로 단정하지 않는다. |
| hazard | 3c 또는 5 시나리오에서 위험 객체와의 마지막 거리가 110m 이내인 등 코드 조건을 만족. 충돌 확정 의미가 아니다. |
| previous | 다른 종료 조건에 해당하지 않고 객체의 첫 기록 시각이 0인 경우. |
| unknown | 위 분류에 해당하지 않아 이유를 정하지 못함. |

<a id="csv-19"></a>

## 19. relevant_trajectories.csv

**파일 의미:** 객체 궤적에 참가자 차량과의 3D 거리(relevance) 및 차체 방향(yaw)을 추가한 표.

**한 행의 의미:** 한 행 = 한 시점의 객체 하나. 참가자 차량 자체도 포함한다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10_derived | 1 |
| no-video | Resampled_previous_10_derived | 371 |

**해석할 때 확인할 점:** relevance의 실제 계산은 sqrt(dx²+dy²+dz²)이다. 값이 높다고 관련성이 높거나 위험하다는 뜻이 아니며, 참가자 차량까지 포함된다는 점에 유의한다.

참고: [공식 객체 거리·방향 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/generate_derived_relevant_trajectories.py), [공식 차체 방향 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/utils/carla.py).

### 형식 1: 20개 컬럼, 372개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/relevant_trajectories.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/relevant_trajectories.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `object_id` | 파생 파일에서 사용하는 객체 ID. 같은 시나리오의 carla_actor_id와 연결한다. | ID | 시나리오 경로와 함께 식별해야 한다. |
| 3 | `carla_objects_log_time` | 객체 메시지가 원래 로그에 기록된 시각. | 절대 시각 s | — |
| 4 | `carla_objects_pose_x` | 지도 좌표계의 객체 x 위치. 차량의 전방 축이나 영상의 가로 픽셀값이 아니다. | m | — |
| 5 | `carla_objects_pose_y` | 지도 좌표계의 객체 y 위치. 차량의 횡방향 축이나 영상의 세로 픽셀값이 아니다. | m | — |
| 6 | `carla_objects_pose_z` | 지도 좌표계의 객체 z 위치·높이. | m | — |
| 7 | `carla_objects_pose_orientation_x` | 차체 자세를 나타내는 quaternion의 x 성분. x축 회전각 자체는 아니다. | 무차원 | — |
| 8 | `carla_objects_pose_orientation_y` | 차체 자세 quaternion의 y 성분. y축 회전각 자체는 아니다. | 무차원 | — |
| 9 | `carla_objects_pose_orientation_z` | 차체 자세 quaternion의 z 성분. z축 회전각 자체는 아니다. | 무차원 | — |
| 10 | `carla_objects_pose_orientation_w` | 차체 자세 quaternion의 스칼라 성분. 다른 세 성분과 함께 하나의 자세를 표현한다. | 무차원 | — |
| 11 | `carla_objects_twist_linear_vx` | 지도 좌표계 x 방향의 선속도. 차량 기준 종속도와 다르다. | m/s | — |
| 12 | `carla_objects_twist_linear_vy` | 지도 좌표계 y 방향의 선속도. 차량 기준 횡속도와 다르다. | m/s | — |
| 13 | `carla_objects_twist_linear_vz` | 지도 좌표계 z 방향의 선속도. | m/s | — |
| 14 | `carla_objects_bbox_x` | 객체 3D 바운딩박스의 x축 크기. 영상의 박스 x 좌표가 아니다. | m | — |
| 15 | `carla_objects_bbox_y` | 객체 3D 바운딩박스의 y축 크기. 영상의 박스 y 좌표가 아니다. | m | — |
| 16 | `carla_objects_bbox_z` | 객체 3D 바운딩박스의 z축 크기. | m | — |
| 17 | `resampled_log_time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 18 | `smoothed_log_time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |
| 19 | `relevance` | 해당 객체와 참가자 차량 사이의 3차원 직선거리. 이름과 달리 분류 확률이나 위험 점수가 아니다. | m | 공식 코드는 x/y/z 위치 차이의 크기로 계산한다. 참가자 차량 자체의 값은 0이다. |
| 20 | `yaw` | 객체 quaternion의 Euler z 회전각에서 90°를 뺀 수평 방향각. | 도(°) | 차체 방향이며 궤적 접선이나 나침반 방위각과 같다고 가정하지 않는다. |

<a id="csv-20"></a>

## 20. steering_reversals.csv

**파일 의미:** 평활화한 바퀴 조향 신호에서 서로 다른 변화량 기준으로 조향 반전 이벤트를 검출한 표.

**한 행의 의미:** 한 행 = 한 시점. 각 이벤트 컬럼의 1은 그 시점의 검출을 뜻하며 누적 횟수가 아니다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10_derived | 1 |
| no-video | Resampled_previous_10_derived | 438 |

**해석할 때 확인할 점:** 공식 코드는 바퀴 조향 신호에 2Hz 저역통과 필터를 양방향(filtfilt)으로 적용한 뒤 반전 시점을 찾는다. 저장값은 미래 신호의 영향이 있는 오프라인 처리 결과다.

참고: [공식 조향 반전 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/generate_derived_steering_features.py).

### 형식 1: 3개 컬럼, 439개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/steering_reversals.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/steering_reversals.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `reversals_0_5` | 조향 변화량 0.5 기준으로 검출된 반전 시점 표시. | 0/1 | 1=검출, 0=해당 시점에 미검출. 변화량 단위는 원 바퀴 조향 신호와 같다. |
| 3 | `reversals_2_5` | 조향 변화량 2.5 기준으로 검출된 반전 시점 표시. | 0/1 | 1=검출, 0=미검출. 누적 횟수가 아니다. |

<a id="csv-21"></a>

## 21. gaze_depth.csv

**파일 의미:** 시선이 향한 영상 좌표에서 깊이 영상의 값을 읽은 표.

**한 행의 의미:** 한 행 = 한 시점. 좌우 눈별 형식과 좌우 구분이 없는 형식이 모두 존재한다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10_derived | 1 |
| no-video | Resampled_previous_10_derived | 430 |

**해석할 때 확인할 점:** 좌우 구분 없는 형식의 단일 gaze_depth를 좌우 평균이라고 단정하지 않는다. 새 형식의 의미를 근거 없이 옛 형식에 복사하지 않는다.

참고: [공식 시선 깊이 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/generate_derived_gaze_depth_features.py), [공식 영상 읽기·깊이 변환](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/ddd_2024_features/video_feature.py).

### 형식 1: 3개 컬럼, 372개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_depth.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_depth.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `gaze_left_depth` | 왼쪽 눈 시선점에 해당하는 장면 깊이 영상의 값. | m (현재 공식 깊이 읽기 경로) | 눈과 모니터 사이 거리가 아니라 시뮬레이션 장면의 깊이. 결측은 0거리와 다르다. |
| 3 | `gaze_right_depth` | 오른쪽 눈 시선점에 해당하는 장면 깊이 영상의 값. | m (현재 공식 깊이 읽기 경로) | 눈과 모니터 사이 거리가 아니라 시뮬레이션 장면의 깊이. 결측은 0거리와 다르다. |

### 형식 2: 2개 컬럼, 59개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7204/R1/driving/2-vehicle_pop_out/no_task/gaze_depth.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7204/R1/driving/2-vehicle_pop_out/no_task/gaze_depth.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `gaze_depth` | 좌우 구분 없는 시선점에 해당하는 장면 깊이 영상의 값. | m (현재 공식 깊이 읽기 경로) | 어느 눈을 썼는지 또는 양안을 합쳤는지는 파일 헤더와 현재 공개 생성 코드만으로 확정하지 못했다. 눈과 모니터 사이 거리가 아니라 시뮬레이션 장면의 깊이. 결측은 0거리와 다르다. |

<a id="csv-22"></a>

## 22. gaze_semantics.csv

**파일 의미:** 시선이 향한 영상 픽셀의 의미 분할 코드를 기록한 표. 도로·차량·보행자 등 무엇을 보고 있는지 나타낸다.

**한 행의 의미:** 한 행 = 한 시점. 좌우 눈별 형식과 다른 헤더를 가진 형식이 모두 존재한다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10_derived | 1 |
| no-video | Resampled_previous_10_derived | 430 |

**해석할 때 확인할 점:** 분류 숫자는 카테고리 ID다. 크기가 클수록 위험하다는 순서가 아니다. cam_seg/gaze_semantics 형식의 cam_seg는 대표 파일에서 모두 -1이며 정확한 생성 의도는 확인하지 못했다.

참고: [공식 시선 의미 분류 계산·코드표](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/generate_derived_gaze_semantic_features.py).

### 형식 1: 3개 컬럼, 372개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_semantics.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_semantics.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `gaze_left_semantics` | 왼쪽 눈 시선점 픽셀의 의미 분류 코드. | 정수 범주 | 예: 1=도로, 14=승용차. -1은 현재 공식 코드의 유효값 미기록 초기값이다. |
| 3 | `gaze_right_semantics` | 오른쪽 눈 시선점 픽셀의 의미 분류 코드. | 정수 범주 | 예: 1=도로, 14=승용차. -1은 현재 공식 코드의 유효값 미기록 초기값이다. |

### 형식 2: 3개 컬럼, 59개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7204/R1/driving/2-vehicle_pop_out/no_task/gaze_semantics.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7204/R1/driving/2-vehicle_pop_out/no_task/gaze_semantics.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `cam_seg` | 좌우 구분 없는 gaze_semantics 형식에 남아 있는 의미 분할 관련 컬럼. | 코드·정의 미확인 | 확인한 대표 파일 2,247행은 모두 -1이다. 좌안 값이나 정상적인 영상 분류값으로 단정하지 않는다. |
| 3 | `gaze_semantics` | 좌우 구분 없는 시선점 픽셀의 의미 분류 코드. | 정수 범주 | 어느 눈을 썼는지 또는 양안을 합쳤는지는 파일 헤더와 현재 공개 생성 코드만으로 확정하지 못했다. 예: 1=도로, 14=승용차. -1은 현재 공식 코드의 유효값 미기록 초기값이다. |

### 의미 분류 코드

| 코드 | 의미 |
| --- | --- |
| -1 | 유효 분류 미기록(현재 공식 코드 초기값) |
| 0 | 미분류 |
| 1 | 도로 |
| 2 | 보도 |
| 3 | 건물 |
| 4 | 벽 |
| 5 | 울타리 |
| 6 | 기둥 |
| 7 | 신호등 |
| 8 | 교통표지 |
| 9 | 식생 |
| 10 | 지형 |
| 11 | 하늘 |
| 12 | 보행자 |
| 13 | 탑승자(rider) |
| 14 | 승용차 |
| 15 | 트럭 |
| 16 | 버스 |
| 17 | 기차 |
| 18 | 오토바이 |
| 19 | 자전거 |
| 20 | 고정 물체 |
| 21 | 이동 가능한 물체 |
| 22 | 기타 |
| 23 | 물 |
| 24 | 도로 선·표시 |
| 25 | 기타 지면 구조 |
| 26 | 교량 |
| 27 | 철도 선로 |
| 28 | 가드레일 |

코드 0은 미분류이고 -1과 다르다. 원본 파일에 공란도 존재할 수 있다. 코드표는 위 공식 생성 파일의 주석 기준이다.

<a id="csv-23"></a>

## 23. gaze_entropy.csv

**파일 의미:** 화면 영역 사이의 시선 이동과 분포가 얼마나 다양하거나 예측하기 어려운지를 요약한 표.

**한 행의 의미:** 한 행 = 한 시점에 대응하는 시간창 통계. 좌우 눈별 형식과 구분 없는 형식이 존재한다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10_derived | 1 |
| no-video | Resampled_previous_10_derived | 438 |

**해석할 때 확인할 점:** 좌우 구분이 없는 3컬럼 형식도 존재한다. 처음 시간창이 부족한 구간 등의 결측을 엔트로피 0으로 바꾸면 의미가 달라진다.

참고: [공식 시선 고정·도약·엔트로피 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/gaze_features.py), [공식 시선 엔트로피 생성 설정](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/generate_derived_gaze_entropy_features.py).

### 형식 1: 5개 컬럼, 372개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_entropy.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_entropy.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `gaze_left_transition_entropy` | 왼쪽 눈 화면 영역 사이 시선 전이의 불확실성 지표. | 엔트로피·무차원 | 현재 공개 생성 설정은 과거 5초, 가로 5×세로 1 영역. 정확한 로그 밑은 별도 라이브러리 확인 필요. |
| 3 | `gaze_left_stationary_entropy` | 왼쪽 눈 화면 영역별 시선 분포의 불확실성 지표. | 엔트로피·무차원 | stationary는 차량 정지나 fixation 판정이 아니라 시선 분포에 관한 용어다. |
| 4 | `gaze_right_transition_entropy` | 오른쪽 눈 화면 영역 사이 시선 전이의 불확실성 지표. | 엔트로피·무차원 | 현재 공개 생성 설정은 과거 5초, 가로 5×세로 1 영역. 정확한 로그 밑은 별도 라이브러리 확인 필요. |
| 5 | `gaze_right_stationary_entropy` | 오른쪽 눈 화면 영역별 시선 분포의 불확실성 지표. | 엔트로피·무차원 | stationary는 차량 정지나 fixation 판정이 아니라 시선 분포에 관한 용어다. |

### 형식 2: 3개 컬럼, 67개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7204/R1/driving/2-vehicle_pop_out/no_task/gaze_entropy.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_10_derived/Participants/7204/R1/driving/2-vehicle_pop_out/no_task/gaze_entropy.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `gaze_transition_entropy` | 좌우 구분 없는 화면 영역 사이 시선 전이의 불확실성 지표. | 엔트로피·무차원 | 어느 눈을 썼는지 또는 양안을 합쳤는지는 파일 헤더와 현재 공개 생성 코드만으로 확정하지 못했다. 현재 공개 생성 설정은 과거 5초, 가로 5×세로 1 영역. 정확한 로그 밑은 별도 라이브러리 확인 필요. |
| 3 | `gaze_stationary_entropy` | 좌우 구분 없는 화면 영역별 시선 분포의 불확실성 지표. | 엔트로피·무차원 | 어느 눈을 썼는지 또는 양안을 합쳤는지는 파일 헤더와 현재 공개 생성 코드만으로 확정하지 못했다. stationary는 차량 정지나 fixation 판정이 아니라 시선 분포에 관한 용어다. |

<a id="csv-24"></a>

## 24. gaze_pitch_yaw.csv

**파일 의미:** 좌우 눈의 시선 방향을 위아래(pitch)와 좌우(yaw) 각도로 표현한 파생 표.

**한 행의 의미:** 한 행 = 한 시점의 좌우 눈 방향각. 차량 yaw와 구분한다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_60_derived | 1 |
| no-video | Resampled_previous_60_derived | 371 |

**해석할 때 확인할 점:** 컬럼명과 샘플 값으로 시선의 수평·수직 각도임을 해석했다. 이번 확인에서는 해당 생성 스크립트를 읽지 못했으므로 정확한 기준축·부호·단위를 미확인으로 표시했다.

### 형식 1: 5개 컬럼, 372개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_60_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_pitch_yaw.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_60_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_pitch_yaw.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `gaze_left_pitch` | 왼쪽 눈 시선의 위아래 방향각. | 각도 (도 단위로 추정) | 생성 파일의 계산식을 직접 확인하지 못해 기준축·부호·단위를 확정하지 않는다. 차량 pitch와 다르다. |
| 3 | `gaze_left_yaw` | 왼쪽 눈 시선의 좌우 방향각. | 각도 (도 단위로 추정) | 차체 yaw와 별개다. 정확한 영점·부호·각도 변환은 생성 코드 추가 확인 필요. |
| 4 | `gaze_right_pitch` | 오른쪽 눈 시선의 위아래 방향각. | 각도 (도 단위로 추정) | 생성 파일의 계산식을 직접 확인하지 못해 기준축·부호·단위를 확정하지 않는다. 차량 pitch와 다르다. |
| 5 | `gaze_right_yaw` | 오른쪽 눈 시선의 좌우 방향각. | 각도 (도 단위로 추정) | 차체 yaw와 별개다. 정확한 영점·부호·각도 변환은 생성 코드 추가 확인 필요. |

<a id="csv-25"></a>

## 25. gaze_fixation_saccade.csv

**파일 의미:** 좌우 눈의 시선 고정(fixation), 빠른 이동(saccade) 검출과 시간창 내 비율.

**한 행의 의미:** 한 행 = 한 시점. 검출 표시와 시간창 비율이 함께 들어 있다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_60_derived | 1 |
| no-video | Resampled_previous_60_derived | 371 |

**해석할 때 확인할 점:** 비율은 일정 주파수 샘플 수의 비율이므로 고정·도약에 할당된 시간의 비율에 해당한다. 고정·도약 검출 자체는 구간 단위 처리이며 실시간 검출 지연은 별도 검토가 필요하다.

참고: [공식 시선 고정·도약·엔트로피 계산](https://github.com/ToyotaResearchInstitute/DBM/blob/main/features/gaze_features.py).

### 형식 1: 9개 컬럼, 372개 파일

대표 원본: [data/IDD/no-video/Processed/Resampled_previous_60_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_fixation_saccade.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/no-video/Processed/Resampled_previous_60_derived/Participants/7201/R1/driving/2b-vehicle_door_open_hazard/statement_task/gaze_fixation_saccade.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `gaze_left_saccade` | 왼쪽 눈 급속 시선 이동(saccade) 구간 검출 표시. | 0/1 | 1=검출 구간에 속함, 0=미검출. 0이 시선 고정 또는 유효 측정을 보증하지 않는다. |
| 3 | `gaze_left_fixation` | 왼쪽 눈 시선 고정(fixation) 구간 검출 표시. | 0/1 | 1=검출 구간에 속함, 0=미검출. 필터와 검출 기준을 적용한 파생값이다. |
| 4 | `gaze_left_fixation_saccade_ratio` | 왼쪽 눈 과거 시간창 내 고정으로 분류된 샘플 수 ÷ 급속 이동 샘플 수. | 비율 | 공식 기본 창은 5초. 분모 0 및 초기 창 부족 시 NaN. 개별 이벤트 개수 비율이 아니다. |
| 5 | `gaze_left_saccade_fixation_ratio` | 왼쪽 눈 과거 시간창 내 급속 이동 샘플 수 ÷ 고정 샘플 수. | 비율 | 분모 0 및 초기 창 부족 시 NaN. 위 비율과 분자·분모가 반대다. |
| 6 | `gaze_right_saccade` | 오른쪽 눈 급속 시선 이동(saccade) 구간 검출 표시. | 0/1 | 1=검출 구간에 속함, 0=미검출. 0이 시선 고정 또는 유효 측정을 보증하지 않는다. |
| 7 | `gaze_right_fixation` | 오른쪽 눈 시선 고정(fixation) 구간 검출 표시. | 0/1 | 1=검출 구간에 속함, 0=미검출. 필터와 검출 기준을 적용한 파생값이다. |
| 8 | `gaze_right_fixation_saccade_ratio` | 오른쪽 눈 과거 시간창 내 고정으로 분류된 샘플 수 ÷ 급속 이동 샘플 수. | 비율 | 공식 기본 창은 5초. 분모 0 및 초기 창 부족 시 NaN. 개별 이벤트 개수 비율이 아니다. |
| 9 | `gaze_right_saccade_fixation_ratio` | 오른쪽 눈 과거 시간창 내 급속 이동 샘플 수 ÷ 고정 샘플 수. | 비율 | 분모 0 및 초기 창 부족 시 NaN. 위 비율과 분자·분모가 반대다. |

<a id="csv-26"></a>

## 26. frame_timing.csv

**파일 의미:** 영상 프레임 번호와 원래·재샘플링 시각을 연결하는 표. 영상 내용 자체를 담지는 않는다.

**한 행의 의미:** 한 행 = 재샘플링 영상의 한 시점/프레임 대응. 카메라 종류 및 축소 영상에 따라 4개 헤더 형식이 있다.

| 배포 폴더 | 처리 버전/위치 | 파일 수 |
| --- | --- | --- |
| Sample | Resampled_previous_10 | 3 |
| Sample | Resampled_previous_10_derived | 1 |

**해석할 때 확인할 점:** 카메라 AVI/MKV의 FPS 메타데이터만으로 시각을 추측하지 말고 이 표의 resampled_frame과 상대 시각을 연결한다. 원본 프레임 ID는 재샘플링 시 중복되거나 건너뛸 수 있다.

참고: [공식 데이터 형식](https://github.com/ToyotaResearchInstitute/DBM/blob/main/data/README.md), [공식 영상 읽기·깊이 변환](https://github.com/ToyotaResearchInstitute/DBM/blob/main/hail-datasets/hail_datasets/datasets/ddd_2024/ddd_2024_features/video_feature.py).

### 형식 1: 8개 컬럼, 1개 파일

대표 원본: [data/IDD/Sample/Processed/Resampled_previous_10/Participants/P710/R1/driving/6e-vehicle_run_red_light/nback_task/cam_depth/frame_timing.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/Sample/Processed/Resampled_previous_10/Participants/P710/R1/driving/6e-vehicle_run_red_light/nback_task/cam_depth/frame_timing.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `cam_depth_frame log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `cam_depth_publish_time_ns` | 카메라 프레임 메시지가 발행된 시각. | ns | 헤더 시각 및 로그 수신 시각과 구분한다. |
| 3 | `cam_depth_header_time_ns` | 카메라 프레임 메시지 헤더에 기록된 시각. | ns | CSV에서 지수 표기 실수로 저장된 값이 있어 큰 정수 정밀도에 주의한다. |
| 4 | `cam_depth_frame` | 원본 카메라 스트림의 프레임 식별 번호. | 정수 | 재샘플링 영상의 resampled_frame 번호와 다를 수 있다. |
| 5 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 6 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 7 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |
| 8 | `resampled_frame` | 저장된 재샘플링 영상에서 대응하는 프레임 번호. | 0부터 시작하는 번호 | resampled 시각과 실제 영상 프레임을 연결한다. |

### 형식 2: 8개 컬럼, 1개 파일

대표 원본: [data/IDD/Sample/Processed/Resampled_previous_10/Participants/P710/R1/driving/6e-vehicle_run_red_light/nback_task/cam_front/frame_timing.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/Sample/Processed/Resampled_previous_10/Participants/P710/R1/driving/6e-vehicle_run_red_light/nback_task/cam_front/frame_timing.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `cam_front_frame log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `cam_front_publish_time_ns` | 카메라 프레임 메시지가 발행된 시각. | ns | 헤더 시각 및 로그 수신 시각과 구분한다. |
| 3 | `cam_front_header_time_ns` | 카메라 프레임 메시지 헤더에 기록된 시각. | ns | CSV에서 지수 표기 실수로 저장된 값이 있어 큰 정수 정밀도에 주의한다. |
| 4 | `cam_front_frame` | 원본 카메라 스트림의 프레임 식별 번호. | 정수 | 재샘플링 영상의 resampled_frame 번호와 다를 수 있다. |
| 5 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 6 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 7 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |
| 8 | `resampled_frame` | 저장된 재샘플링 영상에서 대응하는 프레임 번호. | 0부터 시작하는 번호 | resampled 시각과 실제 영상 프레임을 연결한다. |

### 형식 3: 8개 컬럼, 1개 파일

대표 원본: [data/IDD/Sample/Processed/Resampled_previous_10/Participants/P710/R1/driving/6e-vehicle_run_red_light/nback_task/cam_seg/frame_timing.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/Sample/Processed/Resampled_previous_10/Participants/P710/R1/driving/6e-vehicle_run_red_light/nback_task/cam_seg/frame_timing.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `cam_seg_frame log time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 2 | `cam_seg_publish_time_ns` | 카메라 프레임 메시지가 발행된 시각. | ns | 헤더 시각 및 로그 수신 시각과 구분한다. |
| 3 | `cam_seg_header_time_ns` | 카메라 프레임 메시지 헤더에 기록된 시각. | ns | CSV에서 지수 표기 실수로 저장된 값이 있어 큰 정수 정밀도에 주의한다. |
| 4 | `cam_seg_frame` | 원본 카메라 스트림의 프레임 식별 번호. | 정수 | 재샘플링 영상의 resampled_frame 번호와 다를 수 있다. |
| 5 | `resampled epoch ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 6 | `resampled log time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 7 | `smoothed log time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |
| 8 | `resampled_frame` | 저장된 재샘플링 영상에서 대응하는 프레임 번호. | 0부터 시작하는 번호 | resampled 시각과 실제 영상 프레임을 연결한다. |

### 형식 4: 9개 컬럼, 1개 파일

대표 원본: [data/IDD/Sample/Processed/Resampled_previous_10_derived/Participants/P710/R1/driving/6e-vehicle_run_red_light/nback_task/cam_front_scale4/frame_timing.csv](C:/Users/RTX/Desktop/AIOT/AIOT-Project/AIOT_2026/data/IDD/Sample/Processed/Resampled_previous_10_derived/Participants/P710/R1/driving/6e-vehicle_run_red_light/nback_task/cam_front_scale4/frame_timing.csv)

| 열 | 실제 컬럼명 | 설명 | 단위·값 | 해석 참고 |
| --- | --- | --- | --- | --- |
| 1 | `resampled_epoch_ns` | 해당 시나리오의 시작을 0으로 한 재샘플링 상대 시각. | ns | 초로 바꿀 때 1e9로 나눈다. 시나리오마다 다시 0에서 시작한다. |
| 2 | `cam_front_frame_log_time` | 해당 센서·메시지가 원래 로그에 기록된 시각. | 절대 로그 시각 s | 재샘플링 기준시각 및 장치 자체 시계와 구분한다. |
| 3 | `cam_front_publish_time_ns` | 카메라 프레임 메시지가 발행된 시각. | ns | 헤더 시각 및 로그 수신 시각과 구분한다. |
| 4 | `cam_front_header_time_ns` | 카메라 프레임 메시지 헤더에 기록된 시각. | ns | CSV에서 지수 표기 실수로 저장된 값이 있어 큰 정수 정밀도에 주의한다. |
| 5 | `cam_front_frame` | 원본 카메라 스트림의 프레임 식별 번호. | 정수 | 재샘플링 영상의 resampled_frame 번호와 다를 수 있다. |
| 6 | `resampled_log_time` | 재샘플링된 시간축의 절대 로그 시각. | s | 상대 시간과 구분한다. |
| 7 | `smoothed_log_time` | 전처리 과정에서 보정·평활화한 로그 시각. | s | 정확한 보정 알고리즘은 확인되지 않았다. 공란일 수 있다. |
| 8 | `resampled_frame` | 저장된 재샘플링 영상에서 대응하는 프레임 번호. | 0부터 시작하는 번호 | resampled 시각과 실제 영상 프레임을 연결한다. |
| 9 | `frame_in_chunk` | 데이터 로더가 처리한 청크 안에서의 프레임 순번. | 정수 | 원래 카메라 프레임 번호와 다르다. 축소 영상 시간표에 존재. |

## 데이터 연결과 해석 예시

1. scenario_index에서 참가자 경로·round·cognitive_task와 시나리오를 찾는다.
2. carla_actor_list에서 hero 역할의 객체 ID를 찾고 carla_objects의 같은 ID·시나리오를 연결한다. ego_tracks는 이 참가자 차량의 파생 시계열이다.
3. 같은 시나리오의 상대 ns로 차량·시선·프레임 시간표를 맞춘다. 10Hz/60Hz 간에는 동일한 행 번호를 연결하지 않는다.
4. 영상은 frame_timing의 resampled_frame을 이용해 해당 파일의 실제 프레임과 연결한다.
5. 조건과 사건은 idd_annotation 및 scenario_index로 확인한다. 주변 객체에 참가자의 음주 조건을 복사하지 않는다.

## 확인된 한계와 근거

- 모든 13,042개 파일의 헤더를 검사했지만 모든 데이터 행을 읽어 통계 검증한 것은 아니다. 파일 수가 다르다는 이유만으로 데이터 손실이나 오류로 단정하지 않는다.
- 단일 시선 형식의 눈 선택·통합 방식, cam_seg 잔여 컬럼의 정확한 의도, 일부 장치 신호의 단위, 시선 pitch/yaw의 정확한 각도 기준은 확인하지 못했다. 해당 표에 이를 표시했다.
- 현재 공개 코드의 계산법을 설명한 부분은 다운로드된 모든 파일이 같은 코드 버전으로 생성됐다는 보장이 아니다. 특히 같은 이름의 서로 다른 시선 형식은 구분해 사용해야 한다.
- 출처는 각 절의 로컬 대표 CSV 및 공식 코드·문서 링크에 표시했다. 동일 형식의 다른 참가자·시나리오 파일도 같은 컬럼 설명을 적용한다.

## 문서 범위 검증

- 파일명 26종 및 헤더 형식 32종을 모두 설명했다.
- 형식별 컬럼 설명 행 합계: 397개. 다른 형식에 반복되는 시간·좌표 컬럼도 각각 센 수치다.
- 각 형식의 실제 헤더 순서대로 설명을 배치했다. idd_annotation은 물리 114개 열과 원본 두 줄 헤더를 함께 대조했다.
- 같은 형식으로 묶인 파일 수의 합계: 13,042개.
