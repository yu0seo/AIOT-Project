"""Fetch a reproducible, small AIR-400 comparison set and official model assets.

No training, existing project environment changes, or AIR_125 archive download.
The selected videos are fixed before any model outputs are examined.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import ssl
import time
import urllib.parse
import urllib.request

from air400_paths import ROOT, DATA
PUBLIC = "https://coe.northeastern.edu/Research/AClab/AIR-400/"
MODEL_FILES = {
    "DeepPhys": "DeepPhys_Deep_Body_best.pth",
    "TSCAN": "TSCAN_PCA_Body_best.pth",
    "EfficientPhys": "EfficientPhys_Coarse2fine_Body_best.pth",
    "VIRENet": "VIRENet_Coarse2fine_Body_best.pth",
}


def digest(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


class Downloader:
    def __init__(self, allow_unverified_tls: bool):
        self.context = (ssl._create_unverified_context() if allow_unverified_tls
                        else ssl.create_default_context())

    def read(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "AIR400-comparison/1.0"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, context=self.context, timeout=90) as response:
                    return response.read()
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        raise AssertionError("unreachable")

    def save(self, url: str, path: Path) -> dict:
        if not path.is_file() or path.stat().st_size == 0:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = self.read(url)
            temporary = path.with_name(path.name + ".partial")
            temporary.write_bytes(payload)
            temporary.replace(path)
        return {"path": str(path.relative_to(DATA)), "url": url,
                "bytes": path.stat().st_size, "sha256": digest(path)}

    def repository(self, repo: str, branch: str, destination: Path, select) -> dict:
        commit = json.loads(self.read(f"https://api.github.com/repos/{repo}/commits/{branch}"))["sha"]
        tree = json.loads(self.read(f"https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1"))
        selected = [x for x in tree["tree"] if x["type"] == "blob" and select(x["path"])]
        records = []
        for item in selected:
            relative = Path(item["path"])
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Repository path escaped source directory")
            record = self.save(f"https://raw.githubusercontent.com/{repo}/{commit}/{item['path']}", target)
            data = target.read_bytes()
            blob_hash = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            if blob_hash != item["sha"]:
                raise ValueError(f"Git blob checksum mismatch: {target}")
            records.append(record)
        return {"repository": repo, "commit": commit, "files": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-unverified-tls", action="store_true",
                        help="Per-request exception for public downloads behind this workstation's TLS proxy")
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    download = Downloader(args.allow_unverified_tls)
    repositories = []
    repositories.append(download.repository(
        "michaelwwan/air-400", "main", DATA / "source" / "air-400",
        lambda p: p.startswith("models/") or p.startswith("configs/inference/")
        or p in {"processors/pre_processor.py", "processors/post_processor.py", "infer.py",
                 "README.md", "LICENSE", "environment.yml"} or p.endswith("AGENTS.md")))
    print("Downloaded pinned AIR-400 source", flush=True)
    repositories.append(download.repository(
        "pathak22/pyflow", "master", DATA / "source" / "pyflow",
        lambda p: p.startswith("src/") or p in {"pyflow.pyx", "setup.py", "LICENSE", "README.md"}
        or p.endswith("AGENTS.md")))
    print("Downloaded pinned original Coarse2Fine source", flush=True)

    jobs = []
    for filename in MODEL_FILES.values():
        jobs.append((PUBLIC + "Model%20Checkpoints/" + filename, DATA / "weights" / filename))
    for filename in ("yolov8m.pt", "yolov8n-face.pt"):
        jobs.append((PUBLIC + "ROI%20Detectors/" + filename, DATA / "weights" / filename))
    samples = []
    for i in range(1, 11):
        subject = f"S{i:02d}"
        name = "01" if i == 7 else "1"
        url = PUBLIC + subject + "/"
        jobs.append((url + name + ".mp4", DATA / "videos" / subject / (name + ".mp4")))
        jobs.append((url + "out/" + name + ".hdf5", DATA / "references" / subject / (name + ".hdf5")))
        listing = download.read(url).decode("utf-8", errors="replace")
        csv_files = [urllib.parse.unquote(x) for x in re.findall(r'href="([^"]+)"', listing)
                     if x.lower().endswith(".csv")]
        if len(csv_files) != 1:
            raise ValueError(f"Expected one public VIA CSV for {subject}: {csv_files}")
        csv_name = csv_files[0]
        jobs.append((url + urllib.parse.quote(csv_name), DATA / "references" / subject / csv_name))
        samples.append({"subject": subject, "clip": name,
                        "video": f"videos/{subject}/{name}.mp4",
                        "reference": f"references/{subject}/{name}.hdf5",
                        "annotations": f"references/{subject}/{csv_name}"})
    assets = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download.save, url, target): target for url, target in jobs}
        for future in as_completed(futures):
            record = future.result()
            assets.append(record)
            print(f"Ready {record['path']} ({record['bytes']:,} bytes)", flush=True)
    manifest = {"selection_rule": "First numbered clip from every S01-S10 folder; chosen before predictions",
                "public_dataset": PUBLIC, "models": MODEL_FILES, "samples": samples,
                "repositories": repositories, "assets": sorted(assets, key=lambda x: x["path"]),
                "tls_verification_disabled_for_public_requests": args.allow_unverified_tls}
    (DATA / "assets.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest: {DATA / 'assets.json'}", flush=True)


if __name__ == "__main__":
    main()
