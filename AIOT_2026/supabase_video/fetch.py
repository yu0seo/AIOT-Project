"""PC: download and validate the latest 30 seconds, without modifying model code."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from client import ServiceError, call, get_segment, load_config


def default_config():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config")) / "AIOT-SupabaseVideo" / "supabase_pc.json"


def validate_segment(payload):
    import av
    times = []
    with av.open(io.BytesIO(payload), format="mpegts") as video:
        if len(video.streams.video) != 1 or video.streams.audio:
            raise ValueError("Expected one video stream and no audio.")
        stream = video.streams.video[0]
        if stream.codec_context.name != "h264" or stream.average_rate is None or abs(float(stream.average_rate) - 10) > 0.01:
            raise ValueError("The video is not H.264 at 10 FPS.")
        size = None
        for frame in video.decode(stream):
            if frame.pts is None or len(times) >= 20:
                raise ValueError("Invalid frame count or missing timestamps.")
            if not times and not frame.key_frame:
                raise ValueError("A segment must start with a keyframe.")
            current_size = (frame.width, frame.height)
            size = size or current_size
            if size != current_size:
                raise ValueError("Resolution changed within a segment.")
            times.append(float(frame.pts * frame.time_base))
    if len(times) != 20 or any(abs(b-a-0.1) > 0.005 for a,b in zip(times,times[1:])):
        raise ValueError("Expected exactly 20 consecutive frames at 10 FPS.")
    return size


def download_window(config, output, manifest=None):
    import av
    import imageio_ffmpeg
    manifest = manifest or call(config, "latest", query={"camera_id": config["camera_id"]})
    if manifest.get("fps") != 10 or manifest.get("frame_count") != 300 or len(manifest.get("segments", [])) != 15:
        raise ValueError("Invalid 30-second manifest.")
    output = Path(output).resolve()
    if output.exists() or output.with_suffix(".json").exists():
        raise ValueError("Output exists; choose a new filename.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        contents = list(pool.map(lambda item: get_segment(config, item["download_url"]), manifest["segments"]))
    sizes = []
    for item, content in zip(manifest["segments"], contents):
        sizes.append(validate_segment(content))
        etag = (item.get("etag") or "").strip('"')
        if re.fullmatch(r"[0-9a-fA-F]{32}", etag) and hashlib.md5(content).hexdigest() != etag.lower():
            raise ValueError("Storage ETag does not match the downloaded bytes.")
    if len(set(sizes)) != 1:
        raise ValueError("Resolution changed across the 30-second window.")
    with tempfile.TemporaryDirectory(prefix="supabase-window-", dir=output.parent) as directory:
        root = Path(directory)
        lines = []
        for index, content in enumerate(contents):
            name = f"segment_{index:03d}.ts"
            (root / name).write_bytes(content)
            lines.append(f"file '{name}'\nduration 2.0\n")
        (root / "list.txt").write_text("".join(lines), encoding="ascii")
        pending = root / "latest30.mp4"
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-n",
            "-f", "concat", "-safe", "1", "-i", str(root / "list.txt"), "-map", "0:v:0", "-an",
            "-c:v", "copy", "-movflags", "+faststart", str(pending)], capture_output=True)
        if result.returncode:
            raise ValueError("MP4 remux failed: " + result.stderr.decode("utf-8", errors="replace"))
        times = []
        with av.open(str(pending)) as video:
            for frame in video.decode(video=0):
                if frame.pts is None:
                    raise ValueError("Export timestamps are missing.")
                times.append(float(frame.pts * frame.time_base))
        if len(times) != 300 or any(abs(b-a-0.1) > 0.005 for a,b in zip(times,times[1:])):
            raise ValueError("Export is not 300 consecutive frames at 10 FPS.")
        # Signed links are short-lived credentials. Do not persist them in the manifest.
        saved = dict(manifest)
        saved["segments"] = [{k:v for k,v in row.items() if k != "download_url"} for row in manifest["segments"]]
        saved["download_sha256"] = [hashlib.sha256(content).hexdigest() for content in contents]
        pending.replace(output)
        output.with_suffix(".json").write_text(json.dumps(saved, indent=2), encoding="utf-8")
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config())
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--output", type=Path)
    target.add_argument("--watch-dir", type=Path, help="Poll every 30 seconds; keep at most 6 outputs made in this run")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.output:
        download_window(config, args.output)
        print(f"Saved 300 frames / 10 FPS / 30 seconds: {args.output}")
        return
    previous, created = None, []
    while True:
        try:
            manifest = call(config, "latest", query={"camera_id": config["camera_id"]})
            stamp = manifest["segments"][-1]["capture_end"]
            if stamp != previous:
                name = datetime.fromisoformat(stamp).astimezone(timezone.utc).strftime("window_%Y%m%dT%H%M%S%fZ.mp4")
                output = args.watch_dir / name
                download_window(config, output, manifest)
                print(f"Saved {output}", flush=True)
                created.append(output)
                if len(created) > 6:
                    old = created.pop(0)
                    old.unlink(missing_ok=True)
                    old.with_suffix(".json").unlink(missing_ok=True)
                previous = stamp
        except ServiceError as exc:
            print(f"Waiting ({exc.status}): {exc}", flush=True)
        except OSError:
            print("Download connection failed; retrying at the next poll.", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc))
