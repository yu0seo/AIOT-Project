# Pi → Supabase → PC 영상 전송

Pi가 **10FPS 영상을 2초(20프레임)씩** Supabase의 비공개 Storage에 직접 업로드합니다.
DB에는 카메라 ID, 촬영 세션, 순번, 촬영 시작·종료 시각, 파일 경로, 만료 시각을 기록합니다.
PC는 업로드가 끝난 최신 15개 조각을 받아 **30초·300프레임 MP4**로 묶습니다.
AIR-400과 학습 모델의 코드·가중치는 변경하지 않습니다. 생성된 MP4가 이후 모델 연결 지점입니다.

## 구성된 원격 자원

- 프로젝트: `yu0seo's Project` (`wwkphksqyjqsjouoamly`)
- Storage: `breathing-video` — 비공개, TS 영상만 허용, 조각당 최대 8MiB
- DB: `breathing_video_devices`, `breathing_video_settings`, `breathing_video_segments`
- Edge Function: `breathing-video` — 장치 인증, 업로드 예약, 최신 30초 조회, 파일 삭제
- Cron: `breathing-video-retention` — 10초마다 만료된 실제 파일과 메타데이터 삭제
- Cron: `breathing-video-cron-log-prune` — 이 두 작업의 실행 기록 중 1일 지난 기록만 정리

만료 기준은 **각 조각의 촬영 시작 시각 + 180초**입니다. 3분이 지난 조각은 조회에서 즉시 제외합니다.
실제 파일 삭제는 다음 10초 주기의 작업에서 진행되므로 정상 상태에서도 그만큼의 지연이 있으며,
서비스 오류 때는 다음 작업에서 재시도합니다. PC가 꺼져 있어도 삭제 작업은 Supabase에서 실행됩니다.
DB 행만 지우지 않고 Storage API로 실제 파일을 먼저 삭제합니다.

Pi는 30초마다 다음 15개 업로드 주소를 예약하고, 완성된 2초 조각부터 바로 전송합니다.
카메라는 한 번 열어 계속 촬영하며, 업로드 동안에도 촬영을 이어갑니다.
미전송 영상이 3분을 넘기면 버리고, 빈 구간을 중복 프레임으로 채우지 않습니다.
PC는 같은 촬영 세션의 연속된 300프레임이 있어야 출력합니다.
DB의 촬영 시각은 프로그램 시작 시각과 영상 PTS 차이를 조합한 추정 시각입니다.
센서 노출 시각과 정밀 동기화한 값은 아닙니다. MP4에는 원래 프레임 간격을 유지합니다.

## 접속 설정

현재 PC에 준비한 설정 파일:

```text
C:\Users\dndud\AppData\Local\AIOT-SupabaseVideo\supabase_pi.json
C:\Users\dndud\AppData\Local\AIOT-SupabaseVideo\supabase_pc.json
```

두 파일은 서로 다른 업로드 전용·읽기 전용 장치 키를 갖습니다.
서버 전체 접근 키는 파일에 없으며, Supabase Edge Function 내부에서만 사용합니다.
DB에는 장치 키의 SHA-256 해시만 있습니다. 파일은 Git에 올리지 않습니다.
`supabase_pi.json`만 Pi로 복사하고, PC 설정은 PC에 둡니다.

## 현재 Pi 설치 상태

2026-11-22에 `pi@172.17.163.125`의 `/home/pi/aiot-supabase-video`에
`upload.py`, `client.py`, 업로드 전용 설정을 설치했습니다.
Python 3.13.5, FFmpeg, rpicam 프로그램이 이미 설치되어 있어 패키지를 추가하지 않았습니다.
실제 OV5647 카메라로 40초 제한 시험을 실행하고 정상 종료를 확인했습니다.
상시 촬영이나 자동 시작은 설정하지 않았습니다.

Pi 터미널에서 다시 시작하려면:

```bash
python3 /home/pi/aiot-supabase-video/upload.py
```

설정 파일 권한은 Pi 사용자만 읽고 쓸 수 있는 `600`입니다.
접속에 사용한 PC 전용 SSH 키는 PC의 `C:\Users\dndud\AppData\Local\AIOT-SupabaseVideo\ssh`에 보관합니다.
Pi IP는 네트워크가 바뀌면 달라질 수 있습니다.

## Pi 카메라 화면만 보기

Pi에 설치한 별도 프로그램을 실행하면 Pi 바탕화면/VNC 화면에 카메라 미리보기가 열립니다.
Supabase 접속이나 영상 저장 없이 카메라를 직접 표시합니다.
`upload.py`가 실행 중이면 그 터미널에서 먼저 Ctrl+C로 종료합니다.

```bash
python3 /home/pi/aiot-supabase-video/preview_camera.py
```

전송 프로그램과 같은 OV5647 전체 화각, 10FPS, 1280×960 기준입니다.
창을 닫거나 Ctrl+C로 종료한 뒤 `upload.py`를 실행하면 전송을 다시 시작할 수 있습니다.
같은 카메라를 두 프로그램에서 동시에 열지는 않습니다.
`--duration 3`을 붙이면 3초 후 자동 종료합니다.
VNC에서도 일반 창으로 표시하도록 [공식 Qt 미리보기 옵션](https://www.raspberrypi.com/documentation/accessories/camera-software.html#qt-preview)을 사용합니다.

## Pi 새로 설치·실행

Pi의 같은 폴더에 다음 세 파일을 둡니다.

```text
upload.py
client.py
supabase_pi.json
```

Pi에서 필요한 프로그램을 설치하고 실행합니다.

```bash
sudo apt update
sudo apt install -y ffmpeg rpicam-apps
python3 upload.py --config supabase_pi.json
```

기본값은 확인된 OV5647 모듈에 맞춘 10FPS, 1280×960, 2Mbps,
전체 화각 센서 모드 `1296:972:10`입니다. 다른 카메라는 `--mode auto`로 실행할 수 있습니다.
기존 카메라 프로그램이 실행 중이면 먼저 종료해 카메라를 비워야 합니다.
Pi 시각이 서버와 5초 이상 다르면 시작을 중단하므로 시간 자동 동기화가 켜져 있어야 합니다.
Ctrl+C로 촬영과 업로드를 함께 종료합니다.
40초만 시험 촬영하려면 `python3 upload.py --config supabase_pi.json --duration 40`으로 실행합니다.

카메라를 열지 않고 실제 촬영 명령만 확인하려면:

```bash
python3 upload.py --print-command
```

## PC 실행

현재 PC에는 모델 환경과 분리된 다운로드 환경을 준비했습니다.
저장소 최상위 폴더에서 PowerShell로 실행합니다.

```powershell
& 'C:\Users\dndud\AppData\Local\AIOT-SupabaseVideo\env\Scripts\python.exe' '.\AIOT_2026\supabase_video\fetch.py' --watch-dir '.\AIOT_2026\data\supabase_video\windows'
```

30초마다 최신 30초를 조회합니다. 최초 30초가 모이기 전에는 대기 메시지가 나오고,
파일이 준비되면 MP4와 촬영 시각을 담은 JSON을 저장합니다.
이번 실행에서 만든 출력은 최신 6쌍만 유지합니다. 실행 전부터 있던 출력은 삭제하지 않습니다.
PC 출력에 적용하는 6개 제한과 Supabase 서버의 3분 보관 정책은 별도입니다.
다시 시작할 때 기존 파일을 보존하므로 PC 폴더는 필요에 따라 따로 관리합니다.

한 번만 받으려면 새 파일명을 지정합니다.

```powershell
& 'C:\Users\dndud\AppData\Local\AIOT-SupabaseVideo\env\Scripts\python.exe' '.\AIOT_2026\supabase_video\fetch.py' --output '.\AIOT_2026\data\supabase_video\latest30_001.mp4'
```

기존 출력 파일은 덮어쓰지 않습니다. 입력이 멈춘 지 10초 넘은 영상, 조각 누락,
10FPS·300프레임 불일치, 해상도 변경은 정상 입력으로 내보내지 않습니다.
TS를 MP4로 묶을 때 영상은 재인코딩하지 않습니다. 다운로드 주소는 JSON에 저장하지 않습니다.

다른 Windows PC의 환경을 만들려면 `python .\AIOT_2026\supabase_video\install_pc.py`를 실행하고
읽기 전용 PC 설정을 해당 PC에 복사합니다. PostgreSQL 로컬 설치는 필요하지 않습니다.

## 검증

`tests/test_edge.mjs`: 연속 구간 검사, 누락·오래된 영상·미래 시각 차단,
장치 인증, 새 Supabase 서버 키 전달 방식, 요청 크기 제한을 검사합니다.

```powershell
node .\AIOT_2026\supabase_video\tests\test_edge.mjs
```

`tests/test_cloud.py`는 별도로 등록한 테스트 카메라로 실제 Storage 업로드·다운로드,
권한 분리, 중복 업로드·예약 재시도, 만료 차단, 300프레임 복원과 픽셀 동일성을 검사합니다.
`tests/test_replay.py`는 카메라 대신 10FPS·2초 키프레임 간격의 테스트 파일로
실제 업로더와 다운로더를 함께 실행합니다. 운영용 `pi-camera`로는 테스트하지 않습니다.

클라우드 시험에서 만료 처리한 영상 30개가 예약 작업으로 실제 삭제되는 것도 확인했습니다.
실제 Pi 시험에서도 1280×960, 약 10FPS의 연속된 300프레임을 PC에서 복원했습니다.
출력은 `AIOT_2026/data/supabase_video/pi_camera_30s_001.mp4`이며 길이는 약 29.9996초,
가장 긴 프레임 간격은 약 0.1004초였습니다. 시험 뒤 Pi 촬영 프로세스가 종료된 것도 확인했습니다.
이 실제 촬영분도 촬영 시작 기준 3분이 지난 뒤 예약 작업으로 Storage에서 모두 삭제되는 것을 확인했습니다.
이 시험은 전송 경로 검증입니다. 모델 판단 성능은 별도로 확인해야 합니다.

## 서버 관리와 참고

`schema.sql`은 새 프로젝트용 테이블 구성 참고본입니다. 이미 구성한 서버에 다시 실행하지 않습니다.
`cron.sql`은 삭제 작업 재설정용이며 publishable key를 채워 실행합니다.
서버 전체 접근 키와 정리 전용 키는 Pi·PC에 배포하지 않습니다.
테이블의 일반 클라이언트 접근 권한을 회수하고 RLS를 활성화했으므로
일반 클라이언트용 RLS 정책이 없다는 정보 메시지는 의도한 접근 차단에 해당합니다.

현재 서버의 `pg_net`은 `public`에 설치되어 있어 Supabase의 설치 위치 권고가 남습니다.
실행 중인 예약 작업에 영향을 줄 수 있는 재설치는 적용하지 않았습니다.

3분 보관은 전송량을 제한하지 않습니다. **2Mbps로 계속 촬영하면 업로드와 PC 다운로드가 각각 약 21.6GB/일**입니다.
장기 운용 전에 프로젝트 요금제의 Storage 전송량을 확인해야 합니다.

- [Supabase 비공개 Storage](https://supabase.com/docs/guides/storage/buckets/fundamentals)
- [Storage 파일 삭제](https://supabase.com/docs/guides/storage/management/delete-objects)
- [Supabase Cron](https://supabase.com/docs/guides/cron)
- [pg_net 설치 위치 권고](https://supabase.com/docs/guides/database/database-linter?lint=0014_extension_in_public)
