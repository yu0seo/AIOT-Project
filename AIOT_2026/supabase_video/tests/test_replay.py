"""Run the actual uploader and downloader together against a test camera."""
import argparse
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client import ServiceError, call, load_config
from fetch import download_window
from upload import terminate


def main():
    import imageio_ffmpeg
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config_dir / "supabase_pc.json")
    assert config["camera_id"] != "pi-camera"
    uploader = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / "upload.py"),
        "--config", str(args.config_dir / "supabase_pi.json"), "--source", str(args.source),
        "--ffmpeg", imageio_ffmpeg.get_ffmpeg_exe()])
    started = time.monotonic()
    try:
        # Wait until the new capture session has replaced any previous test session.
        time.sleep(3)
        while time.monotonic() - started < 60:
            try:
                manifest = call(config, "latest", query={"camera_id": config["camera_id"]})
                download_window(config, args.output, manifest)
                print("PASS: continuous uploader -> private Storage -> latest 30s / 300 frames", flush=True)
                uploader.wait(timeout=15)
                assert uploader.returncode == 0
                return
            except ServiceError as exc:
                if exc.status != 409:
                    raise
                time.sleep(1)
        raise AssertionError("Continuous replay did not produce a complete current window")
    finally:
        terminate(uploader)


if __name__ == "__main__":
    main()
