"""Opt-in cloud test. Register a separate test camera before running this file.

Uses only that camera's device credentials; never requires a server admin key.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client import ServiceError, call, load_config, put_segment, reserve
from fetch import download_window, validate_segment


def rejected(status, operation):
    try:
        operation()
    except ServiceError as exc:
        assert exc.status == status, (exc.status, str(exc))
    else:
        raise AssertionError(f"Expected HTTP {status}")


def frame_hashes(path_or_bytes):
    import av
    source = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else str(path_or_bytes)
    with av.open(source) as video:
        return [hashlib.sha256(b"".join(bytes(plane) for plane in frame.planes)).hexdigest()
                for frame in video.decode(video=0)]


def main():
    import imageio_ffmpeg
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    upload = load_config(args.config_dir / "supabase_pi.json")
    read = load_config(args.config_dir / "supabase_pc.json")
    assert upload["camera_id"] == read["camera_id"] and upload["camera_id"] != "pi-camera"
    rejected(401, lambda: call({**read, "device_key": "x" * 40}, "latest", query={"camera_id": read["camera_id"]}))
    rejected(401, lambda: call(upload, "latest", query={"camera_id": read["camera_id"]}))
    rejected(401, lambda: reserve(read, str(uuid.uuid4()), 0, datetime.now(timezone.utc)))
    health = call(read, "health")
    assert health["fps"] == 10 and health["retention_seconds"] == 180
    print("PASS: service configuration and separate upload/read authentication", flush=True)

    generated = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10", "-t", "2", "-an", "-c:v", "libx264",
        "-preset", "ultrafast", "-g", "20", "-keyint_min", "20", "-sc_threshold", "0", "-bf", "0",
        "-f", "mpegts", "pipe:1"], capture_output=True, check=True).stdout
    assert validate_segment(generated) == (320, 240)
    session = str(uuid.uuid4())
    # Use server time so a Windows clock error cannot invalidate this transport test.
    start = datetime.fromisoformat(call(read, "health")["server_time"].replace("Z", "+00:00")) - timedelta(seconds=28)
    plans = reserve(upload, session, 0, start)
    rejected(409, lambda: call(read, "latest", query={"camera_id": read["camera_id"]}))
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda plan: put_segment(upload, plan["upload_url"], generated), plans["segments"]))
    # Upload retry must leave the same object intact.
    put_segment(upload, plans["segments"][0]["upload_url"], generated)
    manifest = call(read, "latest", query={"camera_id": read["camera_id"]})
    download_window(read, args.output, manifest)
    expected = frame_hashes(generated) * 15
    actual = frame_hashes(args.output)
    assert len(actual) == 300 and actual == expected, "Decoded pixel data changed during transport/remux"
    assert "download_url" not in args.output.with_suffix(".json").read_text()
    print("PASS: 15 Storage objects -> 300 frames / 10 FPS / 30s; decoded pixels unchanged", flush=True)
    again = reserve(upload, session, 0, start)
    assert len(again["segments"]) == 15 and all(plan.get("uploaded") for plan in again["segments"])
    rejected(409, lambda: reserve(upload, session, 0, start + timedelta(milliseconds=1)))
    rejected(410, lambda: reserve(upload, str(uuid.uuid4()), 0, start - timedelta(seconds=200)))
    print("PASS: missing objects blocked, reservation retry/conflict and expired upload blocked", flush=True)
    print(json.dumps({"camera_id": read["camera_id"], "session_id": session, "objects": 15}))


if __name__ == "__main__":
    main()
