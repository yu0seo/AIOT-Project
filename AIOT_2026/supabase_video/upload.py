#!/usr/bin/env python3
"""Pi: continuous 10-FPS capture, direct signed uploads into Supabase Storage."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from client import ServiceError, call, load_config, put_segment, reserve


def commands(args, spool):
    camera = ["rpicam-vid", "-t", str(round(args.duration * 1000)), "-n", "--camera", str(args.camera), "--width", str(args.width),
              "--height", str(args.height), "--framerate", "10", "--intra", "20", "--bitrate", str(args.bitrate),
              "--codec", "libav", "--libav-format", "mpegts", "--low-latency", "-o", "-", "--roi", "0,0,1,1"]
    if args.mode != "auto":
        camera += ["--mode", args.mode]
    segment = [args.ffmpeg, "-hide_banner", "-loglevel", "error"]
    segment += ["-re", "-i", str(args.source.resolve())] if args.source else ["-i", "pipe:0"]
    if args.source and args.duration:
        segment += ["-t", str(args.duration)]
    segment += ["-map", "0:v:0", "-an", "-c:v", "copy", "-f", "segment", "-segment_time", "2",
                "-segment_time_delta", "0.05", "-reset_timestamps", "1", "-segment_format", "mpegts",
                "-segment_list", str(spool / "closed.csv"), "-segment_list_type", "csv", "-segment_list_size", "0",
                str(spool / "segment_%012d.ts")]
    return camera, segment


def closed_segments(spool, cursor):
    if not (spool / "closed.csv").exists():
        return [], cursor
    result = []
    with (spool / "closed.csv").open(encoding="utf-8", newline="") as stream:
        stream.seek(cursor)
        while True:
            before = stream.tell()
            line = stream.readline()
            if not line or not line.endswith("\n"):
                return result, before
            name, start, end = next(csv.reader([line]))
            file = spool / Path(name).name
            if not file.resolve().is_relative_to(spool.resolve()):
                raise ValueError("Invalid spool path.")
            result.append((int(file.stem.removeprefix("segment_")), file, float(start), float(end)))


def terminate(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("supabase_pi.json"))
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=960)
    parser.add_argument("--mode", default="1296:972:10", help="OV5647 full field, or auto")
    parser.add_argument("--bitrate", type=int, default=2_000_000)
    parser.add_argument("--duration", type=float, default=0, help="Capture seconds; 0 runs until Ctrl+C")
    parser.add_argument("--source", type=Path, help="Replay a 10-FPS H.264 video with a 2-second GOP")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable path")
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()
    if args.camera < 0 or args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2 or args.bitrate <= 0 or not math.isfinite(args.duration) or args.duration < 0:
        parser.error("Invalid camera, even image dimensions or bitrate.")
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    if args.print_command:
        for command in commands(args, Path("<spool>")):
            print(shlex.join(command))
        return 0
    if not shutil.which(args.ffmpeg) or (not args.source and not shutil.which("rpicam-vid")):
        parser.error("Install ffmpeg and rpicam-apps on the Pi first.")
    if args.source and not args.source.is_file():
        parser.error("The --source file does not exist.")
    config = load_config(args.config)
    health = call(config, "health")
    if abs((datetime.fromisoformat(health["server_time"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()) > 5:
        parser.error("Pi/server clocks differ by more than 5 seconds. Synchronize the Pi clock.")
    session, plans = str(uuid.uuid4()), {}
    camera = segmenter = None
    with tempfile.TemporaryDirectory(prefix="aiot-supabase-video-") as temporary:
        spool = Path(temporary)
        anchor = datetime.now(timezone.utc)
        try:
            capture_command, segment_command = commands(args, spool)
            if not args.source:
                camera = subprocess.Popen(capture_command, stdout=subprocess.PIPE)
                segmenter = subprocess.Popen(segment_command, stdin=camera.stdout)
                camera.stdout.close()
            else:
                segmenter = subprocess.Popen(segment_command)
            print("10 FPS continuous capture; uploading closed 2-second segments. Ctrl+C stops.", flush=True)
            cursor, base_pts, pending = 0, None, []
            while True:
                rows, cursor = closed_segments(spool, cursor)
                pending.extend(rows)
                if pending and base_pts is None:
                    base_pts = pending[0][2]
                keep = []
                for item in pending:
                    start = anchor + timedelta(seconds=item[2] - base_pts)
                    if (datetime.now(timezone.utc) - start).total_seconds() >= 180:
                        item[1].unlink(missing_ok=True)
                        plans.pop(item[0], None)
                        print(f"Expired unsent segment {item[0]}; the gap will not be hidden.", flush=True)
                    else:
                        keep.append(item)
                pending = keep
                if pending:
                    sequence, file, start_pts, end_pts = pending[0]
                    start = anchor + timedelta(seconds=start_pts - base_pts)
                    if abs(end_pts - start_pts - 2) > 0.02:
                        file.unlink(missing_ok=True)
                        pending.pop(0)
                        print(f"Skipped incomplete/non-2-second segment {sequence}.", flush=True)
                        continue
                    try:
                        if sequence not in plans:
                            response = reserve(config, session, sequence, start)
                            plans.update({item["sequence"]: item for item in response["segments"]})
                        plan = plans[sequence]
                        if abs((datetime.fromisoformat(plan["capture_start"].replace("Z", "+00:00")) - start).total_seconds()) > 0.02:
                            raise ValueError("Capture PTS no longer matches its reservation; restart as a new session.")
                        if not plan.get("uploaded"):
                            put_segment(config, plan["upload_url"], file.read_bytes())
                        file.unlink(missing_ok=True)
                        pending.pop(0)
                        plans.pop(sequence)
                        print(f"Uploaded segment {sequence} to Supabase.", flush=True)
                    except ServiceError as exc:
                        if exc.status == 410:
                            pending.pop(0)
                            file.unlink(missing_ok=True)
                        elif exc.status >= 500 or exc.status == 429:
                            print(f"Supabase unavailable ({exc.status}); retrying.", flush=True)
                            time.sleep(2)
                        else:
                            raise
                    except (OSError, TimeoutError):
                        print("Upload connection failed; capture continues with a bounded spool.", flush=True)
                        time.sleep(2)
                elif segmenter.poll() is not None:
                    if segmenter.returncode or (camera and camera.poll() not in (None, 0)):
                        raise RuntimeError("Capture/segmentation failed. Check the messages above.")
                    return 0
                else:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            return 0
        finally:
            terminate(camera)
            if segmenter:
                try:
                    segmenter.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    terminate(segmenter)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Supabase upload failed: {exc}", file=sys.stderr)
        sys.exit(1)
