"""Freeze a grouped Chest study and extract candidate annotation frames."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import re
import urllib.parse

import cv2
import numpy as np

from air400_paths import DATA, FINETUNE, PRESENTATION
from air400_prepare_benchmark import Downloader

CONFIG = FINETUNE / "configs"


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_image(path, image):
    # OpenCV's Windows imwrite does not handle these Korean directory names.
    ok, encoded = cv2.imencode(path.suffix, image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise RuntimeError(f"Image encoding failed: {path}")
    path.write_bytes(encoded.tobytes())


def main():
    CONFIG.mkdir(parents=True, exist_ok=True)
    original = json.loads((DATA / "assets.json").read_text(encoding="utf-8"))
    manifest_path = CONFIG / "study_manifest.json"
    downloader = Downloader(True)  # Scoped to this public dataset; proxy certificate exception recorded below.
    if not manifest_path.exists():
        samples, inventory = [], []
        for old in original["samples"]:
            url = original["public_dataset"] + old["subject"] + "/"
            videos = [urllib.parse.unquote(x) for x in re.findall(r'href="([^"]+)"', downloader.read(url).decode())
                      if x.endswith(".mp4") and x[:-4].isdigit()]
            refs = [urllib.parse.unquote(x) for x in re.findall(r'href="([^"]+)"', downloader.read(url + "out/").decode())
                    if x.endswith(".hdf5") and x[:-5].isdigit()]
            paired = sorted([x for x in videos if int(x[:-4]) in {int(r[:-5]) for r in refs}], key=lambda x: int(x[:-4]))
            middle = paired[len(paired)//2]
            group = re.match(r"(S\d+)_", old["annotations"].split("/")[-1]).group(1)
            split = "val" if group == "S08" else ("test" if group == "S09" else "train")
            inventory.append({"folder": old["subject"], "numbered_videos": len(videos), "paired_hdf5": len(paired),
                              "conservative_source_group": group})
            for filename in (old["clip"] + ".mp4", middle):
                clip = filename[:-4]
                ref_name = next(r for r in refs if int(r[:-5]) == int(clip))
                samples.append({**old, "clip": clip, "video": f"videos/{old['subject']}/{filename}",
                                "reference": f"references/{old['subject']}/{ref_name}", "source_group": group,
                                "split": split, "id": old["subject"] + "_" + clip,
                                "video_url": url + filename, "reference_url": url + "out/" + ref_name})
        manifest = {"created_at": datetime.now().astimezone().isoformat(),
                    "selection_rule": "Existing first numbered clip plus median numbered clip with HDF5, before new inference/training",
                    "split_rule": "CSV source-prefix groups kept together: S03/S013 train, S08 val, S09 test",
                    "group_warning": "Source prefixes conservatively group related recordings; not verified individual identities",
                    "annotation_provenance": "Assistant visual annotation with temporal interpolation and contact-sheet review; no independent human expert review",
                    "deep_phys_training_overlap": "unknown; only this YOLO fine-tuning split is controlled",
                    "tls_proxy_exception_for_public_downloads": True, "inventory": inventory, "samples": samples}
        save_json(manifest_path, manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    def fetch(item):
        return [downloader.save(item["video_url"], DATA / item["video"]),
                downloader.save(item["reference_url"], DATA / item["reference"])]
    with ThreadPoolExecutor(max_workers=3) as pool:
        downloads = list(pool.map(fetch, manifest["samples"]))
    save_json(CONFIG / "download_checksums.json", downloads)
    keyframes = FINETUNE / "annotation_keyframes"
    keyframes.mkdir(exist_ok=True)
    image_root = FINETUNE / "dataset" / "images"
    metadata, sheets = [], []
    for item in manifest["samples"]:
        cap = cv2.VideoCapture(str(DATA / item["video"]))
        fps, count = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        wanted = {int(round(t * fps)) for t in np.arange(1., min(count/fps-1, 60), 2.)}
        anchors = [0, int(15*fps), int(30*fps), int(45*fps), count-1]
        snapshots = []
        index = 0
        while True:
            ok, image = cap.read()
            if not ok:
                break
            if index in wanted or index in anchors:
                image = cv2.resize(image, (640, 360), interpolation=cv2.INTER_AREA)
                if index in wanted:
                    filename = f"{item['id']}_f{index:05d}.jpg"
                    target = image_root / item["split"] / filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    write_image(target, image)
                    metadata.append({"image": str(target.relative_to(FINETUNE)).replace("\\", "/"),
                                     "id": item["id"], "frame_index": index, "time_sec": index/fps,
                                     "split": item["split"], "source_group": item["source_group"]})
                if index in anchors:
                    write_image(keyframes / f"{item['id']}_f{index:05d}.jpg", image)
                    small = cv2.resize(image, (480,270))
                    for x in range(0,480,60):
                        cv2.line(small,(x,0),(x,269),(90,90,90),1)
                        cv2.putText(small,str(round(x/1.5)),(x+2,30),cv2.FONT_HERSHEY_SIMPLEX,.35,(30,230,250),1)
                    for y in range(0,270,60):
                        cv2.line(small,(0,y),(479,y),(90,90,90),1)
                        cv2.putText(small,str(round(y/1.5)),(2,y+45),cv2.FONT_HERSHEY_SIMPLEX,.35,(30,230,250),1)
                    cv2.putText(small,f"{item['id']} t={index/fps:.1f}s {item['split']}",(5,16),cv2.FONT_HERSHEY_SIMPLEX,.45,(20,240,250),1)
                    snapshots.append(small)
            index += 1
        cap.release()
        item.update(fps=float(fps), frames=index, duration_sec=index/fps)
        sheets.append(np.concatenate(snapshots,axis=1))
        print(f"Prepared {item['id']} {item['split']} {index} frames",flush=True)
    save_json(manifest_path, manifest)
    save_json(CONFIG / "image_inventory.json", metadata)
    for start in range(0,len(sheets),5):
        path=keyframes/f"inspection_{start//5+1}.jpg"
        write_image(path,np.concatenate(sheets[start:start+5],axis=0))
    print("Image split counts:", {s:sum(x["split"]==s for x in metadata) for s in ("train","val","test")},flush=True)


if __name__ == "__main__":
    main()
