#!/usr/bin/env python3
"""Run local YOLO instance segmentation on IDD, a video/stream, or a chosen screen area."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "data/models/yolo11l-seg.pt"
WINDOW = "Road Eye - YOLO segmentation (Q / ESC to exit)"
VEHICLE_CLASSES = [2, 3, 5, 7]  # COCO: car, motorcycle, bus, truck; excludes train.


class RunStatus:
    def __init__(self):
        self.path = ROOT / "data/runtime" / f"segmentation-status-{os.getpid()}.json"
        self.state = {"pid": os.getpid(), "frames": 0}
        self.update(stage="loading_model")

    def update(self, **values):
        self.state.update(values, updated_at=datetime.now(timezone.utc).isoformat())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")


def result_window_layout(region, monitors):
    """Prefer free desktop space, and always keep the result within one monitor."""
    gap = 12
    for desired_w, desired_h in ((960, 540), (640, 360), (480, 270)):
        for monitor in monitors:
            left, top = monitor["left"], monitor["top"]
            right, bottom = left + monitor["width"], top + monitor["height"]
            if desired_w + gap * 2 > monitor["width"] or desired_h + 60 > monitor["height"]:
                continue
            candidates = [(region["left"] + region["width"] + gap, region["top"]),
                          (region["left"] - desired_w - gap, region["top"]),
                          (region["left"], region["top"] + region["height"] + gap),
                          (region["left"], region["top"] - desired_h - gap), (left + gap, top + gap)]
            for x, y in candidates:
                x = max(left + gap, min(x, right - desired_w - gap))
                y = max(top + gap, min(y, bottom - desired_h - 48))
                separated = (x + desired_w <= region["left"] or x >= region["left"] + region["width"]
                             or y + desired_h + 36 <= region["top"] or y >= region["top"] + region["height"])
                if separated:
                    return x, y, desired_w, desired_h, False
    monitor = next((m for m in monitors if m["left"] <= region["left"] < m["left"] + m["width"]), monitors[0])
    return (monitor["left"] + gap, monitor["top"] + gap,
            max(200, min(960, monitor["width"] - gap * 2)),
            max(150, min(540, monitor["height"] - 60)), True)


class Segmenter:
    def __init__(self, model_path=DEFAULT_MODEL, device=None, imgsz=640, conf=0.25, classes=None):
        # Keep generated settings and caches inside this year's project.
        os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / "data/runtime/ultralytics"))
        os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "data/runtime/matplotlib"))
        os.environ.setdefault("TORCH_HOME", str(ROOT / "data/runtime/torch"))
        from ultralytics import YOLO
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.utils import YAML, IterableSimpleNamespace
        from ultralytics.utils.checks import check_yaml
        self.path = Path(model_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.model = YOLO(str(self.path))
        if self.model.task != "segment":
            raise ValueError("Use an instance segmentation model such as yolo11l-seg.pt")
        if classes is not None and any(c not in self.model.names for c in classes):
            raise ValueError("The selected model does not contain those class IDs")
        self.options = dict(imgsz=imgsz, conf=conf, classes=classes, verbose=False,
                            save=False, show=False)
        if device is not None:
            self.options["device"] = device
        self.tracker = BYTETracker(IterableSimpleNamespace(**YAML.load(check_yaml("bytetrack.yaml"))))
        self.track_ids = []

    def predict(self, frame):
        start = time.perf_counter()
        # Preserve every YOLO detection and its mask. model.track() filters Results
        # down to confirmed tracks, hiding unmatched/new detections in sparse CCTV.
        result = self.model.predict(frame, **self.options)[0]
        tracks = self.tracker.update(result.boxes.cpu().numpy(), result.orig_img)
        self.track_ids = [None] * len(result.boxes)
        for track in tracks:
            detection_index = int(track[-1])
            if not 0 <= detection_index < len(self.track_ids):
                raise RuntimeError("Tracker returned an invalid detection index")
            self.track_ids[detection_index] = int(track[4])
        elapsed_ms = (time.perf_counter() - start) * 1000
        return result, elapsed_ms


def plot_vehicle_tracks(result, track_ids):
    """Draw all detections, including those whose track ID is not confirmed yet."""
    from ultralytics.utils.plotting import Annotator, colors
    if len(track_ids) != len(result.boxes):
        raise ValueError("One tracking entry is required for every detection")
    display = result.plot(masks=True, boxes=False, labels=False, color_mode="class")
    annotator = Annotator(display, line_width=2)
    for box, track_id in zip(result.boxes, track_ids):
        class_id = int(box.cls.item())
        confidence = float(box.conf.item())
        identity = str(track_id) if track_id is not None else "--"
        color = colors(track_id, bgr=True) if track_id is not None else (180, 180, 180)
        annotator.box_label(box.xyxy[0].tolist(),
                            f"id:{identity} {result.names[class_id]} {confidence:.2f}", color=color)
    return annotator.result()


class ScreenArea:
    """User-selected capture region. Frames remain in local memory."""

    def __init__(self, cv2, np, monitor, region, capture_delay=3):
        from mss import MSS
        self.capture = MSS()
        self.region = None
        try:
            if region:
                self.region = dict(zip(("left", "top", "width", "height"), region))
            else:
                if not 1 <= monitor < len(self.capture.monitors):
                    raise ValueError(f"Monitor must be 1 to {len(self.capture.monitors) - 1}")
                display = self.capture.monitors[monitor]
                from screen_selection import select_screen_region
                self.region = select_screen_region(self.capture, display, capture_delay)
                if self.region is None:
                    raise SelectionCancelled()
            desktop = self.capture.monitors[0]
            if not (desktop["left"] <= self.region["left"] and desktop["top"] <= self.region["top"]
                    and self.region["left"] + self.region["width"] <= desktop["left"] + desktop["width"]
                    and self.region["top"] + self.region["height"] <= desktop["top"] + desktop["height"]):
                raise ValueError("Capture region is outside the desktop")
        except Exception:
            self.close()
            raise

    def read(self, np):
        return np.array(self.capture.grab(self.region))[:, :, :3].copy()

    def close(self):
        self.capture.close()


class SelectionCancelled(Exception):
    """A normal user-requested exit from preparation or region selection."""


def result_window_open(cv2):
    try:
        return cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        return False


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--screen", action="store_true", help="User selects a CCTV screen area")
    source.add_argument("--source", help="Video file or stream URL")
    source.add_argument("--example", choices=("sample", "impaired-crash"), help="Downloaded IDD video")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--device", help="cpu or CUDA device number")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--classes", type=int, nargs="+", default=VEHICLE_CLASSES.copy(),
                        help="Class IDs (default COCO vehicles: 2=car 3=motorcycle 5=bus 7=truck)")
    parser.add_argument("--seconds", type=float, default=0, help="Initial time in a local video")
    parser.add_argument("--monitor", type=int, default=1, help="Display number for screen selection")
    parser.add_argument("--capture-delay", type=float, default=3,
                        help="Seconds after the preparation button before capturing (default 3)")
    parser.add_argument("--region", type=int, nargs=4, metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"))
    parser.add_argument("--snapshot", type=Path, help="Save one segmented PNG and exit (file/IDD only)")
    parser.add_argument("--max-frames", type=int, help="Stop after this many analyzed frames")
    parser.add_argument("--headless", action="store_true", help="Process without showing a result window")
    args = parser.parse_args()
    if not 0 < args.conf <= 1 or not math.isfinite(args.conf):
        parser.error("--conf must be in (0, 1]")
    if args.imgsz <= 0 or args.monitor <= 0:
        parser.error("--imgsz and --monitor must be positive")
    if not math.isfinite(args.capture_delay) or args.capture_delay < 0:
        parser.error("--capture-delay must be finite and nonnegative")
    if not math.isfinite(args.seconds) or args.seconds < 0:
        parser.error("--seconds must be finite and nonnegative")
    if args.max_frames is not None and args.max_frames <= 0:
        parser.error("--max-frames must be positive")
    if args.classes is not None and any(c < 0 for c in args.classes):
        parser.error("--classes must be nonnegative")
    if args.region and (not args.screen or args.region[2] <= 0 or args.region[3] <= 0):
        parser.error("--region requires --screen and positive width/height")
    if args.screen and (args.snapshot or args.seconds):
        parser.error("--snapshot and --seconds are for file/IDD input")
    if args.snapshot and args.snapshot.suffix.lower() != ".png":
        parser.error("--snapshot must end in .png")
    if args.headless and not (args.snapshot or args.max_frames):
        parser.error("Use --snapshot or --max-frames with --headless")
    return args


def main():
    args = parse_args()
    reader = screen = None
    shown = False
    status = RunStatus()
    try:
        import cv2
        import numpy as np
        from inspect_idd import SequentialVideo, Timeline
        output = args.snapshot.resolve() if args.snapshot else None
        if output and output.exists():
            raise FileExistsError(f"Choose a new output filename: {output}")
        segmenter = Segmenter(args.model, args.device, args.imgsz, args.conf, args.classes)
        status.update(model=str(segmenter.path), classes=args.classes, tracker="bytetrack")
        timing = None
        next_index = 0
        is_example = not args.screen and not args.source
        if args.screen:
            print("Prepare the CCTV, then click the capture button. Close the preparation window to exit.", flush=True)
            status.update(stage="waiting_for_screen_selection")
            screen = ScreenArea(cv2, np, args.monitor, args.region, args.capture_delay)
            status.update(stage="screen_selected", region=screen.region)
        elif is_example:
            folder = "selected" if args.example == "impaired-crash" else "sample"
            raw = ROOT / "data/IDD" / folder / "Processed/Resampled_previous_10"
            videos = sorted(raw.glob("Participants/*/*/driving/*/*/cam_front/video.avi"))
            if not videos:
                raise FileNotFoundError(f"No IDD front video found: {raw}")
            video = videos[0]
            timing = Timeline(video.parent / "frame_timing.csv")
            if args.seconds * 1e9 > timing.times[-1]:
                raise ValueError("--seconds is beyond the selected IDD video")
            next_index = min(range(len(timing.times)), key=lambda i: abs(timing.times[i] - args.seconds * 1e9))
            reader = SequentialVideo(cv2, video)
            print(f"Video: {video}", flush=True)
        else:
            source_path = Path(args.source)
            source_timing = source_path.parent / "frame_timing.csv"
            if source_path.is_file() and source_timing.is_file():
                timing = Timeline(source_timing)
                if args.seconds * 1e9 > timing.times[-1]:
                    raise ValueError("--seconds is beyond the source video")
                next_index = min(range(len(timing.times)), key=lambda i: abs(timing.times[i] - args.seconds * 1e9))
                reader = SequentialVideo(cv2, source_path)
            else:
                reader = cv2.VideoCapture(args.source)
                if not reader.isOpened():
                    raise RuntimeError("Cannot open the video/stream source")
                if args.seconds:
                    if "://" in args.source:
                        raise ValueError("--seconds is only supported for local video files")
                    # Decode forward using media timestamps, rather than a guessed frame rate.
                    while True:
                        ok, _ = reader.read()
                        if not ok:
                            raise ValueError("--seconds is beyond the source video")
                        if reader.get(cv2.CAP_PROP_POS_MSEC) >= args.seconds * 1000:
                            break
        print(f"Segmentation ready: {segmenter.path.name}. Q/ESC closes the result window.", flush=True)
        processed = 0
        last_status_at = 0
        while True:
            # Detect X before inference or imshow can recreate a closed HighGUI window.
            if shown and not result_window_open(cv2):
                break
            timestamp = None
            if screen:
                frame = screen.read(np)
            elif timing:
                if next_index >= len(timing.times):
                    break
                row = timing.rows[next_index]
                timestamp = int(row["resampled_epoch_ns"]) / 1e9
                frame = reader.read(int(row["resampled_frame"]))
                next_index += 1
            else:
                ok, frame = reader.read()
                if not ok:
                    break
            result, elapsed_ms = segmenter.predict(frame)
            processed += 1
            counts = Counter(result.names[int(c)] for c in result.boxes.cls.tolist())
            masks = len(result.masks) if result.masks is not None else 0
            track_ids = [value for value in segmenter.track_ids if value is not None]
            if time.monotonic() - last_status_at >= 1:
                status.update(stage="running", frames=processed, objects=dict(counts), masks=masks,
                              inference_ms=round(elapsed_ms, 1), track_ids=track_ids,
                              detections=len(result.boxes), pending_ids=len(result.boxes) - len(track_ids))
                last_status_at = time.monotonic()
            if processed == 1 or output:
                print(f"Frame {processed}: objects={dict(counts)}, masks={masks}, IDs={track_ids}, model_ms={elapsed_ms:.1f}", flush=True)
            if output or not args.headless:
                display = plot_vehicle_tracks(result, segmenter.track_ids)
                title = f"{segmenter.path.stem} | {elapsed_ms:.0f} ms | detected {len(result.boxes)} | IDs {len(track_ids)}"
                if timestamp is not None:
                    title += f" | IDD {timestamp:.1f}s"
                cv2.rectangle(display, (0, 0), (display.shape[1], 32), (20, 20, 20), -1)
                cv2.putText(display, title, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.53,
                            (255, 255, 255), 1, cv2.LINE_AA)
                if is_example:
                    cv2.putText(display, "Data: TRI IDD | CC BY-NC-SA 4.0", (8, display.shape[0] - 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
                if output:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imencode(".png", display)[1].tofile(str(output))
                    print(f"Saved: {output}", flush=True)
                    status.update(stage="completed", frames=processed, snapshot=str(output))
                    return 0
                if not shown:
                    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
                    cv2.resizeWindow(WINDOW, 960, 540)
                    if screen:
                        x, y, width, height, overlaps = result_window_layout(screen.region, screen.capture.monitors[1:])
                        cv2.resizeWindow(WINDOW, width, height)
                        cv2.moveWindow(WINDOW, x, y)
                        status.update(result_window={"left": x, "top": y, "width": width, "height": height},
                                      result_overlaps_source=overlaps)
                        if overlaps:
                            print("Move the CCTV and result window apart; the selected source fills the available desktop.", flush=True)
                    shown = True
                elif not result_window_open(cv2):
                    break
                cv2.imshow(WINDOW, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27) or not result_window_open(cv2):
                    break
            if args.max_frames and processed >= args.max_frames:
                break
        if not processed:
            raise RuntimeError("No frames were processed")
        print(f"Finished: {processed} frames", flush=True)
        status.update(stage="completed", frames=processed)
        return 0
    except (KeyboardInterrupt, SelectionCancelled):
        status.update(stage="cancelled")
        return 0
    except Exception as exc:
        status.update(stage="error", error=str(exc))
        print(f"Segmentation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if reader is not None:
            reader.release()
        if screen is not None:
            screen.close()
        if shown:
            import cv2
            cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
