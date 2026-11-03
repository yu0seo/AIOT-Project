#!/usr/bin/env python3
"""Inspect IDD front video alongside timestamp-matched ego driving features."""

import argparse
from bisect import bisect_left
import csv
import math
from pathlib import Path
import sys
import time


FEATURES = [
    ("longitudinal_speed", "Forward speed", "m/s"),
    ("lateral_speed", "Lateral speed", "m/s"),
    ("longitudinal_acceleration", "Forward acceleration", "m/s^2"),
    ("lateral_acceleration", "Lateral acceleration", "m/s^2"),
    ("longitudinal_jerk", "Forward jerk", "m/s^3"),
    ("lateral_jerk", "Lateral jerk", "m/s^3"),
]
WIDTH, HEIGHT = 1344, 904
WINDOW = "IDD - synchronized video and ego features"
SCENARIO_CODES = ["1a", "2", "2b", "3c", "5", "6e", "7a", "8a"]


def number(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return math.nan


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return [
            {key.strip().replace(" ", "_"): value for key, value in row.items()}
            for row in csv.DictReader(stream)
        ]


class Timeline:
    def __init__(self, path):
        self.rows = sorted(read_rows(path), key=lambda row: int(row["resampled_epoch_ns"]))
        self.times = [int(row["resampled_epoch_ns"]) for row in self.rows]
        if not self.times or any(a == b for a, b in zip(self.times, self.times[1:])):
            raise ValueError(f"Empty or duplicate timestamps: {path}")

    def nearest(self, timestamp, tolerance_ns=75_000_000):
        i = bisect_left(self.times, timestamp)
        candidates = [j for j in (i - 1, i) if 0 <= j < len(self.times)]
        j = min(candidates, key=lambda j: abs(self.times[j] - timestamp))
        return self.rows[j] if abs(self.times[j] - timestamp) <= tolerance_ns else {}


class SequentialVideo:
    """Seek by decoded ordinal: sample AVI metadata reports a misleading 600 fps.

    CAP_PROP_POS_FRAMES can consequently seek to the wrong scene. Reopening and
    decoding forward is slower for backward jumps but preserves the CSV mapping.
    """

    def __init__(self, cv2, path):
        self.cv2, self.path = cv2, path
        self.capture = None
        self.position, self.frame = -1, None
        self.reopen()

    def reopen(self):
        if self.capture is not None:
            self.capture.release()
        self.capture = self.cv2.VideoCapture(str(self.path))
        self.position, self.frame = -1, None
        if not self.capture.isOpened():
            raise RuntimeError(f"Cannot open video: {self.path}")

    def read(self, index):
        if index < self.position:
            self.reopen()
        while self.position < index:
            ok, self.frame = self.capture.read()
            if not ok:
                raise RuntimeError(f"Cannot decode video frame {self.position + 1}")
            self.position += 1
        return self.frame

    def release(self):
        self.capture.release()


def load_data(root, scenario):
    raw = root / "Resampled_previous_10"
    if scenario:
        relative = Path(scenario)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("--scenario must be a relative path under Resampled_previous_10")
    else:
        videos = sorted(raw.glob("Participants/*/*/driving/*/*/cam_front/video.avi"))
        if not videos:
            raise FileNotFoundError(f"No front video found under {raw}. Use the sample dataset.")
        relative = videos[0].parent.parent.relative_to(raw)
    directory = raw / relative
    timing = Timeline(directory / "cam_front" / "frame_timing.csv")
    ego = Timeline(root / "Resampled_previous_10_derived" / relative / "ego_tracks.csv")
    controls = Timeline(directory / "sim_bag" / "carla_hero_vehicle_status.csv")
    return relative, directory / "cam_front" / "video.avi", timing, ego, controls


def scenario_labels(root, scenario):
    """Separate experimental conditions from approximate event annotations.

    Alcohol rule follows the official DDD2024Dataset loader; annotation columns
    are the two-row header groups in the downloaded idd_annotation.csv.
    """
    parts = scenario.parts
    participant, round_name, code, task = parts[1], parts[2], parts[4].split("-")[0], parts[5]
    alcohol = (round_name == "R2") if participant.startswith("P") else (False if participant.isdigit() else None)
    labels = {"alcohol": alcohol, "task": task, "hazard": "unknown", "valid": "unknown", "crashes": []}
    annotation = root / "idd_annotation.csv"
    if not annotation.exists() or code not in SCENARIO_CODES:
        return labels
    with annotation.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    if len(rows) < 2 or rows[1][17:25] != SCENARIO_CODES:
        raise ValueError("Unexpected idd_annotation.csv column layout")
    row = next((row for row in rows[2:] if row and row[0] == participant), None)
    if row is None:
        return labels
    index = SCENARIO_CODES.index(code)
    labels["hazard"] = row[9 + index].strip() or "unannotated"
    labels["valid"] = {"1": "yes", "0": "NO"}.get(row[25 + index].strip(), "unknown")
    labels["crashes"] = [number(value) for value in row[17 + index].split(",") if math.isfinite(number(value))]
    return labels


def label(cv2, image, text, point, scale=0.5, color=(218, 225, 232)):
    cv2.putText(image, text, point, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def chart_background(cv2, np, ego, end_ns, annotations):
    image = np.full((HEIGHT, WIDTH, 3), (24, 21, 18), dtype=np.uint8)
    limits = []
    for index, (column, title, unit) in enumerate(FEATURES):
        x, y = (index % 2) * 672, 440 + (index // 2) * 140
        values = [number(row.get(column)) for row in ego.rows]
        finite = [value for value in values if math.isfinite(value)]
        if finite:
            low, high = min(finite), max(finite)
            margin = max((high - low) * 0.12, 0.01)
            low, high = low - margin, high + margin
        else:
            low, high = -1, 1
        left, top, right, bottom = x + 60, y + 36, x + 650, y + 113
        limits.append((left, top, right, bottom, low, high))
        label(cv2, image, f"{title} [{unit}]", (x + 16, y + 23), 0.48)
        label(cv2, image, f"{high:.2f}", (x + 3, top + 5), 0.33)
        label(cv2, image, f"{low:.2f}", (x + 3, bottom), 0.33)
        cv2.rectangle(image, (left, top), (right, bottom), (73, 65, 56), 1)
        for seconds in annotations["crashes"]:
            if 0 <= seconds * 1e9 <= end_ns:
                crash_x = round(left + seconds * 1e9 / end_ns * (right - left))
                cv2.line(image, (crash_x, top), (crash_x, bottom), (100, 100, 245), 1)
        if low <= 0 <= high:
            zero_y = round(bottom - (0 - low) / (high - low) * (bottom - top))
            cv2.line(image, (left, zero_y), (right, zero_y), (62, 55, 48), 1)
        previous = None
        for timestamp, value in zip(ego.times, values):
            if not math.isfinite(value) or not 0 <= timestamp <= end_ns:
                previous = None
                continue
            point = (round(left + timestamp / end_ns * (right - left)),
                     round(bottom - (value - low) / (high - low) * (bottom - top)))
            if previous is not None:
                cv2.line(image, previous, point, (180, 187, 76), 1, cv2.LINE_AA)
            previous = point
        label(cv2, image, "0 s", (left, bottom + 16), 0.33)
        label(cv2, image, f"{end_ns / 1e9:.1f} s", (right - 48, bottom + 16), 0.33)
    return image, limits


def render(cv2, np, frame, timing_row, ego, controls, background, limits, scenario, end_ns, annotations):
    image = background.copy()
    timestamp = int(timing_row["resampled_epoch_ns"])
    label(cv2, image, "IDD | front video + EGO driving features", (18, 27), 0.67)
    label(cv2, image, "Data: TRI IDD | CC BY-NC-SA 4.0", (912, 27), 0.43)
    label(cv2, image, str(scenario).replace("\\", "/"), (18, 49), 0.42)
    h, w = frame.shape[:2]
    ratio = min(896 / w, 374 / h)
    resized = cv2.resize(frame, (round(w * ratio), round(h * ratio)))
    rh, rw = resized.shape[:2]
    image[60 + (374 - rh) // 2:60 + (374 - rh) // 2 + rh,
          (896 - rw) // 2:(896 - rw) // 2 + rw] = resized
    cv2.rectangle(image, (0, 60), (490, 87), (24, 21, 18), -1)
    label(cv2, image, f"Time {timestamp / 1e9:.2f} s | video frame {timing_row['resampled_frame']}", (12, 80))
    label(cv2, image, "EGO = the vehicle carrying this camera", (912, 82), 0.48, (113, 214, 255))
    alcohol = {True: "YES", False: "NO", None: "unknown"}[annotations["alcohol"]]
    task = annotations["task"].removesuffix("_task")
    label(cv2, image, f"Alcohol: {alcohol} | Distraction: {task}", (912, 106), 0.47, (113, 214, 255))
    current = ego.nearest(timestamp)
    for i, ((column, title, unit), bounds) in enumerate(zip(FEATURES, limits)):
        value = number(current.get(column))
        display = f"{value:.3f}" if math.isfinite(value) else "N/A"
        label(cv2, image, f"{title}: {display} {unit}", (912, 143 + i * 25), 0.44)
        left, top, right, bottom, low, high = bounds
        x = round(left + timestamp / end_ns * (right - left))
        cv2.line(image, (x, top), (x, bottom), (113, 214, 255), 1)
        if math.isfinite(value):
            y = round(bottom - (value - low) / (high - low) * (bottom - top))
            cv2.circle(image, (x, y), 3, (113, 214, 255), -1)
        label(cv2, image, display, (right - 75, top - 12), 0.43, (113, 214, 255))
    control = controls.nearest(timestamp)
    for i, key in enumerate(("throttle", "brake", "steering")):
        value = number(control.get(key))
        label(cv2, image, f"{key}: {value:.2f}", (912 + i * 140, 306), 0.39)
    crash_text = ", ".join(f"~{value:g}s" for value in annotations["crashes"]) or "none annotated"
    label(cv2, image, f"Crash time: {crash_text}", (912, 337), 0.46, (100, 100, 245))
    label(cv2, image, f"Hazard: {annotations['hazard']}", (912, 363), 0.44)
    label(cv2, image, f"Valid hazard: {annotations['valid']}", (912, 389), 0.44)
    label(cv2, image, "Conditions are scenario labels, not frame-level abnormality.", (912, 420), 0.35)
    label(cv2, image, "SPACE play/pause | A/D +/-1 frame | J/L +/-1 s | drag Frame slider | Q/ESC exit", (18, 885), 0.51)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", choices=("sample", "impaired-crash"), default="sample",
                        help="Use the original sample or the downloaded alcohol + crash example")
    parser.add_argument("--processed-root", type=Path,
                        help="Override the example's Processed directory")
    parser.add_argument("--scenario", help="Relative scenario directory under Resampled_previous_10")
    parser.add_argument("--seconds", type=float, default=0, help="Initial scenario time in seconds")
    parser.add_argument("--snapshot", type=Path, help="Save one dashboard PNG and exit without a GUI")
    parser.add_argument("--check", action="store_true", help="Validate timestamps and video metadata, then exit")
    args = parser.parse_args()
    if args.processed_root is None:
        folder = "sample" if args.example == "sample" else "selected"
        args.processed_root = Path(__file__).resolve().parents[1] / "data/IDD" / folder / "Processed"
    if not math.isfinite(args.seconds) or args.seconds < 0:
        parser.error("--seconds must be finite and nonnegative")
    if args.snapshot and args.snapshot.suffix.lower() != ".png":
        parser.error("--snapshot must end in .png")
    capture = None
    window_open = False
    try:
        import cv2
        import numpy as np
        scenario, video, timing, ego, controls = load_data(args.processed_root, args.scenario)
        annotations = scenario_labels(args.processed_root, scenario)
        print(f"Scenario conditions and event annotations: {annotations}")
        end_ns = timing.times[-1]
        if end_ns <= 0 or args.seconds * 1e9 > end_ns:
            raise ValueError(f"Requested time is outside the video (0 to {end_ns / 1e9:.2f} s)")
        capture = SequentialVideo(cv2, video)
        frame_ids = [int(row["resampled_frame"]) for row in timing.rows]
        if any(i < 0 for i in frame_ids) or any(a >= b for a, b in zip(frame_ids, frame_ids[1:])):
            raise ValueError("Video frame indices are negative or not increasing")
        print(f"Scenario: {scenario}\nTimeline: {len(frame_ids)} frames, {end_ns / 1e9:.2f} seconds")
        missing = sum(not ego.nearest(t) for t in timing.times)
        print(f"Timestamp matches: {len(timing.times) - missing}/{len(timing.times)} (tolerance 75 ms)")
        if missing:
            raise ValueError("Video and ego features do not cover the same timeline")
        if args.check:
            capture.read(frame_ids[-1])
            ok, _ = capture.capture.read()
            if ok:
                raise ValueError("Video has extra decoded frames beyond the timing CSV")
            print(f"Decoded video through frame {frame_ids[-1]}; frame count matches CSV")
            for column, _, unit in FEATURES:
                valid = [number(row.get(column)) for row in ego.rows]
                valid = [value for value in valid if math.isfinite(value)]
                print(f"{column} [{unit}]: {len(valid)} finite values")
                if not valid:
                    raise ValueError(f"No finite values for {column}")
            return 0
        background, limits = chart_background(cv2, np, ego, end_ns, annotations)
        position = min(range(len(timing.times)), key=lambda i: abs(timing.times[i] - args.seconds * 1e9))

        def dashboard(index):
            frame_id = frame_ids[index]
            frame = capture.read(frame_id)
            return render(cv2, np, frame, timing.rows[index], ego, controls,
                          background, limits, scenario, end_ns, annotations)

        if args.snapshot:
            output = args.snapshot.resolve()
            if output.exists():
                raise FileExistsError(f"Choose a new snapshot filename: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            png = cv2.imencode(".png", dashboard(position))[1]
            png.tofile(str(output))
            print(f"Saved: {output}")
            return 0
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        window_open = True
        cv2.resizeWindow(WINDOW, WIDTH, HEIGHT)
        cv2.createTrackbar("Frame", WINDOW, position, len(timing.times) - 1, lambda _: None)
        playing, drawn = False, None
        next_frame_at = time.monotonic()
        while True:
            selected = cv2.getTrackbarPos("Frame", WINDOW)
            if selected != position:
                position, playing = selected, False
            if drawn != position:
                cv2.imshow(WINDOW, dashboard(position))
                drawn = position
            key = cv2.waitKey(10) & 0xFF
            if key in (ord("q"), ord("Q"), 27) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == 32:
                playing = not playing
                next_frame_at = time.monotonic()
            elif key in (ord("a"), ord("d"), ord("j"), ord("l")):
                playing = False
                if key in (ord("a"), ord("d")):
                    position += -1 if key == ord("a") else 1
                else:
                    target = timing.times[position] + (-1 if key == ord("j") else 1) * 1_000_000_000
                    position = min(range(len(timing.times)), key=lambda i: abs(timing.times[i] - target))
                position = max(0, min(position, len(timing.times) - 1))
                cv2.setTrackbarPos("Frame", WINDOW, position)
            if playing and time.monotonic() >= next_frame_at:
                if position == len(timing.times) - 1:
                    playing = False
                else:
                    delay = (timing.times[position + 1] - timing.times[position]) / 1e9
                    position += 1
                    cv2.setTrackbarPos("Frame", WINDOW, position)
                    next_frame_at = time.monotonic() + delay
        return 0
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        print(f"IDD inspection failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if capture is not None:
            capture.release()
        if window_open:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
