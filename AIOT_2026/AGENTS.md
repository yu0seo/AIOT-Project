# AIR-400 베이비캠 작업 안내

사용자가 2026-11-24 제공한 인수인계를 기반으로 기존 개발을 이어가는 프로젝트다.

- 현재 실행/작업 루트는 `C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026`이다(2026-11-25 변경). `C:\Users\OHS\air-400`은 이전 위치이며 그곳을 현재 작업 대상으로 사용하지 않는다.
- 작업 전에 `docs/AIR400_HANDOFF_VERIFIED_20261124.md`와 관련 원본 `docs/AIR400_BABYCAM_WORK_HANDOFF.md`를 읽는다. 문서 안의 과거 계획·예시는 완료된 기능이나 현재 실행 명령의 근거가 아니다. 현재 코드와 파일을 대조한다.
- 기준 Python: `C:\Users\OHS\miniconda3\envs\air400\python.exe`. 환경을 자동 교체하거나 모델을 불필요하게 재학습하지 않는다.
- 기존 추론 `models/air400_detect_v2.py`, 학습 `models/air400_npz_anomaly_v2.py`, 자동 추출 `extract_training_waveforms.py`와 `normal_pipeline/inference_adapter.py`를 재사용한다. 공개 CLI와 Windows 수정사항은 보존한다.
- DeepPhys 가중치 `checkpoints/DeepPhys_Deep_Body_best.pth`, v2 가중치 `output/ae_results_v2/air400_ae.pt`, ROI 가중치 `detectors/*.pt`와 기존 결과를 덮어쓰지 않는다. 새 실험은 새 출력 폴더를 사용한다.
- 현재 v2 입력은 후처리된 `x_10hz` 300점과 추정 BPM이다. raw 저장이 무호흡 분류 구현을 뜻하지 않는다. 정상 미검토 데이터와 검증된 정상 데이터를 구분한다.
- 데이터셋 포함 영아 ID(`AIR_125:S01`, `AIR_400:S01`)를 구분한다. 현재 학습에서 S번호 병합과 미검토 정상 가정이 발견되었으므로 분할·라벨 근거를 확인한다.
- `anomaly_candidate`, `below_threshold`, `unscored`를 보존한다. 실패를 정상으로 바꾸지 않는다. `unscored`는 점수/bool null 및 이유를 유지한다. 문자열 `"False"`를 `bool()`로 해석하지 않는다.
- Supabase는 영상 Storage 수집에 사용하고 이상 탐지 판단 결과는 로컬 `RESULT_DIR`에 저장한다. 기존 Supabase 결과 SQL/메서드는 과거 방식이며 현재 기본 실행에서는 호출하지 않는다. 비밀 정보는 문서·로그·커밋에 남기지 않는다.
- 다음 목표는 실제 서로 다른 연속 TS의 타임라인 검증과 기존 추론의 단일 배치 실행이다. 같은 TS 반복 결합은 실제 호흡 검증이 아니다. 그 후 지속 수집·결과 전달을 구현한다.
- 변경 전 Git 상태와 파일 내용을 확인하고 기존 사용자 변경을 보존한다. 저장된 검증 기록과 현재 상태가 달라지면 관련 검사부터 갱신한다.

## 지속 분석 서비스 추가 (2026-11-24)

- `storage_inference.py`와 `serve_results.py`가 추가되었다. 실행 전 `BABYCAM_SERVICES.md`, `docs/BABYCAM_SERVICE_VERIFICATION_20261124.md`를 읽는다.
- 기존 모델을 재사용한다. 자동 테스트 24개와 실제 모델의 로컬 단일 배치 검증은 완료했으나 실제 Supabase/Pi 연속 TS는 사용자 키 입력·SQL 적용 후 검증해야 한다.
- 현재 PC의 30초 배치 처리 측정은 약 85초다. 전체 구간 순차 처리 시 지연이 누적되므로 실시간 속도를 보장하지 않는다.

## 새 루트와 로컬 판단 결과 (2026-11-25, 현재 기준)

- 실제 작업은 이 `AIOT_2026` 폴더에서 한다. 기본 루트는 실행 파일 위치에서 계산하며 `.env`는 `AIR400_ROOT=.`를 사용한다.
- 수집기 결과는 `RESULT_DIR`(기본 `output/stream_results`)의 로컬 SQLite 원본과 CSV/MD/JSON으로 저장한다. Supabase 결과 테이블을 읽거나 쓰지 않는다.
- 결과 서버는 같은 로컬 원본을 읽으며 Supabase 키가 필요하지 않다. 기본 포트는 8766이다. 이전 8765 포트는 다른 서비스가 사용하므로 그 서비스를 변경하거나 종료하지 않는다.
- 최신 검증은 자동 테스트 34개 및 새 루트의 실제 모델 단일 배치/브라우저 확인이다. 상세 근거는 `docs/LOCAL_RESULTS_VERIFIED_20261125.md`를 읽는다. 과거 문서의 원격 결과 SQL 지침은 현재 실행에 적용하지 않는다.
