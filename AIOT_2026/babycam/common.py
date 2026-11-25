import json
import http.client
import math
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TABLE = "babycam_analysis_results"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TS_NAME = re.compile(r"^\d{12}\.ts$")
RESULT_COLUMNS = ("batch_id,stream_id,start_seq,end_seq,status,is_anomaly,anomaly_score,"
                  "threshold,pred_rr_bpm,wave_mse,bpm_mse,waveform,reason,created_at,"
                  "source_duration_sec,duration_sec,continuity,processing_sec,model_signature")


class ResultError(ValueError):
    pass


class RemoteError(RuntimeError):
    """A deliberately sanitized error: never includes credentials or remote response bodies."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value, *, indent=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(value, fp, ensure_ascii=False, allow_nan=False, indent=indent)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def load_env(path):
    values = {}
    if not Path(path).is_file():
        raise ValueError(f"설정 파일이 없습니다: {path}. .env.example을 복사하세요.")
    for number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key.strip()):
            raise ValueError(f".env {number}행은 KEY=VALUE 형식이어야 합니다.")
        value = value.strip()
        if value[:1] in ("'", '"'):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f".env {number}행 따옴표를 확인하세요.")
            value = value[1:-1]
        values[key.strip()] = value
    return values | dict(os.environ)  # Explicit process environment takes precedence.


@dataclass
class Config:
    url: str
    key: str = field(repr=False)
    root: Path = PROJECT_ROOT
    bucket: str = "breathing-video"
    prefix: str = "pi-camera/b68d088e-e0d0-4606-a21e-8e2a8099dda3"
    stream_id: str = "babycam-session-1"
    start_seq: int | None = None
    work_dir: Path = Path("output/stream_batches")
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    poll: float = 2.0
    result_poll: float = 2.0
    port: int = 8766
    result_dir: Path = PROJECT_ROOT / "output" / "stream_results"

    @classmethod
    def load(cls, path, *, require_supabase=True):
        path = Path(path).resolve()
        v = load_env(path) if path.is_file() or require_supabase else dict(os.environ)
        url, key = v.get("SUPABASE_URL", "").rstrip("/"), v.get("SUPABASE_SECRET_KEY", "")
        parsed = urllib.parse.urlsplit(url)
        local = parsed.hostname in ("127.0.0.1", "localhost")
        if require_supabase and (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))):
            raise ValueError(".env의 SUPABASE_URL에 https://프로젝트주소 를 입력하세요.")
        if require_supabase and not (key.startswith("sb_secret_") or key.startswith("eyJ")):
            raise ValueError("SUPABASE_SECRET_KEY에 서버용 sb_secret_... 또는 legacy service_role 키를 넣으세요.")
        if require_supabase and key.startswith("eyJ"):
            import base64
            try:
                payload = key.split(".")[1]
                role = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["role"]
            except (ValueError, KeyError, IndexError):
                raise ValueError("legacy service_role 키 형식을 확인하세요.") from None
            if role != "service_role":
                raise ValueError("anon JWT 대신 서버용 service_role 키를 넣으세요.")
        root = Path(v.get("AIR400_ROOT") or PROJECT_ROOT).expanduser()
        root = (path.parent / root).resolve()
        work = Path(v.get("WORK_DIR", "output/stream_batches"))
        cfg = cls(url=url, key=key, root=root,
                  bucket=v.get("STORAGE_BUCKET", "breathing-video"),
                  prefix=v.get("STORAGE_PREFIX", cls.prefix).strip("/"),
                  stream_id=v.get("STREAM_ID", cls.stream_id),
                  start_seq=None if v.get("START_SEQ", "auto").lower() == "auto" else int(v["START_SEQ"]),
                  work_dir=(root / work).resolve(),
                  ffmpeg=v.get("FFMPEG", "ffmpeg"), ffprobe=v.get("FFPROBE", "ffprobe"),
                  poll=float(v.get("POLL_SECONDS", 2)), result_poll=float(v.get("RESULT_POLL_SECONDS", 2)),
                  port=int(v.get("SERVER_PORT", 8766)),
                  result_dir=(root / Path(v.get("RESULT_DIR", "output/stream_results"))).resolve())
        if (not re.fullmatch(r"[A-Za-z0-9_-]+", cfg.bucket)
                or not re.fullmatch(r"[A-Za-z0-9_./-]+", cfg.prefix)
                or ".." in cfg.prefix.split("/") or not cfg.prefix
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", cfg.stream_id)
                or (cfg.start_seq is not None and not 0 <= cfg.start_seq < 10**12)
                or not 1 <= cfg.poll <= 60 or not 1 <= cfg.result_poll <= 60
                or not 1024 <= cfg.port <= 65535):
            raise ValueError("버킷/prefix/STREAM_ID/번호/조회 간격/포트 설정을 확인하세요.")
        return cfg


def select_batch(objects, next_seq):
    items = {int(o["name"][:-3]): o for o in objects
             if isinstance(o, dict) and isinstance(o.get("name"), str) and TS_NAME.fullmatch(o["name"])}
    if not items:
        return None
    start = min(items) if next_seq is None else next_seq
    return [items[n] for n in range(start, start + 15)] if all(n in items for n in range(start, start + 15)) else None


def validate_result(row):
    row = dict(row)
    status = row.get("status")
    if status not in ("anomaly_candidate", "below_threshold", "unscored"):
        raise ResultError("알 수 없는 결과 상태")
    if status == "unscored":
        for key in ("anomaly_score", "is_anomaly", "pred_rr_bpm", "wave_mse", "bpm_mse", "waveform"):
            row[key] = None
        row["reason"] = str(row.get("reason") or "분석할 수 없는 구간")[:500]
        try:
            threshold = float(row.get("threshold"))
            row["threshold"] = threshold if math.isfinite(threshold) and threshold >= 0 else None
        except (TypeError, ValueError):
            row["threshold"] = None
        return row
    try:
        for key in ("anomaly_score", "threshold", "pred_rr_bpm", "wave_mse", "bpm_mse"):
            row[key] = float(row[key])
            if not math.isfinite(row[key]) or row[key] < 0:
                raise ValueError()
        flag = row["is_anomaly"]
        if isinstance(flag, str) and flag.lower() in ("true", "false"):
            flag = flag.lower() == "true"
        if type(flag) is not bool or flag != (row["anomaly_score"] > row["threshold"]):
            raise ValueError()
        if flag != (status == "anomaly_candidate") or row["pred_rr_bpm"] <= 0:
            raise ValueError()
        row["is_anomaly"] = flag
        wave = row["waveform"]["x_10hz"]
        if not isinstance(wave, list) or len(wave) != 300 or not all(math.isfinite(float(x)) for x in wave):
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ResultError("결과 점수/상태/파형 형식이 올바르지 않습니다.") from None
    return row


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a privileged header to a redirect destination.


class Supabase:
    def __init__(self, cfg):
        self.cfg = cfg
        self.opener = urllib.request.build_opener(NoRedirect)
        self.headers = {"apikey": cfg.key, "Content-Type": "application/json"}
        if cfg.key.startswith("eyJ"):  # New opaque keys belong only in apikey, not Bearer JWT.
            self.headers["Authorization"] = "Bearer " + cfg.key

    def open(self, method, path, body=None, headers=None):
        req = urllib.request.Request(self.cfg.url + path,
                                     data=None if body is None else json.dumps(body, allow_nan=False).encode(),
                                     headers=self.headers | (headers or {}), method=method)
        try:
            return self.opener.open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            hint = "키/프로젝트 권한을 확인하세요" if code in (401, 403) else "버킷/테이블/SQL 설정을 확인하세요"
            raise RemoteError(f"Supabase HTTP {code}: {hint}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RemoteError("Supabase 네트워크 연결/시간 초과") from None

    def request(self, method, path, body=None, headers=None):
        try:
            with self.open(method, path, body, headers) as response:
                content = response.read(8 * 1024 * 1024 + 1)
        except (TimeoutError, OSError, http.client.HTTPException):
            raise RemoteError("Supabase 응답 수신 연결/시간 초과") from None
        try:
            if len(content) > 8 * 1024 * 1024:
                raise ValueError()
            return json.loads(content) if content else None
        except ValueError:
            raise RemoteError("Supabase JSON 응답 형식/크기 오류") from None

    def list_segments(self):
        found, offset = [], 0
        while True:
            page = self.request("POST", f"/storage/v1/object/list/{self.cfg.bucket}",
                                {"prefix": self.cfg.prefix, "limit": 1000, "offset": offset,
                                 "sortBy": {"column": "name", "order": "asc"}})
            if not isinstance(page, list) or not all(isinstance(o, dict) for o in page):
                raise RemoteError("Storage 목록 형식 오류")
            found.extend(page)
            if len(page) < 1000:
                return found
            offset += len(page)

    def download(self, name, destination):
        if not TS_NAME.fullmatch(name):
            raise ValueError("잘못된 TS 이름")
        key = urllib.parse.quote(f"{self.cfg.prefix}/{name}", safe="/")
        temp = destination.with_suffix(".part")
        try:
            with self.open("GET", f"/storage/v1/object/authenticated/{self.cfg.bucket}/{key}") as response:
                expected = response.headers.get("Content-Length")
                total = 0
                with temp.open("wb") as fp:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > 64 * 1024 * 1024:
                            raise RemoteError("TS 파일이 64MB 제한을 초과했습니다")
                        fp.write(chunk)
                if total == 0 or (expected is not None and total != int(expected)):
                    raise RemoteError("TS 파일 다운로드가 불완전합니다")
            os.replace(temp, destination)
        except (TimeoutError, OSError, http.client.HTTPException):
            raise RemoteError("TS 파일 다운로드 연결/저장 오류") from None
        finally:
            temp.unlink(missing_ok=True)

    def save_result(self, row):
        self.request("POST", f"/rest/v1/{TABLE}?on_conflict=batch_id", validate_result(row),
                     {"Prefer": "resolution=ignore-duplicates,return=minimal"})

    def results(self, limit=30):
        query = urllib.parse.urlencode({"select": RESULT_COLUMNS, "stream_id": "eq." + self.cfg.stream_id,
                                       "order": "end_seq.desc", "limit": limit})
        data = self.request("GET", f"/rest/v1/{TABLE}?{query}")
        if not isinstance(data, list):
            raise RemoteError("결과 목록 형식 오류")
        try:
            return [validate_result(row) for row in data]
        except (ResultError, TypeError, ValueError):
            raise RemoteError("저장된 결과의 상태/점수/파형 형식 오류") from None
