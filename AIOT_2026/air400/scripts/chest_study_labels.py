"""Create assistant-reviewed upper-thorax box labels and review contact sheets.

One box per nearly static clip is propagated to its sampled frames. The five
anchor frames and the full sampled-frame contact sheet are visually reviewed.
These are assistant annotations, not independently reviewed anatomical truth.
"""
from datetime import datetime
import hashlib
import json

import cv2
import numpy as np
import yaml

from air400_paths import DATA, FINETUNE, PRESENTATION
from chest_study_prepare import save_json, write_image

# xywh on the 320x180 video plane; selected from original video snapshots,
# without looking at controlled A/B/C waveform scores or detector predictions.
BOXES = {
    "S01_1": [142,64,43,36], "S01_11": [142,64,43,36],
    "S02_1": [175,86,48,44], "S02_21": [179,91,45,43],
    "S03_1": [159,94,46,40], "S03_6": [159,91,46,40],
    "S04_1": [201,80,45,44], "S04_13": [198,80,47,42],
    "S05_1": [199,78,48,47], "S05_23": [200,82,48,47],
    "S06_1": [204,83,47,48], "S06_26": [200,82,48,47],
    "S07_01": [179,83,45,46], "S07_13": [179,83,45,46],
    "S08_1": [179,110,47,45], "S08_11": [179,110,47,45],
    "S09_1": [202,72,48,47], "S09_11": [202,72,48,47],
    "S10_1": [191,63,50,48], "S10_11": [191,64,50,48],
}


def main():
    config = FINETUNE / "configs"
    frozen=config/"chest_annotations.json"
    if frozen.exists():
        existing=json.loads(frozen.read_text(encoding="utf-8"))
        assert existing["boxes"]==BOXES,"Annotations are frozen; create a new study version to change boxes"
        assert all((FINETUNE/x["label"]).is_file() for x in existing["images"]),"A frozen label file is missing"
        print("Frozen annotation set retained",len(existing["images"]),flush=True)
        return
    manifest = json.loads((config / "study_manifest.json").read_text(encoding="utf-8"))
    inventory = json.loads((config / "image_inventory.json").read_text(encoding="utf-8"))
    records, hashes = [], {s:set() for s in ("train","val","test")}
    review = FINETUNE / "labeling_samples"
    review.mkdir(exist_ok=True)
    overview = []
    for item in manifest["samples"]:
        box = BOXES[item["id"]]
        x,y,w,h = box
        assert 0 <= x < x+w <= 320 and 0 <= y < y+h <= 180
        samples = [s for s in inventory if s["id"] == item["id"]]
        tiles = []
        for sample in samples:
            path = FINETUNE / sample["image"]
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            hashes[item["split"]].add(digest)
            label = FINETUNE / "dataset" / "labels" / item["split"] / (path.stem + ".txt")
            label.write_text(f"0 {(x+w/2)/320:.8f} {(y+h/2)/180:.8f} {w/320:.8f} {h/180:.8f}\n",encoding="utf-8")
            image = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            assert image is not None and image.shape[:2] == (360,640)
            cv2.rectangle(image,(x*2,y*2),((x+w)*2,(y+h)*2),(0,200,255),2)
            cv2.putText(image,f"{item['id']} t={sample['time_sec']:.1f}s | {item['split']} | chest (assistant label)",
                        (6,19),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,220,255),1)
            tiles.append(cv2.resize(image,(320,180)))
            records.append({**sample,"box_xywh_on_320x180":box,"image_sha256":digest,
                            "label":str(label.relative_to(FINETUNE)).replace("\\","/")})
            if len(tiles) == 15:
                write_image(review / f"{item['id']}_label_sample.jpg",image)
        while len(tiles) % 5:
            tiles.append(np.zeros_like(tiles[0]))
        sheet=np.concatenate([np.concatenate(tiles[i:i+5],axis=1) for i in range(0,len(tiles),5)],axis=0)
        write_image(review / f"{item['id']}_all_labels.jpg",sheet)
        overview.append(np.concatenate([tiles[0],tiles[len(samples)//2],tiles[len(samples)-1]],axis=1))
    assert not(hashes["train"] & hashes["val"] or hashes["train"] & hashes["test"] or hashes["val"] & hashes["test"])
    groups={s:sorted({x["source_group"] for x in manifest["samples"] if x["split"]==s}) for s in hashes}
    assert not(set(groups["train"]) & set(groups["val"]) or set(groups["train"]) & set(groups["test"]) or set(groups["val"]) & set(groups["test"]))
    save_json(config/"chest_annotations.json",{"created_at":datetime.now().astimezone().isoformat(),
              "definition":"Visible/inferred upper-thorax surface under clothing; excludes head and pelvis; overlapping arms may remain",
              "annotator":"assistant visual annotation; independent human expert review absent",
              "temporal_method":"constant box per near-static clip, reviewed at five anchors and sampled-frame contact sheets",
              "boxes":BOXES,"images":records})
    save_json(config/"split_audit.json",{"groups":groups,"clips":{s:sum(x["split"]==s for x in manifest["samples"]) for s in hashes},
              "images":{s:sum(x["split"]==s for x in inventory) for s in hashes},"exact_image_hash_overlap":False,
              "test_independent_source_groups":len(groups["test"]),"independent_human_reference_labels":False})
    dataset={"path":str((FINETUNE/"dataset").resolve()),"train":"images/train","val":"images/val","test":"images/test","names":{0:"chest"}}
    (config/"chest_dataset.yaml").write_text(yaml.safe_dump(dataset,allow_unicode=True,sort_keys=False),encoding="utf-8")
    for start in range(0,len(overview),5):
        write_image(review/f"overview_{start//5+1}.jpg",np.concatenate(overview[start:start+5],axis=0))
    print(json.dumps({"groups":groups,"labels":len(records)},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
