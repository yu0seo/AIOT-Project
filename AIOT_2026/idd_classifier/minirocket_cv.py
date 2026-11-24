"""참가자 중첩 교차검증. 바깥 테스트로 C/길이/임계값을 고르지 않는다."""
import gc
import platform
import time
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .data import build_manifest, fit_normalizer, make_windows, prepare_tracks, transform_features
from .experiment import prediction_frame, write_json
from .features import FEATURE_DEFINITIONS, FEATURE_NAMES, FEATURE_UNITS, FeatureConfig
from .metrics import (METRIC_NAMES, binary_metrics, participant_macro_auc,
                      select_balanced_threshold, select_threshold)
from .rocket_model import RocketModel, fit_classifier, fit_representation
from .tuning import normalized_subset, participant_folds


def validate_config(config, sample_hz):
    for key in ('outer_folds', 'inner_folds', 'n_kernels', 'max_dilations_per_kernel',
                'smooth_points', 'comparison_warmup_points', 'n_jobs', 'classifier_max_iter'):
        if isinstance(config[key], bool) or not isinstance(config[key], int) or config[key] < 1:
            raise ValueError(f'{key}는 양의 정수여야 합니다.')
    if min(config['outer_folds'], config['inner_folds']) < 2 or config['n_kernels'] < 84:
        raise ValueError('최소 2-fold와 84개 변환 피처가 필요합니다.')
    if config['comparison_warmup_points'] < config['smooth_points']:
        raise ValueError('비교용 초기 이력이 평활화 이력보다 짧습니다.')
    candidates = config['regularization_c']
    if not candidates or len(set(candidates)) != len(candidates) or not all(np.isfinite(c) and c > 0 for c in candidates):
        raise ValueError('중복 없는 양의 규제 C 후보가 필요합니다.')
    for key in ('inner_stride_seconds', 'outer_stride_seconds'):
        stride = config[key]*sample_hz
        if not np.isfinite(stride) or stride < 1 or not float(stride).is_integer():
            raise ValueError('stride는 양의 정수 샘플에 대응해야 합니다.')
    if not np.isfinite(config['classifier_tolerance']) or config['classifier_tolerance'] <= 0:
        raise ValueError('분류기 수렴 허용오차는 양수여야 합니다.')
    if not isinstance(config['bootstrap_repeats'], int) or config['bootstrap_repeats'] < 0:
        raise ValueError('bootstrap 반복 수는 음수가 아닌 정수여야 합니다.')
    transform_features(np.zeros((1, 4)), config['transform'])


def nested_participant_folds(participants, outer_folds, inner_folds, seed):
    result = []
    for index, outer in enumerate(participant_folds(participants, outer_folds, seed), 1):
        development, test = outer['train'], outer['validation']
        result.append({'fold': index, 'development': development, 'test': test,
                       'inner': participant_folds(development, inner_folds, seed+index)})
    return result


def fixed_metrics(frame):
    """행마다 소속 fold의 임계값을 적용하고 ROC-AUC는 원래 점수로 계산한다."""
    return binary_metrics(frame.label, frame.score, frame.threshold.to_numpy())


def mean_defined(values):
    values = [value for value in values if value is not None]
    return float(np.mean(values)) if values else None


def evaluate_oof(frame, bootstrap_repeats=1000, seed=42):
    """fold별 임계값을 유지한 집계와 참가자 군집 bootstrap."""
    if frame.empty or frame.groupby('participant').fold.nunique().max() != 1:
        raise ValueError('각 참가자는 하나의 바깥 테스트 fold에만 속해야 합니다.')
    if frame.groupby('participant').threshold.nunique().max() != 1:
        raise ValueError('각 참가자의 임계값이 일정해야 합니다.')
    if not np.isfinite(frame.threshold).all() or np.any((frame.threshold < 0) | (frame.threshold > np.nextafter(1., np.inf))):
        raise ValueError('유효하지 않은 fold 임계값입니다.')
    per_participant = [{'participant': key, **fixed_metrics(group)}
                       for key, group in frame.groupby('participant', sort=True)]
    macro = {name: mean_defined([row[name] for row in per_participant])
             for name in METRIC_NAMES}
    condition = frame.groupby(['participant', 'fold', 'label', 'threshold'], as_index=False).score.mean()
    groups = [group for _, group in frame.groupby('participant', sort=True)]
    rng = np.random.default_rng(seed)
    samples = {name: [] for name in METRIC_NAMES}
    macro_auc_samples = []
    person_aucs = np.array([row['roc_auc'] for row in per_participant], dtype=float)
    for _ in range(bootstrap_repeats):
        chosen = rng.integers(0, len(groups), len(groups))
        resampled = pd.concat([groups[i] for i in chosen], ignore_index=True)
        metrics = fixed_metrics(resampled)
        for name in METRIC_NAMES:
            if metrics[name] is not None:
                samples[name].append(metrics[name])
        sampled_aucs = person_aucs[chosen]
        sampled_aucs = sampled_aucs[np.isfinite(sampled_aucs)]
        if len(sampled_aucs):
            macro_auc_samples.append(float(np.mean(sampled_aucs)))
    intervals = {name: np.quantile(values, [.025, .975]).tolist() if values else None
                 for name, values in samples.items()}
    fold_metrics = [{'fold': int(key), **fixed_metrics(group)} for key, group in frame.groupby('fold')]
    return {'window': fixed_metrics(frame), 'participant_macro': macro, 'per_participant': per_participant,
            'folds': fold_metrics, 'mean_fold_auc': mean_defined([row['roc_auc'] for row in fold_metrics]),
            'participant_condition': fixed_metrics(condition), 'participant_condition_scores': condition.to_dict('records'),
            'window_cluster_bootstrap_95ci': intervals,
            'participant_macro_auc_95ci': np.quantile(macro_auc_samples, [.025, .975]).tolist() if macro_auc_samples else None,
            'bootstrap': {'unit': '참가자', 'participants': len(groups), 'repeats': bootstrap_repeats},
            'threshold_rule': '각 바깥 fold 내부 OOF에서 정한 임계값을 유지; 전체 OOF로 재조정하지 않음'}


def tune_regularization(tracks, raw, fold, config, directory, max_fpr, seed):
    """바깥 테스트의 라벨/점수 없이 개발 참가자의 내부 OOF만 사용한다."""
    candidates = sorted(config['regularization_c'])
    predictions = {c: [] for c in candidates}
    for index, inner in enumerate(fold['inner'], 1):
        started = time.perf_counter()
        normalizer = fit_normalizer(tracks, inner['train'], config['transform'])
        train = normalized_subset(raw, inner['train'], normalizer)
        validation = normalized_subset(raw, inner['validation'], normalizer)
        transformer, scaler, representation = fit_representation(train['x'], config, seed+index)
        # 검증 변환은 한 번 계산하여 C 후보마다 같은 입력을 쓴다.
        from .rocket_model import as_channels_first
        transformed_validation = scaler.transform(transformer.transform(as_channels_first(validation['x'])))
        iterations = {}
        for c in candidates:
            classifier = fit_classifier(representation, train['y'], c, config, seed+index)
            scores = classifier.predict_proba(transformed_validation)[:, 1]
            predictions[c].append(prediction_frame(validation, scores).assign(inner_fold=index))
            iterations[str(c)] = int(classifier.n_iter_.max())
        write_json(directory/f'inner_{index}_fit.json', {'participants': inner, 'normalizer': normalizer,
                   'train_windows': len(train['y']), 'validation_windows': len(validation['y']),
                   'representation_features': representation.shape[1], 'classifier_iterations': iterations,
                   'seconds': time.perf_counter()-started, 'seed': seed+index})
        print(f"  내부 {index}/{len(fold['inner'])} 완료 ({time.perf_counter()-started:.1f}초)", flush=True)
        del representation, transformed_validation, transformer, scaler, classifier
        gc.collect()
    scores = []
    for c in candidates:
        frame = pd.concat(predictions[c], ignore_index=True)
        frame.to_csv(directory/f'inner_oof_C_{c:g}.csv', index=False)
        scores.append({'c': c, 'participant_macro_auc': participant_macro_auc(frame.label, frame.score, frame.participant),
                       'window_auc': binary_metrics(frame.label, frame.score, .5)['roc_auc']})
    selected = max(scores, key=lambda row: (row['participant_macro_auc'], -row['c']))
    selected_predictions = pd.concat(predictions[selected['c']], ignore_index=True)
    result = {**selected, 'candidates': scores,
              'operating_point': select_threshold(selected_predictions, max_fpr),
              'balanced_operating_point': select_balanced_threshold(selected_predictions),
              'selection_data': '바깥 개발 참가자의 내부 OOF만 사용'}
    write_json(directory/'inner_selection.json', result)
    return result


def fit_outer_model(tracks, raw, fold, config, selection, seed):
    normalizer = fit_normalizer(tracks, fold['development'], config['transform'])
    train = normalized_subset(raw, fold['development'], normalizer)
    transformer, scaler, representation = fit_representation(train['x'], config, seed)
    classifier = fit_classifier(representation, train['y'], selection['c'], config, seed)
    model = RocketModel(transformer, scaler, classifier)
    training = {'participants': fold['development'], 'windows': len(train['y']), 'c': selection['c'],
                'classifier_iterations': int(classifier.n_iter_.max()),
                'representation_features': representation.shape[1],
                'train_auc': binary_metrics(train['y'], classifier.predict_proba(representation)[:, 1], .5)['roc_auc']}
    return model, normalizer, training


def save_bundle(directory, model, normalizer, training, feature_config, fold, seconds, selection, config, anchor):
    joblib.dump(model, directory/'model.joblib', compress=3)
    metadata = {'format_version': 1, 'model_type': 'MiniRocket', 'window_seconds': seconds,
                'timesteps': seconds*feature_config.sample_hz, 'sample_hz': feature_config.sample_hz,
                'feature_order': list(FEATURE_NAMES), 'feature_units': list(FEATURE_UNITS),
                'feature_definitions': list(FEATURE_DEFINITIONS), 'feature_config': asdict(feature_config),
                'preprocessing': feature_config.metadata(), 'normalizer': normalizer,
                'architecture': {'n_kernels': config['n_kernels'], 'actual_features': training['representation_features'],
                                 'classifier': 'L2 LogisticRegression', 'c': selection['c']},
                'threshold': selection['operating_point']['threshold'], 'operating_point': selection['operating_point'],
                'balanced_operating_point': selection['balanced_operating_point'],
                'training': training, 'splits': fold, 'comparison_anchor_steps': anchor,
                'stride_steps': round(config['outer_stride_seconds']*feature_config.sample_hz),
                'coordinate_quality': {'max_control_point_error_m': .5, 'metric_scale_verification_required': True},
                'versions': {name: version(name) for name in ('aeon', 'numpy', 'scikit-learn', 'numba', 'joblib')},
                'limitations': ['IDD 실험 조건 분류이며 실제 CCTV 탐지 정확도가 아님',
                                '외부 테스트 평가용 fold 모델; 5개 모델을 평균해 OOF로 평가하면 누출',
                                '내부 FPR 제한은 바깥 테스트/CCTV FPR을 보장하지 않음']}
    write_json(directory/'metadata.json', metadata)


def run_minirocket_cv(data_root, base, config, output):
    validate_config(config, base['feature']['sample_hz'])
    feature_config = replace(FeatureConfig(**base['feature']), smooth_points=config['smooth_points'])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write_json(output/'config.json', {'base': base, 'minirocket': config})
    write_json(output/'environment.json', {'python': platform.python_version(),
               'packages': {name: version(name) for name in ('aeon', 'numpy', 'pandas', 'scikit-learn', 'scipy', 'numba', 'joblib')}})
    root, manifest = build_manifest(data_root, base)
    manifest.to_csv(output/'scenario_manifest.csv', index=False, encoding='utf-8-sig')
    tracks, audit = prepare_tracks(root, manifest, feature_config)
    audit.to_csv(output/'data_audit.csv', index=False, encoding='utf-8-sig')
    participants = sorted({track.participant for track in tracks})
    folds = nested_participant_folds(participants, config['outer_folds'], config['inner_folds'], config['seed'])
    write_json(output/'folds.json', folds)
    anchor = max(base['window_seconds'])*feature_config.sample_hz+config['comparison_warmup_points']-feature_config.smooth_points
    outer_raw, inner_raw = {}, {}
    for seconds in base['window_seconds']:
        outer_raw[seconds] = make_windows(tracks, participants, seconds*feature_config.sample_hz,
                                         round(config['outer_stride_seconds']*feature_config.sample_hz), anchor)
        inner_raw[seconds] = make_windows(tracks, participants, seconds*feature_config.sample_hz,
                                         round(config['inner_stride_seconds']*feature_config.sample_hz), anchor)
    collected = {seconds: [] for seconds in base['window_seconds']}
    selected_lengths = []
    with threadpool_limits(limits=config['n_jobs']):
        for fold in folds:
            index = fold['fold']
            directory = output/f'fold_{index}'
            directory.mkdir()
            selections = {}
            for seconds in base['window_seconds']:
                print(f"바깥 {index}/{len(folds)} | {seconds}초 내부 선택", flush=True)
                model_directory = directory/f'{seconds}s'
                model_directory.mkdir()
                seed = config['seed']+index*100+seconds
                selections[seconds] = tune_regularization(tracks, inner_raw[seconds], fold, config,
                                                         model_directory, base['max_validation_fpr'], seed)
            selected_seconds = max(selections, key=lambda s: (selections[s]['participant_macro_auc'], -s))
            selected_lengths.append({'fold': index, 'seconds': selected_seconds})
            write_json(directory/'selection_before_test.json', {'selected_seconds': selected_seconds,
                       'selections': selections, 'test_scores_accessed': False})
            for seconds in base['window_seconds']:
                model_started = time.perf_counter()
                model_directory = directory/f'{seconds}s'
                selection = selections[seconds]
                model, normalizer, training = fit_outer_model(tracks, outer_raw[seconds], fold, config, selection,
                                                            config['seed']+index*100+seconds)
                save_bundle(model_directory, model, normalizer, training, feature_config, fold, seconds, selection, config, anchor)
                test = normalized_subset(outer_raw[seconds], fold['test'], normalizer)
                frame = prediction_frame(test, model.predict_scores(test['x']))
                frame = frame.assign(fold=index, seconds=seconds, threshold=selection['operating_point']['threshold'],
                                     balanced_threshold=selection['balanced_operating_point']['threshold'],
                                     selected_length=seconds == selected_seconds)
                frame.to_csv(model_directory/'test_predictions.csv', index=False)
                collected[seconds].append(frame)
                report = evaluate_oof(frame, 0, config['seed'])
                report['training'] = training
                report['seconds_elapsed'] = time.perf_counter()-model_started
                write_json(model_directory/'metrics.json', report)
                print(f"바깥 {index} | {seconds}초 테스트 AUC {report['window']['roc_auc']:.4f} | "
                      f"참가자 macro AUC {report['participant_macro']['roc_auc']:.4f}", flush=True)
                del model
                gc.collect()
    reports = {}
    selected_predictions = []
    for seconds, frames in collected.items():
        frame = pd.concat(frames, ignore_index=True)
        if frame.duplicated(['participant', 'scenario_id', 'end_ns']).any() or set(frame.participant) != set(participants):
            raise ValueError('바깥 OOF Window 중복 또는 참가자 누락입니다.')
        frame.to_csv(output/f'oof_{seconds}s.csv', index=False)
        selected_predictions.append(frame[frame.selected_length])
        reports[str(seconds)] = operating_reports(frame, config)
        write_json(output/f'metrics_{seconds}s.json', reports[str(seconds)])
    selected = pd.concat(selected_predictions, ignore_index=True)
    selected.to_csv(output/'oof_selected_length.csv', index=False)
    report = {'participants': participants, 'scenarios': len(tracks), 'windows_per_length': len(selected),
              'outer_folds': config['outer_folds'], 'inner_folds': config['inner_folds'],
              'results': reports, 'selected_lengths': selected_lengths,
              'selected_length_evaluation': operating_reports(selected, config),
              'elapsed_seconds': time.perf_counter()-started,
              'limitations': ['기존 test 참가자를 포함하는 반복 연구로 새로운 외부 검증은 아님',
                              '실제 CCTV 음주운전 탐지 성능을 의미하지 않음',
                              'pooled OOF AUC는 fold 사이 점수 눈금 차이의 영향을 받을 수 있음']}
    write_json(output/'report.json', report)
    rows = []
    for seconds, result in reports.items():
        for point, metrics in result.items():
            rows.append({'seconds': int(seconds), 'operating_point': point, **metrics['window'],
                         'participant_macro_auc': metrics['participant_macro']['roc_auc'],
                         'mean_fold_auc': metrics['mean_fold_auc']})
    pd.DataFrame(rows).to_csv(output/'comparison.csv', index=False, encoding='utf-8-sig')
    print(f"MiniRocket 참가자 {len(participants)}명 중첩 교차검증 완료: {output}", flush=True)
    return report


def operating_reports(frame, config):
    low_fpr = evaluate_oof(frame, config['bootstrap_repeats'], config['seed'])
    balanced = evaluate_oof(frame.assign(threshold=frame.balanced_threshold),
                            config['bootstrap_repeats'], config['seed'])
    return {'low_fpr': low_fpr, 'balanced': balanced}
