# DeepPhys 정지 입력 억제: 단계별 개발 기록

2026-11-25. 현재 완료 범위는 **1단계: 데이터 검토 목록과 손실 함수**, **2단계: 승인된 학습/검증 구간의 생산 전처리 캐시**, **3단계: teacher/student 학습기와 첫 10회 추가 학습 실험**이다. 인형의 가짜 호흡 파형은 아직 남아 있다. 무호흡 판정 구현/성능 검증과 운영 모델 교체는 하지 않았다.

## 개발 순서

1. 목록과 손실 함수 → 2. 승인 데이터의 생산 전처리 → 3. teacher/student 추가 학습 → 4. 독립 평가 → 5. 신호 존재 검사와 운영 연결.

상세 작업 목록은 `tasks/plan.md`, `tasks/todo.md`에 있다. 기존 공개 CLI/Windows 수정/가중치를 보존하고 실험별 새 출력 폴더를 사용한다.

## 구현한 것

- `prepare_no_motion_experiment.py init`: 기존 splits.csv/metadata의 전체 영아 ID를 사용해 대표 0~30초 후보를 생성한다. 원본 경로는 새 루트로 해석하고 SHA-256을 대조한다. 기존 출력 폴더는 덮어쓰지 않는다.
- `check`: 원본 및 teacher 해시, 정확한 30초 구간 정의, 승인 bool 타입과 근거, 영아/원본의 split 누수를 검사한다. `--require-approved`는 미검토 항목을 거절한다. 실제 디코딩 길이·ROI·전처리 검증은 다음 단계다.
- `normal_pipeline/no_motion.py`의 `preservation_loss`: 정상 raw 출력과 detach한 teacher 출력 간 MSE에 정지 raw 출력의 제곱 평균을 더한다. 진폭을 정규화하지 않는다. teacher 출력은 기존 동작 보존 목표이며 생리학적 정답이 아니다.
- `babycam_tests/test_no_motion.py`: 진폭 민감도, teacher gradient 차단, 출력 갱신, 미검토/문자열 bool 거절, 잘못된 구간 거절, 전체 영아 ID 구분, 그룹/원본 누수, 파일 변경, 기존 실험 보존을 검증한다.

## 실제 생성 결과

`output/no_motion_stage1_20261125/manifest.json`과 `REVIEW.md`를 생성했다.

| 종류 | train | valid | test | 검토 상태 |
|---|---:|---:|---:|---|
| 아기 호흡 후보 | 11 | 3 | 1 | 15개 모두 미검토 |
| 실제 정지 인형 88~102 | 1 | 0 | 0 | 사용자 정지 확인과 기존 영상 검사 기록 |

위 표는 최초 생성 시점이다. 이후 사용자가 `AIR_125_S05_001_0_30`의 호흡 움직임이 잘 보인다고 확인하여 해당 train 구간의 검토 기록을 반영했다. 기존 valid 대표 구간 3개는 잘 안 보인다고 답하여 미승인/선택 제외 근거를 기록했다. 원본 manifest는 각 검토 변경 전에 별도 JSON으로 보존했다.

인형은 정지 입력의 공학적 시험용이며 실제 영아 무호흡 정답이 아니다. 한 촬영에서 나눈 인접 구간을 독립 검증으로 사용하지 않는다. 별도 정지 촬영과 동일 조건의 규칙적 흉곽 움직임 비교 촬영이 필요하다.

## 실행 방법

기준 환경과 작업 폴더:

```powershell
Set-Location 'C:\Users\OHS\Documents\GitHub\AIOT-Project\AIOT_2026'
$py = 'C:\Users\OHS\miniconda3\envs\air400\python.exe'

# 생성된 목록 검사. 모델 학습은 실행하지 않음
& $py -B -X utf8 .\prepare_no_motion_experiment.py check .\output\no_motion_stage1_20261125\manifest.json

# 모든 보유 항목의 검토 승인을 요구하는 검사
& $py -B -X utf8 .\prepare_no_motion_experiment.py check .\output\no_motion_stage1_20261125\manifest.json --require-approved
```

두 번째 명령은 현재 미검토 정상 후보 때문에 종료 코드 1로 거절되는 것이 맞다. 검토 후 사용할 항목의 `review.approved`를 JSON bool `true`로, `review.reviewer`, `review.notes`를 실제 검토자/근거로 기록한다. 사용하지 않을 후보는 목록에서 제외할 수 있다. train/valid/test를 임의로 옮기지 않는다. 명령 통과는 다음 전처리로 넘어갈 데이터 검사의 통과일 뿐, 임상 성능이나 배포 준비를 뜻하지 않는다.

새 후보 목록이 필요하면 새 폴더를 사용한다:

```powershell
& $py -B -X utf8 .\prepare_no_motion_experiment.py init --output .\output\no_motion_stage1_new
```

## 검증 근거와 다음 작업

- 새 테스트 10개를 포함한 기존 전체 테스트 **44개 통과**. 처음 제한된 실행에서 localhost 모의 서버 연결 4개가 WinError 10013으로 실패했고, localhost 연결이 허용된 실행에서는 모두 통과했다. 실제 Supabase는 호출하지 않았다.
- 실제 목록 생성 시 16개 원본 해시 검사를 통과했다. 승인 검사에서는 첫 미검토 구간을 명시하며 거절됐다.
- 2단계에서는 승인 데이터로 전처리 캐시를 만들고, 합성 정지 입력의 원본/영아 split 상속, 450프레임·6채널·ROI 실패 및 설정 지문을 확인한다. 학습에는 train만 사용한다.
- 3단계에서는 teacher eval/gradient 고정과 student 갱신을 실제 DeepPhys로 검증한다. 작은 새 출력 에너지만으로 성공을 선언하지 않고 정상 파형 보존과 독립 정지 영상까지 평가한다. 모델 변경 후 기존 AE 점수/임계값은 다시 검증한다.

## 2단계 실제 완료 기록

새 `cache` 하위 명령은 승인된 항목만 선택하고, 나머지는 승인하지 않은 채 건너뛴다. `--require-approved`로 모든 보유 후보 승인을 요구하는 기존 검사와 구분한다. 0~30초만 지원하며 기존 `DeepPhysRunner`의 ROI/DeepFlow 전처리와 15Hz 프레임 읽기를 직접 재사용한다. 생산 코드는 변경하지 않았다. 학습 목적의 정지 raw 출력은 상수여도 보존하며 FFT/BPM은 목표 생성에 사용하지 않는다.

```powershell
& $py -B -X utf8 .\prepare_no_motion_experiment.py cache `
  .\output\no_motion_stage1_20261125\manifest.json `
  --output .\output\no_motion_stage2_S05_new
```

실행 완료 위치: `output/no_motion_stage2_S05_20261125`. 기존 캐시는 덮어쓰지 않는다.

| 입력 | split | 준비 결과 | teacher raw 표준편차 | 목표 |
|---|---|---|---:|---|
| AIR_125_S05_001_0_30 | train | prepared | 1.7932153 | 기존 teacher raw 그대로 |
| 동일 영상의 첫 프레임 450회 반복 | train, S05 그룹 상속 | prepared | 0 | 450점 0 |
| 실제 정지 인형 88~102 | train | prepared | 1.6788009 | 450점 0 |

3개 모두 입력 `(450,6,96,96)`, float32, 유한값이며 원본/캐시 SHA-256과 그룹/split을 검사했다. 미승인 후보 14개는 전처리에서 제외했다. 완전 반복 영상의 teacher는 비영 상수였고 실제 정지 인형은 크게 흔들렸다. 합성 정지 프레임만으로 실제 카메라 잡음 조건을 대신하지 않는다.

동일하게 전처리된 S05 입력을 기존 `DeepPhysRunner.extract`의 원래 실행 경로에 전달해 raw 수치가 일치함을 확인했다(최대 절대 차이 0). 이 비교에서는 캐시된 전처리 결과를 주입했으며 ROI/DeepFlow를 두 번 재계산해 동등성을 검증한 것은 아니다. 캐시 생성 자체는 실제 ROI/DeepFlow를 사용했다. 기존 모델·전처리·설정 해시는 변경되지 않았다.

전체 자동 테스트 **49개 통과**. `cache.json`, `verification.json`, `normal_equivalence.json`, `teacher_and_targets.png`가 근거다. 입력 NPZ는 약 199MB이며 입력 배열, teacher raw, 학습 목표와 provenance를 포함한다. student는 아직 학습하지 않았다.

검증용 영상 선택을 돕기 위해 기존 valid 영아의 다른 영상 9개와 보기용 30초 미리보기 3개를 `output/validation_alternatives_20261125`에 만들었다. 모두 미승인이다. 검증용 영아를 학습용으로 옮기거나 S05를 학습·검증 양쪽에 넣지 않았다. `REVIEW.md`의 영상 검토 후 선택한 원본으로 검증 캐시를 추가한다. 미리보기 재인코딩 파일은 전처리 원본으로 사용하지 않는다.

## 검증 구간 선택과 3단계 첫 실험

이후 사용자는 `AIR_125_S02_008_0_30`에서 엎드린 자세의 등 움직임을 확인하고 검증용 사용을 명시적으로 승인했다. 실제 원본을 `valid`로 보존해 `output/no_motion_validation_S02_008_20261125`에 정상/합성 정지 2개 캐시를 만들었다. `0000_roi.png`에 등 부분이 포함됨을 직접 확인했다. ROI 추적/미리보기 저장은 새 캐시 도구에만 추가했고 생산 전처리 코드는 바꾸지 않았다.

`train_no_motion.py`는 캐시/원본/teacher/전처리 해시와 승인 기록, 영아 분할, 목표 의미를 검사한다. train만 gradient 계산에 사용하며 valid는 선택에만 사용한다. teacher는 eval 및 requires_grad=False로 고정하고 student는 복사본으로 만든다. student도 dropout을 끈 eval 상태에서 gradient를 계산해 실제 추론 조건과 맞춘다. 프레임 16개씩의 gradient를 누적하며 마지막 부분 배치까지 반영해 구간별 평균 손실과 같게 계산한다.

1회 smoke와 10회 pilot를 각각 새 폴더에서 실행했다. learning rate `1e-5`, 정지 손실 가중치 `1`, AdamW(weight_decay=0), 모든 student 파라미터 추가 학습이다. 사전 설정한 teacher raw 보존 검사(relative MSE ≤0.1, correlation ≥0.95)를 통과한 epoch 중 검증용 합성 정지 출력 에너지가 줄어든 것을 선택한다. 이 숫자는 기존 출력 보존을 위한 공학적 검사이며 의료 임계값이 아니다.

```powershell
& $py -B -X utf8 .\train_no_motion.py `
  --cache .\output\no_motion_stage2_S05_20261125 `
  --cache .\output\no_motion_validation_S02_008_20261125 `
  --epochs 10 --output .\output\no_motion_pilot_new
```

실제 결과: `output/no_motion_smoke_20261125`, `output/no_motion_pilot_10ep_20261125`.

| 확인 항목 | 결과 |
|---|---|
| 선택 epoch | 10 |
| S02 검증 raw와 기존 teacher의 상관계수 | 0.9995446648 |
| S02 검증 raw 상대 MSE | 0.003835916 |
| 학습 인형 raw 출력 에너지 | 2.9768695 → 2.4252485, 약 18.53% 감소 |
| 학습 인형 raw 표준편차 | 1.6788009 → 1.5357188 |
| 학습 인형 후처리 BPM | 29.8828125 → 29.8828125 |
| 학습 인형의 기존 AE 점수 | 0.04436233 → 0.03712615, 둘 다 below_threshold |
| teacher / 원본 파일 | 변경 없음 |
| student | 실제 갱신됨; 별도 best_student.pt / last_student.pt 저장 |

정지 출력 에너지는 줄었지만 **가짜 호흡의 주기/파형 문제는 해결되지 않았다.** 에너지 감소만으로 성공을 선언하거나 기존 AE 점수가 낮아진 것을 개선으로 해석하지 않는다. 위 인형은 학습 영상이므로 독립 평가도 아니다. 검증용 정지는 한 프레임을 반복한 합성 대조군뿐이며 다른 촬영의 실제 정지 잡음/얕은 호흡 대조군이 필요하다. 실제 영아 무호흡 정답은 아직 없다.

`run.json`, `summary.json`, `selected_raw.npz`, `postprocess_diagnostics.json`, `before_after.png`, `REPORT.md`가 수치·파형·원본 불변 근거다. 기존 teacher raw와 캐시 raw도 재계산해 대조한 후 학습했다. 다음 단계는 독립 데이터에서 정지 잔여 신호와 정상 파형 보존을 함께 평가하는 것이다. 현재 새 가중치는 운영에 연결하지 않는다.

후속으로 Kakao 인형의 자동 ROI 실패를 파일 해시에 연결된 수동 영역으로 처리하고, 임계값 이하 결과를 확인한 뒤 해당 30초를 추가한 최대 100회 재학습을 수행했다. 보존 기준 통과 49회를 선택했지만 인형 파형/BPM은 남았다. [MANUAL_ROI_BENCH.md](MANUAL_ROI_BENCH.md)에 처리 범위, 새 입력, 결과와 한계를 기록했다. 전체 자동 테스트는 57개다.
