# LSTM 모델 크기 확대 실험

같은 네 입력 피처를 사용하면서 LSTM hidden size와 층 수를 키운다. 입력 길이는 기존과 같이 3/5/10초를 비교한다. 실험 기준은 [크기 확대 비교 계획](IDD_LARGE_LSTM_PROTOCOL.md)에 있다.

| 구조 | 파라미터 수 | 이전 32×1 요약 LSTM 대비 |
|---|---:|---:|
| 32×1 — 이전 선택 모델 | 4,993 | 1배 |
| 64×2 | 51,457 | 약 10.3배 |
| 128×2 | 201,217 | 약 40.3배 |
| 256×3 | 1,321,985 | 약 264.8배 |

모든 확대 후보는 마지막/평균/최댓값/표준편차의 hidden 표현을 요약하고 하나의 logit으로 분류한다. 외부 입력은 `(batch, time, 4)` 그대로이며 신규 피처를 추가하지 않는다.

## 실행

프로젝트 루트에서 기존 전용 Python 환경을 사용한다. 새로운 라이브러리는 필요하지 않다.

```powershell
.\.venv-idd\Scripts\python.exe -m idd_classifier search --data-root data\IDD\no-video --config configs\idd_lstm.json --search-config configs\idd_large_lstm_search.json --reference-run outputs\idd_lstm_seed42 --output outputs\idd_large_lstm_new
```

기존 train 참가자 12명 안에서 동일한 3-fold를 사용한다. 3개 크기 × 3개 입력 길이 × 3개 fold로 총 27회 학습한다. 매 fold마다 해당 train 참가자의 데이터로만 로그 정규화의 평균과 표준편차를 맞춘다. 탐색 중에는 기존 validation/test 참가자를 사용하지 않는다.

이전 32×1 요약 LSTM과 같은 조건으로 비교하기 위해 7점 평활화, `signed_log1p` 정규화, dropout 0.1, weight decay 0.0001, learning rate 0.001, batch 128을 유지한다. 다층 LSTM에서는 층 사이에도 dropout 0.1이 적용된다. gradient clipping 1.0, 최대 40 epoch, patience 7을 사용하며 검증 참가자 macro AUC 기준으로 checkpoint를 저장한다.

`comparison_warmup_points=21`은 실제 평활화 점 수를 바꾸지 않는다. 이전 실험과 Window의 끝 시각을 일치시키기 위한 비교 기준이다. 실제 추론은 평활화 7점, 즉 0.6초 이력 이후 특징을 만들며, 모델에 필요한 특징 수가 모이면 시작한다.

탐색이 완료되면 길이별 확대 후보를 고정하고 최종 학습·평가를 실행한다.

```powershell
.\.venv-idd\Scripts\python.exe -m idd_classifier finalize --data-root data\IDD\no-video --search-run outputs\idd_large_lstm_new --reference-run outputs\idd_lstm_seed42
```

최종 학습은 train 12명과 validation 4명으로 stride 1초, 최대 50 epoch, patience 8을 사용한다. 기본 임계값은 validation Window FPR≤5% 기준이다. 후보와 길이, 임계값을 모두 고정한 뒤 기존 test 4명을 평가한다. `final/best`는 이 실험 안에서 CV로 선택한 확대 모델이며 운영 적합성을 보장하는 이름이 아니다.

## 저장 및 추론

`cv_results.csv`, `cv_ranking.csv`, `cv_selection.json`에 크기별 탐색 결과를 저장한다. 각 fold에는 모델 가중치, 이력, 정규화 설정과 검증 예측을 남긴다. 최종 결과와 추론용 번들은 `final` 아래 저장한다. 모든 기존 실험 폴더는 보존하며 같은 결과 폴더를 덮어쓰지 않는다.

기존 공통 추론 인터페이스가 hidden size와 층 수를 메타데이터에서 읽으므로 호출 방식은 동일하다.

```python
from idd_classifier.inference import VehiclePredictor

predictor = VehiclePredictor("outputs/idd_large_lstm_cv/final/best")
```

모델 크기 확대만으로 새 참가자 성능이 좋아진다고 가정하지 않는다. train, validation, test 지표를 구분하고 동일한 참가자·시나리오·끝 시각에서 이전 작은 모델과 비교한다. 기존 test 결과를 이미 본 반복 실험이므로 실제 CCTV 또는 새로운 참가자 데이터의 외부 검증도 필요하다.

## 실제 교차검증 결과

확대 후보의 27회 학습을 완료했다. 아래 값은 기존 train 12명 내부 3-fold의 참가자 macro AUC 평균이다. 이전 32×1 결과는 같은 fold, 같은 Window 끝 시각, 같은 정규화로 수행한 이전 학습을 사용했다. 27개 확대 학습 모두 대조군과 검증 Window 및 정규화가 일치함을 확인했다.

| 구조 | 파라미터 | 3초 | 5초 | 10초 |
|---|---:|---:|---:|---:|
| 이전 32×1 | 4,993 | 0.6121 | 0.6214 | 0.6589 |
| 64×2 | 51,457 | 0.6068 | 0.6007 | 0.6282 |
| 128×2 | 201,217 | 0.5939 | 0.6090 | 0.6448 |
| 256×3 | 1,321,985 | 0.6001 | 0.6060 | 0.6240 |

이번 조건에서는 크기를 키워 CV 평균 AUC가 높아지는 결과가 나오지 않았다. 확대 후보 안에서는 3초에 64×2, 5·10초에 128×2를 선택했다. 전체 확대 후보의 선택 길이는 10초다. 이는 확대 모델 사이의 선택이며 이전 작은 모델보다 우수하다는 뜻은 아니다. 상세 fold 결과는 `outputs/idd_large_lstm_cv/cv_results.csv`, 평균·표준편차는 [크기별 CV 표](IDD_LARGE_LSTM_CV.csv)에 있다.

최종 테스트 AUC는 3초 0.5262, 5초 0.4904, 10초 0.4963이었다. 선택된 10초 128×2 번들은 `outputs/idd_large_lstm_cv/final/best`에 저장했다. 이전 작은 모델을 교체하지 않았으며, 이번 크기 확대에서 테스트 성능 향상은 확인하지 못했다. Accuracy·FPR·혼동행렬과 학습 경과는 [실측 결과 보고서](IDD_LARGE_LSTM_RESULTS.md)에 있다.
