# Road Eye 2026

기존 AIR-400 DeepPhys로 영상에서 30초 호흡 파형과 BPM을 자동 추출하는 도구는 [자동 파형 추출 안내](pc/DEEPHYS_EXTRACTION.md)에 있습니다.

라즈베리파이 5 카메라의 인식, VNC 실시간 미리보기, 사진 촬영 코드는 [raspberry_pi](raspberry_pi/README.md)에 있습니다.

라즈베리파이 영상을 Windows PC로 실시간 전송하고 OpenCV로 받는 방법은 [pc](pc/README.md)에 있습니다.

PC 수신 프로그램에 `--track`을 추가하면 YOLO 객체 탐지와 ByteTrack 추적을 실행할 수 있습니다. 설치와 차량 클래스 선택은 [PC 안내](pc/README.md#pc에서-yolo--bytetrack-실행)를 참고하세요.

다운로드한 IDD 샘플의 전방 영상과 같은 시각의 속도·가속도·저크를 함께 확인하려면 [IDD 확인 도구](pc/IDD_INSPECTION.md)를 참고하세요.

현재 CCTV 화면 영역이나 IDD 영상에 YOLO 객체 분할 마스크를 표시하려면 [segmentation 실행 안내](pc/SEGMENTATION.md)를 참고하세요.

IDD 좌표에서 4개 주행 특징을 계산하고 3·5·10초 LSTM을 학습·평가하는 실행 방법은 [시계열 분류 프로젝트 안내](docs/IDD_TRAINING.md)를 참고하세요. [실제 기준 실험 결과](docs/IDD_BASELINE_RESULTS.md)와 [CCTV 추론 인터페이스](idd_classifier/inference.py)도 포함되어 있습니다. 현재 기준 모델의 성능은 관제 적용에 충분하지 않습니다.

같은 네 피처로 전처리·모델을 비교하는 [성능 개선 실험](docs/IDD_IMPROVEMENT.md)에는 참가자 교차검증, LSTM/GRU/TCN 비교, 개선 모델의 기존 추론 인터페이스 연동이 포함되어 있습니다.

LSTM의 너비와 층 수를 64×2, 128×2, 256×3으로 확대하는 방법은 [모델 크기 확대 실험](docs/IDD_LARGE_LSTM.md)에 정리되어 있습니다.

네 피처를 유지한 MiniRocket과 참가자 20명 전체의 중첩 5-fold 평가는 [MiniRocket 실행 안내](docs/IDD_MINIROCKET.md)와 [실제 평가 결과](docs/IDD_MINIROCKET_RESULTS.md)에 정리되어 있습니다.

동일한 참가자 분할과 평가 구간에서 56,513개 파라미터의 단일 소형 네트워크를 비교하는 방법은 [InceptionTime 안내](docs/IDD_INCEPTIONTIME.md)에 있습니다. [실제 동일 5-fold 비교 결과](docs/IDD_INCEPTIONTIME_RESULTS.md)도 포함했습니다.
