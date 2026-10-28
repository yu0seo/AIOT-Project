# 라즈베리파이 5 → Windows PC 실시간 영상

Pi에서 H.264로 압축한 영상을 MPEG-TS/TCP로 전송하고 PC에서 OpenCV로 받아 표시합니다. DB나 별도 영상 서버 설치 없이 한 대의 PC에서 수신하는 첫 구현입니다. 양쪽이 같은 공유기/핫스팟에 연결되어 서로 통신할 수 있어야 합니다.

```text
Pi 카메라 → rpicam-vid → TCP 5000 → PC OpenCV → PC 영상 창/향후 분석
```

VNC는 Pi에서 전송 프로그램을 실행하는 데만 사용합니다. 수신 프로그램은 Windows PC에서 실행하므로, 영상 프레임과 이후 분석은 PC에서 처리합니다.

## 1. Pi에서 전송 시작

기존 `rpicam-hello`, `camera_test.py --live` 등 카메라 미리보기를 먼저 `Ctrl+C`로 종료하세요. VNC 데스크톱의 터미널에서 Pi IP를 확인합니다.

```bash
hostname -I
```

노트북이 접속할 수 있는 Wi-Fi/유선 LAN IP를 사용하세요. 예를 들어 `192.168.0.50`입니다. 여러 IP가 나오면 VNC 연결에 사용한 Pi의 LAN IP를 기준으로 확인할 수 있습니다.

Pi에 이 저장소의 `AIOT_2026/raspberry_pi/stream_camera.py`를 복사하고 해당 폴더에서 실행합니다.

```bash
python3 stream_camera.py
```

기본 설정은 1280×720, 20fps, 2Mbps, TCP 5000입니다. PC가 접속할 때까지 대기하는 것은 정상입니다. `rpicam-vid`가 없으면 Pi에서 `sudo apt update` 후 `sudo apt install -y rpicam-apps`로 설치하세요.

파일을 복사하지 않고 아래 명령으로 동일하게 시작할 수도 있습니다.

```bash
rpicam-vid --timeout 0 --nopreview --camera 0 --width 1280 --height 720 --framerate 20 --bitrate 2000000 --codec libav --libav-format mpegts --low-latency --output 'tcp://0.0.0.0:5000?listen=1'
```

Pi 5의 소프트웨어 인코딩에 맞춰 `--low-latency`를 사용합니다. 실제 지연과 프레임 수는 카메라, 인코딩 부하와 네트워크에 따라 달라집니다.

## 2. Windows PC에서 수신

Windows PowerShell에서 이 `pc` 폴더로 이동한 뒤 실행하세요. Pi/VNC 터미널이 아닙니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe receive_video.py --host 192.168.0.50
```

`192.168.0.50`을 실제 Pi IP로 바꾸세요. 가상환경 활성화 명령 없이 직접 실행하므로 PowerShell 실행 정책을 바꿀 필요가 없습니다. 수신 준비가 끝나면 Windows에 영상 창이 뜹니다. 영상 창에서 `Q`/`ESC`, 창 닫기 또는 터미널의 `Ctrl+C`로 종료하세요.

다음 실행부터는 마지막 명령만 사용하면 됩니다. `python` 명령이 없다면 Windows Python 설치 상태를 확인하세요. Python 런처가 있는 환경에서는 `python` 대신 `py -3`로 가상환경을 만들 수 있습니다.

GUI가 포함된 `opencv-python`을 사용합니다. 같은 환경에 `opencv-python-headless`를 함께 설치하지 마세요.

## 3. 연결이 안 될 때

- **Pi 전송을 먼저 실행**하고 PC 수신을 시작합니다. 카메라를 사용하는 다른 프로그램은 종료합니다.
- PC를 종료하거나 연결이 끊어졌다면 **Pi 전송 프로그램부터 다시 실행**합니다. 이 기본 TCP 서버는 한 연결을 위한 방식이며 자동 재접속 서버가 아닙니다.
- 이 방식은 **동시에 수신 프로그램 하나만** 연결할 수 있습니다. VLC와 Python을 동시에 연결하지 마세요.
- `0.0.0.0`은 Pi가 접속을 기다리는 주소입니다. PC의 `--host`에는 실제 Pi IP를 사용하세요. `127.0.0.1`도 Pi IP가 아닙니다.
- 같은 Wi-Fi여도 게스트/기관 네트워크의 장치 간 통신 차단 때문에 접속하지 못할 수 있습니다. 둘을 같은 개인 공유기나 핫스팟에 연결해 확인하세요. 기존 방화벽이 있다면 로컬 네트워크의 Pi TCP 5000 접근을 확인하세요.
- **`Test-NetConnection Pi-IP -Port 5000`은 이 단일 연결 서버에 접속을 하나 소비할 수 있습니다.** 진단에 사용했다면 Pi 전송을 재시작한 뒤 수신하세요.
- `--low-latency`를 지원하지 않는 오래된 rpicam 패키지는 Raspberry Pi OS 패키지를 업데이트한 뒤 다시 확인하세요.
- 영상이 느리면 아래처럼 해상도와 프레임 수를 낮춰 시작하세요.

```bash
python3 stream_camera.py --width 640 --height 480 --fps 15 --bitrate 1000000
```

## 추가 실행 옵션

```powershell
# Pi 전송 포트도 함께 변경한 경우
.\.venv\Scripts\python.exe receive_video.py --host 192.168.0.50 --port 5001

# 창 없이 5초 수신 확인. 종료 후 Pi 전송도 재시작해야 합니다.
.\.venv\Scripts\python.exe receive_video.py --host 192.168.0.50 --headless --duration 5

# 나중에 MediaMTX/RTSP로 전환하면 수신 주소를 직접 지정할 수 있습니다.
# 이 예는 별도로 RTSP 서버를 구성한 경우에만 작동합니다.
.\.venv\Scripts\python.exe receive_video.py --url rtsp://192.168.0.50:8554/cam
```

## PC에서 YOLO + ByteTrack 실행

이 프로그램은 `--track`을 추가하면 수신한 프레임을 PC의 YOLO로 탐지하고 ByteTrack으로 연결해, 영상에 박스/클래스/신뢰도/추적 ID를 표시합니다. ByteTrack은 객체 간 연결을 담당하며 YOLO가 객체를 탐지합니다. 라즈베리파이는 기존 전송 명령을 사용합니다.

PC에서 수신을 종료한 후, 이 폴더의 CMD/PowerShell에서 추적용 라이브러리를 설치하세요. 이미 만든 가상환경을 그대로 사용하며 새로 만들 필요가 없습니다.

```cmd
.\.venv\Scripts\python.exe -m pip install -r requirements-tracking.txt
```

설치 완료 후 Pi 전송을 다시 시작하고, PC에서 실제 Pi IP를 넣어 실행합니다.

```cmd
.\.venv\Scripts\python.exe receive_video.py --host 192.168.0.50 --track
```

기본 탐지 모델은 `yolo11n.pt`입니다. 첫 실행 시 공식 가중치를 다운로드할 수 있으므로 인터넷 연결이 필요합니다. 모델은 PC에서 준비한 뒤 Pi에 접속합니다. 추가 학습 없이 사전학습된 범주의 일반 객체를 확인할 수 있습니다. 모델이 학습하지 않은 객체의 탐지는 보장하지 않습니다. 천장만 촬영하면 탐지할 대상이 없을 수 있으므로, 사람이나 의자처럼 학습된 범주의 객체를 비춰 확인하세요.

### Road Eye용 차량만 탐지/추적

기본 COCO 사전학습 모델의 클래스 번호는 `2=car`, `3=motorcycle`, `5=bus`, `7=truck`입니다.

```cmd
.\.venv\Scripts\python.exe receive_video.py --host 192.168.0.50 --track --classes 2 3 5 7
```

사용자 학습 모델도 선택할 수 있습니다. 아래 경로는 실제 보유한 탐지용 `.pt` 파일 경로로 바꾸세요. 이 모델에 `--classes`를 사용한다면 COCO 번호가 아닌 해당 모델의 클래스 번호를 사용해야 합니다.

```cmd
.\.venv\Scripts\python.exe receive_video.py --host 192.168.0.50 --track --model "C:\models\best.pt"
```

### 처리 속도 조정

- NVIDIA GPU는 CUDA를 지원하는 PyTorch가 설치된 환경에서 `--device 0`으로 선택할 수 있습니다. 일반 설치만으로 GPU 지원을 보장하지 않습니다.
- GPU가 없을 때도 `--device cpu`로 동작시킬 수 있으나 실제 처리 속도는 PC 성능과 장면에 따라 달라집니다.
- 느리면 `--imgsz 416`으로 모델 입력을 줄여 볼 수 있습니다. 작은/먼 객체의 정확도에 영향을 줄 수 있습니다.
- 기본 `--conf 0.1`은 ByteTrack에 낮은 신뢰도 후보도 전달하기 위한 탐지 하한입니다. 실제 새 추적 생성과 유지에는 ByteTrack의 별도 임계값도 적용됩니다.

```cmd
.\.venv\Scripts\python.exe receive_video.py --host 192.168.0.50 --track --device cpu --imgsz 416
```

`--track` 없이 실행하면 기존의 영상 수신 기능으로 동작하며 추적 라이브러리는 필요하지 않습니다.

### 추적 결과를 시계열 데이터로 확장할 때

`frame`은 PC 메모리에 올라온 OpenCV BGR 영상입니다. `result.boxes`에서 탐지 박스, 클래스, 신뢰도와 추적 ID를 얻을 수 있습니다. ID가 아직 생성되지 않았을 수 있으므로 `result.boxes.id is not None`을 확인한 뒤 사용하세요. ID는 현재 실행/카메라 스트림 안에서의 추적 번호이며, 재실행이나 긴 가림 이후 같은 차량의 ID를 보장하지 않습니다.

수신 스레드는 계속 영상을 읽고 최신 프레임 하나만 유지합니다. 따라서 분석 때문에 처리하지 못한 과거 프레임이 Python 큐에 쌓이지 않지만, PC가 느리면 분석 프레임을 건너뛰게 됩니다. 프레임 사이 이동량이 커지면 ByteTrack의 연결 정확도도 떨어질 수 있으므로 추적 안정성과 처리 속도를 실제 도로 영상으로 확인하세요. 인코더/전송/디코더 내부 지연까지 모두 없애는 방식은 아닙니다.

현재 코드는 영상과 DB 데이터를 저장하지 않습니다. 시계열 특징을 만들 때는 카메라 촬영 시각/스트림 PTS와 연결 세션, 누락된 프레임 처리를 추가하세요. 코드의 프레임 번호는 PC에서 디코딩한 순서이고 수신 시각은 PC 시각이므로, 이를 촬영 시각이나 실제 고정 FPS로 간주해 속도를 계산하면 안 됩니다. 실제 속도(m/s)는 별도 도로 좌표 보정이 필요합니다. 여러 동시 접속과 재연결이 필요해지면 MediaMTX/RTSP로 확장할 수 있습니다.

## 참고

- [Raspberry Pi 공식 카메라/네트워크 스트리밍 문서](https://www.raspberrypi.com/documentation/accessories/camera-software.html)
- [OpenCV Python 패키지 설치](https://github.com/opencv/opencv-python#installation-and-usage)
- [OpenCV 영상 입출력 옵션](https://docs.opencv.org/4.x/d4/d15/group__videoio__flags__base.html)
- [Ultralytics YOLO 객체 추적 및 ByteTrack 설정](https://docs.ultralytics.com/modes/track/)
- [YOLO11 모델](https://docs.ultralytics.com/models/yolo11/)
- [COCO 클래스 번호](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/datasets/coco.yaml)
