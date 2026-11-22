#!/usr/bin/env python3
"""Open the Pi camera directly in a local desktop/VNC preview window."""
import argparse
import math
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=0, help="Preview seconds; 0 runs until stopped")
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("Duration must be a finite nonnegative number.")
    command = ["rpicam-hello", "-t", str(round(args.duration * 1000)), "--qt-preview",
               "--camera", "0", "--framerate", "10", "--viewfinder-width", "1280",
               "--viewfinder-height", "960", "--viewfinder-mode", "1296:972:10",
               "--roi", "0,0,1,1", "--preview", "80,80,960,720"]
    if args.print_command:
        print(shlex.join(command))
        return 0
    if not shutil.which(command[0]):
        parser.error("rpicam-hello is missing. Install rpicam-apps on the Pi.")
    env = os.environ.copy()
    # An SSH launch may still open a window on this user's existing Pi desktop.
    if not env.get("DISPLAY") and Path("/tmp/.X11-unix/X0").exists():
        env["DISPLAY"] = ":0"
        authority = Path.home() / ".Xauthority"
        if authority.exists():
            env.setdefault("XAUTHORITY", str(authority))
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        parser.error("Open this program from the Pi desktop or a VNC desktop terminal.")
    runtime = Path("/run/user") / str(os.getuid())
    if runtime.exists():
        env.setdefault("XDG_RUNTIME_DIR", str(runtime))

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    print("Opening Pi camera preview. Close the window or press Ctrl+C to stop.", flush=True)
    process = subprocess.Popen(command, env=env)
    try:
        result = process.wait()
        if result:
            print("Camera preview failed. If upload.py is using the camera, stop it with Ctrl+C first.", file=sys.stderr)
        return result
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OSError as exc:
        raise SystemExit(str(exc))
