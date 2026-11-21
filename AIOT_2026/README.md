# 영유아 호흡 움직임 모니터링 · AIOT 2026

프로젝트 자료는 **[AIR-400 자료 안내 열기](air400/index.html)** 에서 확인합니다.

```text
AIOT_2026/
├─ air400/
│  ├─ 00_공통자료/              원본 영상·호흡 주석·공개 소스·가중치
│  ├─ 01_파인튜닝전/            모델·예측 파형·박스 화면·설정·지표
│  ├─ 02_Chest_파인튜닝/        학습 이미지·정답 라벨·라벨 샘플·학습 기록
│  ├─ 03_파인튜닝후/            전 단계와 같은 결과 구조
│  ├─ 04_PT자료/                전후 영상·그래프·성능표·사례·실험 개요·라벨 샘플
│  ├─ 05_기존모델비교실험/      기존 4모델 비교 결과·보고서·실행 기록
│  ├─ 06_단일클래스_학습데이터/ 10FPS·30초 DeepPhys 파형·호흡 간격·얼굴 관측 데이터
│  ├─ 07_이상탐지_모델비교/     동일 8:2 분할의 오토인코더·Deep SVDD 모델과 검증 그래프
│  ├─ scripts/                 실행 코드·공통 경로 설정
│  ├─ index.html               폴더 안내와 파일 링크
│  └─ project_status.json      진행 상태
├─ pc/                        Pi 영상 수신·선택적 일반 객체 추적
├─ raspberry_pi/              카메라 확인·영상 전송
└─ data/                      실행환경·캐시 등 내부 자원
```

## 현재 상태

- 기존 비교 실험은 20개 영상으로 수행했습니다. 별도로 AIR-400 번호 영상 295개와 AIR-125 공개 영상 120개에서 10FPS·30초 데이터 809개를 추출했습니다. [추출 결과](air400/06_단일클래스_학습데이터/추출결과.txt)에서 전체 파일과 수치 완전성 기준을 통과한 731개 후보 묶음을 확인합니다. AIR-125 S08의 5개 영상은 현재 비공개여서 제외했습니다.
- 사용자 결정에 따라 731개를 정상으로 가정하고 학습 584개·검증 147개로 나눠 오토인코더와 Deep SVDD를 학습했습니다. 같은 원본 주석 그룹은 분할 간에 섞이지 않습니다. 선택한 체크포인트의 정상 검증 정확도는 각각 96.60%(142/147), 95.24%(140/147)입니다. 이상 검출 성능을 측정한 정확도는 아닙니다. [학습 조건·결과](air400/07_이상탐지_모델비교/normal731_80_20_seed42_v1/실험결과.txt)와 [검증 그래프](air400/07_이상탐지_모델비교/normal731_80_20_seed42_v1/graphs/validation_curves_detail.png)를 확인합니다.
- 실제 영상에서 추출한 이미지 600장에 상체 Chest 참조 박스를 지정했습니다. AI 보조 시각 주석이며 독립 전문가 검수는 없습니다.
- 학습 420장(14클립), 검증 60장(2클립), 시험 120장(4클립)으로 원본 그룹을 분리했습니다. 시험 4클립은 보수적으로 묶은 원본 그룹 1개이므로 독립적인 영유아 4명으로 해석할 수 없습니다.
- 파인튜닝 전·수동 참조·파인튜닝 후 통제 실험은 `control_v1` 하위 폴더에 저장합니다. 실제 완료 상태는 `air400/project_status.json`과 결과 보고서에서 확인합니다.
- [Chest 파인튜닝 전후 결과 보고서](air400/04_PT자료/05_실험개요/index.html): 20클립의 A/B/C 파형 각 20개와 시험 4클립의 영상·그래프를 생성했습니다. 시험에서는 Chest가 모두 미검출됐고 파형 지표도 나빠져, 이번 가중치의 채택을 권하지 않습니다.
- PT 폴더의 `90_기존실험참고`는 이전 4모델 비교입니다. 수동 ROI는 파인튜닝 후 결과나 검수된 학습 정답이 아닙니다.
- 공통 `references`의 HDF5는 공개 호흡 주석입니다. DeepPhys 예측 파형은 단계별 `waveforms`에 저장합니다.
- `control_v1` HDF5의 `respiration`은 적분·추세 제거 후 **대역 필터 전** 신호이며, `respiration_filtered`에 공식 필터 적용값을 따로 보존합니다. 이전 파일럿 HDF5와 혼합하지 마세요.
- [Body·Chest 목표 비교](air400/04_PT자료/08_Body_Chest_목표비교/index.html): 원영상 4클립으로 영역과 전처리 순서를 분리한 2×2 비교, 2클립의 인위적 정지·픽셀 변화 감소 대조를 포함합니다. 총 32개 HDF5를 별도로 보존했습니다. 검증 영상 S02에서 부호만 고정한 추가 분석의 평가 3클립에서는 Body ROI가 호흡점 F1과 대응 시각 오차에서 유리했습니다. 실제 호흡 감소·정지 보존이나 Pi 30FPS 성능을 입증한 시험은 아닙니다.

## 실행 위치

현재 학습 모델 방향은 **파형+호흡 간격 특성을 입력하는 단일클래스 이상 탐지**입니다. 얼굴 검출 이력은 별도 경고 로직용으로 저장합니다.
수집 기준은 공식 Body 순서와 공개 DeepPhys 가중치이며, Chest 파인튜닝 가중치는 사용하지 않습니다.
[전체 클립 수집 설계](air400/06_단일클래스_학습데이터/수집설계.txt)와
[원격 클립 목록](air400/06_단일클래스_학습데이터/configs/source_inventory.json)을 준비했습니다.
이전 설계의 파형 2채널·전신 움직임 5채널은 초기 후보입니다. 현재 추출 기준은 [30초 데이터 설명](air400/06_단일클래스_학습데이터/데이터설명.txt)과 [실행 프로토콜](air400/06_단일클래스_학습데이터/configs/extraction_protocol_30s_v1.json)을 따릅니다.
결과 이름은 `air-400_S01_1_000-030.hdf5`처럼 데이터셋·대상·원본 번호·구간을 포함합니다. 원본 추출 파일의 라벨은 미검토 상태로 유지하며, 07번 실험에서만 사용자 결정에 따른 정상 가정으로 731개를 사용했습니다.

AIR-400 코드는 `pc/air400_*.py`에서 `air400/scripts/`로 이동했습니다.
공통 경로는 `air400/scripts/air400_paths.py`에서 관리합니다.
PowerShell에서 이 `AIOT_2026` 폴더를 기준으로 실행합니다.

```powershell
# 안내·현재 상태 갱신. 학습·영상 추론을 실행하지 않습니다.
& '.\data\air400_benchmark\env\Scripts\python.exe' '.\air400\scripts\refresh_project_index.py'

# 기존 비교 스크립트의 옵션 확인
& '.\data\air400_benchmark\env\Scripts\python.exe' '.\air400\scripts\air400_benchmark.py' --help

# 이미 생성된 통제 실험의 파형을 조건별로 재사용합니다. 기존 파일은 건너뜁니다.
& '.\data\air400_benchmark\env\Scripts\python.exe' '.\air400\scripts\chest_study_infer.py' --conditions A B C
```

통제 실험 순서는 `chest_study_prepare.py` → `chest_study_labels.py` → `chest_study_protocol.py` →
`chest_study_infer.py --conditions A B` → `chest_study_metrics.py --calibrate` →
`chest_study_train.py` → `chest_study_select.py` → `chest_study_infer.py --conditions C` →
`chest_study_report.py` → `refresh_project_index.py` → `chest_study_verify.py`입니다.
학습을 다시 시작하거나 라벨을 바꿀 때는 별도 실험 버전을 만들어 기존 결과와 구분해야 합니다.

가상환경과 네이티브 캐시는 Windows 실행 경로 호환성을 위해 `data/air400_benchmark/env`, `runtime`에 유지했습니다.
사용할 원본 자료·모델·파형·PT 자료는 `air400` 아래에서 확인합니다.

## 카메라 연결

- [라즈베리파이 촬영·전송](raspberry_pi/README.md)
- [PC 영상 수신](pc/README.md)

현재 카메라 코드는 촬영 확인·영상 전송용입니다. 최근 3분 보관 DB와 호흡 알림 서비스는 후속 구현 대상입니다.
이전 프로젝트 삭제 항목은 `air400/cleanup_manifest.json`에 기록합니다.
