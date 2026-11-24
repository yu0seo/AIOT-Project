"""인공 fixture로 같은 5-fold/Window 재사용과 전체 저장 흐름만 검증한다."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from idd_classifier.cli import load_config
from idd_classifier.data import Track, make_windows
from idd_classifier.experiment import prediction_frame
from idd_classifier.features import FeatureConfig, extract_segments
from idd_classifier.inception_cv import check_reference_windows, fit_inner_models, run_inception_cv
from idd_classifier.inference import VehiclePredictor
from idd_classifier.minirocket_cv import nested_participant_folds


class InceptionCVTests(unittest.TestCase):
    def test_rejects_wrong_fold_in_saved_prediction(self):
        raw = {'participant': np.array(['A', 'B']), 'scenario_id': np.array(['A/1', 'B/1']),
               'end_ns': np.array([100, 100]), 'y': np.array([0, 1]), 'fold': np.array([2, 1])}
        folds = [{'fold': 1, 'test': ['A']}, {'fold': 2, 'test': ['B']}]
        with tempfile.TemporaryDirectory(dir='.tmp') as tmp:
            path = Path(tmp)/'reference.csv'
            prediction_frame(raw, [.1, .9]).assign(fold=[1, 2]).to_csv(path, index=False)
            with self.assertRaises(ValueError): check_reference_windows(raw, folds, path)

    def test_same_folds_windows_and_saved_bundles(self):
        Path('.tmp').mkdir(exist_ok=True)
        base = load_config('configs/idd_lstm.json')
        rocket = json.loads(Path('configs/idd_minirocket.json').read_text(encoding='utf-8'))
        network = json.loads(Path('configs/idd_inceptiontime.json').read_text(encoding='utf-8'))
        network.update(filters=2, bottleneck=2, kernels=[9, 5, 3], epochs=1, patience=1,
                       batch_size=16, cpu_threads=2, bootstrap_repeats=0)
        participants = [f'fixture-{index}' for index in range(10)]
        folds = nested_participant_folds(participants, 5, 2, rocket['seed'])
        participant_fold = {p: fold['fold'] for fold in folds for p in fold['test']}
        times = np.arange(140, dtype=np.int64)*100_000_000
        t = times/1e9
        tracks = []
        for index, participant in enumerate(participants):
            for label in (0, 1):
                xy = np.column_stack(((3+label)*t+.1*np.sin(t+index), .1*np.cos(t)))
                segments, _ = extract_segments(times, xy, FeatureConfig(smooth_points=7))
                tracks.append(Track(participant, f'{participant}/{label}', label, segments))
        audit = pd.DataFrame({'scenario_id': [track.scenario_id for track in tracks],
                              'sha256': ['fixture-only']*len(tracks)})
        with tempfile.TemporaryDirectory(dir='.tmp') as tmp:
            root = Path(tmp)
            reference = root/'software_fixture_reference'
            reference.mkdir()
            (reference/'config.json').write_text(json.dumps({'base': base, 'minirocket': rocket}), encoding='utf-8')
            (reference/'folds.json').write_text(json.dumps(folds), encoding='utf-8')
            audit.to_csv(reference/'data_audit.csv', index=False)
            for seconds in (3, 5, 10):
                windows = make_windows(tracks, participants, seconds*10, 10, 114)
                frame = prediction_frame(windows, np.full(len(windows['y']), .5))
                frame.assign(fold=frame.participant.map(participant_fold), threshold=.5,
                             balanced_threshold=.5).to_csv(reference/f'oof_{seconds}s.csv', index=False)
            output = root/'software_fixture_result'
            with patch('idd_classifier.inception_cv.build_manifest', return_value=(root, pd.DataFrame())), \
                 patch('idd_classifier.inception_cv.prepare_tracks', return_value=(tracks, audit)), \
                 contextlib.redirect_stdout(io.StringIO()):
                report = run_inception_cv(root, network, reference, output, 'cpu')
            self.assertEqual(len(report['participants']), 10)
            self.assertEqual(json.loads((output/'folds.json').read_text()), folds)
            self.assertEqual(len(list(output.glob('fold_*/*s/model.pt'))), 15)
            inner_fit = json.loads((output/'fold_1/3s/inner_1/fit.json').read_text(encoding='utf-8'))
            self.assertEqual(inner_fit['train_windows'], 6*len(folds[0]['inner'][0]['train']))
            for seconds in (3, 5, 10):
                current = pd.read_csv(output/f'oof_{seconds}s.csv')
                previous = pd.read_csv(reference/f'oof_{seconds}s.csv')
                keys = ['participant', 'scenario_id', 'end_ns', 'label', 'fold']
                pd.testing.assert_frame_equal(current[keys].sort_values(keys).reset_index(drop=True),
                                              previous[keys].sort_values(keys).reset_index(drop=True))
            self.assertEqual(VehiclePredictor(output/'fold_1'/'3s').metadata['model_type'], 'InceptionTime')
            reuse_config = {**base, **network, 'model_type': 'InceptionTime', 'transform': 'signed_log1p',
                            'feature': {**base['feature'], 'smooth_points': 7}, 'seed': network['seed']+103}
            train_raw = make_windows(tracks, participants, 30, 10, 114)
            val_raw = make_windows(tracks, participants, 30, 30, 114)
            with patch('idd_classifier.inception_cv.train_model', side_effect=AssertionError('완료된 모델 재학습 금지')), \
                 contextlib.redirect_stdout(io.StringIO()):
                reused = fit_inner_models(tracks, train_raw, val_raw, folds[0], reuse_config,
                                          output/'fold_1/3s', 'cpu', resume=True)
            self.assertEqual(reused['refit_epochs'], 1)
            with self.assertRaises(FileExistsError): run_inception_cv(root, network, reference, output, 'cpu')
            with self.assertRaises(ValueError): run_inception_cv(root, network, reference, output, 'cpu', resume=True)


if __name__ == '__main__': unittest.main()
