"""Verify the official-order ablation and edited-input artifacts."""
import json
from html.parser import HTMLParser
from urllib.parse import unquote

from roi_preservation_compare import OUT, CONDITIONS, PROBE_IDS, DATA, CORE, sha, np, h5py
from air400_paths import PROJECT


class Links(HTMLParser):
    def __init__(self):super().__init__();self.refs=[]
    def handle_starttag(self,tag,attrs):
        self.refs.extend(v for k,v in attrs if k in ("href","src"))


def main():
    protocol=json.loads((OUT/"protocol.json").read_text(encoding="utf-8"))
    protocol_sha=sha(OUT/"protocol.json")
    calibration=json.loads((OUT/"validation_polarity.json").read_text(encoding="utf-8"))
    base_rule=json.loads((OUT/"peak_rule.json").read_text(encoding="utf-8"))["rule"]
    assert calibration["design"]["calibration_id"]=="S02_1"
    assert set(calibration["design"]["evaluation_ids"])=={"S01_1","S03_1","S07_01"}
    for condition in CONDITIONS:
        selected=calibration["conditions"][condition]
        assert selected["rule"]["polarity"] in (-1,1)
        for key in ("prominence_std","minimum_distance_sec"):
            assert selected["rule"][key]==base_rule[key]
        assert selected["validation_metrics"]["f1"]==max(c["validation_metrics"]["f1"] for c in selected["candidates"])
    for relative,digest in protocol["source_hashes"].items():assert sha(DATA/relative)==digest,relative
    for sample in protocol["samples"]:assert sha(DATA/sample["video"])==protocol["video_hashes"][sample["id"]]
    records=json.loads((PROJECT/"02_Chest_파인튜닝/configs/download_checksums.json").read_text(encoding="utf-8"))
    input_paths={s[k] for s in protocol["samples"] for k in ("video","reference")}
    checked_inputs=0
    for pair in records:
        for record in pair:
            if record["path"].replace("\\","/") in input_paths:
                assert sha(DATA/record["path"])==record["sha256"]
                checked_inputs+=1
    assert checked_inputs==8
    checked=0;cached_match=[]
    for item in protocol["samples"]:
        alignment=[]
        for condition in CONDITIONS:
            probes=("normal","frozen","attenuated") if item["id"] in PROBE_IDS else ("normal",)
            for probe in probes:
                root=OUT/"runs"/condition/probe
                meta=json.loads((root/(item["id"]+".json")).read_text(encoding="utf-8"))
                assert meta["protocol_sha256"]==protocol_sha
                if probe!="normal":
                    assert "primary_metrics" not in meta and "filtered_metrics_same_reference" not in meta
                    original=json.loads((OUT/"runs"/condition/"normal"/(item["id"]+".json")).read_text(encoding="utf-8"))
                    assert meta["roi_xywh"]==original["roi_xywh"] and meta["flow_size_wh"]==original["flow_size_wh"]
                with h5py.File(root/(item["id"]+".hdf5"),"r") as f:
                    t=f["time_sec"][:];assert np.all(np.diff(t)>0)
                    for key in f:
                        y=f[key][:];assert np.isfinite(y).all(),(condition,probe,key)
                        if key!="annotation_peaks_sec":assert len(y)==len(t)
                    alignment.append((t,f["reference"][:]))
                    if probe=="frozen":
                        core=(t>=CORE[0])&(t<CORE[1])
                        assert float(np.max(f["input_pixel_change"][:][core]))==0
                        assert float(np.max(f["flow_mean_magnitude"][:][core]))<1e-5
                if probe=="normal" and condition=="chest_early96":
                    cached_match.append(meta["previous_pipeline_network_max_abs_difference"])
                checked+=1
        assert all(np.array_equal(alignment[0][0],a[0]) and np.array_equal(alignment[0][1],a[1]) for a in alignment[1:])
    assert checked==32 and len(cached_match)==4 and max(cached_match)<1e-5
    missing=[];links=0
    for page in (OUT/"index.html",PROJECT/"index.html"):
        parser=Links();parser.feed(page.read_text(encoding="utf-8"))
        for target in parser.refs:
            if target.startswith(("https:","http:","#")):continue
            resolved=(page.parent/unquote(target.split("#")[0])).resolve()
            if resolved==OUT/"verification.json":continue
            if not resolved.exists():missing.append(str(resolved))
        links+=len(parser.refs)
    assert not missing,missing
    result={"waveform_files_checked":checked,"video_and_reference_hashes_checked":checked_inputs,
            "official_source_and_weights_unchanged":True,"times_reference_aligned_across_conditions_and_probes":True,
            "frozen_input_pixel_change_and_flow_zero_in_core":True,
            "previous_chest_early96_network_max_difference":max(cached_match),"local_links_checked":links,
            "sign_only_calibration_separate_from_3_evaluation_clips":True,
            "real_apnea_validated":False}
    (OUT/"verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
