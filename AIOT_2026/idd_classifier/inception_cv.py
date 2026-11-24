"""MiniRocket과 동일한 참가자·Window에서 소형 InceptionTime을 평가한다."""
import copy
import json
import os
import platform
import random
import time
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .data import build_manifest, fit_normalizer, make_windows, prepare_tracks
from .experiment import bundle_metadata, prediction_frame, train_model, write_json
from .features import FeatureConfig
from .metrics import participant_macro_auc, select_balanced_threshold, select_threshold
from .minirocket_cv import evaluate_oof, operating_reports
from .model import create_model, model_architecture, predict_scores
from .tuning import normalized_subset

WINDOW_KEYS = ['participant', 'scenario_id', 'end_ns', 'label', 'fold']


def select_refit_epochs(best_epochs):
    if not best_epochs or any(not isinstance(epoch, int) or epoch < 1 for epoch in best_epochs):
        raise ValueError('내부 검증에서 선택된 양의 정수 epoch가 필요합니다.')
    return max(1, int(np.median(best_epochs)))


def validate_config(config):
    for key in ('batch_size', 'epochs', 'patience', 'cpu_threads'):
        if isinstance(config[key], bool) or not isinstance(config[key], int) or config[key] < 1:
            raise ValueError(f'{key}는 양의 정수여야 합니다.')
    for key in ('learning_rate', 'weight_decay'):
        if not np.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f'{key}는 양의 유한한 수여야 합니다.')
    if not isinstance(config['bootstrap_repeats'], int) or config['bootstrap_repeats'] < 0:
        raise ValueError('bootstrap 반복 수를 확인하세요.')
    create_model('InceptionTime', model_architecture({**config, 'model_type': 'InceptionTime'}))


def check_reference_windows(raw, folds, reference_csv):
    """점수 비교 전에 평가 대상이 한 행도 다르지 않은지 확인한다."""
    participant_fold = {p: fold['fold'] for fold in folds for p in fold['test']}
    current = prediction_frame(raw, np.zeros(len(raw['y'])))
    current['fold'] = raw['fold'] if 'fold' in raw else current.participant.map(participant_fold)
    previous = pd.read_csv(reference_csv)
    for frame in (current, previous):
        if frame.duplicated(WINDOW_KEYS[:3]).any():
            raise ValueError('평가 Window가 중복되었습니다.')
    left = current[WINDOW_KEYS].sort_values(WINDOW_KEYS).reset_index(drop=True)
    right = previous[WINDOW_KEYS].sort_values(WINDOW_KEYS).reset_index(drop=True)
    if not left.equals(right):
        raise ValueError('MiniRocket과 평가 참가자/시나리오/시각/라벨/fold가 다릅니다.')


def fit_inner_models(tracks, train_raw, validation_raw, fold, config, directory, device, resume=False):
    frames, best_epochs = [], []
    for index, inner in enumerate(fold['inner'], 1):
        started = time.perf_counter()
        inner_directory = directory/f'inner_{index}'
        inner_directory.mkdir(exist_ok=resume)
        normalizer = fit_normalizer(tracks, inner['train'], config['transform'])
        train = normalized_subset(train_raw, inner['train'], normalizer)
        validation = normalized_subset(validation_raw, inner['validation'], normalizer)
        inner_config = {**config, 'seed': config['seed']+index}
        fit_file = inner_directory/'fit.json'
        if resume and fit_file.exists():
            saved = json.loads(fit_file.read_text(encoding='utf-8'))
            if saved['participants'] != inner or saved['normalizer'] != normalizer or saved['seed'] != inner_config['seed']:
                raise ValueError('재사용할 내부 모델의 참가자/정규화/seed가 다릅니다.')
            model = create_model('InceptionTime', model_architecture(inner_config)).to(device)
            model.load_state_dict(torch.load(inner_directory/'model.pt', map_location=device, weights_only=True))
            training = saved['training']
        else:
            model, training = train_model(train, validation, inner_config, inner_directory, device)
        scores = predict_scores(model, validation['x'], device=device)
        frames.append(prediction_frame(validation, scores).assign(inner_fold=index))
        best_epochs.append(training['best_epoch'])
        write_json(inner_directory/'fit.json', {'participants': inner, 'normalizer': normalizer,
                   'training': training, 'train_windows': len(train['y']),
                   'validation_windows': len(validation['y']), 'seed': inner_config['seed']})
        print(f"  내부 {index}/{len(fold['inner'])} | best epoch {training['best_epoch']} | "
              f"참가자 AUC {training['best_validation_macro_auc']:.4f} | {time.perf_counter()-started:.1f}초", flush=True)
    frame = pd.concat(frames, ignore_index=True)
    frame.to_csv(directory/'inner_oof.csv', index=False)
    selection = {'refit_epochs': select_refit_epochs(best_epochs), 'inner_best_epochs': best_epochs,
                 'participant_macro_auc': participant_macro_auc(frame.label, frame.score, frame.participant),
                 'operating_point': select_threshold(frame, config['max_validation_fpr']),
                 'balanced_operating_point': select_balanced_threshold(frame),
                 'selection_data': '바깥 개발 참가자의 내부 OOF만 사용'}
    write_json(directory/'inner_selection.json', selection)
    return selection


def fit_fixed_epochs(train, config, epochs, directory, device):
    """바깥 테스트를 받지 않는 고정 epoch 재학습. 마지막 가중치를 저장한다."""
    random.seed(config['seed'])
    np.random.seed(config['seed'])
    torch.manual_seed(config['seed'])
    torch.use_deterministic_algorithms(True)
    model = create_model('InceptionTime', model_architecture(config)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config['learning_rate'], weight_decay=config['weight_decay'])
    positive = float(train['y'].sum())
    weight = (len(train['y'])-positive)/positive
    loss_function = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(weight, device=device))
    dataset = TensorDataset(torch.from_numpy(train['x']), torch.from_numpy(train['y']))
    generator = torch.Generator().manual_seed(config['seed'])
    loader = DataLoader(dataset, batch_size=config['batch_size'], shuffle=True, generator=generator, num_workers=0)
    history = []
    for epoch in range(1, epochs+1):
        started, loss_sum = time.perf_counter(), 0.
        model.train()
        for features, labels in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(features.to(device)), labels.to(device))
            if not torch.isfinite(loss):
                raise ValueError('학습 손실이 유한하지 않습니다.')
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
            optimizer.step()
            loss_sum += float(loss.detach())*len(labels)
        history.append({'epoch': epoch, 'train_loss': loss_sum/len(dataset), 'seconds': time.perf_counter()-started})
        pd.DataFrame(history).to_csv(directory/'history.csv', index=False)
    torch.save({key: value.detach().cpu() for key, value in model.state_dict().items()}, directory/'model.pt')
    training = {'epochs_run': epochs, 'epoch_rule': '내부 세 best epoch의 중앙값, 마지막 epoch 가중치 사용',
                'train_pos_weight': weight, 'windows': len(train['y']),
                'parameters': sum(p.numel() for p in model.parameters())}
    return model, training


def compare_models(output, reference, results, config):
    rows, paired = [], []
    rng = np.random.default_rng(config['seed'])
    for seconds in (3, 5, 10):
        old = pd.read_csv(reference/f'oof_{seconds}s.csv')
        old_reports = {'low_fpr': evaluate_oof(old, 0),
                       'balanced': evaluate_oof(old.assign(threshold=old.balanced_threshold), 0)}
        for name, reports in (('MiniRocket', old_reports), ('SmallInceptionTime', results[str(seconds)])):
            for point, metrics in reports.items():
                rows.append({'model': name, 'seconds': seconds, 'operating_point': point, **metrics['window'],
                             'participant_macro_auc': metrics['participant_macro']['roc_auc'],
                             'mean_fold_auc': metrics['mean_fold_auc']})
        old_auc = {row['participant']: row['roc_auc'] for row in old_reports['low_fpr']['per_participant']}
        new_auc = {row['participant']: row['roc_auc'] for row in results[str(seconds)]['low_fpr']['per_participant']}
        differences = np.array([new_auc[p]-old_auc[p] for p in sorted(old_auc)])
        samples = differences[rng.integers(0, len(differences), (10000, len(differences)))].mean(axis=1)
        paired.append({'seconds': seconds, 'auc_difference_inception_minus_minirocket': float(differences.mean()),
                       'paired_participant_bootstrap_95ci': np.quantile(samples, [.025, .975]).tolist(),
                       'participants': len(differences), 'bootstrap_repeats': 10000})
    pd.DataFrame(rows).to_csv(output/'comparison.csv', index=False, encoding='utf-8-sig')
    write_json(output/'paired_model_comparison.json', paired)
    return paired


def run_inception_cv(data_root, network, reference, output, device='cpu', resume=False):
    validate_config(network)
    reference, output = Path(reference), Path(output)
    if output.exists() and not resume:
        raise FileExistsError(f'기존 결과를 덮어쓰지 않습니다: {output}')
    if resume:
        prior = json.loads((output/'config.json').read_text(encoding='utf-8'))
        prior_environment = json.loads((output/'environment.json').read_text(encoding='utf-8'))
        if (prior['network'] != network or Path(prior['reference']).resolve() != reference.resolve()
                or prior_environment['device'] != device
                or prior_environment['packages'] != {name: version(name) for name in ('torch', 'numpy', 'pandas', 'scikit-learn')}):
            raise ValueError('재개에는 동일한 설정·기준 결과·라이브러리·실행 장치가 필요합니다.')
        if list(output.glob('fold_*/*s/test_predictions.csv')):
            raise ValueError('바깥 테스트 생성 후에는 재개하지 않습니다. 완료 결과를 확인하세요.')
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
    if device == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA를 사용할 수 없습니다. GPU 환경 또는 --device cpu를 확인하세요.')
    torch.set_num_threads(network['cpu_threads'])
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    started = time.perf_counter()
    reference_config = json.loads((reference/'config.json').read_text(encoding='utf-8'))
    base, preprocessing = reference_config['base'], reference_config['minirocket']
    feature_config = replace(FeatureConfig(**base['feature']), smooth_points=preprocessing['smooth_points'])
    folds = json.loads((reference/'folds.json').read_text(encoding='utf-8'))
    participants = sorted(p for fold in folds for p in fold['test'])
    if len(participants) != len(set(participants)) or len(folds) != 5:
        raise ValueError('중복 없는 참가자 5-fold 기준 결과가 필요합니다.')
    for fold in folds:
        development, test = set(fold['development']), set(fold['test'])
        if development & test or development | test != set(participants):
            raise ValueError('바깥 분할에 참가자 누출/누락이 있습니다.')
        validated = []
        for inner in fold['inner']:
            if set(inner['train']) & set(inner['validation']) or set(inner['train']+inner['validation']) != development:
                raise ValueError('내부 분할에 참가자 누출/누락이 있습니다.')
            validated.extend(inner['validation'])
        if sorted(validated) != sorted(development):
            raise ValueError('내부 OOF 참가자 중복/누락입니다.')
    root, manifest = build_manifest(data_root, base)
    tracks, audit = prepare_tracks(root, manifest, feature_config)
    if set(track.participant for track in tracks) != set(participants):
        raise ValueError('기준 결과와 실제 대상 참가자가 다릅니다.')
    previous_audit = pd.read_csv(reference/'data_audit.csv')
    if audit.set_index('scenario_id').sha256.to_dict() != previous_audit.set_index('scenario_id').sha256.to_dict():
        raise ValueError('기준 결과와 실제 원본 CSV 해시가 다릅니다.')
    config = {**copy.deepcopy(base), **network, 'model_type': 'InceptionTime', 'feature': asdict(feature_config),
              'transform': preprocessing['transform'], 'checkpoint_metric': 'macro_auc', 'quiet_epochs': True}
    output.mkdir(parents=True, exist_ok=resume)
    write_json(output/'config.json', {'network': network, 'reference': str(reference.resolve()),
                                     'reference_config': reference_config})
    (output/'folds.json').write_bytes((reference/'folds.json').read_bytes())
    manifest.to_csv(output/'scenario_manifest.csv', index=False, encoding='utf-8-sig')
    audit.to_csv(output/'data_audit.csv', index=False, encoding='utf-8-sig')
    write_json(output/'environment.json', {'python': platform.python_version(), 'device': device,
               'gpu': torch.cuda.get_device_name(0) if device == 'cuda' else None, 'cuda': torch.version.cuda,
               'cublas_workspace_config': os.environ.get('CUBLAS_WORKSPACE_CONFIG'),
               'cuda_cache_path': os.environ.get('CUDA_CACHE_PATH'),
               'torch_kernel_cache_path': os.environ.get('PYTORCH_KERNEL_CACHE_PATH'),
               'packages': {name: version(name) for name in ('torch', 'numpy', 'pandas', 'scikit-learn')}})
    sample_hz = feature_config.sample_hz
    anchor = 10*sample_hz+preprocessing['comparison_warmup_points']-feature_config.smooth_points
    outer_raw, inner_raw = {}, {}
    for seconds in (3, 5, 10):
        outer_raw[seconds] = make_windows(tracks, participants, seconds*sample_hz,
                                         round(preprocessing['outer_stride_seconds']*sample_hz), anchor)
        inner_raw[seconds] = make_windows(tracks, participants, seconds*sample_hz,
                                         round(preprocessing['inner_stride_seconds']*sample_hz), anchor)
        check_reference_windows(outer_raw[seconds], folds, reference/f'oof_{seconds}s.csv')
    write_json(output/'comparison_setup.json', {'same_folds_bytes': True, 'same_source_csv_hashes': len(audit),
               'same_evaluation_windows': True, 'feature_config': asdict(feature_config), 'transform': config['transform'],
               'inner_training_stride_seconds': preprocessing['outer_stride_seconds'],
               'inner_validation_stride_seconds': preprocessing['inner_stride_seconds']})
    collected = {seconds: [] for seconds in (3, 5, 10)}
    selected_lengths = []
    for fold in folds:
        index = fold['fold']
        fold_directory = output/f'fold_{index}'
        fold_directory.mkdir(exist_ok=resume)
        selections = {}
        for seconds in (3, 5, 10):
            directory = fold_directory/f'{seconds}s'
            directory.mkdir(exist_ok=resume)
            length_config = {**config, 'seed': network['seed']+100*index+seconds}
            print(f'바깥 {index}/5 | {seconds}초 내부 학습', flush=True)
            selections[seconds] = fit_inner_models(tracks, outer_raw[seconds], inner_raw[seconds], fold,
                                                   length_config, directory, device, resume=resume)
        selected_seconds = max(selections, key=lambda s: (selections[s]['participant_macro_auc'], -s))
        selected_lengths.append({'fold': index, 'seconds': selected_seconds})
        write_json(fold_directory/'selection_before_test.json', {'selected_seconds': selected_seconds,
                   'selections': selections, 'test_scores_accessed': False})
        for seconds in (3, 5, 10):
            directory = fold_directory/f'{seconds}s'
            length_config = {**config, 'seed': network['seed']+100*index+seconds}
            selection = selections[seconds]
            normalizer = fit_normalizer(tracks, fold['development'], config['transform'])
            train = normalized_subset(outer_raw[seconds], fold['development'], normalizer)
            model, training = fit_fixed_epochs(train, length_config, selection['refit_epochs'], directory, device)
            training['participants'] = fold['development']
            metadata = bundle_metadata(length_config, feature_config, normalizer, seconds, training, fold,
                                       selection['operating_point'], anchor, round(preprocessing['outer_stride_seconds']*sample_hz))
            metadata['balanced_operating_point'] = selection['balanced_operating_point']
            metadata['versions'] = {'torch': version('torch'), 'numpy': version('numpy')}
            write_json(directory/'metadata.json', metadata)
            test = normalized_subset(outer_raw[seconds], fold['test'], normalizer)
            frame = prediction_frame(test, predict_scores(model, test['x'], device=device))
            frame = frame.assign(fold=index, seconds=seconds, threshold=selection['operating_point']['threshold'],
                                 balanced_threshold=selection['balanced_operating_point']['threshold'],
                                 selected_length=seconds == selected_seconds)
            frame.to_csv(directory/'test_predictions.csv', index=False)
            metrics = evaluate_oof(frame, 0)
            write_json(directory/'metrics.json', metrics)
            collected[seconds].append(frame)
            print(f"바깥 {index} | {seconds}초 테스트 AUC {metrics['window']['roc_auc']:.4f} | "
                  f"참가자 AUC {metrics['participant_macro']['roc_auc']:.4f}", flush=True)
    results, selected_frames = {}, []
    for seconds, frames in collected.items():
        frame = pd.concat(frames, ignore_index=True)
        check_reference_windows({'participant': frame.participant.to_numpy(), 'scenario_id': frame.scenario_id.to_numpy(),
                                 'end_ns': frame.end_ns.to_numpy(), 'y': frame.label.to_numpy(),
                                 'fold': frame.fold.to_numpy()}, folds, reference/f'oof_{seconds}s.csv')
        frame.to_csv(output/f'oof_{seconds}s.csv', index=False)
        selected_frames.append(frame[frame.selected_length])
        results[str(seconds)] = operating_reports(frame, config)
        write_json(output/f'metrics_{seconds}s.json', results[str(seconds)])
    selected = pd.concat(selected_frames, ignore_index=True)
    selected.to_csv(output/'oof_selected_length.csv', index=False)
    comparison = compare_models(output, reference, results, config)
    report = {'participants': participants, 'scenarios': len(tracks), 'windows_per_length': len(selected),
              'model': 'SmallInceptionTime', 'parameters': training['parameters'], 'results': results,
              'selected_lengths': selected_lengths, 'selected_length_evaluation': operating_reports(selected, config),
              'paired_model_comparison': comparison, 'elapsed_seconds': time.perf_counter()-started,
              'resumed_inner_checkpoints': resume,
              'limitations': ['같은 IDD의 반복 모델 비교이며 새로운 외부 검증은 아님', '실제 CCTV 음주 탐지 정확도가 아님']}
    write_json(output/'report.json', report)
    print(f'소형 InceptionTime 참가자 5-fold 평가 완료: {output}', flush=True)
    return report
