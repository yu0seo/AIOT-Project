# 네 피처 MiniRocket 참가자 5-fold 평가

기존 `speed`, `acceleration`, `jerk`, `turn_rate` 네 입력과 공통 좌표 특징 추출기를 유지한다. 모델은 공식 **aeon 1.6.0의 다변량 MiniRocket → 변환 피처 표준화 → L2 로지스틱 회귀**다. 10,000개 설정에서 실제 9,996개 합성곱 통계가 만들어지며, 이 통계는 모델 내부 표현이다. 외부 입력은 여전히 `(N,30/50/100,4)`다.

MiniRocket은 여러 고정 합성곱 패턴에 반응하는 비율로 시계열을 변환한다. 적은 참가자로 큰 신경망을 학습하는 방식과 다른 기준을 비교하기 위해 도입했다. 변환기의 bias와 분류기는 매번 학습 참가자로만 맞춘다. 기본 MiniRocketClassifier의 Window 단위 내부 CV를 피하고, 참가자별 내부 CV로 로지스틱 회귀의 규제 강도를 선택한다.

완료된 [실제 5-fold 결과](IDD_MINIROCKET_RESULTS.md)에는 모든 참가자의 OOF 평가, 저오탐 운영점과 신뢰구간이 정리되어 있다.

## Windows 설치와 실행

기존 LSTM 환경의 NumPy/pandas 버전은 aeon 1.6.0 지원 범위를 벗어난다. 기존 `.venv-idd`를 보존하고 별도 환경을 사용한다. 아래 명령은 프로젝트 최상위 폴더에서 실행한다. Python 3.14에서 실제 설치·검증했다.

```powershell
python -m venv .venv-minirocket
.\.venv-minirocket\Scripts\python.exe -m pip install -r requirements-minirocket-lock.txt
.\.venv-minirocket\Scripts\python.exe -m pip install --no-deps -e .
.\.venv-minirocket\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv-minirocket\Scripts\python.exe -X utf8 -u -m idd_classifier minirocket-cv `
  --data-root data\IDD\no-video `
  --config configs\idd_lstm.json `
  --rocket-config configs\idd_minirocket.json `
  --output outputs\idd_minirocket_5fold_v1
```

`data-root`와 `output`은 다른 경로로 지정할 수 있다. 기존 결과 폴더를 덮어쓰지 않는다. CPU로 실행하며 최초 Numba 컴파일에는 추가 시간이 걸린다. 일반 설치는 `pip install -e ".[minirocket]"`도 가능하지만, 측정 환경 재현에는 고정 버전 파일을 사용한다.

## 평가 절차

대상은 기존 제외 기준을 적용한 P 참가자 20명, 인지 방해 없는 정상/음주 주행 75개다. 숫자 ID의 별도 정상 주행 코호트는 포함하지 않는다. 라벨은 기존 공식 DBM 규칙과 Alcohol 주석 교차 검증을 유지한다.

1. 참가자 단위 바깥 5-fold: 개발 16명, 테스트 4명. 모든 참가자는 정확히 한 번 테스트한다.
2. 각 개발 집단 안에서 참가자 단위 3-fold: C 후보 `0.001/0.01/0.1/1.0`을 비교한다. 물리 피처 정규화, MiniRocket bias, 변환 피처 표준화, 분류기를 내부 train으로만 맞춘다.
3. 내부 OOF의 참가자 macro ROC-AUC로 C를 선택한다. 각 운전자의 정상/음주 Window를 비교한 AUC를 같은 비중으로 평균한다. C 동률이면 강한 규제인 작은 C를 고른다.
4. 선택된 C의 내부 OOF로 기본 저오탐 임계값(Window FPR≤5%)과 보조 balanced accuracy 임계값을 정한다. 길이도 내부 점수만으로 선택해 기록한다.
5. 개발 16명 전체를 재학습한 뒤 테스트 4명에 적용한다. 바깥 테스트로 설정/임계값을 다시 고르지 않는다.

최종 학습/평가는 stride 1초, 내부 비교는 stride 3초다. 평활화는 과거 7개 좌표만 사용하는 인과적 다항식으로 유지한다. 피처별 `signed_log1p`와 train 평균/표준편차를 적용한다. 3·5·10초의 평가 Window는 같은 종료 시각을 쓴다. 기존 비교용 초기 이력 21점을 맞춰 평가를 11.9초부터 시작하며, 실제 온라인 첫 출력은 연속 유효 관측 시 각각 약 3.5/5.5/10.5초부터 가능하다.

## 결과 파일 읽기

- `folds.json`: 바깥/안쪽 참가자 분리. 같은 참가자의 모든 시나리오와 겹치는 Window는 함께 이동한다.
- `scenario_manifest.csv`, `data_audit.csv`: 실제 대상, 제외 사유, 결측·간격·점프 검사, 원본 CSV 해시.
- `fold_1/3s/inner_oof_C_*.csv`: C별 내부 검증 예측. `inner_*_fit.json`은 train/validation 목록과 정규화 통계다.
- `fold_1/selection_before_test.json`: 테스트 평가 전에 정한 C, 입력 길이, 임계값.
- `fold_1/3s/model.joblib`, `metadata.json`: 변환기/스케일러/분류기와 물리 피처 정의, 평활화, 정규화, 샘플링, 길이, 임계값, 버전. 총 5×3개 평가 모델이 저장된다.
- `oof_3s.csv`, `oof_5s.csv`, `oof_10s.csv`: 각 참가자가 자신의 바깥 테스트에서 받은 점수와 당시 고정된 임계값.
- `metrics_*s.json`, `comparison.csv`, `report.json`: Window/참가자 macro/참가자×조건 지표, fold별 AUC, 혼동행렬, 참가자 군집 bootstrap 95% 구간.
- `oof_selected_length.csv`: 각 fold의 내부 CV에서 선택한 길이를 적용한 별도 평가. 길이 선택 절차 자체의 성능이다.

`low_fpr`는 내부 FPR 제한으로 정한 기본 운영점, `balanced`는 보조 운영점이다. 바깥 fold마다 임계값이 다르므로 행별 원래 임계값을 적용해 Accuracy/Recall/FPR을 합친다. 전체 OOF로 하나의 임계값을 새로 맞추지 않는다.

참가자 macro AUC와 mean fold AUC를 우선 해석한다. pooled OOF AUC는 fold 사이 점수 눈금의 차이에도 영향을 받는다. 군집 bootstrap은 참가자를 복원 추출하므로 겹치는 Window를 독립 표본으로 가정하지 않는다. 이 구간은 고정된 OOF 예측의 참가자 변동을 요약하며, 모델 재학습 변동까지 포함한 구간은 아니다. 참가자×조건 점수는 긴 주행 전체를 평균한 보조 지표이므로 짧은 CCTV 추적 성능과 구분해야 한다.

여기서 FPR은 정상 Window 중 양성 판정 비율이다. 여러 Window 중 한 번만 양성이 나와도 차량 경보를 보내는 정책이라면 차량별 경보 FPR은 달라진다. 관제 연동 전에는 실제 추적 길이와 경보 정책을 고정한 차량 단위 오탐률도 측정해야 한다. 현재 인터페이스는 Window 점수와 판정만 반환한다.

## CCTV 추론

기존 `VehiclePredictor`에 MiniRocket 번들을 그대로 전달한다. YOLO/ByteTrack/Naver 단계 이후 미터 단위 도로 좌표를 입력하는 인터페이스와 품질 보류 동작은 같다.

```python
from idd_classifier.inference import CoordinateQuality, VehiclePredictor

predictor = VehiclePredictor('outputs/idd_minirocket_5fold_v1/fold_1/3s')
# 실제 기준점 실측과 추적 결과로 quality를 구성한다.
quality = CoordinateQuality(
    metric_scale_verified=True, control_point_error_m=measured_error_m,
    within_road_roi=inside_roi, tracking_ok=track_ok, calibration_id='camera-A-v1',
)
result = predictor.update(vehicle_id, timestamp_ns, x_m, y_m, quality=quality)
```

기준점 오차 미측정/초과, 미터 스케일 미검증, ROI 이탈, 추적 불량이면 점수를 내지 않는다. 불연속 관측이나 물리적으로 과도한 점프는 이력을 초기화한다. ByteTrack lost/removed 및 ID 재사용 때 `predictor.drop_track(vehicle_id)`를 호출한다. 미래 좌표로 보간하거나 중단된 추적을 이어 붙이지 않는다.

번들 파일은 직접 학습해 생성한 신뢰할 수 있는 파일만 읽는다. `joblib`은 aeon 객체와 NumPy 파라미터를 함께 저장하는 용도다. 각 fold 모델은 다른 fold의 테스트 참가자를 학습에서 보았으므로 5개 모델을 평균하여 OOF 성능으로 보고하면 누출이다. 전체 20명으로 배포 모델을 학습하려면 별도 학습과 새로운 외부 검증이 필요하다.

## 해석 한계와 근거

이 실험은 기존 4명 고정 테스트를 포함한 같은 IDD에서 반복한 연구다. 바깥 평가 범위가 20명으로 넓어지지만 완전히 새로운 외부 검증은 아니다. 이전 4명 정확도와 직접적인 성능 차이로 비교할 수 없다. 내부 FPR 5%는 재학습 후 바깥 테스트나 CCTV의 FPR 5%를 보장하지 않는다. round·시나리오 교란, 시뮬레이터와 CCTV 좌표 노이즈/스케일 차이도 남는다. IDD 분류 점수는 실제 운전자의 음주 상태를 확정하지 않는다.

- [사전 평가 기준](IDD_MINIROCKET_PROTOCOL.md)
- [MiniRocket 논문](https://arxiv.org/abs/2012.08791)
- [공식 aeon 다변량 MiniRocket](https://www.aeon-toolkit.org/en/stable/api_reference/auto_generated/aeon.transformations.collection.convolution_based.MiniRocket.html)
- [aeon 1.6.0 변환기 코드](https://github.com/aeon-toolkit/aeon/blob/v1.6.0/aeon/transformations/collection/convolution_based/_minirocket.py)
- [LogisticRegression 공식 문서](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html)
