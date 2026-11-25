# 호흡 움직임 존재 판정 실험

2026-11-25. 사용자가 승인한 순서: 수동 ROI 비교(1) → 움직임 존재/BPM 거절(3) → 자동 ROI 연결 및 입력 일치 AE 재평가(4).

## 범위와 완료 조건

- `fixed-roi`: 동일한 원본/15Hz/30초/고정 ROI에서 기존 DeepPhys와 정규화 전 영상 움직임을 비교한다. EfficientPhys는 공식 가중치와 학습 전처리의 호환 여부를 별도로 기록한다. 다른 optical flow 입력 결과를 정식 비교 성능으로 취급하지 않는다.
- `presence`: 저해상도/가림/추적 실패/중단 영상은 측정 불가다. 움직임 근거 없는 FFT BPM을 결과로 승인하지 않는다. 호흡 움직임 있음/검출 안 됨/측정 불가와 기존 AE 상태를 각각 보존한다. 영상만으로 임상 무호흡을 확정하지 않는다.
- `automatic-roi`: 기존 CheckedPreProcessor와 Windows 추론을 재사용해 같은 판정 경로를 연결한다. ROI 실패는 null 점수와 이유를 남긴다. AE 입력이 바뀌면 기존 임계값을 전용하지 않는다. 비교가 후보를 지지하지 않으면 재학습을 강행하지 않는다.

기존 운영 모델/추론/서비스/.env는 보존하고 별도 CLI와 새 output 폴더에서 실험한다. 신호 추출은 새로운 라이브러리 없이 현재 OpenCV/NumPy/SciPy/PyTorch를 사용한다. 단일 창을 전체 영상 길이로 오인하지 않고 30초 미만은 제외한다.

## 검증

`babycam_tests/test_respiration_motion.py`, `test_respiration_presence.py`에서 정지, 국소 주기 운동, 전체 카메라 이동, 무텍스처, 디지털 정지, 유효하지 않은 입력, 미보정/약한 신호/BPM 거절을 검증한다. 기존 unittest 전체를 회귀 검사한다. 실제 영상 결과는 원본 해시·ROI 미리보기·원시 움직임·기존 파형·CSV/JSON/PNG로 남긴다. 분할은 데이터셋 포함 영아 ID 및 원본 촬영 단위로 유지하고 같은 영상의 구간을 독립 검증으로 세지 않는다.

현재 양성 검토는 S05 가슴 움직임과 S02_008 등 움직임 2개다. 나머지는 사용자 승인 정상 가정이며 검토 완료와 구분한다. 인형 두 촬영은 정지 모사이고 실제 영아 무호흡 정답이 아니다. 같은 카메라의 움직이는 인형 양성 대조군은 사용자가 없다고 확인했다. 따라서 임계값의 독립 검증과 운영 채택은 미완료로 남길 수 있다.

## 현재까지 확인한 결과

1. 고정 몸통 ROI, 30초, 동일 원본 5개에서 DeepPhys+DeepFlow와 EfficientPhys+공식 Coarse2Fine를 실제 실행했다. 파형 출력은 서로 다른 임의 단위이므로 진폭을 모델 간 직접 비교하지 않는다. EfficientPhys는 공식 FRAME_DEPTH=10, 180/180/90 시간 배치에 마지막 프레임을 한 번 복제해 450개 출력을 보존했다. 기존 infer.py의 마지막 미완성 청크 삭제와는 다른 명시적 30초 실험 계약이다. 학습 자료와의 영아 중복 여부는 확인하지 못했으므로 독립 정확도 비교가 아니다.
2. DeepPhys는 두 정지 인형 모두 29.88 BPM, EfficientPhys는 각각 38.67/29.88 BPM을 냈다. 이 촬영들에서 파형 모델만 교체해도 정지 입력의 양수 BPM 문제는 남았다. EfficientPhys로 운영 교체하지 않았다.
3. 기본 train 진폭 중간값 임계값은 S02의 약한 움직임을 거절했다. 그 실패를 `output/respiration_calibration_midpoint_20261125`에 보존했다. 후속 개발 보정은 train 정지 진폭 상한에 대한 고정 배수 후보(1.25/1.5/2/3/5/10/16)와 train 중간값 중 valid의 두 라벨을 모두 구분하는 가장 큰 임계값을 선택한다. test 수치와 라벨은 선택에 사용하지 않는다. **valid는 임계값 선택 자료이며 독립 성능 검증 자료가 아니다.**
4. 검출기 입력 경계 문제를 확인했다. 현재 FFmpeg 경로는 RGB인데 Ultralytics의 NumPy 입력은 BGR로 간주되어 내부에서 RGB로 뒤집힌다. 새 인형 첫 프레임에서 YOLO11m은 BGR 입력 시 confidence 약 0.743, RGB 직접 전달 시 미검출이었다. `normal_pipeline/detector_input.py`는 검출기에만 RGB→BGR 변환을 적용하고 DeepPhys용 영상은 RGB로 유지한다. 기존 pre_processor.py를 몰래 바꾸지 않으며 새 경로는 `--correct-detector-color`로 선택한다.
5. 같은 인형에 기존 YOLOv8m은 320×180 샘플 0/10/20초에서 미검출이었지만 원본 해상도에서는 검출했다. YOLO11m은 320×180에서도 세 샘플 모두 검출했다. 해상도 손실과 색상 경계 모두 영향이 있었으며 최신 버전 번호 하나만의 문제로 보지 않는다. 현재 ultralytics 8.3.96 환경과 기존 가중치는 보존했다.
6. YOLO11m+색상 경계 보정의 자동 ROI로 5개 원본을 다시 검사했다. 사용자 검토 아기 2개는 각 5개 창 모두 움직임 있음, 두 인형은 각 5개 창 모두 움직임 검출 안 됨으로 개발용 보정됐다. 임계값은 320×180의 10초 창 진폭 약 0.019939 픽셀이다. 다른 해상도/창 길이/검출기/색상 경로에 전용할 수 없다.
7. 보정에서 제외한 정상 가정 S09_2는 5개 창 중 3개가 움직임 부족 후보였다. 이 결과를 보고 임계값을 다시 낮추지 않았다. 실제 호흡이 작거나 보이지 않는 영상에 대한 오경보 가능성이 남는다. **이 결과는 무호흡 미탐지 해결 또는 운영 채택의 근거가 아니다.**

숫자/ROI/파형: `output/respiration_fixed_roi_coarse_20261125`, `output/respiration_automatic_yolo11_bgr_20261125`, `output/respiration_summary_20261125/comparison.png`, `gate_windows.csv`. 원본 촬영·ROI·가중치·코드 해시를 JSON에 남겼다. 정지 인형을 실제 무호흡이라고 표시하지 않는다.

## 판정 계약

- `motion_present`: 픽셀 움직임, 주기성, 공간 일관성의 개발 기준을 통과했다. 정상 호흡 확정이 아니다.
- `no_motion_detected`: 개발 임계값 이상의 호흡 움직임이 검출되지 않았다. `movement_absence_candidate=true`, `pred_rr_bpm=null`, `clinical_apnea=null`이다. 측정 불가능하거나 움직임이 너무 약한 정상 영상도 포함될 수 있다.
- `unassessable`: 정지 프레임 반복/텍스처 부족/배경 부족/심한 카메라 이동/노출 문제/보정 불일치다. 없음·정상으로 바꾸지 않는다. `movement_absence_candidate=null`이다.
- AE는 위 상태와 분리한다. 움직임 부족 또는 측정 불가에서는 AE의 주 결과를 `unscored`, 점수/bool/BPM을 null로 남긴다. 기존 AE를 강제로 실행한 값은 `legacy_ae_diagnostic`에 별도로 보존한다.
- `production_ready=false`인 보정은 기본 실행에서 채택하지 않는다. 개발용 실행은 `--allow-development-calibration`을 명시해야 한다. 이 플래그는 임상 검증이나 운영 승인으로 해석되지 않는다.
- 10초 창을 5초씩 이동한다. 겹치는 창을 단순 합산하지 않고 측정 불가·시간 공백에서 움직임 부족 누적을 끊는다. 30초 미만 꼬리는 `unscored`다.
- 자동 ROI 보정은 같은 검출기 해시와 색상 어댑터를 요구한다. AE도 실제 검출기/색상 계약과 일치해야 하며 다른 ROI로 학습한 이전 AE를 재사용하려 하면 거절한다.

## Windows Coarse2Fine 준비

초기 환경에는 모듈이 없었다. 기존 pyflow 원본을 실험 폴더로 복사하고 원본 project.h의 Visual Studio 지시대로 복사본의 `_LINUX_MAC`만 해제해 빌드했다. 원본과 Conda 환경은 변경하지 않았다. 1.5픽셀 이동 시험의 중앙값은 약 1.5018픽셀이었다. 완전 동일 프레임에서는 upstream 잡음 추정 경고가 발생하면서 zero flow가 나오는 것을 기록했다. 동일 입력 자체는 영상 중단일 수 있어 존재 판정에서는 측정 불가다.

새 PC에는 Visual Studio C++ Build Tools/Windows SDK가 필요하다. [pyflow 원본](https://github.com/pathak22/pyflow)과 라이선스를 준비한 뒤 실행한다.

```powershell
Set-Location 'C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026'
$airPython = 'C:\Users\OHS\miniconda3\envs\air400\python.exe'
& $airPython -m pip install --no-deps --target .\output\respiration_build_deps Cython==3.0.12
& $airPython -B -X utf8 .\build_respiration_pyflow.py `
  --source .\pyflow --cython-dir .\output\respiration_build_deps `
  --output .\output\respiration_native
```

빌드 성공/원본 불변 여부/원본 해시/생성 바이너리 해시는 build.json, 상세 로그는 build.log에 남는다. 현재 PC에서 `pyflow_windows`와 재현 빌더의 `pyflow_repro` 모두 빌드 성공을 확인했다. 바이너리는 Python/Windows 아키텍처에 종속되므로 다른 환경에서 다시 빌드한다.

가중치: [AIR-400 공식 체크포인트](https://coe.northeastern.edu/Research/AClab/AIR-400/Model%20Checkpoints/), [Ultralytics YOLO11](https://docs.ultralytics.com/models/yolo11/). 이번 EfficientPhys SHA-256은 `fc4cd52bcc3ee60b51f53ca942ee331ea398d5822fd687e30d6de7e965cfcd35`, YOLO11m은 `d5ffc1a674953a08e11a8d21e022781b1b23a19b730afc309290bd9fb5305b95`다. 기존 detectors/checkpoints 파일을 덮어쓰지 않고 새 실험 폴더에 받는다.

## 실행 인터페이스

기준 Python: `C:\Users\OHS\miniconda3\envs\air400\python.exe`.

`respiration_pipeline.py compare --manifest <source-locked JSON> --output <new folder>`는 고정 ROI 비교를, `calibrate --comparison <comparison.json> --output <new folder>`는 개발용 존재 판정 임계값 적합/검증을, `video --input <video> --calibration <calibration.json> --output <new folder>`는 기존 자동 ROI와 연결한 실험을 수행한다. 재실행은 새 출력 폴더를 사용한다. 실제 실행 결과와 상세 명령은 검증 후 이 문서에 추가한다.
