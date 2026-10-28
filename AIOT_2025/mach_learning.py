import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import root_mean_squared_error
import numpy as np
import joblib
# 모듈들을 임포트한다.

df = pd.read_csv('./data/2024TrashData.csv', parse_dates=['measured_at'])
df.sort_values("measured_at", inplace=True)
# 학습시킬 데이터를 불러오고 parse_dates로 measured_at 컬럼을 datetime[ns] 타입으로 변환한다.
# 데이터를 측정 시간 기준으로 정렬한다.

# 청소가 발생함을 나타내는 피쳐를 추가하기 위해 데이터 전처리 수행
df['diff'] = df['distance_cm'].diff()
df['clean'] = (df['diff'] > 30).astype(int)  
# 거리의 차이가 30cm 이상 증가한 경우 청소가 발생한 것으로 간주
# post_clean
df['post_clean'] = df['clean'].rolling(window=3, min_periods=1).max().shift(1).fillna(0)
# df['clean'].rolling(window=3 , min_periods=1)는 최근 3개 행에서 청소가 발생했는지를 확인하는 코드
# 즉, clean의 값이 0 0 1 0 0 0 이면 3개씩 묶어서 1이 포함되었는지를 확인
# 이후 rolling된 값 중 최댓값을 구함, 3개 중 1개라도 1이면 결과 1, 0이면 결과 0
# 즉 최근 3개 지점 중 청소가 발생했으면 post-clean 후보로 표시
# shift(1)은 clean이 발생한 바로 다음 시점부터 영향을 주고 싶을 때 사용
# 즉 clean이 1인 행의 다음 행부터 post_clean이 1이 되도록 함 
# 결측값은 0으로 처리
# ------> clean 값이 1인 다음행부터 3개의 행의 post_clean 값이 1이 됨
# post_clean == 1인 행의 인덱스를 찾는다
idx_to_drop = df[df['post_clean'] == 1].index

# 해당 인덱스의 행을 제거
df = df.drop(idx_to_drop).reset_index(drop=True)

# 시계열 피처
df['hour'] = df['measured_at'].dt.hour
df['dayofweek'] = df['measured_at'].dt.dayofweek
df['diff_ma_15'] = df['diff'].rolling(5).mean()
df['diff_std_15'] = df['diff'].rolling(5).std()

# # 1시간 뒤 거리와 변화량 타깃
df['diff_future'] = df['distance_cm'].shift(-20)
# # 한 시간 뒤의 거리를 미리 계산하여 dist_future 컬럼에 저장
# # 이때 데이터가 3분 간격이기에 20행 뒤의 거리를 통해 1시간 뒤 거리를 구함 
df['delta_1h'] = df['diff_future'] - df['distance_cm']
# 1시간 뒤 거리에서 현재 거리를 빼서 변화량을 구함

features = ['diff', 'diff_ma_15', 'diff_std_15', 'hour', 'dayofweek']
# 학습에 사용할 피처들
# 각각 땅에서 센서까지의 거리, 청소 직후인지 여부, 15분 이동평균, 15분 이동표준편차, 시간대, 요일
# 15분 이동평균과 15분 이동표준편차를 사용하는 이유는 
# 이동편균은 초음파 센서의 잡음이 발생할 수 있기에 평균을 사용해 15분동안 평균적으로 얼마나 차이가 나는지를 반영하기 위함
# 쓰레기 투입이 갑자기 많이 일어나는 시간대가 있다면 표준편차가 크다.
# 따라서 표준편차를 통해 최근 쓰레기 상태가 변동이 심한지 안정적인지 파악 가능하다.
# 피처와 타깃이 다 있는 행만 사용
df = df.dropna(subset=features + ['delta_1h'])

# 학습, 검증 분리
train = df[df['measured_at'] < '2024-12-01']
# 학습용 데이터를 2024년 12월 1일 이전 데이터로 설정하고
valid = df[df['measured_at'] >= '2024-12-01']
# 검증용 데이터를 2024년 12월 1일 이후 데이터로 설정 즉 한달치로 검증을 진행
X_train = train[features]
y_train = train['delta_1h']
# X_train 데이터프레임에서 features 피처들만 X_train에 저장하여 학습 데이터로 사용
# y_train에는 모델이 답으로 학습해야할 데이터인 delta_1h 컬럼을 사용

X_valid = valid[features]
y_valid = valid['delta_1h']
# 검증 데이터도 동일한 방식으로 설정 (12월 이후 한달치로)

# 모델 학습
model = RandomForestRegressor(n_estimators=200, random_state=42)
model.fit(X_train, y_train)
#RandomForestRegressor는 랜덤포레스트 회귀 모델로
# 여러 개의 의사결정나무(Decision Tree)를 생성하고 
# 각 트리가 예측한 값을 평균내서 최종 예측을 만드는 모델
# n_estimators=200은 200개의 트리를 사용하겠다는 의미
# random_state=42는 결과의 재현성을 위해 난수 지정

# 검증 성능 한 번 보기
y_pred_valid = model.predict(X_valid)
rmse = root_mean_squared_error(y_valid,y_pred_valid)
print("Validation RMSE (delta):", rmse)


# 저장
joblib.dump(model, "trash_predictor_delta.pkl")
# joblib.dump() 함수를 사용하여 학습된 모델을 "trash_predictor_delta.pkl" 파일로 저장