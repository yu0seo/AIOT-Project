# YOLO 객체 분할 실행

`segment_video.py`는 YOLO11l-seg(large)로 객체의 박스와 픽셀 마스크를 표시합니다. 기본 가중치는 `AIOT_2026/data/models/yolo11l-seg.pt`입니다. 기본 모델은 COCO 사전학습 객체 모델이며, 도로·차선의 전체 영역 분할 모델은 아닙니다. 현재 실행 환경은 CPU입니다. 결과 영상 위쪽에 실제 사용 중인 모델 파일 이름을 표시합니다.

기본 탐지 대상은 **자동차·오토바이·버스·트럭**(`2 3 5 7`)입니다. `train` 등 나머지 클래스는 출력하지 않습니다. 다른 대상을 보려면 `--classes`로 원하는 클래스 번호를 명시하세요. 이미 실행 중인 프로그램에는 변경이 적용되지 않으므로 종료 후 재실행해야 합니다.

**ByteTrack 추적을 기본 적용**합니다. 박스 라벨에 `id:1 car 0.85`처럼 추적 ID·클래스·신뢰도를 표시합니다. YOLO가 탐지한 모든 차량 박스와 마스크를 유지하고, ID가 아직 확정되지 않은 탐지는 `id:--`와 회색 박스로 표시합니다. ID 확정 여부 때문에 차량을 숨기지 않습니다. ID가 있는 박스는 객체별 색상, 마스크는 클래스별 색상을 사용합니다. 화면 위 `detected`는 전체 탐지 개수, `IDs`는 ID가 연결된 개수입니다.

ID는 현재 실행 중인 입력 안에서 차량을 연결하는 번호입니다. 프로그램 재실행, 긴 가림, 추적 실패 후에는 ID가 바뀔 수 있으며 번호판이나 영구 차량 ID가 아닙니다. CPU 처리 때문에 화면 프레임 간격이 커지면 추적이 불안정해질 수 있습니다. 원래 YOLO가 놓친 차량까지 추적기가 복원하는 기능은 아닙니다.

## 현재 CCTV 화면에서 실행 (CMD)

프로그램을 실행해도 즉시 캡처하지 않습니다. 준비 창이 열린 뒤 브라우저에서 CCTV 영상을 재생하고 화면 왼쪽에 배치하세요.

```cmd
cd /d "C:\Users\dndud\OneDrive\Desktop\coding_folder\AIOT-Project\AIOT_2026"
.venv\Scripts\python.exe pc\segment_video.py --screen
```

1. `Road Eye - CCTV 화면 준비` 창에서 **3초 후 화면 가져오기**를 누릅니다. 누르기 전에는 캡처하지 않습니다.
2. 준비 창이 숨겨지면 3초 안에 CCTV 창을 앞으로 전환합니다. 이후 선택 창에 그 시점의 정지 화면이 표시됩니다.
3. CCTV **영상 부분만** 마우스로 드래그하고 **Enter** 또는 **선택 확정**을 누릅니다. 다른 화면이 찍혔으면 **다시 가져오기** 버튼 또는 **R**로 다시 준비합니다.
4. `Road Eye - YOLO segmentation` 창에 선택 영역의 실시간 객체 마스크와 박스가 표시됩니다.
5. 결과 창이 원본 CCTV 영역을 가리지 않도록 오른쪽으로 이동하세요. 결과 창이 선택 영역을 가리면 결과 화면이 다시 입력되는 문제가 생길 수 있습니다.
6. 준비/선택 창의 **X / Esc / 종료**는 프로그램을 종료합니다. 결과 창의 **Q / Esc / X** 또는 터미널의 **Ctrl+C**도 종료합니다. 종료 뒤 창을 자동으로 다시 만들지 않습니다.

전환 시간이 더 필요하면 `--screen --capture-delay 8`처럼 대기 시간을 바꿀 수 있습니다. 대기 시간은 실행 시점이 아니라 **화면 가져오기 버튼을 누른 시점부터** 적용됩니다.

화면 선택은 사용자가 직접 합니다. 실행 중에는 CCTV 창 위치와 크기를 유지하세요. 이 모드는 화면 픽셀을 분석하므로 스트림 원본의 촬영 시각이나 프레임 번호를 제공하지 않습니다. 주행 속도 계산을 위한 수집 방식과 구분해야 합니다. 기본 실행은 화면이나 영상을 파일에 저장하지 않고 로컬에서 분석합니다.

다른 모니터는 `--monitor 2`로 선택할 수 있습니다. 화면 좌표를 아는 경우 `--screen --region LEFT TOP WIDTH HEIGHT`로 직접 지정할 수 있습니다.

## 다운로드된 IDD 영상

```cmd
.venv\Scripts\python.exe pc\segment_video.py --example impaired-crash --seconds 152
```

기본 sample은 다음과 같이 실행합니다.

```cmd
.venv\Scripts\python.exe pc\segment_video.py --example sample
```

이 모드에서는 `frame_timing.csv`와 실제 디코딩 순서를 사용합니다. 샘플 AVI의 잘못된 FPS 메타데이터로 시점을 추측하지 않습니다. 처리 속도에 따라 원래 영상보다 천천히 재생될 수 있습니다.

## 모델과 입력 조정

```cmd
REM 차량만 분할 (기본 COCO 모델의 클래스 번호)
.venv\Scripts\python.exe pc\segment_video.py --screen --classes 2 3 5 7

REM 느릴 때 모델 입력 크기를 낮추기 (작은 객체 정확도에 영향을 줄 수 있음)
.venv\Scripts\python.exe pc\segment_video.py --screen --imgsz 416

REM 영상 파일이나 실제 스트림 주소 입력
.venv\Scripts\python.exe pc\segment_video.py --source "C:\videos\road.mp4"

REM IDD 한 프레임 분할 결과를 PNG로 저장 (새 파일 이름 사용)
.venv\Scripts\python.exe pc\segment_video.py --example impaired-crash --seconds 155 --snapshot data\IDD\inspection\my_seg_155s.png --headless
```

`--model`에 다른 **segmentation용** `.pt` 파일을 지정할 수 있습니다. 탐지 전용 가중치는 이 도구에서 거부합니다. 사용자 학습 모델은 해당 모델의 클래스 번호를 사용해야 합니다.

기존 Pi 수신 프로그램도 segmentation 모델을 허용하도록 확장했습니다.

```cmd
.venv\Scripts\python.exe pc\receive_video.py --host 실제-Pi-IP --track --model data\models\yolo11l-seg.pt --classes 2 3 5 7
```

이 경우 YOLO segmentation과 ByteTrack을 함께 사용합니다. 실제 Pi 연결 검증은 별도로 필요합니다.

## 설치 및 검증

프로젝트 가상환경에 이미 설치했습니다. 새 환경에서는:

```cmd
.venv\Scripts\python.exe -m pip install -r pc\requirements-segmentation.txt
```

Ultralytics, PyTorch, torchvision, OpenCV, lap, mss를 사용합니다. `mss`는 화면 영역 캡처용입니다. 가중치와 실행 설정/캐시는 `AIOT_2026/data` 아래에 둡니다. IDD 영상의 저작자는 Toyota Research Institute이며 영상과 파생 확인 이미지는 CC BY-NC-SA 4.0 조건을 따릅니다.

참고: [Ultralytics instance segmentation](https://docs.ultralytics.com/tasks/segment/), [YOLO11 모델](https://docs.ultralytics.com/models/yolo11/), [IDD](https://toyotaresearchinstitute.github.io/IDD/).
