#!/usr/bin/env python3
"""Stream a Raspberry Pi 5 camera as H.264/MPEG-TS over TCP."""

import argparse
import shlex
import shutil
import subprocess
import sys


def parse_args():
    parser = argparse.ArgumentParser(description="Pi 카메라 영상을 PC 한 대에 실시간 전송합니다.")
    parser.add_argument("--camera", type=int, default=0, help="카메라 번호 (기본: 0)")
    parser.add_argument("--port", type=int, default=5000, help="접속 포트 (기본: 5000)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--bitrate", type=int, default=2_000_000, help="비트레이트, bit/s")
    parser.add_argument("--print-command", action="store_true", help="실행 명령만 출력하고 종료")
    args = parser.parse_args()
    if args.camera < 0:
        parser.error("--camera는 0 이상이어야 합니다.")
    if not 1 <= args.port <= 65535:
        parser.error("--port는 1~65535여야 합니다.")
    if args.width <= 0 or args.height <= 0 or args.width % 2 or args.height % 2:
        parser.error("--width와 --height는 양의 짝수여야 합니다.")
    if args.fps <= 0 or args.bitrate <= 0:
        parser.error("--fps와 --bitrate는 양수여야 합니다.")
    return args


def main():
    args = parse_args()
    command = [
        "rpicam-vid", "--timeout", "0", "--nopreview",
        "--camera", str(args.camera),
        "--width", str(args.width), "--height", str(args.height),
        "--framerate", str(args.fps), "--bitrate", str(args.bitrate),
        "--codec", "libav", "--libav-format", "mpegts", "--low-latency",
        "--output", f"tcp://0.0.0.0:{args.port}?listen=1",
    ]
    print(shlex.join(command), flush=True)
    if args.print_command:
        return 0
    if shutil.which("rpicam-vid") is None:
        print("Pi의 Raspberry Pi OS에서 실행하세요. 명령이 없다면 sudo apt install -y rpicam-apps", file=sys.stderr)
        return 1
    print("기존 카메라 미리보기 프로그램은 종료한 상태여야 합니다.", flush=True)
    print(f"PC 접속 대기 중: TCP {args.port}. PC 수신 프로그램을 실행하세요.", flush=True)
    print("Pi IP 확인: hostname -I | 중단: Ctrl+C", flush=True)
    print("PC 연결이 끊어지면 이 프로그램부터 다시 실행하세요.", flush=True)
    try:
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            print("전송이 종료되었습니다. 위 오류와 카메라 사용 여부를 확인하세요.", file=sys.stderr)
            return 1
        return 0
    except KeyboardInterrupt:
        print("\n전송을 중단했습니다.")
        return 130
    except OSError as exc:
        print(f"전송 프로그램 실행 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
