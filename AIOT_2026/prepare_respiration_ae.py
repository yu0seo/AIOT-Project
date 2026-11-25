"""Re-extract an approved AE source plan with a different automatic ROI detector."""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import torch

from babycam.common import Config, atomic_json
from normal_pipeline.ae_evaluation import validate_feature_records
from normal_pipeline.no_motion import ROOT,sha256
from normal_pipeline.detector_input import correct_detector_color
from normal_pipeline.respiration_bench import read_first_window


def load_source_plan(path):
    document=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if document.get('schema')!=1 or document.get('complete') is not True:
        raise ValueError('완료된 기존 데이터셋 원본 계획이 필요합니다.')
    validate_feature_records(document['records'],allow_assumed=document.get('normal_assumption_authorized') is True)
    keep=('id','group_id','split','label','reviewed','source','source_sha256','start_sec','end_sec','label_basis','development_exposed')
    records=[{k:r[k] for k in keep if k in r} for r in document['records']]
    for r in records:
        if r['start_sec']!=0 or r['end_sec']!=30 or sha256(ROOT/r['source'])!=r['source_sha256']:
            raise ValueError('원본 해시 또는 0~30초 구간 오류: '+r['id'])
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dataset',type=Path,required=True)
    parser.add_argument('--body-detector',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2,choices=[1,2])
    parser.add_argument('--correct-detector-color',action='store_true')
    args=parser.parse_args()
    records=load_source_plan(args.source_dataset)
    if args.output.exists() or not args.body_detector.is_file():
        parser.error('새 출력 폴더와 실제 body detector 파일이 필요합니다.')
    cfg=Config.load(ROOT/'.env',require_supabase=False)
    if cfg.root!=ROOT:
        parser.error('현재 루트와 AIR400_ROOT가 다릅니다.')
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'execution_source.py').write_bytes(Path(__file__).read_bytes())
    os.environ['YOLO_CONFIG_DIR']=str(args.output/'ultralytics')
    sys.path.insert(0,str(ROOT/'models'))
    import air400_detect_v2 as existing
    torch.set_num_threads(2);cv2.setNumThreads(2)
    body=args.body_detector.resolve()
    tracked=['models/air400_detect_v2.py','models/air400_npz_anomaly_v2.py','models/deep_phys.py',
             'processors/pre_processor.py','processors/post_processor.py',
             'configs/inference/deepphys_deep_infer.yaml','checkpoints/DeepPhys_Deep_Body_best.pth',
             'detectors/yolov8n-face.pt',str(body.relative_to(ROOT)),'normal_pipeline/detector_input.py']
    hashes={name:sha256(ROOT/name) for name in tracked}
    protected={name:sha256(ROOT/name) for name in ['.env','detectors/yolov8m.pt','output/ae_results_v2/air400_ae.pt']}
    contract=dict(video_fs=15,wave_fs=10,wave_samples=300,window_sec=30,roi_mode='automatic',
                  body_detector_sha256=sha256(body),face_detector_sha256=hashes['detectors/yolov8n-face.pt'],
                  deepphys_sha256=hashes['checkpoints/DeepPhys_Deep_Body_best.pth'])
    contract['detector_color_corrected']=args.correct_detector_color
    signature=dict(schema=1,complete=False,normal_assumption_authorized=True,pipeline_hashes=hashes,
                   active_feature_contract=contract,source_plan_sha256=sha256(args.source_dataset),
                   source_sha256=sha256(__file__),records=[],failures=[],
                   limitation='Normal-assumed labels; development-exposed static dolls, not clinical apnea. No old ROI feature reuse.')
    atomic_json(args.output/'plan.json',dict(**signature,source_records=records),indent=2)
    local=threading.local()

    def extract(index,r):
        if not hasattr(local,'runner'):
            a=SimpleNamespace(air400_root=ROOT,config=None,body_detector=body,
                              face_detector=ROOT/'detectors/yolov8n-face.pt',
                              deepphys_ckpt=ROOT/'checkpoints/DeepPhys_Deep_Body_best.pth',no_roi=False,frame_batch=16)
            local.runner=existing.DeepPhysRunner(a,'cuda' if torch.cuda.is_available() else 'cpu')
            if args.correct_detector_color:
                correct_detector_color(local.runner.pre)
        model=local.runner
        destination=args.output/f'{index:04d}';destination.mkdir()
        print('PREPARE',r['id'],flush=True)
        try:
            frames=read_first_window(ROOT/r['source'],cfg.ffmpeg,existing)
            box,detections=model.pre.get_roi_box(frames)
            original=model.pre.get_roi_box
            model.pre.get_roi_box=lambda frames:(box,detections)
            try:
                raw,resp,wave,bpm=model.extract(frames)
            finally:
                model.pre.get_roi_box=original
            metadata=dict(r,roi_mode='automatic',roi_box_xywh=box,active_feature_contract=contract)
            file=destination/'features.npz'
            np.savez_compressed(file,x_10hz=wave,pred_rr_bpm=bpm,raw_model=raw,
                                metadata_json=json.dumps(metadata,ensure_ascii=False))
            x,y,w,h=map(int,box);preview=frames[0].astype(np.uint8).copy()
            cv2.rectangle(preview,(x,y),(x+w,y+h),(255,0,0),2)
            cv2.imwrite(str(destination/'roi.png'),cv2.cvtColor(preview,cv2.COLOR_RGB2BGR))
            result=dict(metadata,status='prepared',file=file.relative_to(args.output).as_posix(),file_sha256=sha256(file))
        except (ValueError,existing.InvalidWindow) as exc:
            result=dict(r,status='unscored',reason=str(exc),anomaly_score=None,is_anomaly=None)
        print('FEATURE',r['id'],result['status'],result.get('reason',''),flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(extract,i,r) for i,r in enumerate(records)]
        for f in as_completed(futures):
            row=f.result()
            signature['records' if row['status']=='prepared' else 'failures'].append(row)
            atomic_json(args.output/'progress.json',signature,indent=2)
    signature['records'].sort(key=lambda r:(r['split'],r['group_id'],r['id']))
    validate_feature_records(signature['records'],allow_assumed=True)
    if any(sha256(ROOT/p)!=digest for p,digest in (hashes|protected).items()):
        raise ValueError('실행 중 모델/설정/원본 보호 파일이 변경됐습니다.')
    signature.update(complete=True,protected_files_unchanged=True)
    atomic_json(args.output/'dataset.json',signature,indent=2)
    print('DONE',len(signature['records']),'prepared',len(signature['failures']),'unscored',flush=True)


if __name__=='__main__':
    main()
