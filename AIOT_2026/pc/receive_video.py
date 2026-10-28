#!/usr/bin/env python3
"""Receive Pi video, optionally detect and track objects on the PC."""

import argparse
import math
from pathlib import Path
import sys
import threading
import time


class LatestFrameReceiver:
    """Continuously drain the decoder; retain only one frame for the consumer.

    The worker owns capture.read/release. Frame numbers and monotonic receive
    times describe PC decoding, not the camera's frame IDs or capture timestamps.
    """

    def __init__(self, capture):
        self.capture = capture
        self.lock = threading.Lock()
        self.stop_requested = threading.Event()
        self.finished = threading.Event()
        self.packet = None
        self.error = None
        self.thread = threading.Thread(target=self._receive, daemon=True)

    def start(self):
        self.thread.start()

    def _receive(self):
        sequence = 0
        try:
            while not self.stop_requested.is_set():
                ok, frame = self.capture.read()
                if not ok:
                    self.error = "프레임 수신이 중단되었습니다. Pi 전송 상태와 네트워크를 확인하세요."
                    break
                sequence += 1
                packet = (sequence, time.monotonic(), frame)
                with self.lock:
                    self.packet = packet
        except Exception as exc:
            self.error = str(exc)
        finally:
            try:
                self.capture.release()
            finally:
                self.finished.set()

    def latest(self):
        with self.lock:
            return self.packet

    def close(self):
        self.stop_requested.set()
        # Network reads have a 5-second timeout. Never release from a second
        # thread while the decoder is reading.
        self.thread.join(timeout=6)


def parse_args():
    parser = argparse.ArgumentParser(description="Windows PC에서 Pi 카메라 영상을 받습니다.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--host", help="라즈베리파이 IP (예: 192.168.0.50)")
    source.add_argument("--url", help="직접 지정할 영상 주소 (예: rtsp://192.168.0.50:8554/cam)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--headless", action="store_true", help="창 없이 수신만 확인")
    parser.add_argument("--duration", type=float, help="첫 프레임 수신 후 자동 종료할 초 단위 시간")
    parser.add_argument("--track", action="store_true", help="PC에서 YOLO 객체 탐지와 ByteTrack 추적 실행")
    parser.add_argument("--model", default="yolo11n.pt", help="YOLO 탐지 모델 파일 (기본: yolo11n.pt)")
    parser.add_argument("--classes", type=int, nargs="+", help="추적할 클래스 번호. 생략하면 모델의 전체 클래스")
    parser.add_argument("--device", help="YOLO 실행 장치 (예: cpu 또는 CUDA GPU 번호 0)")
    parser.add_argument("--imgsz", type=int, default=640, help="YOLO 입력 크기 (기본: 640)")
    parser.add_argument("--conf", type=float, default=0.1, help="탐지 신뢰도 하한 (기본: 0.1)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port는 1~65535여야 합니다.")
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error("--duration은 0보다 큰 유한한 숫자여야 합니다.")
    if args.imgsz <= 0:
        parser.error("--imgsz는 양수여야 합니다.")
    if not math.isfinite(args.conf) or not 0 < args.conf <= 1:
        parser.error("--conf는 0보다 크고 1 이하여야 합니다.")
    if args.classes is not None:
        if not args.track:
            parser.error("--classes는 --track과 함께 사용하세요.")
        if any(class_id < 0 for class_id in args.classes):
            parser.error("--classes 번호는 0 이상이어야 합니다.")
    return args


def main():
    args = parse_args()
    try:
        import cv2
    except ImportError:
        requirements = Path(__file__).resolve().with_name("requirements.txt")
        print(f'OpenCV 설치 필요: "{sys.executable}" -m pip install -r "{requirements}"', file=sys.stderr)
        return 1

    url = args.url or f"tcp://{args.host}:{args.port}"
    capture = None
    receiver = None
    window = "Road Eye - PC video (Q / ESC to quit)"
    window_open = False
    try:
        model = None
        if args.track:
            try:
                from ultralytics import YOLO
                import lap  # Check ByteTrack dependency before opening the live connection.
            except ImportError as exc:
                print(f"추적 라이브러리를 불러올 수 없습니다: {exc}", file=sys.stderr)
                requirements = Path(__file__).resolve().with_name("requirements-tracking.txt")
                print(f'설치: "{sys.executable}" -m pip install -r "{requirements}"', file=sys.stderr)
                return 1
            print(f"YOLO 모델 준비 중: {args.model}. 기본 모델의 첫 실행에는 다운로드가 필요할 수 있습니다.", flush=True)
            model = YOLO(args.model)
            if model.task != "detect":
                raise ValueError("이 프로그램에서는 객체 탐지용 YOLO 모델을 사용하세요.")
            if args.classes is not None and any(class_id not in model.names for class_id in args.classes):
                raise ValueError(f"모델에 없는 클래스 번호입니다. 모델 클래스: {model.names}")
            print("PC 분석 활성화: YOLO 탐지 + ByteTrack 추적", flush=True)
        print(f"접속 중: {url}", flush=True)
        capture = cv2.VideoCapture()
        opened = capture.open(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000,
        ])
        if not opened:
            print("접속 실패: Pi 전송을 먼저 실행하고 IP/포트/같은 네트워크 연결을 확인하세요.", file=sys.stderr)
            print("이 TCP 전송은 한 번에 PC 한 대만 연결합니다. Pi 전송도 다시 시작하세요.", file=sys.stderr)
            return 1
        receiver = LatestFrameReceiver(capture)
        receiver.start()
        if not args.headless:
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)
            window_open = True
        print("수신 시작. 영상 창의 Q/ESC 또는 터미널의 Ctrl+C로 종료합니다.", flush=True)
        previous_sequence = 0
        first_frame_time = None
        while True:
            packet = receiver.latest()
            if packet is not None and packet[0] != previous_sequence:
                sequence, received_at, frame = packet
                previous_sequence = sequence
                if first_frame_time is None:
                    first_frame_time = received_at
                    print(f"첫 프레임 수신: {frame.shape[1]}x{frame.shape[0]}", flush=True)
                display_frame = frame
                if model is not None:
                    started_at = time.perf_counter()
                    options = dict(
                        persist=True, tracker="bytetrack.yaml", classes=args.classes,
                        conf=args.conf, imgsz=args.imgsz, verbose=False, save=False, show=False,
                    )
                    if args.device is not None:
                        options["device"] = args.device
                    result = model.track(frame, **options)[0]
                    inference_ms = (time.perf_counter() - started_at) * 1000
                    if not args.headless:
                        display_frame = result.plot()
                        cv2.putText(
                            display_frame, f"YOLO + ByteTrack | model {inference_ms:.0f} ms",
                            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
                        )
                if not args.headless:
                    cv2.imshow(window, display_frame)
            if args.duration is not None and first_frame_time is not None:
                if time.monotonic() - first_frame_time >= args.duration:
                    print(f"수신 확인 완료: 디코딩한 프레임 {previous_sequence}개", flush=True)
                    return 0
            if receiver.finished.is_set():
                print(receiver.error or "영상 수신이 종료되었습니다.", file=sys.stderr)
                print("다시 연결하려면 Pi 전송 프로그램부터 재실행하세요.", file=sys.stderr)
                return 1
            if args.headless:
                time.sleep(0.01)
            else:
                key = cv2.waitKey(10) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    return 0
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    return 0
    except KeyboardInterrupt:
        print("\n수신을 중단했습니다.")
        return 0
    except Exception as exc:
        print(f"영상 수신/분석 오류: {exc}", file=sys.stderr)
        return 1
    finally:
        if receiver is not None:
            receiver.close()
        elif capture is not None:
            capture.release()
        if window_open:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
