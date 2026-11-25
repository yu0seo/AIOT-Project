"""Local canonical result database plus readable, replaceable CSV/JSON/Markdown exports."""
import csv
import html
import json
import logging
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .common import atomic_json, utc_now, validate_result

LOG = logging.getLogger("babycam.results")
LABELS = {"anomaly_candidate": "이상 후보", "below_threshold": "임계값 이하", "unscored": "분석 불가"}
KST = timezone(timedelta(hours=9))
CSV_FIELDS = ["저장 시각(한국)", "세션", "시작 번호", "끝 번호", "판정", "이상 여부", "BPM",
              "이상 점수", "임계값", "파형 MSE", "BPM MSE", "처리 시간(초)", "이유", "결과 ID"]


class LocalResultError(RuntimeError):
    pass


def korea_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")


def csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def markdown_cell(value):
    if value is None:
        return "—"
    return re.sub(r"([\\`*_\[\]()|])", r"\\\1", html.escape(str(value))).replace("\n", "<br>")


@contextmanager
def atomic_text(path, *, encoding="utf-8"):
    fd, temp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fp:
            yield fp
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


class LocalResults:
    def __init__(self, cfg):
        self.directory = cfg.result_dir.resolve()
        self.stream_id = cfg.stream_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = self.directory / "analysis_results.sqlite3"
        try:
            with self.connection() as conn, conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE IF NOT EXISTS results (batch_id TEXT PRIMARY KEY, "
                             "stream_id TEXT NOT NULL, end_seq INTEGER NOT NULL, created_at TEXT NOT NULL, "
                             "payload TEXT NOT NULL)")
                conn.execute("CREATE INDEX IF NOT EXISTS results_stream ON results(stream_id, end_seq DESC, created_at DESC)")
        except sqlite3.Error:
            raise LocalResultError("로컬 결과 DB를 열 수 없습니다. RESULT_DIR의 경로/권한을 확인하세요.") from None

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db, timeout=10)
        try:
            yield conn
        finally:
            conn.close()

    def results(self, limit=30):
        if not 1 <= limit <= 30:
            raise ValueError("limit은 1~30입니다.")
        try:
            with self.connection() as conn:
                records = conn.execute("SELECT payload FROM results WHERE stream_id=? "
                                       "ORDER BY end_seq DESC, created_at DESC LIMIT ?",
                                       (self.stream_id, limit)).fetchall()
            return [validate_result(json.loads(payload)) for (payload,) in records]
        except (sqlite3.Error, ValueError, TypeError):
            raise LocalResultError("로컬 결과를 읽을 수 없습니다. DB 파일/저장 공간을 확인하세요.") from None

    def save_result(self, payload):
        row = validate_result(payload)
        batch_id = row.get("batch_id", "")
        if not isinstance(batch_id, str) or not re.fullmatch(r"[a-f0-9]{64}", batch_id):
            raise ValueError("결과 batch_id가 올바르지 않습니다.")
        if row.get("stream_id") != self.stream_id or row.get("end_seq") != row.get("start_seq", -100) + 14:
            raise ValueError("결과의 세션/구간 번호를 확인하세요.")
        row.setdefault("created_at", utc_now())
        korea_time(row["created_at"])
        serialized = json.dumps(row, ensure_ascii=False, allow_nan=False)
        try:
            with self.connection() as conn, conn:
                conn.execute("INSERT OR IGNORE INTO results VALUES (?, ?, ?, ?, ?)",
                             (batch_id, self.stream_id, row["end_seq"], row["created_at"], serialized))
                saved = conn.execute("SELECT payload FROM results WHERE batch_id=?", (batch_id,)).fetchone()
            row = json.loads(saved[0])  # Repeated saves preserve the original result and timestamp.
        except sqlite3.Error:
            raise LocalResultError("로컬 결과 저장 실패. 저장 공간/권한을 확인하세요. 커서는 유지됩니다.") from None
        # The committed database remains readable even when Excel locks the derived CSV.
        for exporter in (lambda: self.export_json(row), self.export_markdown, self.export_csv):
            try:
                exporter()
            except OSError:
                LOG.warning("결과 DB 저장은 완료했지만 보기용 파일을 갱신하지 못했습니다. "
                            "Excel/편집기에서 파일을 닫으세요. 다음 저장 때 다시 갱신합니다.")

    def export_json(self, row):
        records = self.directory / "records"
        records.mkdir(exist_ok=True)
        atomic_json(records / f"{row['batch_id']}.json", row, indent=2)
        atomic_json(self.directory / "latest.json", self.results(1)[0], indent=2)

    def export_markdown(self):
        row = self.results(1)[0]
        values = [("저장 시각(한국)", korea_time(row["created_at"])), ("세션", row["stream_id"]),
                  ("구간 번호", f"{row['start_seq']} ~ {row['end_seq']}"),
                  ("판정", LABELS[row["status"]]), ("추정 호흡수(BPM)", row.get("pred_rr_bpm")),
                  ("이상 점수", row.get("anomaly_score")), ("임계값", row.get("threshold")),
                  ("처리 시간(초)", row.get("processing_sec")), ("이유", row.get("reason") or "—"),
                  ("결과 ID", row["batch_id"])]
        text = "# 최신 호흡 분석 결과\n\n| 항목 | 값 |\n|---|---|\n"
        text += "".join(f"| {label} | {markdown_cell(value)} |\n" for label, value in values)
        text += "\n임계값 이하는 임상적 정상 판정이 아니며, 분석 불가는 안전 상태를 뜻하지 않습니다.\n"
        text += "\n전체 기록: analysis_results.csv · 수치/파형: latest.json · 실시간 화면: serve_results.py\n"
        with atomic_text(self.directory / "latest.md") as fp:
            fp.write(text)

    def export_csv(self):
        with atomic_text(self.directory / "analysis_results.csv", encoding="utf-8-sig") as fp, self.connection() as conn:
            writer = csv.writer(fp)
            writer.writerow(CSV_FIELDS)
            for (payload,) in conn.execute("SELECT payload FROM results ORDER BY created_at, end_seq"):
                row = json.loads(payload)
                values = [korea_time(row["created_at"]), row["stream_id"], row["start_seq"], row["end_seq"],
                          LABELS[row["status"]], row.get("is_anomaly"), row.get("pred_rr_bpm"),
                          row.get("anomaly_score"), row.get("threshold"), row.get("wave_mse"), row.get("bpm_mse"),
                          row.get("processing_sec"), row.get("reason", ""), row["batch_id"]]
                writer.writerow([csv_cell(value) for value in values])
