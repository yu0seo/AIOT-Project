# AIR-400 베이비캠 — 팀 개발 환경 설정 및 실행 가이드

기준일: 2026-11-24 · 대상: Windows / PowerShell / Python 3.12

이 문서는 GitHub에서 코드를 받은 팀원이 프로젝트를 설정하고, 담당 개발자가 공유 전에 준비해야 할 항목을 확인하기 위한 안내입니다. 모든 명령은 **팀 저장소의 루트 폴더**에서 실행합니다. 아래 저장소 주소와 경로 예시는 각자의 실제 값으로 바꿉니다.

## 1. 프로젝트가 하는 일과 현재 상태

```text
라즈베리파이 → Supabase Storage의 TS 영상
                         ↓
storage_inference.py: 연속 TS 15개 → 30초 MP4 → 기존 DeepPhys/v2 → Supabase 결과 테이블
                                                                      ↓
serve_results.py: 결과 주기적 조회 → 로컬 API → 브라우저 파형·BPM·분석 상태
```

| 구분 | 현재 상태 |
|---|---|
| 지속 영상 수집·분석 | 구현됨. 기존 DeepPhys, ROI, v2 모델을 재사용 |
| 결과 저장 | Supabase Data API와 신규 결과 테이블용 SQL 구현 |
| 기본 프론트 | 구현됨. 최신 파형·BPM·상태 및 최근 30개 결과 표시 |
| 자동 테스트 | 기존 개발 PC에서 24개 통과 |
| 실제 모델 연결 | 로컬 영상의 서로 다른 연속 TS 15개와 모의 Supabase로 단일 배치 검증 |
| 실제 운영 Supabase/Pi 연결 | 프로젝트 키·SQL·실제 TS를 준비한 뒤 확인 필요 |
| 새 PC 설치 | 아래 설치 절차는 준비안. 깨끗한 새 환경에서의 재현 검증과 의존성 잠금 파일은 아직 필요 |
| 실시간 처리 속도 | 기존 PC에서 30초 입력 처리 약 85초. 모든 구간을 처리하면 지연 누적 가능 |
| 무호흡 판정 | 전용 무호흡 검증 완료 모델이 아님. 일반 이상 후보를 검토하기 위한 시스템 |

`below_threshold`를 임상적 정상, `unscored`를 안전 상태로 해석하지 않습니다. 기존 모델은 불필요하게 재학습하지 않습니다.

## 2. 저장소 관리자가 공유 전에 준비할 것

### 2.1 팀 저장소와 코드

현재 원본 개발 폴더의 `origin`은 AIR-400 원본 저장소 `michaelwwan/air-400`입니다. **팀이 관리할 fork 또는 별도 저장소 주소를 먼저 정해야 합니다.** 기존 Windows 수정과 새 서비스는 원본 저장소를 clone하는 것만으로 받을 수 없습니다.

공유할 코드에 아래 파일이 포함되어 있는지 확인합니다.

```text
<project-root>/
├── storage_inference.py
├── serve_results.py
├── babycam/
│   ├── __init__.py
│   ├── common.py
│   ├── worker.py
│   ├── web.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── babycam_tests/
├── models/
│   ├── air400_detect_v2.py
│   ├── air400_npz_anomaly_v2.py
│   └── deep_phys.py
├── processors/
│   ├── pre_processor.py
│   └── post_processor.py
├── configs/inference/deepphys_deep_infer.yaml
├── .env.example
├── .gitignore
├── supabase_setup.sql
├── TEAM_SETUP.md
├── BABYCAM_SERVICES.md
└── LICENSE
```

위 목록은 핵심 파일 안내입니다. **AIR-400 원본 코드 전체를 포함한 팀 저장소**를 기준으로 하며, 두 실행 파일만 복사해서 실행하는 구조가 아닙니다. 기존 자동 파형 추출도 공유한다면 `extract_training_waveforms.py`, `normal_pipeline/`, `EXTRACT_TRAINING_WAVEFORMS.md`도 함께 포함합니다.

기존 Windows 변경 사항을 보존합니다.

- `infer.py`: Windows에서 안전한 날짜 파일명, CPU map_location, weights_only, num_workers=0, 원시 출력 저장.
- `models/deep_phys.py`: flatten 단계의 reshape.
- `processors/pre_processor.py`: DeepFlow 경로에서 불필요한 무조건 pyflow import 제거 상태.
- 실제 추론에 사용한 YAML과 모델 버전을 함께 보관.

공유 전 Git 상태를 확인하고 **공유할 파일을 지정해서** 스테이징합니다. 현재 폴더에는 영상·데이터·개인 실행 결과 등도 있으므로 전체 폴더를 무조건 추가하지 않습니다.

```powershell
git remote -v
git status --short
git check-ignore .env .env.example
```

`.env`는 제외되고 `.env.example`은 추적 가능해야 합니다. 관리자는 코드와 문서를 선택해 `git add`한 뒤 아래 명령으로 내용을 검토합니다.

```powershell
git diff --cached --stat
git diff --cached
```

원본 `LICENSE`와 출처 표기를 유지합니다. `.env`, API 키, 실제 영아 영상, 실행 중인 state/outbox, 개인 로그를 공유 코드에 넣지 않습니다. `AGENTS.md`와 과거 인수인계 문서는 특정 PC 경로를 포함하므로 공개 범위에 맞게 검토합니다.

### 2.2 가중치는 별도 준비

다음 네 파일은 현재 `.gitignore`의 `*.pt`, `checkpoints/`, `output/` 규칙 등에 의해 제외됩니다. **GitHub에 코드만 올리면 이 가중치들은 전달되지 않습니다.** 관리자는 GitHub Release 또는 팀의 승인된 파일 공유 위치에 버전과 다운로드 위치를 정리해야 합니다. 파일의 공유 조건은 각 제공처 기준으로 확인합니다. GitHub는 큰 바이너리를 Release나 Git LFS로 관리하는 방법을 안내합니다. [GitHub 공식 안내](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

| 각 팀원의 로컬 배치 경로 | 용도 | 확보 방법 |
|---|---|---|
| `checkpoints/DeepPhys_Deep_Body_best.pth` | 사전학습 호흡 추출 모델 | [AIR-400 공식 체크포인트](https://coe.northeastern.edu/Research/AClab/AIR-400/Model%20Checkpoints/) 또는 관리자가 제공한 동일 파일 |
| `detectors/yolov8m.pt` | 몸통 ROI 검출 | [AIR-400 공식 ROI 가중치](https://coe.northeastern.edu/Research/AClab/AIR-400/ROI%20Detectors/) |
| `detectors/yolov8n-face.pt` | 얼굴 ROI 검출 | 위 ROI 가중치 위치 |
| `output/ae_results_v2/air400_ae.pt` | 프로젝트에서 학습한 v2 이상 탐지 모델 | **프로젝트 관리자가 제공**. 공식 AIR-400 다운로드에 포함된다고 가정하면 안 됨 |

공유할 현재 파일의 SHA-256은 아래와 같습니다. 관리자가 모델을 교체하면 이 표와 실험 정보를 함께 갱신합니다.

```text
DeepPhys_Deep_Body_best.pth
66e21247cce4f71056e500b9d67b1f1053f8df3c351abf75823f31d9294da4f8

yolov8m.pt
5d4a90cdc7a21786cc59cd19778e9eafff836df9e2da32524737c7ee6efe4fe5

yolov8n-face.pt
d545bf1add5aa736a4febac4f4f9245a6d596cd0fe70d5d57989fe0cb9e626ca

ae_results_v2/air400_ae.pt
75a4f141df82f515e57cfaf1f98fb7be462dd1e57b2fae4a9196266cbdc3bc79
```

예시 확인 명령:

```powershell
Get-FileHash .\checkpoints\DeepPhys_Deep_Body_best.pth -Algorithm SHA256
Get-FileHash .\output\ae_results_v2\air400_ae.pt -Algorithm SHA256
```

`air400_ae.pt`는 v1도 같은 파일명을 사용합니다. 파일명만 보지 말고 v2 파일을 받아야 합니다. 서비스를 실행하는 데 AIR-400 학습 영상 전체를 다시 다운로드할 필요는 없습니다.

## 3. 팀원의 초기 설정

### 3.1 코드 받기

관리자가 정한 **팀 저장소 주소**로 바꿔 실행합니다.

```powershell
git clone 'https://github.com/TEAM/REPOSITORY.git' babycam
Set-Location .\babycam
$projectRoot = (Get-Location).Path
```

이후 새 PowerShell 창에서도 이 폴더로 이동한 뒤 실행합니다. 다른 개발자의 `C:\Users\OHS\...` 경로를 그대로 사용하지 않습니다.

### 3.2 Python 환경

**이미 검증된 `air400` 환경이 있으면 재사용**합니다. 현재 코드의 `hashlib.file_digest` 때문에 수집기는 Python 3.11 이상이 필요하며, 기존 전체 검증은 Python 3.12.16에서 했습니다. 원본 `environment.yml`은 Python 3.9 기반이므로 이번 서비스용 설치 명령으로 그대로 사용하지 않습니다.

새 PC에서는 Miniconda/Anaconda를 준비하고, Conda 사용이 가능한 터미널에서 새 환경을 만듭니다.

```powershell
conda create -n air400 python=3.12 -y
conda activate air400
python -c "import sys; print(sys.executable); print(sys.version)"
```

아래는 기존 동작 환경을 참고한 **새 환경 설치 준비안**입니다. 현재 문서 작성 과정에서 새 PC/새 환경 설치를 실제 완료한 것은 아닙니다. 관리자가 검증된 환경 파일을 배포했다면 그 파일을 우선합니다.

NVIDIA GPU 환경의 PyTorch:

```powershell
python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu126
```

NVIDIA GPU가 없는 개발 PC에서는 위 명령 대신 CPU 빌드를 선택할 수 있습니다. 전체 영상 추론 속도는 별도로 측정해야 합니다.

```powershell
python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
```

위 설치 조합은 [PyTorch 공식 이전 버전 안내](https://pytorch.org/get-started/previous-versions/)를 참고했습니다. GPU 사용 시 해당 빌드를 지원하는 NVIDIA 드라이버를 준비합니다.

기본 모델·신호 처리 패키지:

```powershell
python -m pip install numpy==2.1.1 scipy==1.18.1 matplotlib==3.11.2 PyYAML==6.0.3 h5py==3.16.0
python -m pip install pillow==13.0.0 requests==2.34.2 tqdm==4.70.1 psutil==7.2.2 py-cpuinfo==9.0.0 pandas==3.1.1 seaborn==0.13.2 ultralytics-thop==2.2.5
python -m pip install opencv-contrib-python==4.11.0.86
python -m pip install ultralytics==8.3.96 --no-deps
```

**OpenCV 의존성에 남은 과제:** DeepFlow에는 contrib 모듈이 필요합니다. OpenCV의 네 배포 패키지는 같은 `cv2` 파일을 사용하므로 여러 종류를 동시에 설치하지 않는 것이 공식 안내입니다. 위 준비안은 Ultralytics의 자동 의존성 설치가 일반 `opencv-python`을 추가하는 것을 피하고, 필요한 의존성을 직접 설치합니다. 다만 Ultralytics 8.3.96의 배포 메타데이터는 `opencv-python`을 요구하므로 `pip check`가 누락을 보고할 수 있습니다. 이는 런타임 DeepFlow 검사와 별개의 **미해결 패키징 문제**입니다. 관리자는 새 환경 설치·추론을 검증하고 이 불일치를 해결하거나 명시한 배포 환경과 잠금 파일을 제공해야 합니다. 이 준비안을 검증 완료된 lock 파일로 취급하지 않습니다. [OpenCV 공식 패키지 안내](https://pypi.org/project/opencv-contrib-python/)

```powershell
python -m pip check
python -c "import torch, cv2; print('torch:', torch.__version__); print('CUDA:', torch.cuda.is_available()); print('OpenCV:', cv2.__version__); ok=hasattr(getattr(cv2,'optflow',None),'createOptFlow_DeepFlow'); print('DeepFlow:',ok); assert ok, 'OpenCV contrib/DeepFlow가 필요합니다'"
```

기존 환경에 여러 OpenCV 패키지가 섞여 있다면, 이미 작동하는 환경을 임의로 지우기 전에 관리자가 환경을 복제하고 원인을 확인합니다. 위 패키지 목록은 지속 추론 경로를 위한 것이며 원본 학습·노트북의 전체 의존성 목록은 아닙니다.

### 3.3 FFmpeg와 가중치 준비

[FFmpeg 공식 다운로드 안내](https://ffmpeg.org/download.html)에 따라 Windows용 FFmpeg/ffprobe를 준비합니다. 두 실행 파일이 포함된 `bin` 폴더를 PATH에 추가한 뒤 새 터미널을 엽니다.

```powershell
ffmpeg -version
ffprobe -version
```

PATH를 바꾸기 어렵다면 이후 `.env`의 `FFMPEG`, `FFPROBE`에 각 exe의 전체 경로를 지정합니다. FFmpeg는 Python 패키지 설치만으로 대체되는 것으로 가정하지 않습니다.

2.2절의 네 가중치를 받아 지정된 경로에 놓습니다. 배치 결과는 다음과 같아야 합니다.

```text
<project-root>/checkpoints/DeepPhys_Deep_Body_best.pth
<project-root>/detectors/yolov8m.pt
<project-root>/detectors/yolov8n-face.pt
<project-root>/output/ae_results_v2/air400_ae.pt
```

### 3.4 `.env` 만들기

기존 파일을 덮어쓰지 않도록 처음 한 번만 복사합니다.

```powershell
if (-not (Test-Path -LiteralPath '.\.env')) {
    Copy-Item -LiteralPath '.\.env.example' -Destination '.\.env'
}
notepad .\.env
```

| 변수 | 설정할 내용 | 담당 |
|---|---|---|
| `SUPABASE_URL` | 대상 프로젝트 URL | Supabase 관리자 제공 |
| `SUPABASE_SECRET_KEY` | 서버용 Secret key 또는 legacy service_role 키 | 권한 있는 서버 담당자에게만 전달 |
| `STORAGE_BUCKET` | 실제 영상 버킷 이름 | Pi/Supabase 담당자와 일치시킴 |
| `STORAGE_PREFIX` | 한 촬영 세션의 실제 TS 경로 | Pi 업로드 경로와 일치시킴 |
| `STREAM_ID` | 결과를 구분할 세션 이름 | 수집기와 결과 서버에서 동일하게 사용 |
| `START_SEQ` | `auto` 또는 최초 시작 번호 | 운영 담당자 결정 |
| `AIR400_ROOT` | **자기 PC의 이 저장소 전체 경로** | 각 팀원 |
| `WORK_DIR` | `output/stream_batches` 등 자기 PC 작업 폴더 | 수집기 담당자 |
| `FFMPEG`, `FFPROBE` | PATH 명령 또는 exe 전체 경로 | 각 팀원 |
| `POLL_SECONDS` | 수집 조회 주기, 기본 2초 | 운영 담당자 |
| `RESULT_POLL_SECONDS` | DB 결과 조회 주기, 기본 2초 | 결과 서버 담당자 |
| `SERVER_PORT` | 화면 포트, 기본 8765 | 결과 서버 담당자 |

개별 값의 예시이며 실제 프로젝트 값으로 변경합니다.

```dotenv
SUPABASE_URL=https://PROJECT_REF.supabase.co
SUPABASE_SECRET_KEY=서버담당자가전달한키
STORAGE_BUCKET=breathing-video
STORAGE_PREFIX=pi-camera/your-session-id
STREAM_ID=babycam-session-1
START_SEQ=auto
AIR400_ROOT=C:/work/babycam
WORK_DIR=output/stream_batches
FFMPEG=ffmpeg
FFPROBE=ffprobe
POLL_SECONDS=2
RESULT_POLL_SECONDS=2
SERVER_PORT=8765
```

- Secret key는 Supabase 대시보드의 API Keys에서 확인합니다. `sb_secret_...` 또는 legacy `service_role`을 사용하며, `anon`/publishable 키·DB 비밀번호·Personal Access Token을 이 칸에 넣지 않습니다. [공식 키 안내](https://supabase.com/docs/guides/getting-started/api-keys)
- 브라우저 프론트에는 서버 키를 넣지 않습니다. 화면은 Python API를 사용합니다.
- `.env` 안의 `$projectRoot` 같은 셸 변수는 자동 치환되지 않습니다. 실제 경로를 적습니다. 같은 행 뒤에 주석도 붙이지 않습니다.
- 셸 환경 변수가 있으면 `.env` 값보다 우선합니다. 파일을 바꿨는데 값이 그대로면 환경 변수도 확인합니다.
- `START_SEQ=auto`는 첫 실행 때 가장 오래된 TS부터 시작합니다. 밀린 영상이 많다면 번호와 세션을 확인하여 최초 시작 번호를 정합니다.
- `.env`에 들어 있는 예전 개발 PC 경로와 Storage prefix를 새 PC의 실제 값으로 반드시 바꿉니다.

### 3.5 Supabase 관리자의 DB 준비

프로젝트 관리자 한 명이 대상 프로젝트의 **SQL Editor**에서 [supabase_setup.sql](supabase_setup.sql)을 한 번 실행합니다.

- 새 테이블: `public.babycam_analysis_results`.
- RLS를 켜고 `anon`/`authenticated`의 직접 접근을 허용하지 않습니다.
- 서버용 키가 사용하는 `service_role`에 조회·삽입 권한을 줍니다.
- 동일 이름의 테이블이 있으면 SQL은 중단됩니다. 테이블을 지우고 다시 만드는 대신 관리자가 기존 스키마를 대조합니다.
- 기존 Storage 버킷이나 Pi 업로드 권한을 만드는 SQL은 아닙니다. 영상 버킷과 업로드 설정은 별도로 준비되어 있어야 합니다.

팀원 전원이 SQL을 반복 실행할 필요는 없습니다. 관리자는 실제 대상 프로젝트와 Data API 노출/권한까지 확인합니다.

## 4. 실행 순서

### 4.1 테스트 → 접근 확인 → 한 배치 확인

Conda 환경을 활성화하고 저장소 루트에서 실행합니다.

```powershell
conda activate air400
python -B -X utf8 -m unittest discover -s .\babycam_tests -v
python -X utf8 .\storage_inference.py --check
python -X utf8 .\storage_inference.py --once
```

`--check`는 설정·모델 파일 해시 계산·실행 파일 경로·Storage 목록·결과 테이블 접근을 확인합니다. **모델을 실제 로드하거나 추론까지 하는 검사는 아닙니다.** 신규 환경은 `--once`까지 확인해야 합니다.

`--once`의 종료 코드:

| 코드 | 의미 |
|---|---|
| 0 | 배치 한 개의 결과를 DB에 저장. `unscored`도 저장 성공일 수 있으므로 상태/이유 확인 필요 |
| 2 | 연속 TS 부족, 처리 재시도 대기, 실행 루프 중 원격 오류 등으로 아직 저장하지 못함 |
| 1 | 설정·파일·모델 로드 등 시작/실행 오류. 시작 단계 원격 접근 오류도 여기에 해당 가능 |

실제 서로 다른 TS 15개가 수집되고, 새 DB 행에 올바른 번호·상태·파형이 있는지 확인합니다. 같은 TS를 반복 연결해서 성공한 것을 운영 영상 검증으로 간주하지 않습니다.

### 4.2 지속 실행: 터미널 두 개

첫 번째 PowerShell 창에서 수집기를 실행합니다.

```powershell
Set-Location 'C:\work\babycam'
conda activate air400
python -X utf8 .\storage_inference.py
```

두 번째 PowerShell 창에서 결과 서버를 실행합니다.

```powershell
Set-Location 'C:\work\babycam'
conda activate air400
python -X utf8 .\serve_results.py
```

`C:\work\babycam`은 자기 PC의 경로로 바꿉니다. 브라우저에서 **http://127.0.0.1:8765**를 엽니다. 포트를 바꿨다면 설정한 포트로 접속합니다. HTML 파일을 파일 탐색기에서 직접 열지 않습니다.

각 터미널에서 `Ctrl+C`로 종료합니다. 터미널 종료·PC 절전·재부팅 시 프로그램도 멈춥니다. Windows 서비스/자동 부팅 등록은 아직 포함하지 않습니다.

### 4.3 프론트 화면만 개발할 때

키나 GPU가 없어도 Python 3.11 이상에서 빈 미리보기 화면을 확인할 수 있습니다. 이 명령은 `.env`를 읽지 않고 기본 포트 8765를 사용합니다.

```powershell
python -X utf8 .\serve_results.py --preview
```

미리보기는 가짜 BPM이나 분석 결과를 만들지 않습니다. 실제 결과를 읽을 때는 `--preview`를 제거하고 `.env`를 설정합니다. Supabase에서 이미 생성된 결과만 표시하는 서버에는 DeepPhys 모델/GPU가 필요하지 않지만, 해당 Python 서버의 Supabase 접근 설정은 필요합니다.

**현재 주소는 해당 PC 전용입니다.** 다른 팀원 PC/휴대폰에서 이 PC의 `127.0.0.1`로 접근할 수 없습니다. 원격 배포와 사용자 인증은 개발 예정 기능입니다.

## 5. 운영 중 알아둘 동작

| 항목 | 동작 |
|---|---|
| 입력 이름 | 한 prefix 안의 `000000000210.ts`처럼 12자리 숫자 TS |
| 배치 구성 | 번호가 연속된 15개. 누락 번호는 자동으로 건너뛰지 않고 대기 |
| 길이 조건 | 합계 30±0.25초. 범위 밖의 입력은 임의로 반복/늘리지 않음 |
| 작은 길이 차이 | 허용 범위 안에서만 마지막 프레임 연장 또는 잘라내기로 30초에 맞추고 보정량 기록 |
| 모델 입력 | 기존 전처리 후 10Hz 파형 300점 + DeepPhys 추정 BPM |
| 추가 보관 | 원시 출력 450점 및 fs 정보, NPZ/CSV |
| 결과 상태 | `anomaly_candidate`, `below_threshold`, `unscored` |
| 분석 불가 | 점수·BPM·bool·파형 null, 이유 보존 |
| DB 저장 실패 | 로컬 outbox를 보존하고 재전송. 완료된 분석을 다시 수행하지 않음 |
| 영상/처리 오류 | 최대 3회 시도 후 `unscored`로 기록하고 다음 배치 진행 |
| 원본 덮어쓰기 감지 | 수집기 중단. 세션/prefix/작업 폴더 점검 필요 |
| 보관 정책 | 완료된 원본 TS/MP4는 최근 3배치 유지. 작은 NPZ/CSV/결과는 계속 유지 |
| 결과 조회 실패 | 화면에 오류와 마지막 성공 시간을 표시하고 기존 결과 유지 |

재시작 시 `WORK_DIR/state.json`에서 이어갑니다. 실행 중 state/outbox를 수정하거나 삭제하지 않습니다. 입력/시작 번호/모델/서명 대상 코드 등이 바뀌면 기존 작업 폴더 사용을 거절하므로, 이전 결과를 보관한 상태에서 새 `WORK_DIR`를 지정합니다.

Pi가 번호를 초기화하거나 새 촬영 세션을 시작하면 새 Storage prefix와 `STREAM_ID`, `WORK_DIR`를 사용합니다. 수집기와 결과 서버의 `STREAM_ID`가 다르면 결과가 보이지 않습니다.

**한 스트림의 운영 수집기는 담당 PC 한 대에서 실행합니다.** 로컬 파일 잠금은 같은 작업 폴더의 중복 실행만 막습니다. 서로 다른 PC의 수집기를 조정하는 분산 잠금은 아직 없습니다.

## 6. 프론트 개발자가 사용할 API

현재 프론트와 같은 Python 서버에서 호출합니다. 외부 프론트를 위한 CORS/인증 설정은 포함되어 있지 않습니다.

| API | 응답 |
|---|---|
| `GET /api/results?limit=30` | `results`, `last_success_at`, `error`, `mode`, `server_time` |
| `GET /api/health` | 조회 상태·마지막 성공 시간·오류·모드 |

`limit`은 1~30이며 결과는 `end_seq` 내림차순입니다. `results`의 주요 필드는 다음과 같습니다.

- 식별: `batch_id`, `stream_id`, `start_seq`, `end_seq`, `created_at`.
- 분석: `status`, `is_anomaly`, `anomaly_score`, `threshold`, `pred_rr_bpm`, `wave_mse`, `bpm_mse`, `reason`.
- 파형: `waveform.x_10hz` 300점, `waveform.raw_model` 450점, `fs=10`, `raw_fs=15`.
- 실행 근거: `source_duration_sec`, `duration_sec`, `continuity`, `processing_sec`, `model_signature`.

`unscored`에서는 점수/파형/BPM/이상 여부가 null입니다. 프론트는 이를 0점·정상으로 변환하지 말고 ‘분석 불가’로 표시합니다. 문자열 `"False"`를 참으로 해석하는 변환도 피합니다. `created_at`은 결과 저장 시각이며 원본 영상의 촬영 시각이 아닙니다.

## 7. 담당 개발자의 남은 작업

| 우선순위 | 담당 | 해줘야 할 일 | 완료 기준 |
|---|---|---|---|
| P0 | 저장소 관리자 | 팀 저장소 주소 확정, 새 서비스/Windows 변경/테스트/문서 포함 | 다른 PC가 clone하여 핵심 파일 확인 가능 |
| P0 | 모델 담당자 | 네 가중치의 전달 위치·버전·해시·사용 조건 정리 | 팀원이 재학습 없이 동일 파일 배치 가능 |
| P0 | 환경 담당자 | 새 Windows 환경 설치, Ultralytics/OpenCV 의존성 문제 정리, 검증된 lock/환경 파일 제공 | import·DeepFlow·의존성 상태·실제 단일 배치 재현 결과 기록 |
| P0 | Supabase 담당자 | 프로젝트/Storage 경로/서버 키 전달 방식 확정, 결과 SQL 적용, 권한 확인 | `--check` 성공 및 실제 결과 행 확인 |
| P0 | Pi 담당자 | 약 2초 TS 생성, 12자리 연속 번호, 덮어쓰기 방지, 세션 교체 규칙 제공 | 실제 연속 15개 확보, 누락/중복/촬영 시간 검증 |
| P0 | 통합 담당자 | 실제 Pi→Storage→모델→DB→화면 단일 배치 시험 | 번호·길이·파형·BPM·상태·처리 시간 근거 보관 |
| P1 | 영상/성능 담당자 | 약 85초/배치 병목 측정 및 DeepFlow 경로 개선 검토 | 30초 입력 대비 처리량/지연 측정. 모델 전처리 영향 함께 검증 |
| P1 | 운영 담당자 | 장시간 실행·재시작·네트워크 오류·Storage 보관 기간·디스크 사용량 점검 | 커서/중복/실패 처리와 backlog 관리 확인 |
| P1 | 프론트/백엔드 담당자 | 원격 앱이 필요하면 인증·사용자별 접근·HTTPS·배포 구조 설계 | 서버 키 없이 허용된 사용자만 결과 접근 |
| P2 | 모델 담당자 | 정상 라벨 수동 검토, AIR-125/AIR-400 영아 ID 구분, 전처리 동등성 평가 | 검토된 데이터와 누수 없는 평가 근거 확보 |
| P2 | 모델/검증 담당자 | 별도 무호흡 정의·정답 데이터·판정 불가 기준 검증 | 일반 이상 점수와 무호흡 검증 결과를 구분해 보고 |

현재 모델의 학습 773구간은 메타데이터상 모두 `unreviewed`였고, 두 데이터셋의 같은 S번호를 합친 그룹 기록이 있습니다. 저장된 분할 간 ID/영상/원본 해시 중복은 발견되지 않았지만 정상 라벨과 임상 성능이 검증된 것은 아닙니다. 기존 모델을 보관하면서 개선 필요성과 새 버전을 검토합니다.

## 8. 자주 막히는 지점

| 증상 | 확인할 것 |
|---|---|
| 파일/가중치를 찾지 못함 | GitHub에서 가중치가 자동으로 내려오지 않음. 2.2절 파일 배치와 `AIR400_ROOT` 확인 |
| Supabase HTTP 401/403 | 프로젝트 URL과 서버 키가 같은 프로젝트인지, 올바른 키인지 확인 |
| 결과 테이블 오류 | 관리자의 SQL 적용 여부, 기존 스키마, Data API 노출/권한 확인 |
| 계속 TS 대기 | 버킷/prefix, 12자리 파일명, 실제 연속 15개, `START_SEQ`와 이미 저장된 커서 확인 |
| 화면에 결과가 없음 | 양쪽 `STREAM_ID`, 동일 Supabase 프로젝트, 수집기 실제 DB 저장 여부 확인 |
| ffmpeg/ffprobe 없음 | PATH 또는 `.env`의 두 exe 경로 확인 |
| DeepFlow가 없음 | 실제 import된 cv2와 contrib 설치 확인. ROI/Optical Flow를 꺼서 통과시키지 않음 |
| 이전 실행과 설정이 다름 | 코드·모델·입력 변경 여부 확인 후 새 `WORK_DIR` 사용. 기존 상태는 보존 |
| 포트가 이미 사용 중 | 기존 결과 서버/미리보기 종료 또는 실제 모드의 `SERVER_PORT` 변경 |
| 분석 불가 | DB의 reason과 해당 배치 `merge.log`, CSV, NPZ 확인. 정상으로 바꾸지 않음 |
| 결과가 늦음 | 현재 처리 속도와 밀린 영상 수 확인. 조회 주기만 줄여도 추론 병목은 해결되지 않음 |

## 9. 관련 문서와 README 연결

- [로컬 실행 상세 안내](BABYCAM_SERVICES.md)
- [서비스 검증 기록](docs/BABYCAM_SERVICE_VERIFICATION_20261124.md)
- [기존 코드/모델 인수인계 검증](docs/AIR400_HANDOFF_VERIFIED_20261124.md)
- [기존 자동 파형 추출 안내](EXTRACT_TRAINING_WAVEFORMS.md)

관리자가 GitHub에 올릴 때 저장소 `README.md` 상단에 다음 링크를 넣으면 팀원이 이 문서를 찾기 쉽습니다.

```markdown
[팀 개발 환경 설정 및 실행 가이드](TEAM_SETUP.md)
```

이 문서 작성 작업에서는 원격 저장소 생성·커밋·push, 새 Python 환경 설치, 실제 Supabase 변경을 수행하지 않았습니다. 공개할 저장소 주소와 모델 배포 위치, 새 환경 검증 결과는 관리자가 확정 후 갱신합니다.
