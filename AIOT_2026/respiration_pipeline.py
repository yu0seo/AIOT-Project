"""고정 ROI 비교 -> 개발용 존재 판정 -> 기존 자동 ROI/AE 연결 실험."""
import argparse
import csv
import json
import os
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import torch

from babycam.common import Config, atomic_json
from normal_pipeline.manual_roi import roi_box
from normal_pipeline.no_motion import ROOT, sha256
from normal_pipeline.no_motion_cache import encode_inputs, raw_prediction
from normal_pipeline.detector_input import correct_detector_color,verify_roi_contract
from normal_pipeline.respiration_bench import (efficient_raw, efficient_coarse_inputs, load_native_pyflow,
                                              motion_windows, read_first_window,
                                              read_manifest, summarize_decisions)
from normal_pipeline.respiration_motion import motion_features
from normal_pipeline.respiration_presence import classify_motion, fit_calibration, combine_decisions


def context(output):
    if output.exists():
        raise ValueError('새 --output 폴더를 지정하세요. 기존 결과를 덮어쓰지 않습니다.')
    cfg = Config.load(ROOT/'.env',require_supabase=False)
    if cfg.root != ROOT:
        raise ValueError('현재 프로젝트와 AIR400_ROOT가 다릅니다.')
    output.mkdir(parents=True,exist_ok=False)
    (output/'execution_source.py').write_bytes(Path(__file__).read_bytes())
    os.environ['YOLO_CONFIG_DIR'] = str(output/'ultralytics')
    sys.path.insert(0,str(ROOT/'models'))
    import air400_detect_v2 as existing
    files = ['.env','models/air400_detect_v2.py','models/air400_npz_anomaly_v2.py',
             'processors/pre_processor.py','processors/post_processor.py',
             'configs/inference/deepphys_deep_infer.yaml','checkpoints/DeepPhys_Deep_Body_best.pth',
             'output/ae_results_v2/air400_ae.pt','detectors/yolov8m.pt','detectors/yolov8n-face.pt']
    protected = {p:sha256(ROOT/p) for p in files}
    cv2.setNumThreads(2)
    torch.set_num_threads(2)
    return cfg, existing, protected


def runner(existing, checkpoint, body_detector=None, color_corrected=False):
    args = SimpleNamespace(air400_root=ROOT,config=None,deepphys_ckpt=checkpoint,
                           body_detector=body_detector or ROOT/'detectors/yolov8m.pt',
                           face_detector=ROOT/'detectors/yolov8n-face.pt',no_roi=False,frame_batch=16)
    result=existing.DeepPhysRunner(args,'cuda' if torch.cuda.is_available() else 'cpu')
    if color_corrected:
        correct_detector_color(result.pre)
    return result


def feature_hashes():
    return {p:sha256(ROOT/p) for p in ['normal_pipeline/respiration_motion.py',
                                      'normal_pipeline/respiration_bench.py']}


def finish(output, report, protected):
    report['protected_files_unchanged'] = all(sha256(ROOT/p)==h for p,h in protected.items())
    if not report['protected_files_unchanged']:
        raise ValueError('실행 중 보호된 모델/설정/소스가 변경됐습니다.')
    report['complete'] = True
    atomic_json(output/'comparison.json',report,indent=2)
    fields = ['id','label','roi_mode','status','respiration_state','movement_absence_candidate',
              'pred_rr_bpm','anomaly_score','is_anomaly','reason','quality_ok','amplitude_px','candidate_bpm',
              'periodic_concentration','spatial_coherence','deepphys_bpm_diagnostic','error']
    with (output/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fields,extrasaction='ignore'); writer.writeheader()
        writer.writerows(report['records'])
    names={'motion_present':'호흡 움직임 있음','no_motion_detected':'호흡 움직임 검출 안 됨',
           'unassessable':'측정 불가'}
    lines=['# 호흡 움직임 실험 결과','',
           '개발용 결과입니다. 인형 정지는 실제 영아 무호흡 정답이 아니며 운영 모델은 교체하지 않았습니다.','',
           '| 구간 | 움직임 판정 | 승인 BPM | AE 상태 | 이유 |',
           '|---|---|---:|---|---|']
    for r in report['records']:
        lines.append(f"| {r['id']} | {names.get(r.get('respiration_state'), '비교용 수치만 저장')} | "
                     f"{r.get('pred_rr_bpm') if r.get('pred_rr_bpm') is not None else '—'} | "
                     f"{r.get('status','미적용')} | {r.get('reason') or r.get('error') or ''} |")
    (output/'results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(output),cases=len(report['records']),complete=True),ensure_ascii=False))


def compare(args):
    doc = read_manifest(args.manifest)
    cfg, existing, protected = context(args.output)
    base = runner(existing,ROOT/'checkpoints/DeepPhys_Deep_Body_best.pth',args.body_detector,args.correct_detector_color)
    efficient = None
    native=load_native_pyflow(args.pyflow_module) if args.pyflow_module else None
    if args.efficient_deepflow_diagnostic or native is not None:
        if args.efficient_checkpoint is None:
            raise ValueError('--efficient-checkpoint가 필요합니다.')
        from models.efficient_phys import EfficientPhys
        efficient = EfficientPhys(img_size=96,frame_depth=10)
        state=torch.load(args.efficient_checkpoint,map_location='cpu',weights_only=True)
        state=state.get('state_dict',state)
        efficient.load_state_dict({k.removeprefix('module.'):v for k,v in state.items()},strict=True)
        efficient.to(base.device).eval()
    report = dict(schema=1,complete=False,experimental_only=True,manifest_sha256=sha256(args.manifest),
                  protected_hashes=protected,feature_hashes=feature_hashes(),records=[],
                  efficientphys=dict(official_training_flow='coarse2fine',
                                     actual_flow='coarse2fine' if native else 'deep',
                                     flow_matches_training=native is not None,production_eligible=False,
                                     status='official_flow_bench' if native else 'diagnostic_mismatched_flow' if efficient else 'unscored',
                                     temporal_contract='450 samples; TSM depth10; batches180/180/90 + duplicate final frame',
                                     native_module_sha256=sha256(args.pyflow_module) if native else None,
                                     checkpoint_sha256=sha256(args.efficient_checkpoint) if efficient else None),
                  production_model_replaced=False,same_camera_positive_control=False,
                  execution_source_sha256=sha256(__file__),
                  detector_color_corrected=args.correct_detector_color,
                  detector_adapter_sha256=sha256(ROOT/'normal_pipeline/detector_input.py'),
                  body_detector_sha256=sha256(args.body_detector or ROOT/'detectors/yolov8m.pt'))
    for index, record in enumerate(doc['records']):
        print('COMPARE',record['id'],flush=True)
        case_dir=args.output/f'{index:04d}'; case_dir.mkdir()
        result=dict(record,roi_mode=args.roi_mode,error=None)
        arrays={}
        try:
            frames=read_first_window(ROOT/record['source'],cfg.ffmpeg,existing)
            box=record['roi_xywh_normalized']
            if args.roi_mode=='automatic':
                automatic,_=base.pre.get_roi_box(frames)
                box=[automatic[0]/320,automatic[1]/180,automatic[2]/320,automatic[3]/180]
            result['roi_xywh_normalized']=box
            pixels=roi_box(box,180,320)
            preview=frames[0].astype(np.uint8).copy()
            x,y,w,h=map(int,pixels)
            cv2.rectangle(preview,(x,y),(x+w,y+h),(255,0,0),2)
            cv2.imwrite(str(case_dir/'roi.png'),cv2.cvtColor(preview,cv2.COLOR_RGB2BGR))
            motion=motion_features(frames,box,15)
            result.update({k:v for k,v in motion.items() if not isinstance(v,np.ndarray)})
            result['windows']=motion_windows(frames,box)
            arrays['motion_pixels']=motion['waveform']
            arrays['background_velocity']=motion['background_velocity']
            if not args.motion_only:
                inputs=encode_inputs(frames,base,box)
                raw=raw_prediction(inputs,base)
                arrays['deepphys_raw']=raw
                resp,bpm=base.post.post_process(torch.from_numpy(raw),fs=15,diff_flag=base.diff_flag,
                                               infant_flag=base.infant_flag,use_bandpass=True,eval_method=base.rr_method)
                arrays['deepphys_processed']=np.asarray(resp)
                result['deepphys_bpm_diagnostic']=float(bpm)
                result['deepphys_raw_std']=float(raw.std())
            if efficient is not None:
                if args.motion_only:
                    raise ValueError('--motion-only와 EfficientPhys 실행을 함께 지정할 수 없습니다.')
                einputs=efficient_coarse_inputs(frames,base,box,native) if native else inputs
                eraw=efficient_raw(einputs,efficient,base.device)
                arrays['efficientphys_coarse2fine_raw' if native else 'efficientphys_deepflow_raw_diagnostic']=eraw
                _, ebpm=base.post.post_process(torch.from_numpy(eraw),fs=15,diff_flag=True,
                                               infant_flag=True,use_bandpass=True,eval_method='FFT')
                result['efficientphys_bpm_diagnostic']=float(ebpm)
                result['efficientphys_raw_std']=float(eraw.std())
            np.savez_compressed(case_dir/'signals.npz',**arrays,fs=15)
            render_case(case_dir,record['id'],arrays)
            result['signals_file']=str((case_dir/'signals.npz').relative_to(args.output))
            result['signals_sha256']=sha256(case_dir/'signals.npz')
        except (ValueError,existing.InvalidWindow,OSError) as exc:
            result.update(error=str(exc),windows=[],status='unscored')
        report['records'].append(result)
        atomic_json(args.output/'comparison.json',report,indent=2)
        print('RESULT',record['id'],result.get('amplitude_px'),result.get('quality_reasons'),result['error'],flush=True)
    finish(args.output,report,protected)


def render_case(directory,name,arrays):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(len(arrays)-1,1,figsize=(12,2.5*(len(arrays)-1)),sharex=True)
    axes=np.atleast_1d(axes)
    for axis,(key,values) in zip(axes,[(k,v) for k,v in arrays.items() if v.ndim==1]):
        axis.plot(np.arange(len(values))/15,values,linewidth=.8)
        axis.set_ylabel(key.replace('_',' '),fontsize=8); axis.grid(alpha=.2)
    axes[-1].set_xlabel('Time (s)'); fig.suptitle(name+' — separate units; no amplitude normalization')
    fig.tight_layout(); fig.savefig(directory/'signals.png',dpi=130); plt.close(fig)


def calibrate(args):
    if args.output.exists():
        raise ValueError('새 --output 폴더를 지정하세요.')
    report=json.loads(args.comparison.read_text(encoding='utf-8-sig'))
    current=feature_hashes()
    if report.get('complete') is not True or any(report['feature_hashes'].get(p)!=h for p,h in current.items()):
        raise ValueError('완료된 현재 소스의 비교가 필요합니다.')
    records=[r for r in report['records'] if not r.get('error')]
    if not records or len({r['roi_mode'] for r in records})!=1:
        raise ValueError('동일 ROI 모드의 유효한 사례가 필요합니다.')
    if report.get('detector_color_corrected') is True and report.get('detector_adapter_sha256')!=sha256(ROOT/'normal_pipeline/detector_input.py'):
        raise ValueError('비교 이후 검출기 입력 어댑터가 변경됐습니다.')
    calibration=fit_calibration(records)
    calibration.update(comparison_sha256=sha256(args.comparison),feature_hashes=feature_hashes(),
                       decision_source_sha256=sha256(ROOT/'normal_pipeline/respiration_presence.py'),
                       roi_mode=records[0]['roi_mode'],body_detector_sha256=report.get('body_detector_sha256',
                           report['protected_hashes']['detectors/yolov8m.pt']),
                       detector_color_corrected=report.get('detector_color_corrected',False),
                       detector_adapter_sha256=report.get('detector_adapter_sha256'),
                       source_cases=[dict(id=r['id'],group_id=r['group_id'],
                       source_sha256=r['source_sha256'],split=r['split']) for r in records])
    args.output.mkdir(parents=True,exist_ok=False)
    atomic_json(args.output/'calibration.json',calibration,indent=2)
    print(json.dumps({k:calibration[k] for k in ('development_usable','production_ready','amplitude_threshold_px','reason')},ensure_ascii=False))


def video(args):
    calibration=json.loads(args.calibration.read_text(encoding='utf-8-sig'))
    if calibration['feature_hashes'] != feature_hashes():
        raise ValueError('보정 후 특성 코드가 변경됐습니다. 새 비교/보정이 필요합니다.')
    if calibration['decision_source_sha256'] != sha256(ROOT/'normal_pipeline/respiration_presence.py'):
        raise ValueError('보정 후 판정 코드가 변경됐습니다. 새 보정이 필요합니다.')
    cfg,existing,protected=context(args.output)
    body=args.body_detector or ROOT/'detectors/yolov8m.pt'
    if calibration.get('detector_color_corrected',False) != args.correct_detector_color:
        raise ValueError('보정과 실제 ROI 검출기 색상 경로가 다릅니다.')
    if args.correct_detector_color and calibration.get('detector_adapter_sha256')!=sha256(ROOT/'normal_pipeline/detector_input.py'):
        raise ValueError('보정 후 검출기 입력 어댑터가 바뀌었습니다.')
    base=runner(existing,ROOT/'checkpoints/DeepPhys_Deep_Body_best.pth',body,args.correct_detector_color)
    scorer=existing.AnomalyV2(args.ae_checkpoint,base.device)
    state=torch.load(args.ae_checkpoint,map_location='cpu',weights_only=True)
    expected=state.get('feature_pipeline_hashes',{})
    verify_roi_contract(state,sha256(body),args.correct_detector_color)
    for path,digest in expected.items():
        if not (ROOT/path).is_file() or sha256(ROOT/path)!=digest:
            raise ValueError('AE 학습 특성 파이프라인 해시 불일치: '+path)
    report=dict(schema=1,complete=False,experimental_only=True,feature_hashes=feature_hashes(),
                source_sha256=sha256(args.input),calibration_sha256=sha256(args.calibration),
                ae_checkpoint_sha256=sha256(args.ae_checkpoint),records=[],
                production_model_replaced=False,roi_transfer_validated=False)
    roi_calibrated=(calibration.get('roi_mode')=='automatic' and calibration.get('development_usable') is True
                    and calibration.get('body_detector_sha256')==sha256(body))
    report['development_roi_calibration_matches']=roi_calibrated
    all_decisions=[]
    # Existing automatic ROI and exact production DeepPhys/AE input. No manual fallback.
    with closing(existing.frame_windows(args.input,cfg.ffmpeg,base)) as windows:
        for index,(count,frames) in enumerate(windows):
            if args.max_windows is not None and index>=args.max_windows:
                break
            row=dict(id=f'window_{index:06d}',label='unreviewed',roi_mode='automatic',
                     start_sec=index*30,end_sec=index*30+count/15,status='unscored',
                     is_anomaly=None,anomaly_score=None,pred_rr_bpm=None,reason=None,error=None)
            row.update(respiration_state='unassessable',movement_absence_candidate=None,clinical_apnea=None)
            try:
                if count!=450 or frames is None:
                    raise ValueError('30초 미만 구간')
                pixel_box,detections=base.pre.get_roi_box(frames)
                box=[pixel_box[0]/320,pixel_box[1]/180,pixel_box[2]/320,pixel_box[3]/180]
                motion=motion_features(frames,box,15)
                row.update({k:v for k,v in motion.items() if not isinstance(v,np.ndarray)})
                row.update(roi_xywh_normalized=box,roi_detection_frames=len(detections))
                decisions=[]
                for f in motion_windows(frames,box):
                    decision=classify_motion(f,calibration,allow_development=args.allow_development_calibration)
                    decision.update(start_sec=f['start_sec']+index*30,end_sec=f['end_sec']+index*30)
                    decisions.append(decision)
                all_decisions.extend(decisions)
                row['presence_windows']=summarize_decisions(all_decisions)[-len(decisions):]
                try:
                    raw,resp,wave,bpm=base.extract(frames)
                    wx,wb,score=scorer.score(wave,bpm)
                    row['legacy_ae_diagnostic']=dict(anomaly_score=score,is_anomaly=score>scorer.threshold,
                                                   pred_rr_bpm=bpm,wave_mse=wx,bpm_mse=wb)
                    np.savez_compressed(args.output/f'{index:06d}.npz',raw_model=raw,x_10hz=wave,
                                        pred_rr_bpm=bpm,motion_pixels=motion['waveform'])
                except existing.InvalidWindow as exc:
                    row['legacy_ae_diagnostic']=dict(status='unscored',reason=str(exc),anomaly_score=None,is_anomaly=None)
                row.update(combine_decisions(decisions,row['legacy_ae_diagnostic'],
                           roi_calibrated=roi_calibrated,allow_development=args.allow_development_calibration))
                row['experimental_state_counts']=dict(Counter(d['respiration_state'] for d in decisions))
                row['candidate_motion_bpm_diagnostic']=row.pop('candidate_bpm',None)
            except (ValueError,existing.InvalidWindow) as exc:
                row.update(reason=str(exc),error=str(exc),respiration_state='unassessable')
            report['records'].append(row)
            atomic_json(args.output/'comparison.json',report,indent=2)
            print('AUTO',row['id'],row['reason'],flush=True)
    finish(args.output,report,protected)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('compare'); p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--roi-mode',choices=['fixed_manual','automatic'],default='fixed_manual')
    p.add_argument('--body-detector',type=Path)
    p.add_argument('--correct-detector-color',action='store_true')
    p.add_argument('--motion-only',action='store_true')
    p.add_argument('--efficient-checkpoint',type=Path)
    p.add_argument('--pyflow-module',type=Path)
    p.add_argument('--efficient-deepflow-diagnostic',action='store_true')
    p=sub.add_parser('calibrate'); p.add_argument('--comparison',type=Path,required=True)
    p=sub.add_parser('video'); p.add_argument('--input',type=Path,required=True)
    p.add_argument('--body-detector',type=Path)
    p.add_argument('--correct-detector-color',action='store_true')
    p.add_argument('--calibration',type=Path,required=True)
    p.add_argument('--ae-checkpoint',type=Path,default=ROOT/'output/ae_retrained_evaluated_20261125/air400_ae.pt')
    p.add_argument('--allow-development-calibration',action='store_true')
    p.add_argument('--max-windows',type=int,default=None)
    for p in sub.choices.values():
        p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='video' and args.max_windows is not None and args.max_windows<1:
        parser.error('--max-windows는 양수여야 합니다.')
    try:
        globals()[args.command](args)
    except (ValueError,OSError) as exc:
        parser.exit(2,f'오류: {exc}\n')


if __name__=='__main__':
    main()
