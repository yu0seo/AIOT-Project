"""Inventory numbered public clips and record a collection design; no video inference."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import html
import json
import re
import ssl
import time
import urllib.parse
import urllib.request

from air400_paths import DATA, PROJECT

TARGET=PROJECT/"06_단일클래스_학습데이터"
BASE="https://coe.northeastern.edu/Research/AClab/AIR-400/"


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")


def listing(url):
    # This workstation's existing TLS proxy exception is limited to this public host.
    assert url.startswith(BASE)
    context=ssl._create_unverified_context()
    for attempt in range(3):
        try:
            request=urllib.request.Request(url,headers={"User-Agent":"AIOT-dataset-inventory/1.0"})
            with urllib.request.urlopen(request,context=context,timeout=20) as result:
                page=result.read().decode("utf-8")
            return [urllib.parse.unquote(html.unescape(s)) for s in re.findall(r'href="([^"]+)"',page)]
        except Exception:
            if attempt==2:raise
            time.sleep(1)


def inspect_subject(number):
    folder=f"S{number:02d}";url=BASE+folder+"/"
    files=listing(url);references=listing(url+"out/")
    videos=sorted((s for s in files if re.fullmatch(r"\d+\.mp4",s)),key=lambda s:int(s[:-4]))
    refs={int(s[:-5]):s for s in references if re.fullmatch(r"\d+\.hdf5",s)}
    csvs=[s for s in files if s.lower().endswith(".csv")]
    samples=[]
    for name in videos:
        clip=name[:-4];reference=refs.get(int(clip))
        samples.append({"id":folder+"_"+clip,"folder":folder,"clip":clip,"video_url":url+name,
            "video_relative_path":f"videos/{folder}/{name}","reference_available":reference is not None,
            "reference_url":url+"out/"+reference if reference else None,
            "csv_annotation_files":csvs,"duration_status":"Read actual duration/timestamps during ingestion; numbered short-clip candidates only",
            "training_use":"unreviewed_original_clip","synthetic":False})
    return {"folder":folder,"numbered_video_count":len(videos),"paired_reference_count":sum(s["reference_available"] for s in samples),"samples":samples}


def main():
    config=TARGET/"configs"
    config.mkdir(parents=True,exist_ok=True)
    now=datetime.now().astimezone().isoformat()
    channels=[
        {"name":"waveform_detrended","kind":"waveform","definition":"Official cumulative integration and lambda=100 detrend, before bandpass"},
        {"name":"waveform_filtered","kind":"waveform","definition":"Official 0.3-1.0Hz forward-backward bandpass output; offline batch signal"},
        {"name":"motion_speed_mean","kind":"motion","definition":"Spatial mean sqrt((u/W/dt)^2+(v/H/dt)^2), before any flow Z-score","unit":"ROI fraction / second"},
        {"name":"motion_speed_p90","kind":"motion","definition":"Spatial 90th percentile of the same normalized flow speed","unit":"ROI fraction / second"},
        {"name":"motion_vx_mean","kind":"motion","definition":"Spatial mean u/W/dt before Z-score","unit":"ROI width fraction / second"},
        {"name":"motion_vy_mean","kind":"motion","definition":"Spatial mean v/H/dt before Z-score","unit":"ROI height fraction / second"},
        {"name":"pixel_change_rate","kind":"motion","definition":"Mean absolute adjacent grayscale pixel difference /255/dt in the same ROI","unit":"image intensity fraction / second"},
    ]
    model=DATA/"weights/DeepPhys_Deep_Body_best.pth"
    with model.open("rb") as handle:model_hash=hashlib.file_digest(handle,"sha256").hexdigest()
    design={"version":"oneclass_collection_design_v1","created_at":now,
        "status":"design_before_bulk_extraction","bulk_video_download_started":False,"bulk_inference_started":False,
        "modeling":{"objective":"Single-class anomaly detection with waveform and motion time series","binary_classification":False,"model_or_feature_ablation_requested":False},
        "extractor":{"roi":"Official Body ROI from original public detector","waveform_model":"DeepPhys_Deep_Body_best.pth","waveform_model_sha256":model_hash,
            "preprocess_order":"320x180 frame -> Body crop -> DeepFlow at original crop size -> official standardization -> 96x96 DeepPhys input",
            "fine_tuned_chest_detector_used":False,"early_resize_before_flow":False,
            "motion_branch":"Copy raw optical-flow statistics before official normalization; no low-motion threshold or per-clip feature Z-score"},
        "channels":channels,"time_alignment":{"raw_archive_fps":"Native FPS and source timestamps retained", "classifier_grid_hz_recommendation":10,
            "classifier_grid_status":"Derive a shared time grid from archived channels; no assumption that native frames have equal actual dt",
            "motion_pair_convention":"u,v and pixel difference at t refer to frame[t] -> frame[t+1], same pairing used by released preprocessor",
            "last_motion_sample":"Invalid, mask explicitly; never silently treat zero flow padding as a real stop"},
        "retention":{"input_unit":"Entire provided numbered short clip; record actual duration rather than assume exactly 60s",
            "drop_remainder_of_180_frames":False,"implementation_requirement":"Keep official preprocessing sequence; infer the final partial DeepPhys batch instead of dropping it. Validate equivalence on complete chunks before bulk run."},
        "additional_archive_fields":["network_output", "time_sec", "source_frame_index", "source_timestamp_sec", "frame_dt_sec", "sample_available_time_sec", "motion_valid", "roi_xywh", "body_detection_valid", "roi_brightness", "roi_sharpness", "native_flow_mean_magnitude", "native_flow_p90_magnitude", "native_flow_mean_u", "native_flow_mean_v", "native_pixel_change_mean", "optional_reference_and_peak_annotations_not_model_inputs"],
        "scaling":{"store_before_model_feature_scaling":True,"feature_scaler":"Fit on selected normal training partition only; reuse fixed parameters for deployment","per_window_motion_standardization":False},
        "quality":{"extract_all_original_candidates":True,"assume_every_original_is_normal":False,
            "training_selection":"Review valid breathing-observable windows; retain flags for missing ROI/low visibility/recording failure; do not mix synthetic control folders into normal training"},
        "deployment_contract":{"official_waveforms_are_offline":True,"whole_clip_standardization_and_zero_phase_filter":True,
            "requirement":"Training feature examples and Raspberry Pi downstream inference must use the same time window and processing context. Archived full-clip waveforms are not automatically a causal live detector; changing preprocessing normalization requires new model inference."},
        "dataset_scope":{"folders":[f"S{i:02d}" for i in range(1,11)],"filename_rule":"numeric basename .mp4 in the folder itself", "hdf_reference_required_for_prediction":False,"separate_assets_not_part_of_this_scope":["AIR_125.zip","original_videos subfolders","root duplicate demo video"]},
        "tls_exception":"Per-request public-host exception matching existing workstation proxy setup"}
    review_path=config/"model_input_review.json"
    if review_path.exists():
        design["status"]="model_input_features_under_review_before_bulk"
        design["model_input_channels_finalized"]=False
        design["channels_role"]="Initial extraction/storage candidates, not mandatory model inputs"
        design["feature_selection_review"]=review_path.name
    face_plan=config/"face_observation_design_v1.json"
    if face_plan.exists():
        design["face_observation_export"]={"design_file":face_plan.name,"role":"Separate observation/alert metadata, not a confirmed respiration-model channel","implementation_status":"planned_not_implemented"}
    save(config/"extraction_design_v1.json",design)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:subjects=list(pool.map(inspect_subject,range(1,11)))
        samples=[s for subject in subjects for s in subject["samples"]]
        inventory={"enumerated_at":datetime.now().astimezone().isoformat(),"base_url":BASE,
            "scope":"S01-S10 folder-level numbered .mp4 short clips; actual durations still to be decoded", "listing_only":True,
            "numbered_video_count":len(samples),"paired_reference_count":sum(s["reference_available"] for s in samples),
            "without_reference_count":sum(not s["reference_available"] for s in samples),
            "subjects":[{k:v for k,v in s.items() if k!="samples"} for s in subjects],"samples":samples}
        save(config/"source_inventory.json",inventory)
        error_path=config/"inventory_error.json"
        if error_path.exists():
            previous=json.loads(error_path.read_text(encoding="utf-8"))
            previous["resolved_by_successful_inventory_at"]=inventory["enumerated_at"]
            save(error_path,previous)
        print(json.dumps({k:v for k,v in inventory.items() if k not in ("samples","subjects")},ensure_ascii=False,indent=2))
    except Exception as error:
        save(config/"inventory_error.json",{"time":now,"error":str(error),"bulk_extraction_started":False})
        raise
    print("Saved collection design only; no new videos downloaded and no model inference run",flush=True)


if __name__=="__main__":main()
