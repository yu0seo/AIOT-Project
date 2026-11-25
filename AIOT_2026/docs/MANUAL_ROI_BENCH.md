# 고정 인형 영상의 수동 몸통 영역

2026-11-25. 자동 person 검출에 실패한 인형 시험을 처리하기 위한 별도 전처리 경로다. 운영 YOLO/검출 임계값/DeepPhys 코드는 변경하지 않았다.

## 원인과 처리 범위

기존 `PreProcessor.detect_body_box`는 YOLO 결과의 `person`(class 0)만 고른다. 새 인형 파일에서는 이 영역을 찾지 못했고, 기존 `DeepPhysRunner`가 점수 계산 전에 `unscored`로 거절했다. 사람 검출 성공을 위해 인형을 반드시 person으로 분류하도록 만드는 대신, 위치가 고정된 시험 영상에 명시적인 몸통 사각형을 지정한다.

이 경로는 실제 정지 인형(`static_real`) 자료에만 허용한다. ROI 사각형과 원본 SHA-256을 함께 기록한다. 전체 화면 대체, 범위를 벗어난 좌표, 해시 불일치, 미승인 구간은 거절한다. 수동 지정은 YOLO 검출 성공으로 보고하지 않으며, `roi_mode=manual_source_locked`와 빈 검출 목록을 유지한다. 자동 검출 실패를 정상으로 바꾸지 않는다.

## 실제 적용한 파일

- `KakaoTalk_20261125_195038778.mp4`: 59.458333초, 960×720.
- SHA-256: `31edb0fa942b77566f3f7bbe2c08cd2121bba99e340f53d6478b2a66bb827b4a`.
- ROI 정규화 좌표 `[x,y,w,h]`: `[0.34,0.18,0.50,0.72]`.
- 원본 좌표 기준 약 x=326.4, y=129.6, 폭=480, 높이=518.4. 대표 프레임에서 머리·몸통·팔다리를 포함하는 것을 확인했다.
- 기존 영상 읽기의 320×180 리사이즈 뒤에 좌표를 환산해 크롭한다. 원본을 먼저 잘라 다시 320×180으로 키우는 다른 전처리를 만들지 않았다. 이후 크롭/DeepFlow/정규화/96×96 입력/DeepPhys 실행은 기존 코드다.
- 첫 0~30초만 사용한다. 끝의 30초 미만 구간을 패딩하거나 반복하지 않는다.

실제 지정은 새 실험 manifest의 해당 record에 다음과 같이 기록했다. source 자체의 해시도 동일해야 한다.

```json
"manual_roi": {
  "source_sha256": "31edb0fa942b77566f3f7bbe2c08cd2121bba99e340f53d6478b2a66bb827b4a",
  "box_xywh_normalized": [0.34, 0.18, 0.50, 0.72],
  "reason": "Automatic person detector found no body; fixed doll bench annotation"
}
```

## 실행과 재학습 조건

`prepare_no_motion_experiment.py cache`는 이제 승인된 정지 입력만 따로 준비할 수 있다. 실제 학습의 호흡/정지 train/valid 필수 조건은 `train_no_motion.py`가 계속 검사한다.

```powershell
Set-Location 'C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026'
$py = 'C:\Users\OHS\miniconda3\envs\air400\python.exe'
& $py -B -X utf8 .\prepare_no_motion_experiment.py cache `
  .\output\doll_kakao_20261125\manual_roi_v1\manifest.json `
  --output .\output\doll_kakao_20261125\manual_roi_cache_new
```

실제 결과는 `output/doll_kakao_20261125/manual_roi_v1/cache`다. `manual_roi_preview.png`와 캐시의 `0000_roi.png`에서 범위를 확인할 수 있다. 원본 영상 사본과 해시를 해당 실험 폴더에 보존했다.

자동 ROI 결과는 여전히 `unscored`이며 별도 수동 ROI 실험의 첫 30초 결과는 다음과 같다.

| DeepPhys 모델 | 추정 BPM | 기존 AE 점수 | 상태 |
|---|---:|---:|---|
| 기존 가중치 | 29.8828125 | 0.09574954 | below_threshold |
| 앞선 10회 학습 가중치 | 29.8828125 | 0.09298740 | below_threshold |

따라서 사용자의 이전 조건부 요청에 따라 이 수동 ROI 구간을 정지 인형의 학습용 자료로 추가했다. 실제 영아 무호흡 정답으로 라벨링하지 않는다. S05 학습/ S02_008 검증 영아 분할을 유지하며, 새 인형 파일의 다른 구간을 검증용으로 옮기지 않는다.

## 검증

전체 자동 테스트 **57개 통과**. 좌표 환산/범위/전체 화면 거절, 원본 해시 연결, 실제 정지 시험용 제한, 예외 시 자동 검출 함수 복구, 기존 입력 채널/전처리/학습/서비스 테스트를 포함한다. 수동 ROI 미지정 시 자동 경로를 그대로 사용한다. 운영 수집기의 설정/가중치/진행 상태는 바꾸지 않았다.

새 몸통 검출기를 도입하는 것은 별도 과제다. 움직이는 아기나 카메라 위치가 바뀌는 운영 영상에 이 고정 사각형을 자동 적용하지 않는다.

## 새 인형 구간을 추가한 재학습 완료

기존 teacher에서 student를 새로 복사해 학습 S05/기존 인형/새 수동 ROI 인형과 합성 정지 입력을 사용했다. S02_008과 해당 합성 정지는 valid로만 사용했다. 기존 원본 가중치를 덮어쓰거나, 같은 인형 파일의 인접 구간을 valid로 사용하지 않았다.

최대 100회 실험에서 보존 기준을 만족한 49회를 선택했다. 50회 이후에는 보존 기준을 벗어나 후보에서 제외했다. 검증용 teacher raw 대비 상관계수 0.98484758, 상대 MSE 0.09628749였다.

| 구간 | raw 에너지 감소 | raw std 전→후 | 후처리 BPM 전→후 |
|---|---:|---|---|
| 기존 인형 88~102, train | 51.54% | 1.67880 → 1.19942 | 29.88 → 29.88 |
| 새 인형 수동 ROI, train | 33.41% | 2.07679 → 1.69390 | 29.88 → 29.88 |
| 검증 아기 S02_008, valid | 39.74% | 1.54253 → 1.24910 | 28.12 → 28.12 |

정지 인형만 선택적으로 억제한 결과라고 볼 수 없다. 아기 출력 에너지도 줄었고 인형의 가짜 파형과 양수 BPM은 남았다. 새 인형의 기존 AE 점수도 0.09574954 → 0.07057218로 임계값 이하를 유지했다. 따라서 수동 ROI로 분석 중단은 해결했지만 무호흡 탐지는 해결되지 않았으며 운영 가중치는 교체하지 않았다.

결과: `output/no_motion_kakao_expanded_100ep_20261125/REPORT.md`, `run.json`, `summary.json`, `postprocess_diagnostics.json`, `before_after.png`, `best_student.pt`. 감소율은 학습 자료의 수치이며 독립적인 실제 정지 촬영의 성능이 아니다. 기존 teacher/모델/설정 해시와 운영 상태는 보존됐다.
