# 영상을 넣어 30초 호흡 파형과 BPM 자동 추출

기존 Windows AIR-400 코드와 `DeepPhys_Deep_Body_best.pth`를 사용합니다. DeepPhys를 재학습하지 않고 **영상 → 30초 독립 추론 → 10Hz 파형 300점 + 추정 BPM**을 자동 저장합니다. 정답 HDF5, HTML 검토, 정상 구간 승인은 실행에 필요하지 않습니다.

## 바로 실행

기본 AIR 폴더에 설치한 복사본은 현재 PowerShell 폴더와 관계없이 다음 한 줄로 실행합니다.

```powershell
& C:\Users\OHS\miniconda3\envs\air400\python.exe -X utf8 C:\Users\OHS\air-400\extract_training_waveforms.py
```

기존 `air400` 환경의 Python을 직접 실행하므로 Conda 활성화나 환경 재설치가 필요 없습니다. 아래는 이 프로젝트 폴더를 기준으로 한 PowerShell 명령입니다.

```powershell
Set-Location C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026
& C:\Users\OHS\miniconda3\envs\air400\python.exe -X utf8 .\pc\extract_respiration.py
```

아무 옵션 없이 실행하면 다음 경로를 사용합니다.

- 입력: `C:\Users\OHS\air-400\data`의 하위 폴더 전체
- 모델 설정: `C:\Users\OHS\air-400\configs\inference\deepphys_deep_infer.yaml`
- 체크포인트: `C:\Users\OHS\air-400\checkpoints\DeepPhys_Deep_Body_best.pth`
- 기존 공통 추론 코드: `C:\Users\OHS\air-400\normal_pipeline\inference_adapter.py`
- 결과: `C:\Users\OHS\air-400\output\training_30s`

기본 간격은 30초입니다. 예를 들어 60초 영상은 `0~30`, `30~60` 두 구간이 됩니다. 남은 30초 미만의 꼬리와 30초 미만 영상은 채우거나 늘리지 않습니다. 원본 영상·라벨·기존 승인 파일은 수정하지 않습니다.

## 저장 파일

```text
training_30s/
  X.npy                     (N, 1, 300) float32, 10Hz 추정 파형
  bpm.npy                   (N,) float32, 같은 행 순서의 추정 BPM
  metadata.csv              행 번호, 영아 ID, 원본 영상, 시작/끝 초, BPM
  errors.csv                제외/실패한 영상·구간과 이유
  summary.json              완료 수와 기존 결과 재사용 수
  run.json                  실제 모델·설정·소스 해시 기록
  windows/
    AIR_400_S01_1/
      000000.npz            0~30초 결과 및 원시 모델 출력
      000000.png            해당 구간의 DeepPhys 추정 파형 그래프
      000030.npz            30~60초 결과
      000030.png
```

`metadata.csv`의 `sample_index=0`은 `X[0]`, `bpm[0]`과 같습니다. AIR-125와 AIR-400의 동명 영아는 `AIR_125:S01`, `AIR_400:S01`로 구분합니다. 일반 영상의 영아 ID는 빈칸으로 둡니다. 같은 파일명도 폴더가 다르면 구분합니다.

개별 NPZ에는 다음이 들어 있습니다. `np.load(파일, allow_pickle=False)`로 읽습니다.

| 키 | 내용 |
|---|---|
| `x_10hz` | 추가 Z-score 정규화 없이 저장한 후처리 파형 300점 |
| `pred_rr_bpm` | 기존 AIR 후처리기로 계산한 해당 30초의 추정 BPM |
| `raw_model` | 누적합·detrend·bandpass 전 모델 출력; 원본 FPS에 따른 길이 |
| `respiration`, `time_sec`, `fs` | 원본 FPS에서 후처리한 파형, 구간 내 상대 시간, 샘플링 주파수 |
| `metadata_json` | 원본 영상/구간/모델 실행을 식별하는 기록 |

## 자주 쓰는 옵션

먼저 대상 수만 확인하기:

```powershell
& C:\Users\OHS\miniconda3\envs\air400\python.exe -X utf8 .\pc\extract_respiration.py --dry-run
```

영상 한 편만 처리하기:

```powershell
& C:\Users\OHS\miniconda3\envs\air400\python.exe -X utf8 .\pc\extract_respiration.py --input C:\Users\OHS\air-400\data\AIR_400\S01\1.mp4 --output .\outputs\one_video
```

폴더를 지정하고 5초 간격으로 겹쳐 추출하기(60초 영상당 최대 7구간):

```powershell
& C:\Users\OHS\miniconda3\envs\air400\python.exe -X utf8 .\pc\extract_respiration.py --input C:\Users\OHS\air-400\data --stride 5 --output C:\Users\OHS\air-400\output\training_30s_stride5
```

첫 구간 하나만 시험하려면 `--limit-windows 1`, 그래프가 필요 없으면 `--no-plots`를 추가합니다. `--air-repo`, `--config`, `--checkpoint`로 경로를 바꿀 수 있습니다. 기존 `normal_pipeline` 공통 추론 코드가 필요합니다.

## 중단 후 이어서 실행

`Ctrl+C`로 중단한 뒤 **같은 명령**으로 재실행하면 완료된 NPZ를 재사용합니다. 파형 배열과 CSV는 현재 실행 대상의 성공한 구간만 모아 다시 저장합니다. 완성 NPZ가 생긴 뒤 중단되었다면, 아직 전체 `X.npy`에 합쳐지지 않았더라도 재실행 시 포함됩니다. 같은 출력 폴더에 명령을 동시에 두 개 실행하지 마세요.

입력 경로·모델·코드·추론 설정을 바꾸었거나 원본 영상/완료 파일이 달라졌으면 혼합 저장을 거부합니다. 이 경우 새 `--output` 폴더를 사용하세요. 실패 구간은 정상 데이터처럼 0으로 채우지 않고 `errors.csv`에 기록합니다. 제외/실패가 있으면 종료 코드는 2이며 성공한 구간의 배열은 저장됩니다. `--limit-windows`는 기존 완료 구간을 포함해 처음 N개 구간만 선택합니다.

## 학습에서 읽기

```python
import numpy as np
import torch

root = r"C:\Users\OHS\air-400\output\training_30s"
x = np.load(root + r"\X.npy", allow_pickle=False)       # (N,1,300)
bpm = np.load(root + r"\bpm.npy", allow_pickle=False)   # (N,)
tensor = torch.from_numpy(x)
```

이 결과는 **DeepPhys의 추정값**입니다. BPM은 정답 라벨이 아니며, 정상/비정상 여부는 자동 지정하지 않습니다(`label_status=unreviewed`). 정상 데이터만 학습할 때는 필요한 정상 구간을 골라 사용하고, 학습/검증/테스트 분할은 `subject_id` 기준으로 하세요. 영아 ID가 빈 일반 영상은 먼저 같은 영아의 영상들을 묶어야 합니다. 추가 정규화 계수는 train에서만 계산하세요.

각 30초 영상에 기존 공통 adapter를 독립 적용하므로, 전체 영상을 먼저 필터링한 뒤 30초로 자르지 않습니다. ROI·DeepFlow·누적합·detrend·영아 0.3~1.0Hz bandpass·BPM 계산을 재사용합니다. 이 기존 필터의 BPM 검색 범위는 18~60이며, 그 밖의 호흡 이상을 이 값만으로 판단할 수 없습니다. Windows의 `num_workers=0`, 안전한 체크포인트 로딩도 유지합니다.

## 확인한 결과

2026-11-21 기준 로컬 데이터의 실행 계획은 **영상 389개, 겹치지 않는 30초 구간 773개**입니다. 9.997fps 영상 5개는 기존 adapter의 정수 FPS 조건에 맞지 않아 제외 기록을 남깁니다. 정답 라벨이 없는 AIR-400 S02 영상도 영상이 유효하면 추출합니다.

실제 AIR-400 S01/1.mp4에서 30초 파형 두 개와 BPM 21.09375/22.265625를 생성했습니다. 재실행은 완료된 결과를 재사용하며, 정상 호흡 판정은 하지 않습니다. 전체 데이터의 모델 추론은 위 실행 명령으로 시작합니다.

자동 테스트:

```powershell
& .\.venv-idd\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_respiration_extraction.py -v
```

단위 테스트는 모델/영상 디코더 경계를 대체하고 파일 탐색·시간 경계·배열 저장·재사용·실패 제외·다른 구간의 캐시 혼용 차단을 검사합니다. 실제 영상/체크포인트 실행 결과는 `outputs\deepphys_smoke_final`에 별도 보관합니다.
