# 지속 분석 서비스 검증 및 작업 상태

확인일: 2026-11-24, 한국 시간.

## 구현한 파일

- `storage_inference.py`: 지속 영상 수집/결합/기존 추론/결과 저장의 실행 진입점.
- `serve_results.py`: 지속 결과 조회와 로컬 화면/API 실행 진입점.
- `babycam/common.py`: 환경 설정·Supabase Storage/Data REST API·입출력 검증.
- `babycam/worker.py`: 배치·FFmpeg·기존 v2 모델 재사용·상태/outbox·파일 잠금.
- `babycam/web.py`, `babycam/static/*`: 결과 조회 캐시와 기본 프론트.
- `.env.example` 및 빈 값으로 생성한 `.env`: 프로젝트 URL과 서버 전용 키를 사용자가 채움.
- `supabase_setup.sql`: 새로운 결과 테이블을 준비하는 SQL. 실제 대상 프로젝트에는 적용하지 않음.
- `BABYCAM_SERVICES.md`: 키 위치, SQL 준비, 두 PowerShell 실행, 재시작/오류 동작 안내.

## 검증 결과

1. 최신 구현의 자동 테스트 **24개 통과**. 연속 번호 선택·누락 대기·짧은 입력 거절·Windows 경로·opaque 키 헤더·페이지네이션·중단된 HTTP 응답·문자열 False·unscored null 처리·재시작 outbox·동일 batch_id 재시도·입력 변경 중단·단일 프로세스 잠금·로컬 API 및 Host 보호 등을 확인했다.
2. 기존 로컬 `C:\Users\OHS\air-400\test.mp4`의 첫 30초를 **서로 다른 연속 2초 구간 15개**로 잘라 TS 테스트 입력을 만들었다. 동일 TS 반복으로 만들지 않았다.
3. 실제 FFmpeg 결합 및 기존 ROI/DeepFlow/DeepPhys/v2 모델을 실행했다. Storage/Data API는 localhost 모의 서버로만 연결했다. 실제 Supabase에는 데이터를 보내지 않았다.
4. 결과: 30초 MP4, 후처리 파형 300점, 원시 출력 450점, BPM `40.4296875`, 점수 `0.11251972615718842`, 상태 `below_threshold`. 커서가 0에서 15로 이동하고 원격 모의 결과 1개가 저장되었다. 이는 임상 판정 검증이 아니다.
5. 한 배치 처리 시간 **85.094초**. 약 70초가 DeepFlow 계산에 사용되었다. 모든 30초 배치를 순차 처리하면 지연이 누적될 수 있으며 현재는 실시간 처리 속도를 보장하지 않는다.
6. 실제 Chrome에서 파형·BPM·점수 표시, 빈 결과 대기와 기존 값 초기화, 새 unscored 결과 자동 갱신과 파형/점수 비우기, 조회 오류 시 이전 결과 및 오류/마지막 성공 시간 표시를 확인했다. 브라우저 console error는 없었다.
7. 모의 통합 서버와 UI 검증 서버는 검증 후 종료했다. 실제 서비스를 상시 실행해 둔 상태는 아니다.

검증용 산출물은 `C:\Users\OHS\Documents\Codex\2026-11-18\referenced-chatgpt-conversation-this-is-an\outputs\babycam_verification`에 있다. 서비스의 실제 결과와 혼동하지 않도록 운영 WORK_DIR에 복사하지 않았다.

첫 통합 실행에서 기존 Ultralytics 버전이 사용자 전역 설정의 낯선 `openvino_msg` 항목을 경고하고 기본 설정 파일을 다시 생성했다. 모델 로드와 추론은 성공했다. 이후 서비스는 `YOLO_CONFIG_DIR`를 작업 폴더 안으로 분리하도록 보완했다. 기존 모델·Windows 수정 소스는 수정하지 않았다.

## 운영 연결에 남은 일

- 사용자가 `.env`에 대상 프로젝트 URL과 Secret 또는 legacy service_role 키를 입력.
- 사용자가 대상 Supabase의 SQL Editor에서 신규 결과 테이블 SQL을 실행.
- `storage_inference.py --check`로 해당 Storage/테이블 접근 확인.
- 실제 Pi에서 업로드된 서로 다른 연속 TS 15개로 `--once` 검증. 번호뿐 아니라 실제 촬영 시간 연속성과 세션 경계 확인 필요.
- 실제 결과가 갱신되는 것을 확인한 뒤 두 프로그램을 지속 실행.
- 처리 속도가 필요 수준에 못 미치면 별도 측정 후 DeepFlow 경로를 개선. 현재 학습 라벨/영아 ID/전처리 차이 및 무호흡 검증 한계는 기존 검증 문서에 기록한 상태를 유지.

원본 인수인계와 `docs/AIR400_HANDOFF_VERIFIED_20261124.md`는 이 작업 이전의 기록으로 보존한다. 새 서비스의 현재 실행 방법과 상태는 `BABYCAM_SERVICES.md` 및 이 문서를 함께 읽는다.
