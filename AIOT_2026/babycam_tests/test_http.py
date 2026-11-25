import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

from babycam.common import Config, RemoteError, Supabase
from babycam.web import ResultCache, make_server
from test_core import result


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls
        class MockSupabase(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, dict(self.headers), data))
                if "/object/list/" in self.path:
                    offset = data["offset"]
                    payload = [{"name": f"{n:012}.ts"} for n in range(offset, min(1015, offset+1000))]
                    body = json.dumps(payload).encode()
                else:
                    body = b""
                self.send_response(200); self.end_headers(); self.wfile.write(body)
            def do_GET(self):
                calls.append((self.path, dict(self.headers), None))
                self.send_response(200)
                self.send_header("Content-Length", "5"); self.end_headers(); self.wfile.write(b"video")
            def log_message(self, *_):
                pass
        self.remote = ThreadingHTTPServer(("127.0.0.1", 0), MockSupabase)
        threading.Thread(target=self.remote.serve_forever, daemon=True).start()
        self.addCleanup(self.remote.server_close)
        self.addCleanup(self.remote.shutdown)
        self.cfg = Config(f"http://127.0.0.1:{self.remote.server_port}", "sb_secret_test")
        self.api = Supabase(self.cfg)

    def test_storage_paginates_and_opaque_key_is_not_bearer(self):
        self.assertEqual(len(self.api.list_segments()), 1015)
        self.assertEqual([c[2]["offset"] for c in self.calls], [0, 1000])
        self.assertEqual(self.calls[0][1]["Apikey"], "sb_secret_test")
        self.assertNotIn("Authorization", self.calls[0][1])

    def test_download_uses_private_endpoint_and_atomic_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "000000000210.ts"
            self.api.download(path.name, path)
            self.assertEqual(path.read_bytes(), b"video")
            self.assertFalse(path.with_suffix(".part").exists())
        self.assertIn("/object/authenticated/breathing-video/", self.calls[0][0])

    def test_result_upload_ignores_duplicates_and_preserves_false(self):
        self.api.save_result(result())
        self.assertIn("on_conflict=batch_id", self.calls[0][0])
        self.assertEqual(self.calls[0][1]["Prefer"], "resolution=ignore-duplicates,return=minimal")
        self.assertIs(self.calls[0][2]["is_anomaly"], False)

    def test_cache_keeps_last_result_on_network_failure(self):
        cache, api = ResultCache(), Mock()
        api.results.return_value = [result()]
        cache.refresh(api)
        success = cache.snapshot()["last_success_at"]
        api.results.side_effect = RemoteError("secret must not reach browser")
        cache.refresh(api)
        data = cache.snapshot()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["last_success_at"], success)
        self.assertNotIn("secret", data["error"])

    def test_local_api_static_assets_and_host_guard(self):
        cache = ResultCache(preview=True)
        server = make_server(0, cache)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/api/results") as response:
            self.assertEqual(json.load(response)["results"], [])
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        for asset in ("/", "/app.js", "/style.css"):
            with urllib.request.urlopen(base + asset) as response:
                self.assertGreater(len(response.read()), 0)
        for path, code in (("/.env", 404), ("/api/results?limit=-1", 400)):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(base + path)
            self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(urllib.request.Request(base + "/api/results", headers={"Host":"attacker.invalid"}))
        self.assertEqual(ctx.exception.code, 403)

    def test_busy_port_is_rejected_instead_of_shared(self):
        server = make_server(0, ResultCache())
        self.addCleanup(server.server_close)
        with self.assertRaises(OSError):
            duplicate = make_server(server.server_port, ResultCache())
            duplicate.server_close()


if __name__ == "__main__":
    unittest.main()
