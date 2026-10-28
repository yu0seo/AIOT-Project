import pandas as pd
import pymysql
import joblib

model = joblib.load("trash_predictor_delta.pkl")  # 새로 학습한 변화량 모델

db_config = {
    "host": "aiot.mysql.database.azure.com",
    "user": "root1",
    "password": "admin123@",
    "database": "2025_distance_data",
    "port": 3306,
    "cursorclass": pymysql.cursors.DictCursor,
} # 그대로

features = ['diff', 'diff_ma_15', 'diff_std_15', 'hour', 'dayofweek']
FULL_THRESHOLD = 15  # 이 값 이하면 꽉 찬 상태로 볼 기준

# 1) DB에서 데이터 읽기
def predict_one_hour():
    conn = pymysql.connect(**db_config)
    query = """
        SELECT measured_at, distance_cm
        FROM distance_data
        ORDER BY measured_at ASC
    """
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(query)
        rows = cur.fetchall()
    conn.close()

    df_new = pd.DataFrame(rows)

    # 2) 전처리
    df_new['measured_at'] = pd.to_datetime(df_new['measured_at'], errors='coerce')
    df_new['distance_cm'] = pd.to_numeric(df_new['distance_cm'], errors='coerce')

    # 센서 물리 범위 안으로 잘라서 모델에 넣기 (학습 범위 0~50과 맞추기)
    df_new['distance_cm'] = df_new['distance_cm'].clip(lower=0, upper=50)

    df_new = df_new.dropna(subset=['measured_at', 'distance_cm'])
    df_new = df_new.sort_values('measured_at')

    df_new['diff'] = df_new['distance_cm'].diff()
    df_new['clean_inferred'] = (df_new['diff'] > 30).astype(int)  # 학습 기준과 맞추면 더 좋음

    df_new['post_clean'] = (
        df_new['clean_inferred'].rolling(window=3, min_periods=1).max().shift(1).fillna(0)
    )

    df_new['hour'] = df_new['measured_at'].dt.hour
    df_new['dayofweek'] = df_new['measured_at'].dt.dayofweek
    df_new['diff_ma_15'] = df_new['distance_cm'].rolling(5).mean()
    df_new['diff_std_15'] = df_new['distance_cm'].rolling(5).std()

    df_new.fillna(method='bfill', inplace=True)
    df_new.fillna(method='ffill', inplace=True)

    # 3) 변화량 예측
    X_new = df_new[features]
    delta_pred = model.predict(X_new)  # 1시간 동안의 변화량
    df_new['delta_1h_pred'] = delta_pred

    # 4) 1시간 뒤 절대 거리로 환산
    df_new['predicted_1h'] = df_new['distance_cm'] + df_new['delta_1h_pred']
    df_new['predicted_1h'] = df_new['predicted_1h'].clip(lower=0, upper=50)
 
    # 5) 경고 판단
    latest = df_new.iloc[-1]
    pred = latest['predicted_1h']

    if pred <= FULL_THRESHOLD:
        status = "danger"
    elif pred <= FULL_THRESHOLD + 10:
        status = "caution"
    elif pred <= 50:
        status = "okay"
    else:
        status = "none"

    return float(latest['predicted_1h']), status
