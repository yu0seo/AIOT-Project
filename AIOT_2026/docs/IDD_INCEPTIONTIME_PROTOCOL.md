# 소형 InceptionTime 비교 기준

학습 실행 전에 정한 비교 기준이다. MiniRocket 결과와 원본 데이터는 보존한다.

- 기준 결과는 `outputs/idd_minirocket_5fold_v1`이다. 이 결과의 `folds.json`을 그대로 사용한다. 바깥 5-fold마다 개발 16명/테스트 4명, 개발 집단 내부 참가자 3-fold도 동일하다.
- 동일한 P 참가자 20명, no_task 주행 75개와 원본 CSV 해시를 확인한다. 네 피처의 순서·정의·단위, 10Hz, 과거 7점 평활화, signed_log1p, train 기준 정규화를 유지한다.
- 3/5/10초를 비교한다. 내부·최종 학습과 테스트는 stride 1초, 내부 검증은 stride 3초다. 조기 종료 epoch를 최종 재학습에 적용할 때 학습 Window 밀도가 달라지지 않게 한다. MiniRocket의 내부 학습 stride 3초와는 차이가 있으며, 동일 참가자와 전체 주행을 사용한다. 비교용 초기 이력 21점은 동일하다. MiniRocket의 OOF와 참가자·시나리오·종료 시각·라벨·fold가 일치해야 비교한다.
- 공식 InceptionTime 구조를 참고한 소형 단일 네트워크다. 16개 필터, bottleneck 16, 3개 Inception 모듈, 3모듈마다 잔차 연결, global average pooling, dropout 0.3, 이진 logit을 사용한다. 원 논문의 5개 네트워크 ensemble과 구분한다.
- 합성곱 커널은 39/19/9다. 공식 Keras 구현의 40/20/10을 홀수로 조정해 양쪽 같은 padding을 쓴다. 전체 Window가 수집된 시점에 출력하며 아직 들어오지 않은 프레임을 사용하지 않는다.
- 모델 크기와 학습률 등을 테스트 점수로 탐색하지 않는다. 고정된 `configs/idd_inceptiontime.json`으로 평가한다. AdamW, BCEWithLogitsLoss, train 클래스 가중치, gradient clipping을 사용한다.
- 각 내부 train 참가자로만 정규화를 계산하고 모델을 학습한다. validation 참가자 macro AUC로 최대 40 epoch/patience 6의 early stopping과 체크포인트 선택을 한다.
- 내부 OOF 점수로 저오탐(Window FPR≤5%) 및 보조 balanced accuracy 임계값을 정한다. 바깥 재학습 epoch 수는 세 내부 best epoch의 중앙값으로 정한다. 테스트를 조기 종료에 사용하지 않는다.
- 각 길이의 설정과 내부 CV 점수로 고른 길이를 테스트 실행 전에 저장한다. 개발 16명으로 정해진 epoch 수만 학습하고 고정된 임계값으로 테스트 4명을 평가한다.
- 15개 최종 모델과 내부 검증 모델·학습 이력·임계값·정규화·온라인 추론 설정을 저장한다. 전체 20명 OOF와 참가자 macro 지표, 참가자 군집 bootstrap 구간을 계산한다.
- MiniRocket과 동일 참가자의 AUC 차이를 짝지어 비교한다. 비교는 사후 기술 분석이며, 비교 결과로 모델 임계값이나 학습 설정을 다시 맞추지 않는다.
- 여러 모델을 같은 IDD에서 반복 비교하는 연구다. 이번 5-fold도 완전히 새로운 외부 검증은 아니며 실제 CCTV 음주 탐지 성능을 보장하지 않는다.

근거: [공식 InceptionTime 코드](https://github.com/hfawaz/InceptionTime/blob/master/classifiers/inception.py), [논문](https://arxiv.org/abs/1909.04939), [PyTorch Conv1d](https://docs.pytorch.org/docs/2.15/generated/torch.nn.Conv1d.html).
