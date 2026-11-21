"""Verify study labels, immutable weights, aligned HDF5 outputs and report links."""
import hashlib
import json
from html.parser import HTMLParser
from urllib.parse import unquote

import h5py
import numpy as np

from chest_study_core import AFTER, BEFORE, CONFIG, CONDITION_ROOTS, DATA, FINETUNE, PRESENTATION, PROJECT, load_manifest, save_json


class Links(HTMLParser):
    def __init__(self):super().__init__();self.refs=[]
    def handle_starttag(self,tag,attrs):
        self.refs.extend(v for k,v in attrs if k in ("href","src"))


def main():
    protocol=json.loads((CONFIG/"controlled_protocol.json").read_text(encoding="utf-8"))
    annotations=json.loads((CONFIG/"chest_annotations.json").read_text(encoding="utf-8"))
    samples=load_manifest()["samples"]
    input_records=json.loads((CONFIG/"download_checksums.json").read_text(encoding="utf-8"))
    for pair in input_records:
        for record in pair:
            path=DATA/record["path"]
            assert path.stat().st_size==record["bytes"],path
            with path.open("rb") as handle:
                assert hashlib.file_digest(handle,"sha256").hexdigest()==record["sha256"],path
    chest_sha=hashlib.sha256((FINETUNE/"models/chest_yolov8m_best.pt").read_bytes()).hexdigest()
    assert hashlib.sha256((AFTER/"models/chest_yolov8m_best.pt").read_bytes()).hexdigest()==chest_sha
    for path in (DATA/"weights/DeepPhys_Deep_Body_best.pth",BEFORE/"models/DeepPhys_Deep_Body_best.pth",AFTER/"models/DeepPhys_Deep_Body_best.pth"):
        assert hashlib.sha256(path.read_bytes()).hexdigest()==protocol["frozen_deepphys_sha256"],path
    hashes={s:set() for s in ("train","val","test")}
    for record in annotations["images"]:
        image=FINETUNE/record["image"]
        digest=hashlib.sha256(image.read_bytes()).hexdigest()
        assert digest==record["image_sha256"],image
        hashes[record["split"]].add(digest)
        label=(FINETUNE/record["label"]).read_text().split()
        assert len(label)==5 and label[0]=="0"
        x,y,w,h=map(float,label[1:])
        assert 0<w<=1 and 0<h<=1 and 0<=x-w/2<x+w/2<=1 and 0<=y-h/2<y+h/2<=1
    assert not(hashes["train"]&hashes["val"] or hashes["train"]&hashes["test"] or hashes["val"]&hashes["test"])
    checked=0
    for item in samples:
        arrays=[]
        for condition in "ABC":
            root=CONDITION_ROOTS[condition]
            summary=json.loads((root/"metrics/control_v1"/(item["id"]+".json")).read_text(encoding="utf-8"))
            assert summary["flow_input_wh"]==[96,96]
            if condition=="C":assert summary["chest_checkpoint_sha256"]==chest_sha
            with h5py.File(root/summary["waveform_file"],"r") as f:
                for key in f:
                    assert np.isfinite(f[key][:]).all(),(item["id"],condition,key)
                times=f["time_sec"][:]
                if condition=="C":assert f.attrs["chest_checkpoint_sha256"]==chest_sha
                assert np.all(np.diff(times)>0)
                for key in ("respiration","respiration_filtered","network_output","motion_level_raw_flow","reference","reference_detrended"):
                    assert len(f[key])==len(times),(item["id"],condition,key)
                arrays.append((times,f["reference"][:],summary["protocol_annotation_signature"]))
            checked+=1
        assert all(np.array_equal(arrays[0][0],x[0]) and np.array_equal(arrays[0][1],x[1]) and arrays[0][2]==x[2] for x in arrays[1:])
    link_count=0
    for path in (PROJECT/"index.html",PRESENTATION/"05_실험개요/index.html"):
        parser=Links();parser.feed(path.read_text(encoding="utf-8"))
        missing=[r for r in parser.refs if not r.startswith(("https:","http:","#")) and not (path.parent/unquote(r.split("#")[0])).resolve().exists()]
        assert not missing,(path,missing)
        link_count+=len(parser.refs)
    result={"video_reference_input_hashes_checked":sum(map(len,input_records)),"labels_checked":len(annotations["images"]),"exact_cross_split_image_overlap":False,
            "waveform_files_checked":checked,"times_and_reference_equal_across_ABC":True,
            "deepphys_hash_unchanged_before_after":True,"local_links_checked":link_count}
    save_json(PRESENTATION/"05_실험개요/verification.json",result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
