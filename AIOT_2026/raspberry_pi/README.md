# Raspberry Pi 5 카메라 작동 확인

Raspberry Pi OS Bookworm/Trixie와 CSI 리본 케이블로 연결한 지원 카메라 모듈을 기준으로 합니다. 실제 카메라 모델에 따라 별도 드라이버가 필요할 수 있습니다.

카메라 작동을 확인했다면 [PC 실시간 수신 안내](../pc/README.md)에 따라 `stream_camera.py`로 영상을 전송할 수 있습니다.

## 바탕화면 아이콘으로 PC 영상 전송 시작

`RoadEye.desktop`은 전송 명령이 들어 있는 실행 아이콘입니다. 이 파일 하나를 **Pi의 바탕화면**으로 복사하세요. `.txt` 확장자가 붙지 않도록 합니다.

처음 한 번만 Pi 파일 관리자에서 해당 파일이 있는 폴더를 터미널로 열고 실행 권한을 줍니다.

```bash
chmod +x RoadEye.desktop
```

이후 VNC 바탕화면의 아이콘을 더블클릭하면 터미널이 열리고 영상 전송 접속을 기다립니다. 처음 실행할 때 신뢰/실행 여부를 묻는 경우 직접 만든 이 실행 아이콘에 대해 실행을 허용하세요. 기존 카메라 미리보기는 먼저 종료해야 합니다. PC 수신 프로그램은 별도로 실행하며 PC의 `--host`에 실제 Pi IP를 입력합니다. 아이콘 안의 `0.0.0.0`은 그대로 둡니다.

중지는 열린 터미널의 `Ctrl+C`입니다. PC 연결을 끊고 다시 접속하려면 아이콘을 다시 실행하세요. 터미널이 즉시 닫힌다면 파일이 있는 폴더의 터미널에서 기존 전송 명령을 직접 실행하여 오류를 확인하세요. 이 파일은 클릭했을 때 실행하며 부팅 시 자동 실행을 설정하지 않습니다.

이 실행 아이콘은 [freedesktop Desktop Entry 규격](https://specifications.freedesktop.org/desktop-entry/latest-single/)의 `Exec`와 `Terminal=true`를 사용합니다.

## VNC에서 실시간 영상 보기

**OpenCV 설치 없이 사용할 수 있습니다.** VNC로 접속한 Pi 데스크톱에서 터미널을 열고 `camera_test.py`가 있는 폴더에서 실행하세요.

```bash
python3 camera_test.py --live
```

640×480 실시간 영상 창을 계속 표시합니다. 사진이나 동영상 파일을 저장하지 않으며, 종료는 실행한 터미널에서 `Ctrl+C`를 누르세요. `--seconds`는 사진 촬영 대기 시간이며 `--live`의 실행 시간을 제한하지 않습니다.

VNC처럼 원격 화면으로 볼 때 적합한 소프트웨어 Qt 미리보기(`Preview.QT`)를 사용합니다. 모니터 없이 VNC로 접속한 경우에도 이 방식을 사용할 수 있습니다. VNC 화면 갱신 속도와 네트워크 상태에 따라 지연이나 끊김은 생길 수 있습니다.

Python 파일을 옮기기 전에 아래 기본 명령으로도 바로 확인할 수 있습니다.

```bash
rpicam-hello --qt-preview --timeout 0
```

이 명령 역시 VNC 데스크톱 안의 터미널에서 실행하고 `Ctrl+C`로 종료합니다. 두 카메라 프로그램은 동시에 실행하지 마세요. 명령이 없다면 `sudo apt install -y rpicam-apps`로 설치하세요.

## 1. 연결과 카메라 인식 확인

1. Pi 전원을 완전히 끄고 전원 케이블을 분리합니다.
2. 카메라에 맞는 Pi 5용 케이블로 CAM/DISP 커넥터에 연결하고 잠금 장치를 고정합니다. Pi 5 보드 쪽은 22핀 커넥터입니다. 카메라 쪽 핀 수는 모듈에 맞춰야 합니다.
3. 부팅 후 Pi 터미널에서 실행합니다.

```bash
rpicam-hello --list-cameras
```

`0 : imx219 ...`, `0 : imx708 ...` 등 카메라 정보가 나오면 인식된 상태입니다. `No cameras available`이면 프로그램 실행보다 케이블 방향, 접촉, 카메라 호환성을 먼저 확인하세요. 연결을 바꿀 때는 전원을 끄세요.

## 2. Python 라이브러리 설치

Pi 터미널에서 시스템 Python용 패키지를 설치합니다.

```bash
sudo apt update
sudo apt install -y python3-picamera2
```

`rpicam-hello` 명령도 없다면 `sudo apt install -y rpicam-apps`로 설치합니다.

Picamera2와 libcamera의 호환성을 위해 `pip`보다 OS 패키지를 사용합니다. 가상환경을 사용한다면 시스템 패키지가 보이도록 `python3 -m venv --system-site-packages .venv`로 만드세요.

## 3. 코드 실행

이 폴더를 Pi로 복사하거나 저장소를 Pi에 내려받고, `camera_test.py`가 있는 폴더에서 실행하세요. 노트북의 Windows Python에서 실행하는 코드가 아닙니다.

```bash
# 인식된 카메라 목록
python3 camera_test.py --list

# VNC에서 사진 저장 없이 실시간 영상 보기
python3 camera_test.py --live

# 모니터 없이 SSH로 접속한 경우도 사용 가능: 3초 후 사진 저장
python3 camera_test.py

# VNC 또는 Pi 그래픽 데스크톱에서 10초 미리보기 후 사진 저장
python3 camera_test.py --preview --seconds 10

# 저장 위치를 직접 지정
python3 camera_test.py --output ./test.jpg

# 목록에서 두 번째로 인식된 카메라 선택
python3 camera_test.py --camera 1
```

기본 실행은 이 스크립트 옆 `captures/` 폴더에 날짜와 시간이 붙은 1280×720 JPG 사진을 저장합니다. `--preview`는 지정한 시간 동안 미리보기를 표시한 뒤 사진을 저장하고 종료합니다. `Ctrl+C`로 중단할 수 있습니다. 사진을 직접 열어 밝기, 초점, 장면이 정상인지 확인하세요.

**미리보기는 Pi 데스크톱 창에 표시되므로 VNC 화면에서 볼 수 있습니다.** 일반 SSH 접속만으로 노트북에 영상이 뜨지는 않습니다. SSH에서는 옵션 없이 촬영하고 출력된 경로의 사진을 노트북으로 복사해 확인하세요.

## 빠른 확인용 기본 명령

Python 코드와 별도로 아래 명령으로 드라이버와 촬영을 확인할 수 있습니다. 다른 카메라 프로그램과 동시에 실행하지 마세요.

```bash
# VNC에서 볼 수 있는 Qt 미리보기. Ctrl+C로 종료
rpicam-hello --qt-preview --timeout 0

# SSH에서도 미리보기 없이 사진 저장
rpicam-still --nopreview --timeout 3000 --output quick_test.jpg
```

## 문제 해결

- `No module named picamera2` 또는 `libcamera`: 위 OS 패키지를 설치하고 시스템 `python3`를 사용하세요. 가상환경이라면 시스템 패키지 접근 설정을 확인하세요.
- 카메라 사용 중 오류: `rpicam-hello`, 다른 Python 카메라 프로그램, MediaMTX 등을 종료한 뒤 다시 실행하세요.
- Qt/디스플레이 오류: VNC 데스크톱 안의 터미널에서 실행하고 `sudo` 없이 사용하세요. GUI 의존성을 포함한 `python3-picamera2` 패키지도 설치되어 있어야 합니다.
- 검거나 흐린 사진: 렌즈 덮개, 조명, 초점과 케이블을 확인하고 `--seconds 5`로 다시 촬영하세요.
- 카메라 미감지: 전원을 끈 뒤 케이블과 카메라 모델의 지원 여부를 확인하세요. 특정 서드파티 모듈은 제조사 드라이버/설정이 필요합니다.

## 참고

- [Raspberry Pi 공식 카메라 문서](https://www.raspberrypi.com/documentation/accessories/camera-software.html)
- [Picamera2 공식 저장소](https://github.com/raspberrypi/picamera2)
- [Picamera2 공식 매뉴얼: Qt preview 및 Remote preview windows](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)

현재 개발 PC에서 Python 문법과 도움말/잘못된 인자 처리를 확인할 수 있지만, 촬영과 미리보기는 Pi 5와 실제 카메라에서 확인해야 합니다.
