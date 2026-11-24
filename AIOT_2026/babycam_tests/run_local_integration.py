"""Explicit local integration fixture, NOT an uploader or a production data source.

Uses 15 different consecutive cuts of the existing local test.mp4, real FFmpeg and
the existing trained AIR-400 models. Supabase HTTP is emulated only on loopback.
"""
import argparse
import json
import logging
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from babycam.common import Config, Supabase, atomic_json, utc_now
from babycam.web import ResultCache, make_server
from babycam.worker import BatchProcessor, ExistingPipeline, Worker, signature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--serve-ui", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    source = args.output / "fixture_segments"
    source.mkdir(parents=True, exist_ok=True)
    if not any(source.glob("*.ts")):
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", r"C:\Users\OHS\air-400\test.mp4",
                        "-t", "30", "-an", "-vf", "fps=10", "-c:v", "libx264", "-preset", "ultrafast",
                        "-crf", "20", "-g", "20", "-keyint_min", "20", "-sc_threshold", "0",
                        "-f", "segment", "-segment_time", "2", "-reset_timestamps", "1",
                        "-segment_format", "mpegts", str(source / "%012d.ts")], check=True, timeout=120)
    files = sorted(source.glob("*.ts"))
    assert len(files) == 15, len(files)
    records = {}
    class FakeSupabase(BaseHTTPRequestHandler):
        def reply(self, data):
            body = json.dumps(data).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "/object/list/" in self.path:
                return self.reply([{"name": p.name, "id": p.stem, "updated_at":"fixture", "metadata":{"size":p.stat().st_size}} for p in files])
            if "/rest/v1/babycam_analysis_results" in self.path:
                records.setdefault(payload["batch_id"], payload | {"created_at": utc_now()})
                return self.reply(None)
            self.send_error(404)
        def do_GET(self):
            path = urlsplit(self.path).path
            if "/object/authenticated/" in path:
                file = source / path.rsplit("/", 1)[-1]
                body = file.read_bytes()
                self.send_response(200); self.send_header("Content-Length",str(len(body)))
                self.end_headers(); self.wfile.write(body)
            elif "/rest/v1/" in path:
                self.reply(list(records.values()))
            else:
                self.send_error(404)
        def log_message(self, *_):
            pass
    remote = ThreadingHTTPServer(("127.0.0.1", 0), FakeSupabase)
    threading.Thread(target=remote.serve_forever, daemon=True).start()
    cfg = Config(f"http://127.0.0.1:{remote.server_port}", "sb_secret_local_fixture",
                 stream_id="local-integration-only", work_dir=args.output / "worker")
    api = Supabase(cfg)
    pipeline = ExistingPipeline(cfg)
    worker = Worker(cfg, api, BatchProcessor(cfg, api, pipeline), signature(cfg))
    assert worker.tick() == "saved"
    assert worker.state["next_seq"] == 15
    assert len(records) == 1
    row = next(iter(records.values()))
    assert row["duration_sec"] == 30.0
    assert row["status"] in ("below_threshold", "anomaly_candidate"), row
    assert len(row["waveform"]["x_10hz"]) == 300
    assert len(row["waveform"]["raw_model"]) == 450
    atomic_json(args.output / "real_model_result.json", row)
    cache = ResultCache()
    cache.refresh(api)
    assert len(cache.snapshot()["results"]) == 1
    print("LOCAL_INTEGRATION_OK", json.dumps({k:row[k] for k in ("status","pred_rr_bpm","anomaly_score","processing_sec")}), flush=True)
    if args.serve_ui:
        server = make_server(8765, cache)
        print("UI_READY http://127.0.0.1:8765", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    remote.shutdown(); remote.server_close()


if __name__ == "__main__":
    main()
