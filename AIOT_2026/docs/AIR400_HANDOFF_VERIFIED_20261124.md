# AIR-400 베이비캠 인수인계 검증 기록

확인일: 2026-11-24, 한국 시간. 원본 인수인계 840행 전체를 읽고 로컬 코드·설정·가중치·NPZ·CSV 및 실행 환경과 대조했다. 이 문서는 원본을 대체하지 않는 검증 보충 기록이다. 원본의 계획과 예시를 이미 구현된 기능으로 간주하지 않는다.

## 1. 기준 자료와 작업 범위

- 실제 AIR-400 실행 루트: `C:\Users\OHS\air-400`.
- 원본: `C:\Users\OHS\Downloads\AIR400_BABYCAM_WORK_HANDOFF.md`.
- 원본 SHA-256: `6aef903b9496bd7da38f3985c774b23219eb958526d626103f8053057da2bd0d`, 69,569바이트, 840행.
- 프로젝트 보관본: `C:\Users\OHS\air-400\docs\AIR400_BABYCAM_WORK_HANDOFF.md`.
- 기계 판독 검증 결과: `AIR400_HANDOFF_AUDIT_20261124.json`. 파일 해시·환경·분할·재계산 결과를 포함한다.
- 현재 Codex 작업 폴더 `C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026`는 Road Eye/IDD 등도 포함하는 별도 저장소다. 그 안의 `pc/extract_respiration.py`는 기존 자동 추출 도구의 원본이고, AIR-400에 설치된 실행 파일은 `extract_training_waveforms.py`다. 두 저장소의 작업을 혼동하지 않는다.

이번 인수인계에서는 기존 모델·추론·전처리 코드를 변경하거나 재학습하지 않았다. 검사 스크립트, 결과, 인수인계 문서와 프로젝트 안내만 추가했다. 기존 미커밋 변경은 보존했다. DB·Storage 쓰기, 테이블 생성, 프로젝트 복구·배포는 수행하지 않았다.

## 2. 실제 파일과 실행으로 확인한 사실

| 항목 | 확인 결과 |
|---|---|
| DeepPhys 가중치 | `checkpoints/DeepPhys_Deep_Body_best.pth` 존재. 현재 해시가 훈련용 NPZ의 `run.json`에 기록된 해시와 일치 |
| ROI 가중치 | `detectors/yolov8m.pt`, `detectors/yolov8n-face.pt` 존재 |
| 학습 코드 | `models/air400_npz_anomaly_v2.py` 존재. 기존 1D CNN denoising autoencoder와 BPM 헤드 유지 대상 |
| 추론 코드 | `models/air400_detect_v2.py` 존재. `video`, `npz` CLI와 세 가지 결과 상태 구현 |
| v2 체크포인트 | `output/ae_results_v2/air400_ae.pt`, `model_version=2`, 가중치 16개 텐서 정상 로드 |
| 학습 기록 | `best_epoch=67`, `best_val_loss=0.08832445910725838`, `bpm_weight=0.2`, `threshold=1.0177805423736572` |
| 평가 산출물 | `splits.csv`, `valid_scores.csv`, `test_scores.csv` 존재. 이 디렉터리에서 손실곡선 파일은 확인하지 못함 |
| 기존 자동 추출 | `extract_training_waveforms.py`, `normal_pipeline/inference_adapter.py` 및 `output/training_30s` 존재 |
| 원시 출력 | 현재 `infer.py`는 후처리 전 `raw_pred`를 반환하고 `*_raw.hdf5`의 `raw_prediction`, `time_sec`에 저장 |
| NPZ 원시 신호 | 기존 자동 추출기와 v2 영상 모드 모두 `raw_model`을 저장. 추가 모델을 만들 필요 없음 |
| 짧은 영상 처리 | v2 영상 모드는 마지막 30초 미만 구간을 `unscored`로 기록하는 코드가 있음. 기존 CSV에도 60~60.4초 꼬리 제외 기록 존재 |

### 실행 환경

권장 재사용 Python은 `C:\Users\OHS\miniconda3\envs\air400\python.exe`다.

- Python 3.12.16, PyTorch 2.8.0+cu126, torchvision 0.23.0+cu126.
- CUDA 사용 가능, NVIDIA GeForce RTX 2060 확인.
- 실제 import된 OpenCV 4.11.0에서 `cv2.optflow.createOptFlow_DeepFlow` 확인.
- NumPy 2.1.1, SciPy 1.18.1, h5py 3.16.0, matplotlib 3.11.2, PyYAML 6.0.3, ultralytics 8.3.96.
- `opencv-python` 5.1.0.95와 `opencv-contrib-python` 4.11.0.86 배포 메타데이터가 함께 설치되어 있다. 현재 import는 작동하지만 향후 재설치 시 혼동 가능성이 있으므로 자동 정리하거나 교체하지 않는다.
- PATH에서 FFmpeg/ffprobe 9.0.2 설치 경로를 확인했다. 별도로 `normal_pipeline/tools/ffmpeg.exe` 7.1 실행도 확인했다. 재현 실험에서는 사용할 실행 파일을 명시한다.
- 다른 Python인 `C:\Python314\python.exe`도 있으나 h5py가 없고 AIR-400 기준 환경으로 검증하지 않았다.
- `air400` 환경에 Supabase Python SDK는 설치되어 있지 않다. 이번 확인 과정에서 설치하지 않았다.

### 유지할 Windows 변경

실제 코드에서 확인했다.

- `processors/pre_processor.py`: DeepFlow 경로에서 사용하지 않는 무조건 `pyflow` import가 주석 처리되어 있음. 이 상태는 pyflow 방식 자체의 동작을 보장하지 않는다.
- `infer.py`: Windows 파일명에 안전한 `strftime` 사용.
- `infer.py`: `torch.load(..., map_location="cpu", weights_only=True)` 사용.
- `infer.py`: DataLoader `num_workers=0`.
- `models/deep_phys.py`: flatten 단계에 `reshape` 사용.

## 3. 학습 데이터와 점수 재현 결과

저장된 학습 구간은 **773개**, `X.npy`의 기록 shape은 `(773, 1, 300)`이다. 30초·10Hz이며 이 실행의 stride는 **30초**다. 5초 stride는 추출기의 선택 옵션이고, 저장된 이번 학습 데이터가 5초 간격으로 생성된 것은 아니다.

| 분할 | 구간 수 | 저장된 S번호 그룹 | metadata의 데이터셋 포함 영아 ID 수 |
|---|---:|---|---:|
| train | 538 | S01, S03, S04, S05, S06, S08, S10 | 11 |
| valid | 195 | S02, S07 | 3 |
| test | 40 | S09 | 1 |

- 773개 모두 CSV에서는 `is_normal=True`, `valid_input=True`지만 metadata의 `label_status`는 모두 **`unreviewed`**다. 임상적으로 정상임이 확인된 학습 집합이라는 근거는 없다. 실제 학습 CLI와 정상 선택 옵션은 체크포인트에 저장되어 있지 않아 명령 자체는 복원할 수 없다.
- `AIR_125:S01`~`S05`와 `AIR_400:S01`~`S05`가 각각 동일한 S번호 그룹으로 합쳐져 있다. 기본 학습 코드가 폴더명에서 S번호만 추출하기 때문이다. 이후 새 학습이 필요할 때는 실제 metadata의 `subject_id`를 사용하도록 `--subject-key subject_id`를 검토한다. 이번에는 기존 모델을 재학습하지 않았다.
- 저장된 영아 ID, 데이터셋 포함 영아 ID, 영상 ID, 원본 SHA-256 기준으로 train/valid/test 간 교집합은 없었다. 따라서 위의 잘못된 ID 병합을 곧바로 분할 간 누수라고 단정하지 않는다. 실명·원본 수집 메타데이터를 통한 영아 동일성 검증까지 수행한 것은 아니다.
- 검증 195개 및 테스트 40개 NPZ를 현재 v2 체크포인트로 CPU에서 다시 계산했다. 기존 세 점수와의 최대 절대 차이는 각각 `1.430511474609375e-6`, `2.384185791015625e-7`이었다. 전부 허용 오차 `2e-6` 이내였다.
- 저장된 검증 점수의 99% 분위수(`method="higher"`)는 체크포인트 임계값과 정확히 일치했다. 검증 CSV의 이상 후보 1개, 테스트 CSV의 이상 후보 0개는 임상 성능 지표가 아니다.
- 기존 영상 실행 산출물 `output/detect_test_retry2`의 두 NPZ도 재계산했으며 최대 점수 차이는 `2.98e-8`이었다. 이번에는 영상→DeepFlow→DeepPhys 전체를 새로 실행하지 않았다.
- 기존 CLI의 NPZ 모드를 실제로 새 실행하여 1개 구간에 `below_threshold` 결과가 생성되고 종료 코드 0임을 확인했다. 결과는 Codex 산출물의 `v2_npz_cli_20261124/anomaly_scores.csv`에 있다.

재계산 검사 실행 명령:

```powershell
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -B -X utf8 `
  'C:\Users\OHS\air-400\docs\audit_air400_handoff.py'
```

검사 스크립트는 모델을 학습하거나 입력을 수정하지 않는다. 현재 상태를 읽고 실행 파일 옆의 감사 JSON을 갱신한다. 다른 시점에 다시 실행하면 그 시점의 파일 상태를 기록하므로 날짜가 붙은 기존 JSON을 먼저 별도 보관한다.

### 추출 완료 상태와 데이터 파일

`output/training_30s/summary.json`은 `complete_with_errors`다. AIR-125 S03의 001~005.mp4 5개가 FPS 9.997로 정수 FPS 조건을 충족하지 않아 제외되어 있다. 성공한 773구간만 보고 전체 영상 처리가 오류 없이 끝났다고 표현하지 않는다.

로컬 파일 조사에서 AIR-125 MP4 99개/HDF5 125개, AIR-400 MP4 295개/HDF5 275개를 확인했다. 부가 파일과 다운로드 완료 여부를 포함한 공식 원본 manifest 대조는 하지 않았으므로 전체 데이터가 완전하다는 결론은 내리지 않는다.

HDF5 두 파일을 직접 열어 키와 shape를 확인했다. 전체 HDF5의 스키마가 동일한지는 미검증이다.

- `data/AIR_125/S01/001.hdf5`: `filename`, `impulse` `(900,)`, `respiration` `(900,)`.
- `data/AIR_400/S01/out/1.hdf5`: `filename`, `respiration` `(600,)`.

## 4. 현재 생산 경로와 학습 경로의 차이

기존 기능을 재사용하되 동일 전처리라고 단정하지 않는다.

| 항목 | 기존 훈련용 자동 추출기 | v2 영상 추론 |
|---|---|---|
| 영상 FPS | 원본의 정수 FPS 유지 | FFmpeg `fps=15`로 변환 |
| 저장된 학습 구간의 FPS | 10Hz 영상 678개, 15Hz 영상 95개 | 30초당 450프레임 |
| 전처리 chunk | 기존 추론 함수를 재사용하고 `CHUNK_LENGTH=10` 적용 | 450프레임 버퍼에 `DO_CHUNK=False` |
| DeepPhys 프레임 batch | 기존 추론 경로 설정 | 기본 `--frame-batch 16` |
| 10Hz 변환 | polyphase, `padtype="line"` | `resample_poly(resp, 2, 3)`, 기본 경계 처리 |

기존 모델 입력은 `x_10hz` **후처리 파형 300점 + DeepPhys 추정 BPM**이다. `raw_model`을 저장한다고 자동으로 무호흡 분류를 하는 것은 아니다. 현재 v2는 원시 신호를 무호흡 전용 입력으로 사용하지 않는다. 평평하거나 유효하지 않은 입력은 `unscored`로 거절될 수 있다.

현재 `run.json`에 기록된 DeepPhys 체크포인트와 나열된 소스 파일 해시는 현재 설치 파일과 일치했다. 다만 v2 모델 체크포인트 자체에는 추출기 설정·해시·정상 라벨 선택 명령이 없으므로 이 파일 하나로 학습 전체 계보를 증명할 수 없다.

Pi 10FPS 영상을 15FPS로 변환하면 새 관측 프레임이 생기는 것이 아니다. Optical Flow·ROI·경계 처리 차이가 점수에 미치는 영향과 실제 30초 배치 처리 시간은 다음 단계에서 측정한다. 이번 기록은 점수 계산 재현성 확인이며 실시간성·추출 동등성·임상 성능 검증이 아니다.

## 5. 문서 기록으로만 확인되거나 아직 미검증인 사항

- 문서의 Storage 정보: bucket `breathing-video`, prefix `pi-camera/b68d088e-e0d0-4606-a21e-8e2a8099dda3/`, 12자리 번호 TS 파일. prefix ID가 사용자/기기/세션 중 무엇인지는 알 수 없다.
- TS 샘플의 H.264/1280×960/10FPS/약 2초/20프레임과 동일 샘플 15회 결합 성공은 **인수인계 문서의 기존 검사 기록**이다. 이번 로컬 점검에서는 해당 TS 샘플을 확보하여 다시 검사하지 않았다.
- 실제 서로 다른 연속 TS 15개의 누락·중복·시간 연속성·세션 경계·약 30초 결합은 미검증이다. 동일 샘플 반복 결합을 실제 호흡 분석 성공으로 간주하지 않는다. 업로드 간격과 캡처 길이를 구분한다.
- 연결된 Supabase 프로젝트 목록을 읽기 전용으로 확인했다. 활성 프로젝트의 `storage.buckets`에서 정확히 `breathing-video`를 조회한 결과는 없었다. 다른 비활성 프로젝트도 있으나 복구·변경하지 않았다. 따라서 현재 연결에서 대상 프로젝트를 식별하지 못한 것이며 버킷 자체가 존재하지 않는다고 단정하지 않는다.
- 이 프로세스의 관련 Supabase 환경 변수는 설정되어 있지 않았고 AIR-400 루트에서 `.env*` 파일은 발견하지 못했다. 사용자/시스템 전체 환경이나 다른 앱의 비밀 저장소까지 조사한 것은 아니다.
- 실제 대상 프로젝트 URL/ref, 테이블·컬럼·RLS, 사용자/기기 대응, 영상 캡처 timestamp·manifest, 프론트엔드 저장소와 기존 표시 API는 미확인이다.
- 원시 영상부터 시작하는 최신 환경의 전체 재실행, 처리 지연·장시간 안정성·재시도 시험은 이번에 수행하지 않았다.
- 정상 검토·무호흡 정답·외부 검증 데이터·임상 판정 성능은 확보되지 않았다. `below_threshold`는 임계값 이하이며 임상적 정상 판정이 아니다.

## 6. 구현 예정 기능과 다음 작업 순서

AIR-400 루트에서 `storage_inference.py`, 지속 결과 전달 서비스, 프론트엔드 소스는 발견하지 못했다. 문서에 나온 테이블 `breathing_analysis_results` 및 컬럼들은 제안 예시이며 실제 스키마로 채택된 사실이 없다.

1. 대상 Supabase 프로젝트 URL/ref와 실제 업로드 코드·세그먼트 목록·타임라인 정보를 확인한다. 필요한 인증 정보는 로컬 비밀 설정에 저장하고 문서/대화/커밋에 넣지 않는다.
2. 서로 다른 연속 TS를 확보하고 순서·누락·중복·캡처 시간·세션 경계를 검사한다. 길이와 디코딩 결과를 검사하여 실제 30초 배치를 만든다. 단순히 15개라는 이유만으로 30초라고 보장하지 않는다.
3. 기존 `models/air400_detect_v2.py`에 단일 실제 배치를 전달한다. ROI·DeepFlow를 임의로 꺼서 통과시키지 않고, 결과 NPZ·CSV·실행 설정·시간을 보관한다.
4. 실제 DB 스키마와 기존 프론트 코드를 확인한 뒤, 기존 구조에 맞게 결과 저장과 프론트 갱신 인터페이스를 연결한다. 추측으로 새 테이블이나 API를 만들지 않는다.
5. 단일 배치 성공 후 지속 수집기와 결과 전달 프로세스를 추가한다. 재시작 상태, 중복 처리 방지, 제한된 재시도, 오류 기록, backlog/처리 시간 측정을 포함한다.
6. 이후 실제 정상/이상 검토 및 전처리 동등성을 평가하고 필요성이 확인되었을 때 별도 버전으로 개선한다. 기존 체크포인트와 결과를 덮어쓰지 않는다.

결과 상태는 `anomaly_candidate`, `below_threshold`, `unscored`를 보존한다. `unscored`는 점수와 bool을 null로 전달하고 원인을 기록한다. CSV의 문자열 `"False"`에 `bool()`을 적용하지 않는다. 실패·누락을 정상 결과로 변환하지 않는다.

## 7. 보존한 작업 상태

점검 전 AIR-400 Git 상태에서 기존 수정 파일은 `configs/inference/deepphys_deep_infer.yaml`, `infer.py`, `models/deep_phys.py`, `processors/pre_processor.py`였다. 자동 추출기, v1/v2 모델 스크립트, 데이터, `normal_pipeline`, `normal_data`, `pyflow`, `test.mp4` 등도 미추적 상태였다. 이번 작업에서 이를 정리·커밋·리셋하지 않았다.

원본 인수인계 보관본, 이 검증 문서, 감사 JSON·검사 스크립트, AIR-400 루트의 짧은 `AGENTS.md`를 기준 문서로 추가했다. 원본의 과거 기록은 그대로 두고 이 보충 문서에서 확인 수준을 갱신한다. 다음 개발은 위 6절의 단일 실제 배치 검증부터 이어간다.
