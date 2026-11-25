# 영상 수집·분석 / 로컬 결과 보기

변경 기준: 2026-11-25. 현재 작업 폴더는 `C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026`입니다. 기존 DeepPhys·ROI·v2 모델과 Windows 수정사항을 재사용합니다.

**Supabase는 영상 Storage 수집에 사용하고, 이상 탐지 판단 결과는 로컬 파일에 저장합니다.** 결과 테이블 생성과 `supabase_setup.sql` 실행은 현재 기본 흐름에 필요하지 않습니다.

## 저장되는 파일

기본 위치는 저장소의 `output/stream_results/`이며 `.env`의 `RESULT_DIR`로 변경할 수 있습니다.

```text
output/stream_results/
├── analysis_results.csv       전체 판단 기록. Excel용 UTF-8 BOM, 한국어 열 이름
├── latest.md                  최신 구간의 판정·BPM·점수·이유 요약
├── latest.json                최신 구간의 전체 수치와 파형
├── records/<batch_id>.json    구간별 전체 결과
└── analysis_results.sqlite3   중복 방지와 안전한 저장을 위한 내부 원본
```

판단이 저장된 뒤 CSV·요약·JSON 파일이 생성/갱신됩니다. CSV에는 한국 시각, 세션, 시작/끝 번호, 판정, 이상 여부, BPM, 점수, 임계값, 처리 시간과 실패 이유가 들어 있습니다. JSON에는 파형 300점과 원시 출력 450점도 보관합니다.

- 빠르게 보기: `latest.md`.
- 여러 구간 비교/Excel: `analysis_results.csv`.
- 파형 그래프 자동 갱신: 아래 결과 서버의 웹 화면.
- 프로그래밍 연동: `latest.json`, `records/*.json`, 로컬 API.

SQLite 파일은 직접 편집하지 않습니다. 같은 결과 ID를 다시 저장해도 중복 행이 생기지 않습니다. Excel에서 CSV를 열어 파일 교체가 막히면 원본 결과는 DB에 저장되며 경고를 남깁니다. 파일을 닫으면 다음 저장 때 CSV를 다시 갱신합니다. 그동안 웹 화면은 원본 DB의 최신 결과를 읽습니다.

## 설정

`.env`에서 아래 항목을 확인합니다. 이미 입력한 Supabase 키는 그대로 사용할 수 있습니다.

```dotenv
AIR400_ROOT=.
WORK_DIR=output/stream_batches
RESULT_DIR=output/stream_results
```

`AIR400_ROOT=.`는 `.env`가 있는 저장소 폴더를 의미합니다. `WORK_DIR`는 다운로드/분석 진행 상태, `RESULT_DIR`는 판단 결과입니다.

수집기에는 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `STORAGE_BUCKET`, `STORAGE_PREFIX`도 필요합니다. 키는 브라우저나 GitHub에 올리지 않습니다. `STREAM_ID`는 수집기와 결과 서버에서 동일하게 사용합니다. `START_SEQ=auto`는 최초 실행 때 가장 오래된 TS부터 시작합니다.

결과 서버는 Supabase 키 없이 로컬 결과를 볼 수 있습니다. 같은 `RESULT_DIR`, `STREAM_ID`를 사용하면 됩니다. `.env`가 없으면 현재 저장소의 기본 결과 폴더와 기본 세션을 읽습니다.

## 연결 확인과 단일 배치

```powershell
Set-Location 'C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026'
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -X utf8 .\storage_inference.py --check
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -X utf8 .\storage_inference.py --once
```

`--check`는 필수 모델 파일, 실행 파일 경로, Supabase Storage 목록과 로컬 저장 폴더를 확인합니다. 실제 추론은 `--once`에서 수행합니다. 운영 결과 DB에는 쓰지 않습니다.

`--once` 종료 코드 0은 결과 한 건 저장 성공입니다. `unscored`도 저장 성공일 수 있으므로 판정과 이유를 확인하세요. 2는 대기/재시도, 1은 시작·설정·모델 로드 등의 오류입니다.

## 계속 실행

첫 번째 PowerShell 창:

```powershell
Set-Location 'C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026'
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -X utf8 .\storage_inference.py
```

두 번째 PowerShell 창:

```powershell
Set-Location 'C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026'
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -X utf8 .\serve_results.py
```

화면: **http://127.0.0.1:8766**. CSV·MD 파일은 서버를 켜지 않고도 열 수 있습니다. 종료는 각 창에서 `Ctrl+C`입니다. 아직 결과가 없을 때 화면만 보려면 `serve_results.py --preview`를 사용합니다. 미리보기는 가짜 결과를 생성하지 않습니다.

## 처리 규칙과 보존

- 12자리 번호 TS 15개가 모두 연속으로 있어야 시작합니다. 누락 번호를 자동으로 건너뛰지 않습니다.
- 길이 합계는 30±0.25초여야 합니다. 작은 끝부분 차이만 보정하고, 짧은 영상을 반복해 30초를 만들지 않습니다.
- 번호나 TS PTS만으로 실제 촬영 시각 연속성을 확정할 수 없습니다. Pi의 세션/촬영 timestamp 검증은 별도로 필요합니다.
- `anomaly_candidate`는 이상 후보, `below_threshold`는 임계값 이하, `unscored`는 분석 불가입니다. 마지막 상태는 점수·BPM·bool·파형을 null로 보관하고 이유를 표시합니다.
- 실패/누락을 정상 결과로 바꾸지 않습니다. 원시 출력 저장만으로 무호흡 전용 판단이 구현된 것은 아닙니다.
- 완료된 분석은 로컬 outbox를 거쳐 결과 DB에 저장한 뒤 커서를 이동합니다. 저장 실패 시 재개해도 같은 결과 ID를 사용하며 재추론하지 않습니다.
- 이전 실행과 모델/설정/코드가 다르다고 나오면 기존 상태를 보관하고 새 `WORK_DIR`를 사용합니다. 실행 중 `state.json`을 지우거나 고치지 않습니다.
- 세션 또는 번호가 초기화되면 새 prefix, `STREAM_ID`, `WORK_DIR`를 사용합니다. 동시에 여러 세션을 운영할 때는 `RESULT_DIR`도 분리합니다.
- 완료된 TS/MP4는 최근 3배치만 유지합니다. 판단 DB·CSV·JSON·NPZ는 자동 삭제하지 않으므로 디스크 사용량을 확인합니다.
- 이전 위치의 CSV·과거 Supabase 결과를 자동으로 가져오지는 않습니다. 기존 파일과 이력은 그대로 보존합니다.

기존 PC의 30초 배치 처리 측정은 약 85초였습니다. 전체 구간을 순서대로 처리하면 지연이 누적될 수 있습니다. 조회 주기를 줄여도 DeepFlow 추론 병목이 해결되지는 않습니다.

## 로컬 API와 테스트

- `GET /api/results?limit=30`: 로컬 결과와 마지막 조회 성공 시각/오류. `source=local`.
- `GET /api/health`: 조회 상태. 키·환경 파일은 제공하지 않음.
- 기존 결과 필드와 세 가지 상태는 유지합니다. `created_at`은 결과 저장 시각이며 촬영 시각이 아닙니다.

```powershell
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -B -X utf8 -m unittest discover -s .\babycam_tests -v
```

팀 설치 안내는 [TEAM_SETUP.md](TEAM_SETUP.md)를 참고합니다. 2026-11-24 인수인계/검증 문서의 옛 경로와 원격 결과 저장 설명은 과거 기록이며, 현재 실행은 이 문서를 따릅니다.
