"""Prepare a first subject-wise AE experiment through the production video path."""
import argparse
import csv
import json
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from scipy.signal import resample_poly

from babycam.common import Config, atomic_json
from normal_pipeline.no_motion import ROOT, sha256

EXCLUDED = {'AIR_125_S02_001_0_30','AIR_400_S02_1_0_30','AIR_400_S07_01_0_30','AIR_400_S09_1_0_30'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--per-subject',type=int,default=2)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--normal-assumption-approved',action='store_true',required=True)
    args=parser.parse_args()
    if args.per_subject<1 or not 1<=args.workers<=2:
        parser.error('per-subject는 양수, workers는 1~2여야 합니다.')
    prepare(args)


def prepare(args):
    out=args.output.resolve()
    if out.exists():
        raise ValueError('새 출력 폴더를 지정하세요. 기존 실험은 덮어쓰지 않습니다.')
    with (ROOT/'output/ae_results_v2/splits.csv').open(encoding='utf-8-sig',newline='') as fp:
        old=list(csv.DictReader(fp))
    groups=defaultdict(list)
    for row in old:
        meta=json.loads(row['metadata_json'])
        if meta['start_sec']!=0:
            continue
        ident=row['video_id']+'_0_30'
        if ident in EXCLUDED:
            continue
        source=Path(meta['video']);source=ROOT.joinpath(*source.parts[source.parts.index('data'):])
        groups[meta['subject_id']].append(dict(id=ident,group_id=meta['subject_id'],split=row['split'],
              source=source.relative_to(ROOT).as_posix(),source_sha256=meta['source_sha256'],
              start_sec=0,end_sec=30,label='normal_assumed',reviewed=False,
              label_basis='User explicitly authorized remaining data as normal-assumed; not manually verified.'))
    # These two production caches already have reviewed source records and original teacher raw.
    reuse={}
    for relative in ['output/no_motion_stage2_S05_20261125','output/no_motion_validation_S02_008_20261125']:
        folder=ROOT/relative;cache=json.loads((folder/'cache.json').read_text(encoding='utf-8'))
        for record in cache['cases']:
            if record['kind']=='breathing_candidate':
                reuse[record['id']]=(folder,record,cache['teacher_sha256'])
    # Use the specifically reviewed S02 alternative rather than replacing it with an unreviewed source.
    review_manifest=json.loads((ROOT/'output/no_motion_stage1_20261125/manifest.json').read_text(encoding='utf-8'))
    for record in review_manifest['records']:
        if record['kind']=='breathing_candidate' and record['review']['approved'] is True:
            items=groups[record['group_id']]
            items[:]=[r for r in items if r['id']!=record['id']]
            items.insert(0,{k:record[k] for k in ('id','group_id','split','source','source_sha256','start_sec','end_sec')} |
                         dict(label='normal_reviewed_motion',reviewed=True,label_basis=record['review']['notes']))
    for group,items in groups.items():
        if len({r['split'] for r in items})!=1:
            raise ValueError(f'영아 split 충돌: {group}')
        first=[r for r in items if r['reviewed']]
        rest=sorted((r for r in items if not r['reviewed']),key=lambda r:int(r['id'].split('_')[-3]))
        groups[group]=first+rest
    cfg=Config.load(ROOT/'.env',require_supabase=False)
    if cfg.root!=ROOT:
        raise ValueError('현재 루트와 .env 루트가 다릅니다.')
    tracked=['models/air400_detect_v2.py','models/air400_npz_anomaly_v2.py','models/deep_phys.py',
             'processors/pre_processor.py','processors/post_processor.py',
             'configs/inference/deepphys_deep_infer.yaml','checkpoints/DeepPhys_Deep_Body_best.pth',
             'detectors/yolov8m.pt','detectors/yolov8n-face.pt','output/ae_results_v2/air400_ae.pt']
    hashes={name:sha256(ROOT/name) for name in tracked}
    out.mkdir(parents=True,exist_ok=False)
    os.environ['YOLO_CONFIG_DIR']=str(out/'ultralytics')
    sys.path.insert(0,str(ROOT/'models'))
    import air400_detect_v2 as existing
    signature=dict(pipeline_hashes=hashes,source_sha256=sha256(__file__),normal_assumption_authorized=True,
                   per_subject=args.per_subject,workers=args.workers,excluded=sorted(EXCLUDED),
                   purpose='First production-preprocessed AE retrain; labels are normal-assumed except explicit reviews.')
    atomic_json(out/'plan.json',signature,indent=2)
    local=threading.local();lock=threading.Lock();records=[];failures=[]

    def runner():
        if not hasattr(local,'runner'):
            device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            a=SimpleNamespace(air400_root=ROOT,config=None,deepphys_ckpt=ROOT/'checkpoints/DeepPhys_Deep_Body_best.pth',
                              body_detector=ROOT/'detectors/yolov8m.pt',face_detector=ROOT/'detectors/yolov8n-face.pt',
                              no_roi=False,frame_batch=16)
            local.runner=existing.DeepPhysRunner(a,device)
            local.scorer=existing.AnomalyV2(ROOT/'output/ae_results_v2/air400_ae.pt',device)
        return local.runner

    def group_task(group,items):
        success=0
        for r in items:
            if success>=args.per_subject:
                break
            if sha256(ROOT/r['source'])!=r['source_sha256']:
                raise ValueError('원본 해시 불일치: '+r['id'])
            destination=out/'features'/r['id'];destination.mkdir(parents=True,exist_ok=False)
            model=runner()
            if r['id'] in reuse:
                folder,record,teacher_sha=reuse[r['id']]
                if teacher_sha!=hashes['checkpoints/DeepPhys_Deep_Body_best.pth'] or sha256(folder/record['file'])!=record['file_sha256']:
                    raise ValueError('재사용 캐시 지문 불일치')
                with np.load(folder/record['file'],allow_pickle=False) as data:
                    raw=data['teacher_raw']
                resp,bpm=model.post.post_process(torch.from_numpy(raw),fs=15,diff_flag=model.diff_flag,
                    infant_flag=model.infant_flag,use_bandpass=True,eval_method=model.rr_method)
                wave=resample_poly(resp,2,3).astype(np.float32)
                file=destination/'features.npz'
                np.savez_compressed(file,x_10hz=wave,pred_rr_bpm=bpm,raw_model=raw,metadata_json=json.dumps(r,ensure_ascii=False))
                result=dict(r,status='prepared',file=file.relative_to(out).as_posix(),file_sha256=sha256(file),reused_production_teacher_raw=True)
            else:
                a=SimpleNamespace(input=ROOT/r['source'],out_dir=destination,ffmpeg=cfg.ffmpeg)
                with closing(existing.video_rows(a,model,local.scorer)) as rows:
                    row=next(rows)
                if row['status']=='unscored':
                    result=dict(r,status='unscored',reason=row['reason'])
                else:
                    file=destination/row['npz_file']
                    result=dict(r,status='prepared',file=file.relative_to(out).as_posix(),file_sha256=sha256(file),
                                legacy_score_diagnostic_only=row['anomaly_score'])
            with lock:
                (records if result['status']=='prepared' else failures).append(result)
                atomic_json(out/'progress.json',dict(prepared=len(records),unscored=len(failures),
                            records=records,failures=failures),indent=2)
                print('FEATURE',r['id'],result['status'],result.get('reason',''),flush=True)
            if result['status']=='prepared':
                success+=1
        return group,success

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(group_task,group,items) for group,items in groups.items()]
        for f in as_completed(futures):
            print('GROUP_DONE',f.result(),flush=True)
    # Add two actual static sources for AE validation/challenge, never reconstruction training.
    negatives=[('output/no_motion_stage2_S05_20261125','static_doll_88_102','valid'),
               ('output/doll_kakao_20261125/manual_roi_v1/cache','static_kakao_195038778_0_30','test')]
    for directory,ident,split in negatives:
        folder=ROOT/directory;cache=json.loads((folder/'cache.json').read_text(encoding='utf-8'))
        c=next(r for r in cache['cases'] if r['id']==ident)
        if cache['teacher_sha256']!=hashes['checkpoints/DeepPhys_Deep_Body_best.pth'] or sha256(folder/c['file'])!=c['file_sha256']:
            raise ValueError('정지 캐시 지문 오류')
        with np.load(folder/c['file'],allow_pickle=False) as data:
            raw=data['teacher_raw']
        from processors.post_processor import PostProcessor
        resp,bpm=PostProcessor().post_process(torch.from_numpy(raw),fs=15,diff_flag=True,infant_flag=True,use_bandpass=True,eval_method='FFT')
        destination=out/'features'/ident;destination.mkdir(parents=True,exist_ok=False);file=destination/'features.npz'
        record={k:c[k] for k in ('id','group_id','source','source_sha256','start_sec','end_sec')}
        record.update(split=split,label='static_simulation',reviewed=True,origin_deepphys_split=c['split'],
                      development_exposed=True,roi_mode=c.get('roi_mode','automatic'),label_basis=c['review']['notes'])
        np.savez_compressed(file,x_10hz=resample_poly(resp,2,3).astype(np.float32),pred_rr_bpm=bpm,
                            raw_model=raw,metadata_json=json.dumps(record,ensure_ascii=False))
        records.append(dict(record,status='prepared',file=file.relative_to(out).as_posix(),file_sha256=sha256(file)))
    if any(sha256(ROOT/name)!=digest for name,digest in hashes.items()):
        raise ValueError('생산 모델/설정이 변경되었습니다.')
    atomic_json(out/'dataset.json',dict(schema=1,complete=True,**signature,
                records=sorted(records,key=lambda r:(r['split'],r['group_id'],r['id'])),failures=failures,
                limitation='Normal-assumed labels; static dolls are not clinical apnea; negative test source already development-exposed.'),indent=2)
    print('DATASET_DONE',len(records),'prepared',len(failures),'unscored',flush=True)


if __name__=='__main__':
    main()
