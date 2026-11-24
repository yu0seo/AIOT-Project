# AIR 정상 호흡 이상 탐지 학습 데이터 구축

이 코드는 **기존 DeepPhys를 재학습하지 않고**, 사람이 승인한 정상 구간의 영상으로부터 이상 탐지 모델의 입력 `(N, 1, 300)`을 만드는 도구입니다. 기준 폴더는 `C:\Users\OHS\air-400`입니다. 기존 Conda 환경 `air400`, 원본 코드, 체크포인트와 Windows 수정사항을 유지합니다.

## 현재 준비된 것

- 공식 데이터 서버에서 전체 AIR-400 번호 영상 295개와 제공된 라벨 275개를 다운로드했습니다. S02의 `41.mp4`~`60.mp4` 20개에는 같은 이름의 라벨이 없어 제외합니다.
- AIR-125 공식 ZIP도 다운로드·해제했습니다. 로컬 영상은 99개, HDF5 라벨은 125개입니다. S06~S08의 나머지 26개 영상은 `data\AIR_125\s06-s07-s08-yt-links.xlsx`에 외부 링크와 구간 시간이 제공됩니다. 이 26개를 로컬 영상으로 확보했다고 간주하지 않습니다.
- 전체 다운로드 파일 571개, 합계 2,842,322,713바이트(약 2.84GB). 재다운로드용 ZIP도 보관했습니다. 원본 장시간 녹화·시각화 보조 파일은 학습용 번호 영상 배포에 포함하지 않았습니다.
- 로컬 영상 394개 검사 결과, 검토 대기 369개와 제외 25개입니다. 제외는 라벨 누락 20개와 9.997fps 영상 5개입니다. 정수 FPS로 몰래 반올림하지 않습니다.
- `normal_data\review\index.html`에 영상과 정답 파형을 확인할 화면을 만들었습니다. **승인된 정상 구간은 현재 0개입니다.**
- 실제 `DeepPhys_Deep_Body_best.pth`로 10fps 영상 30초 추론을 실행했습니다. 원시 출력 300개, 최종 입력 `(1,1,300)`을 확인했고, 파일에서 읽은 영상과 서비스용 RGB 버퍼 경로의 출력 차이는 0이었습니다.
- AIR-125의 FMP4 영상은 브라우저에서 지원하지 않아, 검토 화면에 H.264 MP4 또는 VP8 WebM 복사본을 연결합니다. AIR-400의 기존 H.264 영상은 그대로 재생합니다. 원본 영상과 라벨은 바꾸지 않습니다.

공식 배포 구조와 로컬 검사 결과가 다르면 `data\download_report.json`과 `normal_data\manifest.json`을 우선 확인하세요. 내려받은 파일을 정상 호흡이라고 자동 라벨링하지 않습니다.

## 1. 환경과 파일 위치

설치 위치:

```text
C:\Users\OHS\air-400\
  normal_pipeline\              이 코드 묶음
    pipeline.py
    inference_adapter.py
    download_data.py
    test_pipeline.py
  data\
    AIR_125\S01\001.mp4
    AIR_125\S01\001.hdf5
    AIR_400\S01\1.mp4
    AIR_400\S01\out\1.hdf5
    archives\AIR_125.zip
    download_report.json
  normal_data\
    manifest.json               실제 파일·키·해시·제외 이유
    approvals.json              사람이 명시적으로 승인한 구간
    review\index.html           수동 검토 시작 화면
```

PowerShell에서 다음과 같이 시작합니다. Conda 환경을 새로 만들거나 PyTorch를 재설치할 필요가 없습니다.

```powershell
Set-Location C:\Users\OHS\air-400
conda activate air400
python -c "import torch, numpy, scipy, h5py, cv2, matplotlib, yaml, certifi; print('OK')"
```

`h5py`처럼 빠진 패키지가 있을 때에만 해당 패키지를 설치하세요. 광학 흐름은 이미 설정된 `cv2.optflow.createOptFlow_DeepFlow()`를 사용합니다. `opencv-python`과 `opencv-contrib-python`을 함께 새로 설치하지 마세요.

## 2. 다운로드 또는 이어받기

현재 다운로드는 완료했습니다. 다른 PC에서 받거나 중단된 다운로드를 재시도하려면:

```powershell
python .\normal_pipeline\download_data.py --dest .\data
```

기존 완성 파일은 서버의 길이와 비교하고 로컬 SHA-256을 기록합니다. `.part` 파일은 서버가 Range를 확인해 줄 때 이어받습니다. HTTPS 인증서 검증은 유지하며 기존 환경의 `certifi` 인증서 묶음을 사용합니다. ZIP 해제 시 경로 이탈·심볼릭 링크를 거부하고 기존 파일은 CRC까지 비교합니다. 공식 서버가 체크섬을 제공하지 않으므로 SHA-256 기록은 이후 변경 감지용입니다.

AIR-125의 외부 영상 26개는 ZIP에 없습니다. 링크 영상은 원본 접근 가능 여부와 Excel의 자르기 구간을 확인해 정확히 대응시켜야 합니다. 현재 파이프라인은 이를 추측하여 연결하거나 다른 영상으로 대체하지 않습니다. 해당 영상을 추가한 뒤에는 새 검토 폴더로 다시 검사하세요.

## 3. 영상·정답 파형을 사람이 검토

이미 생성된 화면을 엽니다.

```powershell
Start-Process .\normal_data\review\index.html
```

각 영상을 재생하면서 해당 구간의 정답 파형, 큰 움직임·가림·카메라 움직임, 영상과 파형의 정렬을 확인하세요. 파형 주파수나 진폭만으로 정상이라고 승인하지 마세요. 주석은 정상/무호흡 진단 라벨이 아닙니다.

**화면의 두 그래프는 출처가 다릅니다.** 첫 번째는 사람이 표시한 호흡 시점에 가우시안을 적용한 HDF5 정답 주석이므로 일정 높이의 뾰족한 봉우리로 보입니다. 센서로 측정한 연속 호흡량이 아닙니다. 두 번째는 영상을 DeepPhys에 넣고 기존 누적합·추세 제거·필터 처리를 거쳐 얻는 추정 파형입니다. 이상 탐지 학습 배열에는 두 번째 종류를 사용합니다. 첫 그래프의 모양을 둘째처럼 보이게 가공해 대체하지 않습니다.

현재 `AIR_125_S01_001` 화면에는 동일 영상의 0~30초에 대한 실제 DeepPhys 추정 그래프도 표시합니다. 나머지 영상은 추론 결과를 만들기 전까지 ‘아직 이 영상의 추론 결과를 생성하지 않았습니다’라고 표시합니다. 두 그래프는 진폭 단위가 다르므로 진폭 크기를 직접 비교하지 마세요.

검토용 복사본은 원본 FPS와 프레임 수를 유지하며 최대 가로 1280픽셀, 음성 제외로 저장합니다. 실제 학습·추론은 변환 전 원본을 사용합니다. `scan`은 이제 이 검토용 영상을 자동 준비합니다. 기존 검토 화면만 고치려면 다음 명령을 실행하세요. 이미 만들어진 복사본은 재사용하고, manifest와 정상 구간 승인은 보존합니다.

```powershell
python .\normal_pipeline\review_media.py repair --workdir .\normal_data
```

다른 영상의 추정 파형도 검토 화면에 추가하려면 다음 예시의 `--clip`을 해당 영상 ID로 바꾸세요. 정상 승인과 별개인 추론 기능입니다.

```powershell
python .\normal_pipeline\review_media.py predict --workdir .\normal_data --clip AIR_125_S01_001 --start 0 --repo . --config .\configs\inference\deepphys_deep_infer.yaml --checkpoint .\checkpoints\DeepPhys_Deep_Body_best.pth
```

독립 실행형 FFmpeg가 `normal_pipeline\tools\ffmpeg.exe`에 있으면 빠른 H.264 변환을 사용합니다. 없으면 기존 OpenCV의 VP8 인코더를 사용하며 시간이 더 걸릴 수 있습니다. Conda 환경 재설치는 필요 없습니다.

실제 HDF5에는 `respiration`과 `filename`이 있고 AIR-125에는 `impulse`도 있습니다. 검사기는 파일마다 실제 데이터셋 이름·shape·dtype을 기록합니다. 정답 라벨에 시간축이 없으면 기존 `BaseDataset._resample_ppg`처럼 전체 영상 길이에 대응시킨 **검토용 시간축**을 사용합니다. 예를 들어 영상 60.9초와 라벨 600점이 항상 정확히 일치한다는 증거는 아닙니다. 정렬이 불확실하면 해당 구간을 승인하지 마세요.

새로 검사할 때에는:

```powershell
python .\normal_pipeline\pipeline.py scan --air125 .\data\AIR_125 --air400 .\data\AIR_400 --out .\normal_data_v2
```

확실한 초 단위 시간 키나 라벨 샘플링 주파수를 알고 있는 파일 집합이라면 `--time-key 키이름` 또는 `--label-fs 10`을 명시할 수 있습니다. 키 이름·단위·주파수를 추측하지 마세요. 서로 다른 시간축을 가진 집합은 별도 검사 설정이 필요합니다.

## 4. 확인한 정상 구간만 명시적으로 승인

아래는 **사용 문법 예시**입니다. `AIR_400_S01_1`의 0~60초를 실제로 정상·양호·정렬됨으로 검토한 경우에만 실행하세요. 지금 이 구간이 정상이라는 뜻은 아닙니다.

```powershell
python .\normal_pipeline\pipeline.py approve --workdir .\normal_data --clip AIR_400_S01_1 --normal 0 60 --reviewer "검토자이름" --video-reviewed --label-reviewed --alignment-confirmed --quality-acceptable --notes "검토 근거"
```

분리된 구간이라면 `--normal 0 30 --normal 35 65`처럼 반복합니다. 끝 시간은 실제 영상과 정답 라벨 범위 안에 있어야 합니다. 같은 클립을 재승인하면 그 클립의 구간 목록 전체가 새 목록으로 바뀝니다. 영상·파형·정렬·품질 확인 네 항목과 검토자 이름이 모두 필수입니다. 파일 내용이 바뀌면 이전 승인은 사용할 수 없습니다.

윈도우는 영상 시작 기준 `0, 5, 10, ...`초에서 시작하며 `[시작, 시작+30)` **전체가 한 승인 구간 안에** 있어야 합니다. 승인 구간을 이어 붙이지 않습니다. 30초 미만 영상·짧은 구간·불완전한 프레임은 늘리거나 0으로 채우지 않습니다. 60초 정상 구간은 최대 7개 윈도우가 됩니다.

## 5. 영아 단위 분할 고정

최소 3명의 서로 다른 영아에서 사용할 정상 구간을 승인한 다음:

```powershell
python .\normal_pipeline\pipeline.py split --workdir .\normal_data --seed 100
```

`AIR_125:S01`과 `AIR_400:S01`은 다른 영아입니다. 한 영아의 모든 영상과 겹치는 윈도우는 같은 split으로 갑니다. 약 70/15/15 비율을 영아 수로 반올림하며 각 split에 최소 1명을 배정합니다. 표본 수 비율이 정확히 70/15/15라는 뜻은 아닙니다. `splits.json`은 자동 덮어쓰지 않으며, 테스트 결과를 보고 다시 무작위 분할하면 안 됩니다.

같은 영상 바이트가 다른 영아 이름 아래 복사된 경우에도 검사/생성 단계에서 차단합니다. 원본 녹화를 임의로 다른 영아 ID로 이름 변경하지 마세요.

## 6. DeepPhys 추론 및 학습 배열 생성

체크포인트의 학습 영아를 알고 있다면 다음 형식의 JSON을 만들어 `--provenance`로 지정하세요.

```json
{
  "status": "known",
  "checkpoint_sha256": "실제 체크포인트의 SHA-256",
  "training_subjects": ["AIR_400:S01", "AIR_125:S02"],
  "evidence": "이 체크포인트를 학습한 설정/기록의 위치"
}
```

`training_subjects`는 전체 목록이어야 합니다. 해당 체크포인트가 val/test 영아로 학습되었다면 생성을 중단합니다. 공개 `best.pth`의 이름만으로 학습 영아를 알 수는 없습니다. 현재 로컬 체크포인트의 영아 학습 이력이 확인되지 않았으므로, **탐색용 데이터**를 만들 때에는 아래처럼 그 사실을 명시적으로 수용합니다.

```powershell
python .\normal_pipeline\pipeline.py build --repo . --config .\configs\inference\deepphys_deep_infer.yaml --checkpoint .\checkpoints\DeepPhys_Deep_Body_best.pth --workdir .\normal_data --dest .\normal_dataset_v1 --allow-unknown-extractor-training
```

학습 이력을 확인했다면 마지막 옵션 대신 `--provenance .\extractor_training.json`을 사용하세요. 알 수 없는 이력을 허용하면 보고서에 `heldout_extractor_subjects_verified: false`가 기록되며, 이 결과를 추론기까지 영아 누수가 없는 독립 성능 평가라고 부를 수 없습니다. 깨끗한 평가에는 held-out 영아를 보지 않은 별도 체크포인트/분할이 필요할 수 있습니다.

생성 결과:

| 파일 | 내용 |
|---|---|
| `X_train.npy`, `X_val.npy`, `X_test.npy` | 공통 정규화를 적용한 float32 `(N,1,300)` |
| `X_*_unscaled.npy` | 공통 정규화 전의 **후처리된** 파형 |
| `normalization.json` | train 윈도우에서만 계산한 공통 평균·표준편차 |
| `windows.json` | 배열 행 ↔ 영아·영상·시작/끝 초·split·해시·RMS/PTP 대응 |
| `extractor.json` | 실제 설정, 원본 코드·체크포인트·검출기 해시와 실행 환경 |
| `approvals.json`, `manifest.json`, `splits.json` | 재현 가능한 검토·원본·분할 기록 |
| `build_report.json` | 생성 수, 제외 이유, 추론기 학습 이력 확인 상태 |

각 30초 추론 HDF5는 `normal_data\cache\설정서명\`에 저장되며 `raw_model`, `respiration`, `time_sec`, `x_10hz`를 포함합니다. `raw_model`은 누적합·detrend·bandpass 전 모델 출력이며, `X_*_unscaled`와 다릅니다. 모델 출력은 설정에 따라 파형의 시간 차분일 수 있습니다. 실패 후 재실행하면 같은 원본·설정의 추론 캐시를 재사용합니다. 완성 데이터 폴더는 덮어쓰지 않으므로 새 `--dest`를 사용하세요.

## 7. 실제 서비스와 같은 경로 사용

단일 영상의 30초 구간을 시험하려면:

```powershell
python .\normal_pipeline\pipeline.py predict --repo . --config .\configs\inference\deepphys_deep_infer.yaml --checkpoint .\checkpoints\DeepPhys_Deep_Body_best.pth --video .\data\AIR_400\S01\1.mp4 --start 0 --out .\prediction_example
```

학습 데이터 생성 후에는 `--scaler .\normal_dataset_v1\normalization.json`을 추가해 정규화한 입력까지 만듭니다. 체크포인트/설정/소스가 다르면 다른 정규화 파일의 사용을 거부합니다.

라즈베리파이 영상 수신 프로그램에서는 아래 공통 API를 호출하세요. 모듈 검색 경로에 `normal_pipeline`을 추가해야 합니다.

```python
import json
import sys
sys.path.insert(0, r"C:\Users\OHS\air-400\normal_pipeline")
from inference_adapter import AirExtractor

extractor = AirExtractor(
    r"C:\Users\OHS\air-400",
    r"C:\Users\OHS\air-400\configs\inference\deepphys_deep_infer.yaml",
    r"C:\Users\OHS\air-400\checkpoints\DeepPhys_Deep_Body_best.pth",
)
with open(r"C:\Users\OHS\air-400\normal_dataset_v1\normalization.json", encoding="utf-8") as f:
    scaler = json.load(f)

# frames_rgb: 실제 최근 30초 RGB uint8 (T,H,W,3), 예: 10fps면 300장
# timestamps: 각 프레임의 실제 수집 시간(초), 누락 검사용
# fs: 정수 프레임 주파수. OpenCV BGR 입력은 RGB로 바꿔야 함.
x, diagnostics = extractor.model_input(frames_rgb, fs, scaler, timestamps)
# x.shape == (1,1,300). 여기서 별도 이상 탐지 모델에 전달.
```

수신기는 30초 버퍼를 5초 간격으로 갱신해야 합니다. 프레임 누락·시간 불규칙은 예외로 보고되므로 `판단 불가`로 처리해야 하며, 실제 ROI 검출 상태·가림·큰 움직임도 서비스 측에서 확인해야 합니다. 이 도구가 그 품질 판정기나 의료 경보 시스템까지 구현한 것은 아닙니다. DeepFlow 계산이 5초보다 오래 걸릴 수 있어 갱신 주기와 실측 처리 속도는 별도 확인이 필요합니다.

중요한 일치 조건:

- 매 30초 버퍼마다 원본 `PreProcessor`의 ROI/DeepFlow/정규화, `InferenceDataset.__getitem__`, `infer.run_inference`, `PostProcessor`를 재사용합니다. 전체 60초 파형을 먼저 추론한 뒤 자르는 방식은 사용하지 않습니다.
- 기존 설정의 `CHUNK_LENGTH=180`은 10fps 30초(300장)를 180장으로 줄입니다. **복사한 실행 설정에서만** `CHUNK_LENGTH=FRAME_DEPTH=10`, `DO_CHUNK=True`로 변경합니다. 파일은 수정하지 않습니다. 변경 내용은 `extractor.json`에 기록됩니다. 15fps 30초(450장)도 온전히 처리합니다.
- 원본의 `DO_CHUNK=False` 설정을 사용하는 기존 서비스에 이 데이터만 연결하면 다른 경로가 될 수 있습니다. 학습/서비스 양쪽에서 이 adapter를 사용하세요.
- 기존 0.3~1.0Hz bandpass와 detrend를 그대로 재사용해 분포를 맞춥니다. 이 필터는 대역 밖 이상 정보를 줄일 수 있습니다. 필터를 바꾸려면 데이터와 정규화 계수를 다시 생성하고 서비스 경로도 함께 바꿔야 합니다.
- 창마다 파형 Z-score를 추가하지 않습니다. 다만 기존 영상·flow 표준화 자체는 유지하므로 출력 진폭이 절대 호흡량을 나타내지는 않습니다.
- 동일 시점까지 수집한 30초 버퍼 내부에서만 양방향 필터와 리샘플링을 적용합니다. 30초 끝 이후의 영상을 참조하지 않습니다.
- `num_workers=0`, `torch.load(..., map_location='cpu', weights_only=True)`, 단일 GPU 노출을 사용합니다. 기존 Windows 로그 파일명과 `pyflow` 관련 수정도 보존합니다.

## 8. 학습에 연결 및 검증

```python
import numpy as np
import torch

x_train = np.load(r"C:\Users\OHS\air-400\normal_dataset_v1\X_train.npy", allow_pickle=False)
train_tensor = torch.from_numpy(x_train)  # (N,1,300)
# Autoencoder의 입력과 복원 목표가 모두 train_tensor입니다.
```

이 요청의 산출물은 데이터 구축 파이프라인입니다. 이상 탐지 모델 훈련, 임계값 선택, 비정상 호흡에 대한 성능 검증은 별도 단계입니다. 정상 데이터만으로 민감도나 실제 이상 탐지 성능을 입증할 수 없습니다.

검증 명령:

```powershell
python -m unittest discover -s .\normal_pipeline -v
```

`verification_real.json`에 실제 체크포인트 추론 결과, 파일/버퍼 경로 비교, 짧은 버퍼와 프레임 시간 간격 오류 거부 결과가 있습니다. 정상 구간 승인을 만들어 넣지 않고 추론 기능만 검증했습니다. 출처는 `SOURCES.md`를 참고하세요.
