"""Download only the authorized numbered AIR-400 clips and original AIR-125 archive."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import shutil
import ssl
import time
import urllib.request
import zipfile

from air400_paths import DATA, PROJECT

BASE = "https://coe.northeastern.edu/Research/AClab/AIR-400/"
OUT = PROJECT / "06_단일클래스_학습데이터"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def download(url, target, expected=None):
    assert url.startswith(BASE)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and (expected is None or target.stat().st_size == expected):
        return {"path": str(target.relative_to(DATA)), "status": "reused", "bytes": target.stat().st_size}
    partial = target.with_suffix(target.suffix + ".part")
    # Public-host-only TLS proxy compatibility, matching this workspace's downloader.
    context = ssl._create_unverified_context()
    for attempt in range(4):
        try:
            headers = {"User-Agent": "AIOT-authorized-dataset-download/1.0"}
            offset = partial.stat().st_size if partial.exists() else 0
            if offset:
                headers["Range"] = f"bytes={offset}-"
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), context=context, timeout=45) as response:
                append = offset > 0 and response.status == 206
                if expected is None and response.headers.get("Content-Length"):
                    expected = int(response.headers["Content-Length"]) + (offset if append else 0)
                with partial.open("ab" if append else "wb") as handle:
                    shutil.copyfileobj(response, handle, length=1024 * 1024)
            if expected is not None and partial.stat().st_size != expected:
                raise ValueError(f"Size mismatch: {partial.stat().st_size} != {expected}")
            partial.replace(target)
            return {"path": str(target.relative_to(DATA)), "status": "downloaded", "bytes": target.stat().st_size}
        except Exception as error:
            if attempt == 3:
                return {"path": str(target.relative_to(DATA)), "status": "error", "error": str(error)}
            time.sleep(1 + attempt)


def main():
    listing = json.loads((OUT / "configs/storage_estimate.json").read_text(encoding="utf-8"))
    archive = DATA / "archives/AIR_125.zip"
    tasks = [(r["url"], DATA / r["relative_path"], r["content_length_bytes"]) for r in listing["files"]]
    tasks.append((BASE + "AIR_125.zip", archive, 992984589))
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = [pool.submit(download, *task) for task in tasks]
        for future in as_completed(pending):
            result = future.result()
            results.append(result)
            if len(results) % 10 == 0 or result["status"] == "error" or len(results) == len(tasks):
                state = {"updated_at": datetime.now().astimezone().isoformat(), "finished": len(results), "total": len(tasks),
                         "errors": sum(r["status"] == "error" for r in results), "files": results}
                save(OUT / "configs/download_status.json", state)
                print(f"Downloads {len(results)}/{len(tasks)}, errors={state['errors']}", flush=True)
    if not archive.is_file():
        raise RuntimeError("AIR-125 archive download failed; see download_status.json")
    root = (DATA / "datasets").resolve()
    extracted = []
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            if not info.filename.startswith("AIR_125/") or info.is_dir():
                continue
            if info.filename.rsplit("/", 1)[-1].startswith("._"):
                continue
            target = (root / info.filename).resolve()
            if not target.is_relative_to(root):
                raise ValueError("Archive path escapes dataset root")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or target.stat().st_size != info.file_size:
                with handle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            extracted.append({"path": str(target.relative_to(DATA)), "bytes": info.file_size, "crc32": info.CRC})
    archive_sha = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
    save(OUT / "configs/air125_archive_inventory.json", {"archive": str(archive.relative_to(DATA)), "archive_sha256": archive_sha,
        "files": extracted, "video_count": sum(r["path"].lower().endswith(".mp4") for r in extracted),
        "excluded": "__MACOSX resource forks; no original_videos or processed previews downloaded"})
    print(f"AIR-125 extracted: {sum(r['path'].lower().endswith('.mp4') for r in extracted)} video files", flush=True)
    if any(r["status"] == "error" for r in results):
        raise RuntimeError("Some downloads failed; rerun to resume")


if __name__ == "__main__":
    main()
