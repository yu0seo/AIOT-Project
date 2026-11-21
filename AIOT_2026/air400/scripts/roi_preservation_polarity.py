"""Transparent supplementary validation-only sign calibration; no time shifting."""
from datetime import datetime
import json
import h5py

from roi_preservation_compare import OUT, CONDITIONS
from chest_study_metrics import score_signal


def main():
    target=OUT/"validation_polarity.json"
    if target.exists():print("Validation polarity already frozen");return
    for condition in CONDITIONS:
        assert (OUT/"runs"/condition/"normal/S02_1.hdf5").exists()
    addendum={"recorded_at":datetime.now().astimezone().isoformat(),
        "reason":"Signed correlation showed that the old Chest-selected common -1 sign can disadvantage Body. Supplementary analysis calibrates only sign on the existing S02 validation clip.",
        "status":"Supplementary analysis introduced after inspecting some initial normal outputs; not fully preregistered",
        "original_protocol_and_results_preserved":True,"calibration_id":"S02_1",
        "evaluation_ids":["S01_1","S03_1","S07_01"],
        "parameters_allowed_to_select":["one global +1 or -1 polarity per condition"],
        "not_selected":["time lag","prominence","minimum peak distance","filter bounds","model weights"],
        "selection_metric":"Validation F1 only; lower event-time MAE breaks ties; evaluated at official filtered stage",
        "purpose":"Fair supplementary comparison, not independent final validation or per-clip alignment"}
    (OUT/"analysis_addendum.json").write_text(json.dumps(addendum,ensure_ascii=False,indent=2),encoding="utf-8")
    base=json.loads((OUT/"peak_rule.json").read_text(encoding="utf-8"))["rule"]
    calibration={}
    for condition in CONDITIONS:
        with h5py.File(OUT/"runs"/condition/"normal/S02_1.hdf5","r") as f:
            t=f["time_sec"][:];wave=f["respiration_filtered"][:]
            ref=f["reference_detrended"][:];peaks=f["annotation_peaks_sec"][:]
        candidates=[]
        for sign in (-1,1):
            rule={**base,"polarity":sign}
            m=score_signal(t,wave,ref,peaks,rule)
            candidates.append({"rule":rule,"validation_metrics":m})
        best=max(candidates,key=lambda c:(c["validation_metrics"]["f1"],-(c["validation_metrics"]["event_time_mae_sec"] if c["validation_metrics"]["event_time_mae_sec"] is not None else 1e6)))
        calibration[condition]={**best,"candidates":candidates}
    target.write_text(json.dumps({"design":addendum,"conditions":calibration},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v["rule"] for k,v in calibration.items()},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
