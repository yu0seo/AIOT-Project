# 소형 InceptionTime 동일 5-fold 비교

이 실험은 MiniRocket과 동일한 네 피처, 참가자 20명, 3/5/10초 평가 Window를 사용한다. `outputs/idd_minirocket_5fold_v1`의 참가자 분할을 그대로 복사하고 실제 CSV 해시와 평가 행을 검사한다. 동일한 평가 데이터에서 모델의 표현 학습 방식을 비교하는 실험이다.

완료된 [실제 비교 결과](IDD_INCEPTIONTIME_RESULTS.md)에 두 모델의 운영점별 지표와 참가자별 차이를 정리했다.

## 모델

PyTorch 단일 네트워크, 학습 파라미터 **56,513개**다.

```text
(N,T,4)
 → 채널 축 변환 (N,4,T)
 → Inception 모듈 3개 + 잔차 연결
 → 시간축 평균 pooling
 → Dropout(0.3)
 → 선형층 → 이진 logit
```

각 모듈은 bottleneck 16채널 뒤 39/19/9 커널의 병렬 Conv1d 세 개와 max-pool/1×1 Conv 가지를 합친다. 가지별 필터 16개를 이어 64채널을 만들고 BatchNorm/ReLU를 적용한다. 과거 Window 전체가 확보된 뒤 점수를 내므로 아직 수집하지 않은 좌표를 사용하지 않는다.

원 논문의 InceptionTime은 여러 네트워크의 ensemble이다. 여기서는 소형 단일 네트워크를 사용한다. 공식 Keras 코드의 40/20/10 커널을 대칭 padding이 가능한 39/19/9로 조정했다. 이 구조와 PyTorch의 기본 초기화, 이진 BCE/AdamW는 이번 기준 모델의 설정이며 원 논문의 학습 조건과 구분한다.

## 실행

현재 환경에서 GPU 장기 실행 지연이 반복돼 최종 평가는 CPU에서 수행한다. MiniRocket과 같은 PyTorch 2.15.0 CPU 및 데이터 라이브러리 버전을 `requirements-inceptiontime-lock.txt`에 고정했다. GPU 시험은 바깥 테스트 전에 중단했으며 최종 비교 결과에 포함하지 않는다.

```powershell
python -m venv .venv-inceptiontime-cpu
.\.venv-inceptiontime-cpu\Scripts\python.exe -m pip install -r requirements-inceptiontime-lock.txt
.\.venv-inceptiontime-cpu\Scripts\python.exe -m pip install --no-deps -e .
.\.venv-inceptiontime-cpu\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv-inceptiontime-cpu\Scripts\python.exe -X utf8 -u -m idd_classifier inception-cv `
  --data-root data\IDD\no-video `
  --config configs\idd_inceptiontime.json `
  --reference-run outputs\idd_minirocket_5fold_v1 `
  --output outputs\idd_inceptiontime_5fold_cpu_v1 `
  --device cpu
```

이미 설치된 `.venv-minirocket\Scripts\python.exe`로도 같은 CPU 명령을 실행할 수 있다. 기존 결과 폴더는 덮어쓰지 않는다. `reference-run`에는 완료된 MiniRocket 실행의 config/folds/audit/OOF 파일이 필요하다. 경로는 인자로 지정한다. 실제 사용 환경은 결과의 `environment.json`에 남는다. CUDA 설치 환경에서는 `--device cuda`도 지원한다.

바깥 테스트가 생성되기 전에 중단된 실행은 같은 명령에 `--resume`을 추가해 복구할 수 있다. 설정·참조 실행·라이브러리·실행 장치가 같아야 한다. 완료된 내부 모델은 참가자/정규화/seed를 검사해 재사용하고, 미완료 내부 학습은 해당 seed의 처음부터 다시 실행한다. 바깥 테스트 생성 후에는 이 재개 기능을 허용하지 않는다. `elapsed_seconds`는 재개한 실행 구간의 시간이며 이전 작업 시간은 포함하지 않는다.

## 참가자 분리와 학습

- 바깥 5-fold: 개발 16명/테스트 4명, 전체 20명이 한 번씩 테스트한다. 같은 운전자의 모든 시나리오/겹치는 Window가 함께 이동한다.
- 안쪽 3-fold: MiniRocket과 같은 참가자 분리다. train 참가자로만 물리 피처 정규화를 계산하고 학습한다. BatchNorm도 평가 시에는 학습 통계를 고정한다.
- 피처는 10Hz, 과거 7점 인과적 평활화, signed_log1p, train 평균/표준편차를 유지한다. 세 길이의 평가 종료 시각도 같다.
- 내부/최종 학습은 모두 stride 1초다. 내부 검증은 stride 3초, 테스트는 stride 1초다. MiniRocket 내부 학습 stride 3초와 차이가 있으며, 조기 종료 epoch의 의미를 최종 학습과 맞추기 위한 선택이다. 바깥 개발 집단의 최종 학습 Window와 테스트 Window는 동일하다.
- BCEWithLogitsLoss의 클래스 가중치는 각 train에서 계산한다. AdamW, 학습률 0.001, weight decay 0.01, 최대 40 epoch, patience 6, gradient norm 1을 사용한다.
- 내부 validation 참가자 macro AUC로 best checkpoint를 고른다. 내부 OOF로 기본 저오탐(Window FPR≤5%) 및 보조 balanced accuracy 임계값을 정한다.
- 세 내부 best epoch의 중앙값을 재학습 epoch로 정한다. 개발 16명 전체에서 그 횟수만큼 학습한 마지막 모델을 사용한다. 바깥 테스트를 조기 종료나 임계값 조정에 사용하지 않는다.
- 세 길이 중 내부 CV 점수가 가장 높은 길이도 테스트 전에 정해 별도 기록한다. 전체 OOF를 본 뒤 설정을 다시 고르지 않는다.

모델 구조/학습률/정규화는 이번 실험에서 고정된 설정이다. 테스트 점수에 맞춘 구조 탐색이나 여러 seed 중 선택은 수행하지 않는다. [사전 비교 기준](IDD_INCEPTIONTIME_PROTOCOL.md)을 함께 참고한다.

## 저장 파일

- `folds.json`: MiniRocket 원본 분할과 바이트 단위로 동일하다.
- `comparison_setup.json`: 동일 CSV 해시, 평가 Window 확인, 전처리와 학습/검증 간격.
- `fold_1/3s/inner_1/`: 내부 모델 `model.pt`, epoch별 `history.csv`, 참가자/정규화 `fit.json`.
- `fold_1/selection_before_test.json`: 세 길이의 내부 점수·임계값·재학습 횟수와 선택된 길이.
- `fold_1/3s/model.pt`, `metadata.json`: 최종 16명 학습 모델과 공통 추론 설정. 총 15개 최종 번들이다.
- `oof_3s.csv`, `oof_5s.csv`, `oof_10s.csv`: 전체 20명 테스트 예측과 각 fold의 고정 임계값.
- `metrics_*s.json`, `report.json`: Window/참가자 macro/참가자×조건 지표, 혼동행렬, 참가자 군집 bootstrap 95% 구간.
- `comparison.csv`: 동일 평가 행에서 MiniRocket과 InceptionTime의 두 운영점 비교.
- `paired_model_comparison.json`: 참가자별 AUC 차이의 짝지은 bootstrap 구간. 고정 OOF 예측을 이용한 사후 비교다.

## CCTV 좌표 추론

```python
from idd_classifier.inference import VehiclePredictor

predictor = VehiclePredictor('outputs/idd_inceptiontime_5fold_cpu_v1/fold_1/3s')
result = predictor.update(vehicle_id, timestamp_ns, x_m, y_m, quality=coordinate_quality)
```

`coordinate_quality`는 실제 기준점 오차, 미터 스케일, 도로 ROI, 추적 품질과 보정 버전을 확인해 구성한다. 기존 `CoordinateQuality`와 추적 초기화/판단 보류 동작이 그대로 적용된다. 추적 중단/ID 재사용은 `drop_track`으로 알린다. 유효 이력이 부족하면 점수가 반환되지 않는다.

## 해석 범위와 근거

동일한 데이터에서 여러 모델을 반복 비교했으므로 새로운 외부 검증은 아니다. IDD 점수가 실제 CCTV의 음주 여부 판정 정확도를 의미하지 않는다. Window FPR은 차량별 경보 FPR과도 구분해야 한다. 여러 CV 모델을 평균해 OOF 성능으로 보고하면 학습 참가자가 섞이므로 그렇게 사용하지 않는다.

- [InceptionTime 공식 코드](https://github.com/hfawaz/InceptionTime/blob/master/classifiers/inception.py)
- [InceptionTime 논문](https://arxiv.org/abs/1909.04939)
- [PyTorch Conv1d](https://docs.pytorch.org/docs/2.15/generated/torch.nn.Conv1d.html)
- [PyTorch AdamW](https://docs.pytorch.org/docs/2.15/generated/torch.optim.AdamW.html)
- [PyTorch 재현성](https://docs.pytorch.org/docs/2.15/notes/randomness.html)
