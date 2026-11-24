import argparse
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .common import Config, RemoteError, Supabase, utc_now

LOG = logging.getLogger("babycam.web")
STATIC = Path(__file__).with_name("static")


class ResultCache:
    def __init__(self, preview=False):
        self.lock = threading.Lock()
        self.data = dict(results=[], last_success_at=None, error=None, mode="preview" if preview else "live")

    def snapshot(self):
        with self.lock:
            return dict(self.data, server_time=utc_now())

    def refresh(self, api):
        try:
            results = api.results(30)
            with self.lock:
                self.data.update(results=results, last_success_at=utc_now(), error=None)
        except RemoteError as exc:
            LOG.warning("결과 조회 실패: %s", exc)
            with self.lock:
                self.data["error"] = "Supabase 결과 조회에 실패했습니다. 마지막 결과를 표시합니다."


def make_server(port, cache):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed:
                return self.reply(403, {"error": {"code": "FORBIDDEN", "message": "localhost에서 접속하세요."}})
            uri = urlsplit(self.path)
            if uri.path == "/api/results":
                try:
                    limit = int(parse_qs(uri.query).get("limit", ["30"])[0])
                    if not 1 <= limit <= 30:
                        raise ValueError()
                except ValueError:
                    return self.reply(400, {"error": {"code": "INVALID_LIMIT", "message": "limit은 1~30입니다."}})
                data = cache.snapshot()
                data["results"] = data["results"][:limit]
                return self.reply(200, data)
            if uri.path == "/api/health":
                data = cache.snapshot()
                data.pop("results")
                return self.reply(200, data)
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if uri.path in assets:
                name, mime = assets[uri.path]
                return self.reply(200, (STATIC / name).read_bytes(), mime)
            return self.reply(404, {"error": {"code": "NOT_FOUND", "message": "경로를 찾을 수 없습니다."}})

        def reply(self, status, value, mime="application/json; charset=utf-8"):
            content = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(default_env):
    parser = argparse.ArgumentParser(description="Supabase 분석 결과 조회 + 로컬 실시간 화면/API")
    parser.add_argument("--env", type=Path, default=default_env)
    parser.add_argument("--preview", action="store_true", help="키 없이 빈 대기 화면만 확인; 가짜 분석 결과 없음")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    try:
        cfg = Config("", "") if args.preview else Config.load(args.env)
        cache = ResultCache(args.preview)
        server = make_server(cfg.port, cache)
        thread = None
        if not args.preview:
            api = Supabase(cfg)
            def poll():
                while not stop.is_set():
                    cache.refresh(api)
                    stop.wait(cfg.result_poll)
            thread = threading.Thread(target=poll, daemon=True, name="supabase-results")
            thread.start()
        LOG.info("화면: http://127.0.0.1:%d  (Ctrl+C 종료)", cfg.port)
        try:
            server.serve_forever(poll_interval=.5)
        finally:
            stop.set()
            server.server_close()
            if thread:
                thread.join(timeout=1)
        return 0
    except KeyboardInterrupt:
        LOG.info("결과 서버 종료")
        return 0
    except (ValueError, OSError) as exc:
        LOG.error("결과 서버 시작 오류: %s", exc)
        return 1
