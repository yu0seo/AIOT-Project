from flask import Flask,render_template
import pymysql
from model_predictor import predict_one_hour

app = Flask(__name__)

db_config = {
    "host": "aiot.mysql.database.azure.com",
    "user": "root1",
    "password": "admin123@",
    "database": "2025_distance_data",
    "port": 3306,
    "cursorclass": pymysql.cursors.DictCursor
}

@app.route("/")
def index():
    conn = pymysql.connect(**db_config)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, distance_cm, measured_at
        FROM distance_data
        ORDER BY id DESC
        LIMIT 1
    """)
    latest = cur.fetchone()
    conn.close()

    except_cm, expect_status = predict_one_hour()


    return render_template('index.html', latest=latest, expect_cm = except_cm, expect = expect_status)

if __name__ == '__main__':
    app.debug = True
    app.run()