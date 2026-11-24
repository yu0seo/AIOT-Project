# Supabase 영상 수집·분석 / 결과 표시 실행 안내

설치 위치는 `C:\Users\OHS\air-400`입니다. 기존 DeepPhys·ROI·v2 이상 탐지 모델을 그대로 불러오며 재학습하지 않습니다. Supabase SDK 등 추가 패키지는 필요 없습니다. 기존 `air400` Conda 환경과 PATH의 FFmpeg/ffprobe를 사용합니다.

## 두 프로그램의 역할

| 프로그램 | 계속 수행하는 작업 |
|---|---|
| `storage_inference.py` | Supabase Storage 조회 → 연속 TS 15개 다운로드 → 길이/포맷 검사 → 30초 MP4 → 기존 DeepPhys/v2 → Supabase 결과 저장 |
| `serve_results.py` | Supabase 결과를 2초마다 읽기 → 로컬 API/화면 제공 → 브라우저에서 1초마다 자동 갱신 |

영상은 문서에 나온 Storage 버킷에서 가져옵니다. PostgreSQL 테이블에 영상 바이너리가 들어 있다는 가정은 하지 않습니다. 프론트가 아직 없으므로 파형·BPM·상태·최근 30개 결과를 보여주는 기본 화면을 포함했습니다.

## 1. `.env`에 두 항목 입력

`C:\Users\OHS\air-400\.env`를 메모장 또는 VS Code로 엽니다. 빈 파일도 함께 만들어 두었습니다.

```dotenv
SUPABASE_URL=https://프로젝트-ref.supabase.co
SUPABASE_SECRET_KEY=서버전용키
```

| 항목 | 어디서 찾는지 / 무엇을 넣는지 |
|---|---|
| `SUPABASE_URL` | Supabase 대상 프로젝트의 Connect 또는 Settings → Data API/API의 Project URL |
| `SUPABASE_SECRET_KEY` | Settings → API Keys의 **Secret key (`sb_secret_...`)**. 또는 Legacy API Keys의 **service_role** 키. 둘 중 하나 |

키는 대시보드에서 직접 찾아 `.env`에만 입력하세요. 채팅에 붙여넣을 필요는 없습니다. `anon`, `sb_publishable_...`, DB 비밀번호, Personal Access Token은 이 서버 설정에 사용하지 않습니다. 브라우저는 Python API만 사용하며 Supabase 키를 받지 않습니다. 기존 `.gitignore`가 `.env`를 제외합니다.

기본값이 들어 있는 아래 항목도 현재 버킷과 일치하는지 확인합니다.

```dotenv
STORAGE_BUCKET=breathing-video
STORAGE_PREFIX=pi-camera/b68d088e-e0d0-4606-a21e-8e2a8099dda3
STREAM_ID=babycam-session-1
START_SEQ=auto
```

- `START_SEQ=auto`: 첫 실행에서 해당 prefix의 가장 오래된 TS부터 처리합니다. 이전 영상이 많으면 밀린 순서대로 처리합니다. 특정 번호부터 시작하려면 처음 실행 전에 `START_SEQ=210`처럼 설정합니다.
- 재시작하면 `WORK_DIR`의 커서를 사용합니다. 모델·입력·시작 번호 설정을 바꾸면 새 `WORK_DIR`를 지정해야 합니다. 키 교체와 조회 주기 변경에는 기존 커서를 재사용할 수 있습니다.
- 업로더가 번호를 0으로 초기화하거나 다른 촬영 세션을 시작하면 새 Storage prefix와 `STREAM_ID`, `WORK_DIR`를 사용합니다. 같은 번호의 TS를 덮어쓰는 방식은 지원하지 않습니다.
- `.env`는 `KEY=VALUE` 또는 따옴표로 감싼 값만 사용합니다. 같은 행 뒤에 주석을 붙이지 않습니다. 셸 환경 변수가 있으면 파일 값보다 우선합니다.

## 2. 결과 테이블 준비: SQL 1회 실행

대상 Supabase 프로젝트의 **SQL Editor**에서 `C:\Users\OHS\air-400\supabase_setup.sql` 전체를 실행합니다. 새 테이블 `public.babycam_analysis_results`를 만듭니다. 기존 영상 버킷과 다른 테이블은 수정하지 않습니다. 같은 테이블명이 이미 있으면 실행이 중단되므로 기존 스키마를 먼저 확인합니다.

테이블은 RLS를 켜고 `anon`/`authenticated` 접근을 허용하지 않습니다. 신뢰된 Python 서버의 secret/service_role 키로만 읽기·쓰기를 합니다. 현재 화면은 로컬 PC 전용이며, 원격 공개 서비스와 사용자 로그인은 구현 범위에 포함되어 있지 않습니다.

## 3. 연결 확인 및 단일 배치 실행

PowerShell에서 그대로 실행합니다.

```powershell
Set-Location 'C:\Users\OHS\air-400'
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -X utf8 .\storage_inference.py --check
```

`--check`는 설정·필수 모델 파일·FFmpeg/ffprobe·Storage 목록·결과 테이블 조회를 확인합니다. 추론하거나 결과를 쓰지는 않습니다.

처음에는 한 배치만 실행합니다.

```powershell
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -X utf8 .\storage_inference.py --once
```

종료 코드 0은 한 배치 저장 성공, 2는 TS 부족/네트워크 오류/재시도 대기입니다. TS가 충분히 업로드된 뒤 다시 실행하거나 아래 지속 실행 모드를 사용합니다. CSV/화면에서 `unscored`가 나왔으면 DB 저장 성공과 호흡 분석 성공을 구분하고 원인을 확인합니다.

## 4. 두 창에서 계속 실행

첫 번째 PowerShell 창:

```powershell
Set-Location 'C:\Users\OHS\air-400'
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -X utf8 .\storage_inference.py
```

두 번째 PowerShell 창:

```powershell
Set-Location 'C:\Users\OHS\air-400'
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -X utf8 .\serve_results.py
```

브라우저에서 **http://127.0.0.1:8765**를 엽니다. HTML 파일을 직접 열지 않습니다. 종료는 각 창에서 `Ctrl+C`입니다. PC가 꺼지거나 절전 상태가 되면 실행도 멈춥니다.

키를 넣기 전에 화면만 보려면:

```powershell
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -X utf8 .\serve_results.py --preview
```

미리보기는 빈 대기 화면만 제공하며 분석 결과를 생성하지 않습니다. 실제 모드와 같은 포트를 사용하므로 하나만 실행합니다.

## 처리 조건과 오류 동작

- `000000000210.ts`처럼 12자리 TS 파일명을 사용합니다. 연속 번호 15개가 모두 있어야 시작합니다. 빠진 번호를 임의로 건너뛰지 않습니다.
- 15개 합계가 **30±0.25초** 범위여야 합니다. 짧은 입력을 반복해 30초로 늘리지 않습니다. 이 범위 안의 작은 끝부분 차이만 마지막 프레임 연장/잘라내기로 보정하고 그 양을 결과에 기록합니다.
- 번호 연속성은 실제 촬영 시간의 연속성을 증명하지 못합니다. TS PTS가 연속되면 참고 기록을 남기지만 실제 capture timestamp 검증을 대신하지 않습니다. 문서의 같은 TS 15회 반복 실험을 실제 분석 데이터로 사용하지 않습니다.
- 기존 모델은 후처리 파형 300점과 DeepPhys 추정 BPM을 사용합니다. 원시 출력 450점도 보관하지만 무호흡 전용 판정을 새로 구현한 것은 아닙니다.
- `below_threshold`는 임계값 이하, `anomaly_candidate`는 이상 후보, `unscored`는 분석 불가입니다. 분석 불가는 점수·BPM·bool·파형을 null로 저장합니다.
- 네트워크 오류는 커서를 유지하고 재시도합니다. 분석을 마친 뒤 DB 저장만 실패하면 로컬 outbox를 다시 올리며 재추론하지 않습니다. 같은 batch_id 저장은 중복 무시됩니다.
- 잘못된 영상/처리 오류는 최대 3회 시도 후 `unscored`로 저장하고 다음 배치로 진행합니다. 입력 TS 덮어쓰기를 감지하면 수집기를 중단합니다. 같은 WORK_DIR 수집기 중복 실행도 거부합니다.
- `output/stream_batches/state.json`은 재개 상태입니다. 실행 중 삭제/수정하지 않습니다. 배치별 manifest, MP4, `inference_*/windows/*.npz`, CSV, result.json을 남깁니다. 완료된 원본 TS/결합 MP4는 최근 3배치만 보관하고, 작은 NPZ/CSV/결과는 유지합니다.
- DB 연결 오류가 나면 화면은 마지막 결과와 오류·마지막 성공 시간을 함께 표시합니다. 이전 결과를 새 분석 결과로 바꾸지 않습니다.

**처리 속도:** 이 PC의 실제 기존 모델로 로컬 30초 배치 하나를 검증한 처리 시간은 약 **85초**였습니다. 30초마다 모든 구간을 분석하면 backlog가 누적됩니다. 현재 프로그램은 순서대로 전부 처리하며 자동으로 구간을 버리지 않습니다. 실시간성을 확보하려면 별도 측정과 기존 DeepFlow 경로 최적화가 필요합니다.

## 결과 API와 추후 프론트 연동

- `GET http://127.0.0.1:8765/api/results?limit=30`: `{results, last_success_at, error, mode, server_time}`.
- `GET http://127.0.0.1:8765/api/health`: 마지막 조회 성공 시각/오류/모드.
- 결과 필드: `batch_id`, `stream_id`, `start_seq`, `end_seq`, `status`, `is_anomaly`, `anomaly_score`, `threshold`, `pred_rr_bpm`, `wave_mse`, `bpm_mse`, `waveform`, `reason`, `created_at`, `duration_sec`, `source_duration_sec`, `continuity`, `processing_sec`, `model_signature`.
- `waveform.x_10hz`는 300점, `waveform.raw_model`은 450점입니다. 각각 fs=10, raw_fs=15입니다. 결과 서버는 `.env`, 영상 파일, 로컬 임의 파일을 제공하지 않습니다.
- 화면과 API는 localhost 전용입니다. 추후 외부 프론트/모바일 앱으로 확장할 때 인증·사용자별 권한·HTTPS를 기존 앱 구조에 맞게 추가합니다.

## 검증 범위와 참고

로컬 HTTP 모의 Supabase, 누락/짧은 배치, bool/null 처리, 재시작·중복·저장 실패, 기본 웹/API를 테스트했습니다. 로컬 `test.mp4`의 서로 다른 연속 2초 구간 15개로 FFmpeg→기존 모델→모의 Storage/DB→화면 흐름을 검증했습니다. 실제 Supabase 운영 프로젝트와 Pi의 실제 TS 연속성은 키 입력 후 `--check`, `--once`로 확인해야 합니다. 실 Supabase 스키마 SQL은 대상 프로젝트에 자동 적용하지 않았습니다.

현재 공식 문서에 맞춰 신규 secret 키는 `apikey` 헤더에, legacy service_role JWT는 `apikey`와 Bearer 헤더에 넣습니다. 재시도 저장은 PostgREST의 `resolution=ignore-duplicates`를 사용합니다.

- [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys)
- [Storage list API 공식 구현](https://github.com/supabase/storage-js/blob/main/src/packages/StorageFileApi.ts)
- [Supabase 비공개 파일 다운로드](https://supabase.com/docs/reference/python/storage-from-download)
- [PostgREST upsert](https://docs.postgrest.org/en/stable/references/api/tables_views.html#upsert)

테스트 실행:

```powershell
& 'C:\Users\OHS\miniconda3\envs\air400\python.exe' -B -X utf8 -m unittest discover -s .\babycam_tests -v
```

`babycam_tests`는 배포 시 설치한 테스트 폴더입니다. 원본 묶음 안에서는 같은 명령의 경로를 `tests`로 사용합니다. 로컬 통합/브라우저 fixture는 검증 전용이며 실제 서비스 대신 실행하는 파일이 아닙니다.
