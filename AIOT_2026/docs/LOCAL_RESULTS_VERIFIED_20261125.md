# 새 작업 루트와 로컬 결과 저장 검증

기준일: 2026-11-25, 한국 시간.

## 현재 결정

- 작업 루트: `C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026`.
- Supabase는 영상 Storage 수집에만 사용한다. 판단 결과는 이 PC의 `RESULT_DIR`에 저장한다.
- 기본 결과 폴더는 `output/stream_results`, 기본 화면 주소는 `http://127.0.0.1:8766`이다.
- `.env`의 입력된 키와 기존 다른 설정을 보존하고 루트·로컬 결과 경로·포트만 변경했다.
- 기존 DeepPhys/v2/ROI 가중치, 전처리와 Windows 수정 코드는 변경하지 않았다. 자동 학습 추출기의 기본 루트만 현재 스크립트 위치로 바꿨다.

## 구현과 보존

`babycam/local_results.py`가 SQLite 원본에 결과 ID로 중복 없이 저장한다. 같은 ID의 재시도는 최초 내용과 저장 시각을 보존한다. 이후 `analysis_results.csv`, `latest.md`, `latest.json`, `records/<batch_id>.json`을 갱신한다. CSV는 한국어 헤더·한국 시각·UTF-8 BOM을 사용한다.

Excel 파일 잠금 때문에 CSV 교체가 실패해도 이미 확정된 원본은 잃지 않으며 다음 저장 때 내보내기를 재시도한다. 원본 저장 실패는 outbox/커서를 유지한다. `unscored`의 점수·BPM·bool·파형은 null로 유지한다.

`serve_results.py`는 로컬 원본을 조회한다. 실제 실행 파일을 Supabase 키가 없는 별도 로컬 설정으로 시작해 화면을 확인했다. 현재 수집기는 Supabase 결과 API를 호출하지 않는다. 기존 원격 결과 메서드와 SQL은 과거 방식의 보관/호환 파일로 남겨 두었다.

이전 위치의 결과·과거 DB 데이터는 자동 이관하지 않았다. 2026-11-24 인수인계 문서는 그 당시의 기록으로 보존했다. 현재 설정과 실행은 `BABYCAM_SERVICES.md`, `TEAM_SETUP.md`를 따른다.

## 검증 근거

1. 자동 테스트 **34개 통과**. 로컬 저장/재시작/중복/세션 필터, CSV 수식 이스케이프, Excel 잠금, 키 없는 결과 조회, 기존 배치/HTTP 로직을 확인했다.
2. 새 작업 폴더의 `test.mp4`에서 서로 다른 연속 2초 TS 15개를 만들었다. 실제 FFmpeg와 기존 ROI/DeepFlow/DeepPhys/v2를 실행했다. Storage API만 localhost 모의 서버로 제공했고, 결과 Data API 요청 수가 0임을 검사했다.
3. 실제 모델 결과: 30초, 10Hz 파형 300점, 원시 출력 450점, BPM `40.4296875`, 이상 점수 `0.11251972615718842`, 상태 `below_threshold`. 처리 시간은 **86.969초**였다. 커서는 0에서 15로 진행했고 로컬 원본/CSV/MD/JSON이 생성됐다.
4. 검증 산출물은 `output/local_results_verification_20261125/results`에 분리했다. 운영 결과 폴더에는 CSV 헤더만 초기화했으며 가짜 판단 행을 넣지 않았다.
5. 실제 Chrome에서 로컬 원본의 파형·BPM·상태와 `로컬 결과 · 자동 갱신 중` 표시를 확인했다. console error는 없었다. 검증용 결과 서버는 확인 후 종료했다.
6. 8765에서 다른 로컬 서비스가 사용 중인 것을 확인했다. 다른 서비스는 변경하지 않았다. Windows에서 포트를 공유해 잘못된 화면이 열리는 문제를 테스트로 재현한 뒤 재사용 금지와 `SO_EXCLUSIVEADDRUSE`로 수정했고 중복 포트 거절 테스트를 통과했다. [Microsoft 소켓 공식 설명](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse)

실제 Pi 업로드의 시간 연속성과 운영 Supabase Storage 연결은 이번 로컬 검증에 포함되지 않는다. 30초마다 전 구간을 분석하면 현재 속도에서 지연이 누적될 수 있다. 이 결과는 임상 성능 검증이 아니다.
