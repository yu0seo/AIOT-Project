# 성능 개선 실험 실행 안내

기존 네 피처와 단위를 유지하면서 전처리 정규화, 신경망의 시점 요약 방식, 모델 종류를 비교한다. 원본 baseline 결과와 모델은 덮어쓰지 않는다. 실험 전에 정한 기준은 [비교 계획](IDD_IMPROVEMENT_PROTOCOL.md)에 있다.

## 이번 실제 실행 결과

9개 후보·3개 입력 길이·3개 참가자 fold의 **81회 학습**을 실행했다. CV에서는 짧은 7점 평활화, 로그 정규화, 전체 시점 요약 LSTM이 선택되었다. 10초 CV macro AUC는 기준 방식 0.6122에서 후보 0.6589로 높아졌다. 최종 학습/검증은 기존 train 12명 / validation 4명으로 수행했고 test 4명은 선택 고정 후 평가했다.

그러나 **테스트 참가자에서 의미 있는 성능 개선은 확인하지 못했다.** 동일한 2,977개 테스트 Window에서의 AUC는 다음과 같다.

| 입력 길이 | 기존 AUC | 후보 AUC | 후보 기본 임계값 Accuracy | Recall | FPR |
|---|---:|---:|---:|---:|---:|
| 3초 | 0.5122 | 0.5214 | 48.20% | 5.11% | 7.62% |
| 5초 | 0.5134 | 0.5202 | 48.20% | 5.44% | 7.96% |
| 10초 | 0.5208 | 0.5199 | 48.91% | 7.63% | 8.78% |

10초 AUC 차이의 참가자 군집 95% 구간은 약 `[-0.0581, +0.0321]`로 0을 포함한다. 5초 보조 임계값의 Accuracy는 52.80%지만 FPR이 33.67%다. 이 수치를 관제용 정확도 향상으로 주장하지 않는다. 기존 best는 보존했고 새 후보는 별도 실험 결과로 저장했다. 전체 지표는 [후속 결과 보고서](IDD_IMPROVEMENT_RESULTS.md)에 있다.

후속 진단에서 10초 후보의 train AUC는 0.7107, validation 참가자 macro AUC는 0.6518, test AUC는 0.5199였다. 학습 패턴을 더 잘 맞추었지만 새로운 참가자에게 그 효과가 유지되지 않았다. 기존 11점 평활화의 10초 Window 평균을 확인하면, train의 비음주/음주 평균 speed는 9.99/10.68m/s였고 test는 10.22/10.10m/s였다. 평균 jerk 차이도 train 약 0.46m/s³에서 test 약 0.13m/s³로 작아졌다. 이는 기술 통계이며 실패 원인의 확정이나 네 피처의 정보 한계 증명으로 해석하지 않는다.

실제 결과 폴더는 `outputs/idd_improvement_cv/final`이다. `best`는 CV 선택 후보이며 운영 권장 모델을 뜻하지 않는다. 실제 CSV의 온라인 재생은 세 길이 각각 156개 비교 Window에서 배치 점수와 최대 약 `1.2e-7` 차이로 일치했다.

## 실행

프로젝트 루트에서 기존 전용 환경을 사용한다. 새 라이브러리 설치는 필요하지 않다.

```powershell
.\.venv-idd\Scripts\python.exe -m idd_classifier search --data-root data\IDD\no-video --config configs\idd_lstm.json --search-config configs\idd_search.json --reference-run outputs\idd_lstm_seed42 --output outputs\idd_improvement_new
```

이 명령은 기존 train 12명만 읽어 3-fold 참가자 교차검증을 수행한다. 9개 후보 × 3개 길이 × 3개 fold = 81회 학습이다. 정규화는 매 fold의 train 참가자만 사용해 다시 맞춘다. 탐색용 stride는 3초다. 모든 후보는 동일한 Window 끝 시각을 사용한다.

`cv_results.csv`에는 fold별 결과, `cv_ranking.csv`에는 평균과 표준편차, `cv_selection.json`에는 길이별 선택 후보가 저장된다. CV 점수는 모델 선택에 사용되었으므로 독립적인 최종 성능 추정치가 아니다.

후보를 고정한 뒤 최종 재학습과 평가를 실행한다.

```powershell
.\.venv-idd\Scripts\python.exe -m idd_classifier finalize --data-root data\IDD\no-video --search-run outputs\idd_improvement_new --reference-run outputs\idd_lstm_seed42
```

최종 학습은 기존 train 12명, validation 4명으로 stride 1초를 사용한다. 후보와 입력 길이는 CV에서 고른 것을 유지한다. 모든 임계값과 모델을 저장한 뒤 기존 test 4명을 평가한다. 결과는 탐색 폴더의 `final` 아래 저장된다. 기존 폴더를 덮어쓰지 않으므로 같은 실험을 다시 수행하려면 새 탐색 폴더를 지정한다.

## 변경 사항

- 기존 마지막 hidden state LSTM과, 전체 시점의 last/mean/max/std를 내부에서 요약하는 LSTM을 비교한다. 입력은 계속 `(batch, time, 4)`다.
- GRU와 인과적 TCN도 같은 인터페이스로 비교한다. TCN은 왼쪽에만 padding한 dilated Conv1d를 사용하므로 미래 시각을 읽지 않는다.
- `identity`와 `signed_log1p` 정규화를 비교한다. 후자는 원시 특징을 `sign(x)*log1p(abs(x))`로 변환한 뒤 train 평균/표준편차로 정규화한다. 원시 피처 계산식은 그대로이며, clipping이나 큰 값의 삭제는 하지 않는다.
- 정규화 방법은 `metadata.json`의 `normalizer.transform`에 저장되며 학습과 추론 모두 `data.normalize`를 사용한다. 기존 번들에서 이 필드가 없으면 원래 identity 정규화를 적용한다.
- 평활화 점 수는 7/11/21을 비교한다. 첫 특징까지 필요한 이력은 각각 0.6/1.0/2.0초다. 실제 차량 관측에 필요한 총 시간도 그만큼 달라지며 번들의 설정에 기록된다.
- early stopping은 참가자 macro ROC-AUC를 기준으로 한다. 검증 손실과 macro AUC를 모두 `history.csv`에 기록한다.

## 결과 해석

기본 `metadata.threshold`는 validation FPR≤5% 기준의 저오탐 임계값이다. 별도로 validation 참가자 macro balanced accuracy를 최대화한 보조 임계값도 저장한다. 보조 Accuracy가 높더라도 FPR을 함께 확인해야 하며, 이 임계값으로 기본 관제 임계값을 조용히 바꾸지 않는다.

기존 모델과 비교할 때는 같은 참가자·시나리오·끝 시각의 Window만 연결한다. 참가자 군집 bootstrap으로 개선−기존 지표 차이의 95% 구간을 계산한다. 기존 test 결과를 이미 알고 시작한 후속 연구이므로 새로운 외부 검증을 대체할 수 없다.

`final/best`는 CV로 선택한 길이의 모델이며 test가 가장 좋았던 모델을 고른 것이 아니다. 기존 `outputs/idd_lstm_seed42/best`는 보존된다. 개선 모델도 같은 `VehiclePredictor` 인터페이스로 읽을 수 있다.

## 공식 API 근거

- [PyTorch GRU](https://docs.pytorch.org/docs/2.15/generated/torch.nn.GRU.html)
- [PyTorch Conv1d](https://docs.pytorch.org/docs/2.15/generated/torch.nn.Conv1d.html)
- [scikit-learn 참가자 등 그룹 단위 교차검증](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data)
