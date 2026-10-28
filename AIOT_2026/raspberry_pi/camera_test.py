#!/usr/bin/env python3
"""Raspberry Pi 5 CSI camera check using Picamera2."""

import argparse
from datetime import datetime
import math
import os
from pathlib import Path
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(description="카메라 실시간 미리보기 또는 1280x720 사진 촬영을 실행합니다.")
    parser.add_argument("--list", action="store_true", help="인식된 카메라 목록만 출력")
    parser.add_argument("--camera", type=int, default=0, help="카메라 번호 (기본: 0)")
    parser.add_argument("--preview", action="store_true", help="Pi 데스크톱에 미리보기 표시")
    parser.add_argument("--live", action="store_true", help="VNC용 실시간 미리보기만 계속 표시 (사진 저장 없음)")
    parser.add_argument("--seconds", type=float, default=3.0, help="촬영 전 대기/미리보기 시간 (기본: 3초)")
    parser.add_argument("--output", type=Path, help="저장할 JPG/PNG 파일 경로")
    args = parser.parse_args()
    if args.camera < 0:
        parser.error("--camera는 0 이상이어야 합니다.")
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds는 0보다 큰 유한한 숫자여야 합니다.")
    if args.output and args.output.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        parser.error("--output은 .jpg, .jpeg 또는 .png 확장자를 사용하세요.")
    if args.live and args.output:
        parser.error("--live는 사진을 저장하지 않으므로 --output과 함께 사용할 수 없습니다.")
    return args


def main():
    args = parse_args()
    try:
        from picamera2 import Picamera2, Preview
    except ImportError as exc:
        print(f"Picamera2를 불러올 수 없습니다: {exc}", file=sys.stderr)
        print("Raspberry Pi OS에서 sudo apt install python3-picamera2 실행 후 시스템 python3로 실행하세요.", file=sys.stderr)
        return 1

    camera = None
    try:
        cameras = Picamera2.global_camera_info()
        if not cameras:
            print("카메라가 감지되지 않았습니다. 전원을 끈 뒤 CSI 케이블 연결을 확인하세요.", file=sys.stderr)
            print("추가 확인: rpicam-hello --list-cameras", file=sys.stderr)
            return 1

        for index, info in enumerate(cameras):
            print(f"카메라 {index}: {info.get('Model', 'unknown')} ({info.get('Id', '')})")
        if args.list:
            return 0
        if args.camera >= len(cameras):
            print(f"카메라 {args.camera}이 없습니다. 위 목록의 번호를 사용하세요.", file=sys.stderr)
            return 1
        if (args.preview or args.live) and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            print("미리보기는 VNC로 접속한 Pi 데스크톱 안의 터미널에서 실행하세요.", file=sys.stderr)
            return 1

        if not args.live:
            output = args.output
            if output is None:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                output = Path(__file__).resolve().parent / "captures" / f"camera_{stamp}.jpg"
            output = output.expanduser().resolve()
            if output.exists():
                print(f"파일이 이미 있습니다. 다른 --output 경로를 사용하세요: {output}", file=sys.stderr)
                return 1
            output.parent.mkdir(parents=True, exist_ok=True)

        camera = Picamera2(camera_num=args.camera)
        # A smaller live preview reduces software rendering and VNC traffic.
        size = (640, 480) if args.live else (1280, 720)
        config = camera.create_preview_configuration(main={"size": size})
        camera.configure(config)
        if args.preview or args.live:
            # Software Qt preview is suitable for VNC without a physical monitor.
            camera.start_preview(Preview.QT)
        camera.start()

        if args.live:
            print("실시간 영상 표시 중 (640x480). 사진/영상 파일은 저장하지 않습니다.", flush=True)
            print("종료하려면 실행한 터미널에서 Ctrl+C를 누르세요.", flush=True)
            while True:
                time.sleep(0.1)

        # Allow automatic exposure and white balance to settle before capture.
        print(f"카메라 작동 중: {args.seconds:g}초 후 촬영합니다. 중단: Ctrl+C", flush=True)
        time.sleep(args.seconds)
        camera.capture_file(str(output))
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("사진 파일이 저장되지 않았습니다.")
        print(f"사진 저장 완료: {output}")
        print("사진을 열어 실제 장면이 정상적으로 보이는지 확인하세요.")
        return 0
    except KeyboardInterrupt:
        print("\n카메라를 중단했습니다.")
        return 130
    except Exception as exc:
        print(f"카메라 테스트 실패: {exc}", file=sys.stderr)
        print("다른 카메라 프로그램을 종료하고 rpicam-hello --list-cameras로 확인하세요.", file=sys.stderr)
        return 1
    finally:
        if camera is not None:
            camera.close()


if __name__ == "__main__":
    sys.exit(main())
