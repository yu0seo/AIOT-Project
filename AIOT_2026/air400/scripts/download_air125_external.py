"""Fetch only the three public videos linked by AIR-125, then reproduce its listed clip ranges."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import imageio_ffmpeg

from air400_paths import DATA, PROJECT
from download_oneclass_sources import save

OUT = PROJECT/"06_단일클래스_학습데이터"
NODE = "C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt/dependencies/node/bin/node.exe"


def seconds(text):
    parts = str(text).split(":")
    # The sheet labels mm:ss; S07/S08 store mm:ss:00, not hour-long offsets.
    if len(parts) not in (2, 3) or (len(parts) == 3 and int(parts[2]) != 0):
        raise ValueError(f"Unexpected timestamp: {text}")
    return int(parts[0])*60+int(parts[1])


def main():
    rows = json.loads((OUT/"configs/air125_external_links.json").read_text(encoding="utf-8"))["rows"]
    clips = []
    for row in rows:
        cells = {c["cell"][0]: c for c in row["cells"]}
        if cells.get("A", {}).get("value") not in ("S06", "S07", "S08"):
            continue
        clips.append({"subject": cells["A"]["value"], "clip": cells["B"]["value"],
            "url": cells["C"]["hyperlink"] or cells["C"]["value"],
            "start_sec": seconds(cells["D"]["value"]), "end_sec": seconds(cells["E"]["value"]),
            "source_sheet": row["sheet"], "source_row": cells["A"]["cell"][1:]})
    media = DATA/"datasets/AIR_125/external_sources"
    media.mkdir(parents=True, exist_ok=True)
    previous_path = OUT/"configs/air125_external_download_status.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8"))["source_results"] if previous_path.exists() else []

    def fetch(subject):
        link = next(c["url"] for c in clips if c["subject"] == subject)
        target = media/(subject+".mp4")
        if target.exists(): return {"subject": subject, "status": "reused", "path": str(target)}
        private = next((r for r in previous if r["subject"] == subject and "private video" in str(r.get("reason", "")).lower()), None)
        if private:
            return private
        command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-progress",
                   "--socket-timeout", "20", "--retries", "1", "--extractor-retries", "1",
                   "--js-runtimes", "node:"+NODE,
                   "-f", "bestvideo[ext=mp4][height<=1080][vcodec^=avc1]/best[ext=mp4][height<=1080]/bestvideo[ext=mp4][height<=1080]",
                   "-o", str(target), link]
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            (media/(subject+"_download.log")).write_text(result.stdout+result.stderr, encoding="utf-8")
            return {"subject": subject, "status": "downloaded" if result.returncode == 0 and target.exists() else "unavailable",
                    "returncode": result.returncode, "log": str((media/(subject+"_download.log")).relative_to(DATA)),
                    "reason": result.stderr[-1500:] if result.returncode else None}
        except subprocess.TimeoutExpired:
            return {"subject": subject, "status": "unavailable", "reason": "Public download timed out; no login or private cookies used"}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, ("S06", "S07", "S08")))
    available = {r["subject"] for r in results if r["status"] in ("downloaded", "reused")}
    exports = []
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for c in clips:
        if c["subject"] not in available:
            continue
        target = DATA/"datasets/AIR_125"/c["subject"]/(c["clip"]+".mp4")
        source = media/(c["subject"]+".mp4")
        if not target.exists():
            temporary = target.with_suffix(".partial.mp4")
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                "-ss", str(c["start_sec"]), "-t", str(c["end_sec"]-c["start_sec"]),
                "-an", "-c:v", "libx264", "-crf", "0", "-preset", "veryfast", "-threads", "2",
                "-movflags", "+faststart", str(temporary)]
            subprocess.run(command, check=True, capture_output=True, timeout=240)
            temporary.replace(target)
        exports.append({**c, "video": str(target.relative_to(DATA)), "encoding": "lossless H264 CRF0; frame-accurate range from source sheet"})
        print("Prepared", c["subject"], c["clip"], flush=True)
    save(OUT/"configs/air125_external_download_status.json", {"source_results": results, "clips_prepared": len(exports),
         "clips": exports, "timestamp_interpretation": "Sheet header mm:ss; trailing :00 ignored after matching minute-long annotation durations",
         "not_prepared": [c for c in clips if c["subject"] not in available]})
    print(json.dumps({"source_results": results, "clips_prepared": len(exports)}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
