"""MiniRocket 축, 저장/추론, 참가자 분리와 fold별 임계값을 검증한다."""
import contextlib
import io
import json
import tempfile
import unittest
import warnings
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from idd_classifier.features import FEATURE_NAMES, FeatureConfig, extract_segments
from idd_classifier.cli import load_config
from idd_classifier.data import Track
from idd_classifier.inference import CoordinateQuality, VehiclePredictor
from idd_classifier.minirocket_cv import evaluate_oof, nested_participant_folds, run_minirocket_cv, validate_config
from idd_classifier.rocket_model import RocketModel, as_channels_first, fit_classifier, fit_representation


class MiniRocketTests(unittest.TestCase):
    def setUp(self):
        Path('.tmp').mkdir(exist_ok=True)

    def test_axis_and_input_validation(self):
        values = np.arange(2*30*4).reshape(2, 30, 4)
        transformed = as_channels_first(values)
        self.assertEqual(transformed.shape, (2, 4, 30))
        np.testing.assert_array_equal(transformed[1, 2], values[1, :, 2])
        for invalid in (np.zeros((2, 8, 4)), np.zeros((2, 30, 5)), np.full((2, 30, 4), np.nan)):
            with self.assertRaises(ValueError): as_channels_first(invalid)

    def test_nested_folds_cover_twenty_once(self):
        participants = [f'P{i}' for i in range(20)]
        folds = nested_participant_folds(participants, 5, 3, 42)
        tested = []
        for fold in folds:
            self.assertEqual(len(fold['test']), 4)
            self.assertEqual(len(fold['development']), 16)
            tested.extend(fold['test'])
            validated = []
            for inner in fold['inner']:
                self.assertFalse(set(inner['train']) & set(inner['validation']))
                self.assertEqual(set(inner['train']) | set(inner['validation']), set(fold['development']))
                self.assertFalse(set(inner['train']+inner['validation']) & set(fold['test']))
                validated.extend(inner['validation'])
            self.assertEqual(sorted(validated), sorted(fold['development']))
        self.assertEqual(sorted(tested), sorted(participants))

    def test_fold_thresholds_are_not_retuned_on_oof(self):
        frame = pd.DataFrame({'participant': ['A', 'A', 'B', 'B'], 'fold': [1, 1, 2, 2],
                              'label': [0, 1, 0, 1], 'score': [.6, .8, .2, .4],
                              'threshold': [.7, .7, .1, .1]})
        report = evaluate_oof(frame, bootstrap_repeats=20, seed=42)
        self.assertEqual(report['window']['accuracy'], .75)
        self.assertEqual(report['window']['fpr'], .5)
        self.assertEqual(report['window']['recall'], 1.)
        self.assertEqual(report['window']['roc_auc'], .75)
        self.assertEqual(report['participant_macro']['roc_auc'], 1.)
        self.assertEqual(report['window']['confusion_matrix'], [[1, 1], [0, 2]])
        duplicate = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
        duplicate.loc[len(duplicate)-1, 'fold'] = 3
        with self.assertRaises(ValueError): evaluate_oof(duplicate, 0, 42)

    def test_invalid_search_configuration(self):
        config = json.loads(Path('configs/idd_minirocket.json').read_text(encoding='utf-8'))
        for changes in ({'regularization_c': []}, {'n_kernels': 1}, {'n_jobs': 0},
                        {'comparison_warmup_points': 2}, {'outer_folds': 1}):
            with self.assertRaises(ValueError): validate_config({**config, **changes}, 10)

    def test_single_class_metrics_remain_undefined_without_warnings(self):
        frame = pd.DataFrame({'participant': ['A', 'A', 'B', 'B'], 'fold': [1, 1, 2, 2],
                              'label': [0, 0, 0, 0], 'score': [.1, .3, .2, .6], 'threshold': [.5]*4})
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            report = evaluate_oof(frame, bootstrap_repeats=5, seed=42)
        self.assertIsNone(report['participant_macro']['roc_auc'])
        self.assertIsNone(report['participant_macro']['recall'])
        self.assertIsNone(report['participant_macro_auc_95ci'])
        self.assertIsNone(report['mean_fold_auc'])

    def test_correlated_positive_representation_converges(self):
        config = json.loads(Path('configs/idd_minirocket.json').read_text(encoding='utf-8'))
        config['classifier_max_iter'] = 100
        representation = 20+np.random.default_rng(42).normal(size=(100, 1000))
        labels = np.arange(100) % 2
        classifier = fit_classifier(representation, labels, 1., config, 42)
        self.assertLess(classifier.n_iter_.max(), 100)
        self.assertGreater(classifier.score(representation, labels), .95)

    def test_fitted_representation_is_fixed_and_matches_online_reload(self):
        config = json.loads(Path('configs/idd_minirocket.json').read_text(encoding='utf-8'))
        config.update(n_kernels=168, n_jobs=2)
        feature_config = FeatureConfig(smooth_points=7)
        seconds = np.arange(150)/10
        timestamps = np.arange(150, dtype=np.int64)*100_000_000
        xy = np.column_stack((4*seconds+.1*np.sin(seconds), .2*np.sin(seconds*.7)))
        segments, _ = extract_segments(timestamps, xy, feature_config)
        features = segments[0].values
        windows = np.stack([features[i:i+30] for i in range(50)])
        transformer, scaler, representation = fit_representation(windows[:40], config, 42)
        before = scaler.scale_.copy()
        classifier = fit_classifier(representation, np.arange(40) % 2, .01, config, 42)
        model = RocketModel(transformer, scaler, classifier)
        first = model.predict_scores(windows[40:])
        model.predict_scores(windows[40:]*100)
        np.testing.assert_array_equal(scaler.scale_, before)
        np.testing.assert_array_equal(first, model.predict_scores(windows[40:]))
        with tempfile.TemporaryDirectory(dir='.tmp') as tmp:
            directory = Path(tmp)
            metadata = {'format_version': 1, 'model_type': 'MiniRocket', 'window_seconds': 3,
                        'timesteps': 30, 'sample_hz': 10, 'feature_order': list(FEATURE_NAMES),
                        'feature_config': asdict(feature_config), 'threshold': .5,
                        'normalizer': {'mean': [0]*4, 'std': [1]*4, 'transform': 'identity'},
                        'coordinate_quality': {'max_control_point_error_m': .5}}
            (directory/'metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
            joblib.dump(model, directory/'model.joblib')
            predictor = VehiclePredictor(directory)
            quality = CoordinateQuality(True, 0., True, True, 'fixture')
            for stamp, point in zip(timestamps, xy):
                result = predictor.update('vehicle', int(stamp), *point, quality=quality)
            self.assertEqual(result['status'], 'ok')
            expected = model.predict_scores(features[-30:][None])[0]
            self.assertAlmostEqual(result['score'], expected, places=12)
            self.assertEqual(predictor.update('vehicle', int(timestamps[-1]), *xy[-1])['status'], 'abstain')

    def test_nested_runner_persists_all_oof_and_fifteen_bundles(self):
        """작은 인공 fixture로 전체 저장 흐름만 검증하며 실제 성능을 측정하지 않는다."""
        base = load_config('configs/idd_lstm.json')
        config = json.loads(Path('configs/idd_minirocket.json').read_text(encoding='utf-8'))
        config.update(n_kernels=84, n_jobs=1, inner_folds=2, regularization_c=[.001, .01], bootstrap_repeats=0)
        tracks = []
        timestamps = np.arange(140, dtype=np.int64)*100_000_000
        t = timestamps/1e9
        for participant_index in range(10):
            participant = f'fixture-{participant_index}'
            for label in (0, 1):
                xy = np.column_stack((t*(3+label)+.1*np.sin(t+participant_index), .1*np.cos(t)))
                segments, _ = extract_segments(timestamps, xy, FeatureConfig(smooth_points=7))
                tracks.append(Track(participant, f'{participant}/{label}', label, segments))
        with tempfile.TemporaryDirectory(dir='.tmp') as tmp:
            directory = Path(tmp)/'software_test'
            with patch('idd_classifier.minirocket_cv.build_manifest', return_value=(Path(tmp), pd.DataFrame())), \
                 patch('idd_classifier.minirocket_cv.prepare_tracks', return_value=(tracks, pd.DataFrame())), \
                 contextlib.redirect_stdout(io.StringIO()):
                report = run_minirocket_cv(tmp, base, config, directory)
            self.assertEqual(len(report['participants']), 10)
            self.assertEqual(len(list(directory.glob('fold_*/*s/model.joblib'))), 15)
            for seconds in (3, 5, 10):
                frame = pd.read_csv(directory/f'oof_{seconds}s.csv')
                self.assertEqual(frame.participant.nunique(), 10)
                self.assertTrue((frame.groupby('participant').fold.nunique() == 1).all())
                self.assertFalse(frame.duplicated(['participant', 'scenario_id', 'end_ns']).any())
                self.assertEqual(len(frame), report['windows_per_length'])
            self.assertEqual(len(pd.read_csv(directory/'oof_selected_length.csv')), report['windows_per_length'])
            self.assertEqual(VehiclePredictor(directory/'fold_1'/'3s').metadata['model_type'], 'MiniRocket')


if __name__ == '__main__': unittest.main()
