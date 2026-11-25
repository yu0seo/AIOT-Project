"""Small isolated DeepPhys fine-tuning experiment on reviewed cached inputs."""
import argparse
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from babycam.common import atomic_json
from normal_pipeline.no_motion import ROOT, sha256, validate_records
from normal_pipeline.no_motion_cache import raw_prediction
from normal_pipeline.no_motion_train import freeze_teacher, preservation_metrics, train_epoch


def load_caches(folders):
    cases, signatures, seen = [], [], set()
    teacher_sha = None
    for folder in folders:
        cache = json.loads((folder/'cache.json').read_text(encoding='utf-8-sig'))
        if cache.get('schema') != 1 or cache.get('complete') is not True:
            raise ValueError('완료된 schema 1 캐시만 사용합니다.')
        if cache.get('video_fs') != 15 or cache.get('samples') != 450 or cache.get('frame_batch') != 16 or cache.get('roi') is not True:
            raise ValueError('생산 추론의 전처리 계약과 다른 캐시입니다.')
        signature = {k:v for k,v in cache['pipeline_hashes'].items() if k != 'cache_source'}
        if signatures and signatures[0] != signature:
            raise ValueError('캐시들의 모델/생산 전처리 지문이 다릅니다.')
        signatures.append(signature)
        for name, digest in signature.items():
            if sha256(ROOT/name) != digest:
                raise ValueError(f'현재 파일과 캐시 지문이 다릅니다: {name}')
        if teacher_sha is not None and teacher_sha != cache['teacher_sha256']:
            raise ValueError('teacher 가중치가 다른 캐시입니다.')
        teacher_sha = cache['teacher_sha256']
        for record in cache['cases']:
            if record['status'] != 'prepared':
                raise ValueError(f'분석 불가 구간은 학습할 수 없습니다: {record["id"]}')
            if record['id'] in seen:
                raise ValueError('중복 캐시 구간')
            seen.add(record['id'])
            file = (folder/record['file']).resolve()
            if not file.is_relative_to(folder.resolve()) or sha256(file) != record['file_sha256']:
                raise ValueError('캐시 파일 경로/해시 오류')
            with np.load(file, allow_pickle=False) as data:
                inputs = data['inputs']; target = data['target_raw']; teacher = data['teacher_raw']
                meta = json.loads(str(data['metadata_json']))
            for key in ('id', 'group_id', 'split', 'kind', 'source_sha256', 'review'):
                if meta[key] != record[key]:
                    raise ValueError('캐시 내부와 외부 provenance 불일치')
            if meta.get('manual_roi') != record.get('manual_roi'):
                raise ValueError('수동 ROI provenance 불일치')
            if (inputs.shape != (450,6,96,96) or inputs.dtype != np.float32
                    or target.shape != (450,) or teacher.shape != (450,)
                    or not all(np.isfinite(v).all() for v in (inputs,target,teacher))):
                raise ValueError('캐시 shape/dtype/유한값 오류')
            if record['kind'] == 'breathing_candidate':
                if not np.array_equal(target, teacher) or teacher.std() < 1e-8:
                    raise ValueError('호흡 목표가 유효한 teacher raw와 다릅니다.')
            elif np.count_nonzero(target):
                raise ValueError('정지 목표는 raw 0이어야 합니다.')
            cases.append(dict(record, inputs=inputs, target_raw=target.astype(np.float32), teacher_raw=teacher))
    validate_records(cases, require_approved=True)
    for split in ('train','valid'):
        subset = [c for c in cases if c['split'] == split]
        if not any(c['kind']=='breathing_candidate' for c in subset) or not any(c['kind']!='breathing_candidate' for c in subset):
            raise ValueError(f'{split}에 호흡/정지 입력이 모두 필요합니다.')
    if not any(c['split']=='train' and c['kind']=='static_real' for c in cases):
        raise ValueError('실제 정지 잡음 학습 입력이 필요합니다.')
    return cases, signatures[0], teacher_sha


def evaluate(model, cases, device):
    model.eval()
    runner = SimpleNamespace(model=model,device=device,batch_size=16)
    rows, predictions = [], {}
    for case in cases:
        raw = raw_prediction(case['inputs'], runner)
        predictions[case['id']] = raw
        metrics = preservation_metrics(raw, case['teacher_raw'])
        rows.append(dict(id=case['id'],split=case['split'],kind=case['kind'],**metrics))
    return rows, predictions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=10)
    parser.add_argument('--lr', type=float, default=1e-5)
    parser.add_argument('--still-weight', type=float, default=1.)
    parser.add_argument('--max-relative-mse', type=float, default=.1)
    parser.add_argument('--min-correlation', type=float, default=.95)
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        parser.exit(1, f'오류: {exc}\n')


def run(args):
    if args.output.exists():
        raise ValueError('새 --output 폴더를 지정하세요. 원본과 이전 실험을 덮어쓰지 않습니다.')
    numbers = (args.lr,args.still_weight,args.max_relative_mse,args.min_correlation)
    if (args.epochs < 1 or not all(math.isfinite(v) for v in numbers) or min(numbers[:3]) <= 0
            or not 0 <= args.min_correlation <= 1):
        raise ValueError('학습 설정 값 오류')
    cases, signature, teacher_sha = load_caches([p.resolve() for p in args.cache])
    from models.deep_phys import DeepPhys
    torch.manual_seed(20261125)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    teacher = DeepPhys(in_channels=3,img_size=96)
    checkpoint = ROOT/'checkpoints/DeepPhys_Deep_Body_best.pth'
    if sha256(checkpoint) != teacher_sha:
        raise ValueError('원본 teacher 가중치 불일치')
    weights = torch.load(checkpoint,map_location='cpu',weights_only=True)
    weights = weights.get('state_dict', weights)
    teacher.load_state_dict({k.removeprefix('module.'):v for k,v in weights.items()}, strict=True)
    teacher = freeze_teacher(teacher.to(device))
    original = {k:v.detach().cpu().clone() for k,v in teacher.state_dict().items()}
    student = copy.deepcopy(teacher)
    for p in student.parameters():
        p.requires_grad_(True)
    student.eval()
    train = [c for c in cases if c['split']=='train']
    # Test data, if supplied, is never used for gradients or model selection.
    valid = [c for c in cases if c['split']=='valid']
    baseline, teacher_predictions = evaluate(teacher,cases,device)
    for c in cases:
        if not np.allclose(teacher_predictions[c['id']],c['teacher_raw'],rtol=1e-5,atol=1e-5):
            raise ValueError(f'현재 teacher 출력과 캐시 raw가 다릅니다: {c["id"]}')
    args.output.mkdir(parents=True,exist_ok=False)
    config = {k:([str(x) for x in v] if k=='cache' else str(v) if isinstance(v,Path) else v) for k,v in vars(args).items()}
    record = dict(config=config,device=str(device),teacher_sha256=teacher_sha,pipeline_hashes=signature,
                  cache_sha256={str(p.resolve()):sha256(p/'cache.json') for p in args.cache},
                  cases=[{k:v for k,v in c.items() if k not in ('inputs','target_raw','teacher_raw')} for c in cases],
                  baseline=baseline,history=[],limitation='Experimental only; one breathing train infant and one valid infant, synthetic-only static validation; no clinical apnea validation.')
    atomic_json(args.output/'run.json',record,indent=2)
    optimizer = torch.optim.AdamW(student.parameters(),lr=args.lr,weight_decay=0.)
    best = float('inf'); selected_epoch = None
    baseline_static = np.mean([r['raw_energy'] for r in baseline if r['split']=='valid' and r['kind']!='breathing_candidate'])
    for epoch in range(1,args.epochs+1):
        objective = train_epoch(student,train,optimizer,device,16,args.still_weight)
        metrics, _ = evaluate(student,valid,device)
        breathing = [r for r in metrics if r['kind']=='breathing_candidate']
        eligible = all(r['relative_mse'] <= args.max_relative_mse and r['correlation'] is not None
                       and r['correlation'] >= args.min_correlation for r in breathing)
        static_energy = float(np.mean([r['raw_energy'] for r in metrics if r['kind']!='breathing_candidate']))
        entry = dict(epoch=epoch,train_objective=objective,valid=metrics,
                     preservation_guard_passed=eligible,valid_static_energy=static_energy)
        record['history'].append(entry)
        # Guards are engineering preservation checks, not medical thresholds.
        if eligible and static_energy < min(best,baseline_static):
            best = static_energy; selected_epoch = epoch
            torch.save({'state_dict':{k:v.detach().cpu() for k,v in student.state_dict().items()},
                        'experiment':'no_motion_teacher_preservation','epoch':epoch,
                        'teacher_sha256':teacher_sha},args.output/'best_student.pt')
        atomic_json(args.output/'run.json',record,indent=2)
        print(json.dumps(entry,ensure_ascii=False),flush=True)
    torch.save({'state_dict':{k:v.detach().cpu() for k,v in student.state_dict().items()},
                'experiment':'no_motion_teacher_preservation','epoch':args.epochs,
                'teacher_sha256':teacher_sha},args.output/'last_student.pt')
    last, _ = evaluate(student,cases,device)
    selected = None
    if selected_epoch is not None:
        saved = torch.load(args.output/'best_student.pt',map_location='cpu',weights_only=True)
        student.load_state_dict(saved['state_dict'])
        selected, predictions = evaluate(student,cases,device)
        arrays = {f'case_{i:03d}':predictions[c['id']] for i,c in enumerate(cases)}
        np.savez_compressed(args.output/'selected_raw.npz',**arrays)
    teacher_unchanged = all(torch.equal(v.detach().cpu(),original[k]) for k,v in teacher.state_dict().items())
    if not teacher_unchanged or any(p.grad is not None for p in teacher.parameters()):
        raise ValueError('teacher가 변경되거나 gradient가 생성되었습니다.')
    if any(sha256(ROOT/name)!=digest for name,digest in signature.items()):
        raise ValueError('원본 모델/설정이 변경되었습니다.')
    summary = dict(status='experimental_only',selected_epoch=selected_epoch,selected=selected,last=last,
                   teacher_unchanged=True,protected_files_unchanged=True,
                   student_changed=any(not torch.equal(v.detach().cpu(),original[k]) for k,v in student.state_dict().items()),
                   independent_real_static_validation=False,production_model_replaced=False)
    atomic_json(args.output/'summary.json',summary,indent=2)
    print('DONE',json.dumps({k:v for k,v in summary.items() if k not in ('selected','last')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
