"""Retrain the existing AE on normal inputs; select using labelled validation."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from babycam.common import atomic_json
from models.air400_npz_anomaly_v2 import Autoencoder, BPM_WEIGHT, errors, make_loader, score, write_csv
from normal_pipeline.ae_evaluation import classification_metrics, normal_train_statistics, select_threshold, validate_feature_records
from normal_pipeline.no_motion import ROOT, sha256


def load_dataset(directory):
    d=json.loads((directory/'dataset.json').read_text(encoding='utf-8-sig'))
    if d.get('schema')!=1 or d.get('complete') is not True:
        raise ValueError('완료된 schema 1 데이터셋이 필요합니다.')
    rows=d['records']
    validate_feature_records(rows,allow_assumed=d.get('normal_assumption_authorized') is True)
    for name,digest in d['pipeline_hashes'].items():
        if sha256(ROOT/name)!=digest:
            raise ValueError('생산 모델/전처리 지문 불일치: '+name)
    waves,bpms=[],[]
    for r in rows:
        file=(directory/r['file']).resolve()
        if not file.is_relative_to(directory.resolve()) or sha256(file)!=r['file_sha256']:
            raise ValueError('입력 파형 경로/해시 오류')
        if sha256(ROOT/r['source'])!=r['source_sha256']:
            raise ValueError('원본 영상 해시 오류')
        with np.load(file,allow_pickle=False) as data:
            x=np.asarray(data['x_10hz'],dtype=np.float32)
            b=float(np.asarray(data['pred_rr_bpm']).item())
            meta=json.loads(str(data['metadata_json']))
        if x.shape!=(300,) or not np.isfinite(x).all() or x.min()==x.max() or not np.isfinite(b) or b<=0:
            raise ValueError('유효하지 않은 10Hz/300점 파형 또는 BPM')
        if 'id' in meta:
            for key in ('id','group_id','split','label','source_sha256'):
                if meta[key]!=r[key]:
                    raise ValueError('파형과 데이터셋 provenance 불일치')
        elif (Path(meta['video']).resolve()!=(ROOT/r['source']).resolve()
              or meta['start_sec']!=0 or meta['end_sec']!=30):
            raise ValueError('생산 추론 NPZ의 영상/시간 정보 불일치')
        waves.append(x);bpms.append(b)
    return np.stack(waves)[:,None,:],np.asarray(bpms,dtype=np.float32)[:,None],rows,d


def run(args):
    out=args.output.resolve();directory=args.dataset.resolve()
    if out.exists():
        raise ValueError('새 출력 폴더를 지정하세요. 기존 모델은 덮어쓰지 않습니다.')
    if args.epochs<1 or args.patience<1 or not np.isfinite(args.max_fpr) or not 0<=args.max_fpr<1:
        raise ValueError('학습 설정 오류')
    waves,bpms,rows,dataset=load_dataset(directory)
    abnormal=np.asarray([r['label']=='static_simulation' for r in rows],dtype=bool)
    splits=np.asarray([r['split'] for r in rows])
    train=np.flatnonzero((splits=='train') & ~abnormal)
    valid=np.flatnonzero(splits=='valid');test=np.flatnonzero(splits=='test')
    if not len(train) or not len(test) or not abnormal[valid].any() or abnormal[valid].all():
        raise ValueError('정상 train, 정상/정지 valid, 별도 test가 필요합니다.')
    if len({rows[i]['group_id'] for i in train})<2:
        raise ValueError('첫 AE 비교 실험도 정상 학습 영아가 최소 2개 그룹 필요합니다.')
    stats=normal_train_statistics(waves,bpms,splits,abnormal)
    torch.manual_seed(42)
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model=Autoencoder().to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=5e-4,weight_decay=1e-3)
    train_loader=make_loader(waves,bpms,train,stats,shuffle=True)
    valid_loader=make_loader(waves,bpms,valid,stats)
    test_loader=make_loader(waves,bpms,test,stats)
    out.mkdir(parents=True,exist_ok=False)
    run=dict(dataset=str(directory),dataset_sha256=sha256(directory/'dataset.json'),
             epochs=args.epochs,patience=args.patience,max_validation_fpr=args.max_fpr,
             counts={split:dict(normal=int(np.sum((splits==split)&~abnormal)),static_simulation=int(np.sum((splits==split)&abnormal))) for split in ('train','valid','test')},
             stats=stats,device=str(device),seed=42,bpm_weight=BPM_WEIGHT,history=[],
             original_pipeline_hashes=dataset['pipeline_hashes'],
             experiment_source_hashes={name:sha256(ROOT/name) for name in ('retrain_ae_evaluated.py','normal_pipeline/ae_evaluation.py')},
             limitation=dataset['limitation'])
    atomic_json(out/'run.json',run,indent=2)
    best=None;best_state=None;best_epoch=None;best_threshold=None;stale=0
    for epoch in range(1,args.epochs+1):
        model.train();total=0.
        for x,b in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss=errors(model,x.to(device),b.to(device),training=True)[:,2].mean()
            if not torch.isfinite(loss):
                raise ValueError('학습 손실이 유한하지 않습니다.')
            loss.backward();optimizer.step();total+=float(loss.detach())*len(x)
        valid_scores=score(model,valid_loader,device)
        threshold,metrics=select_threshold(valid_scores[:,2],abnormal[valid],args.max_fpr)
        normal_loss=float(valid_scores[~abnormal[valid],2].mean(dtype=np.float64))
        # Validation discrimination first; normal reconstruction breaks ties.
        # No test score is computed until this selection loop has finished.
        key=(metrics['balanced_accuracy'],-normal_loss)
        if best is None or key>best:
            best=key;best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
            best_epoch=epoch;best_threshold=threshold;stale=0
        else:
            stale+=1
        entry=dict(epoch=epoch,train_loss=total/len(train),valid_normal_loss=normal_loss,
                   threshold=threshold,valid=metrics)
        run['history'].append(entry)
        atomic_json(out/'run.json',run,indent=2)
        if epoch==1 or epoch%10==0 or stale>=args.patience:
            print('AE_EPOCH',json.dumps(entry),flush=True)
        if stale>=args.patience:
            break
    model.load_state_dict(best_state)
    valid_scores=score(model,valid_loader,device)
    test_scores=score(model,test_loader,device)
    train_scores=score(model,make_loader(waves,bpms,train,stats),device)
    checkpoint=dict(model_version=2,state_dict=best_state,stats=stats,bpm_weight=BPM_WEIGHT,
                    threshold=float(best_threshold),best_epoch=int(best_epoch),best_val_loss=float(-best[1]),
                    training_scope='normal_only_reconstruction',selection='mixed_validation_balanced_accuracy_with_fpr_constraint',
                    dataset_sha256=run['dataset_sha256'],feature_pipeline_hashes=dataset['pipeline_hashes'],
                    feature_contract=dict(video_fs=15,wave_fs=10,wave_samples=300,window_sec=30) |
                                     dataset.get('active_feature_contract',{}),
                    label_counts=run['counts'],normal_assumption_authorized=True,experimental_only=True)
    torch.save(checkpoint,out/'air400_ae.pt')
    reports={}
    # Restore original order only for reporting, after selecting weights/threshold.
    all_scores={int(i):s for indices,array in ((train,train_scores),(valid,valid_scores),(test,test_scores)) for i,s in zip(indices,array)}
    predictions=[]
    for i,r in enumerate(rows):
        wx,wb,ax=map(float,all_scores[i]);flag=ax>best_threshold
        predictions.append(dict(id=r['id'],group_id=r['group_id'],split=r['split'],label=r['label'],reviewed=r['reviewed'],
                           pred_rr_bpm=float(bpms[i,0]),wave_mse=wx,bpm_mse=wb,anomaly_score=ax,
                           threshold=float(best_threshold),is_anomaly=bool(flag),
                           status='anomaly_candidate' if flag else 'below_threshold'))
    write_csv(out/'scores.csv',predictions)
    for split,indices,array in [('valid',valid,valid_scores),('test',test,test_scores)]:
        reports[split]=classification_metrics(array[:,2],abnormal[indices],best_threshold)
        reports[split+'_always_normal']=classification_metrics(np.zeros(len(indices)),abnormal[indices],1.)
    bpm_deviation=np.abs(bpms[:,0]-stats['bpm_mean'])/stats['bpm_std']
    bpm_threshold,_=select_threshold(bpm_deviation[valid],abnormal[valid],args.max_fpr)
    reports['test_bpm_deviation_baseline']=classification_metrics(bpm_deviation[test],abnormal[test],bpm_threshold)
    # Compatibility check with the unchanged inference loader, using the new path explicitly.
    import sys
    sys.path.insert(0,str(ROOT/'models'))
    from air400_detect_v2 import AnomalyV2
    restored=AnomalyV2(out/'air400_ae.pt',device)
    max_diff=0.
    for i in test:
        actual=restored.score(waves[i,0],float(bpms[i,0]))
        max_diff=max(max_diff,float(np.max(np.abs(np.asarray(actual)-all_scores[int(i)]))))
    if max_diff>2e-5:
        raise ValueError('저장 모델의 실제 추론 결과가 평가와 다릅니다.')
    if any(sha256(ROOT/name)!=digest for name,digest in dataset['pipeline_hashes'].items()):
        raise ValueError('기존 운영 파일이 변경되었습니다.')
    summary=dict(status='experimental_only',best_epoch=best_epoch,epochs_run=len(run['history']),threshold=best_threshold,
                 metrics=reports,inference_reload_max_abs_diff=max_diff,original_files_unchanged=True,
                 clinical_apnea_test_count=0,normal_labels_are_assumed=True,
                 production_model_replaced=False,negative_test_development_exposed=True)
    atomic_json(out/'summary.json',summary,indent=2)
    print('AE_DONE',json.dumps(summary),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--epochs',type=int,default=500)
    parser.add_argument('--patience',type=int,default=20)
    parser.add_argument('--max-fpr',type=float,default=.05)
    args=parser.parse_args()
    try:
        run(args)
    except (ValueError,OSError,KeyError,RuntimeError) as exc:
        parser.exit(1,f'오류: {exc}\n')


if __name__=='__main__':
    main()
