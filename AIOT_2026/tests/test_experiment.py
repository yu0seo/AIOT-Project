"""인공 생성 fixture로 파일 저장/재로딩만 검증한다. 성능 실험이 아니다."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from idd_classifier.cli import load_config
from idd_classifier.data import SCENARIO_CODES
from idd_classifier.experiment import run_experiment
from idd_classifier.inference import VehiclePredictor
from idd_classifier.improvement import finalize_search
from idd_classifier.tuning import run_search


class ExperimentTests(unittest.TestCase):
    def test_complete_three_length_pipeline_with_synthetic_fixture(self):
        Path('.tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='.tmp') as tmp:
            root = Path(tmp)/'fixture'
            root.mkdir()
            annotation = [['']*65 for _ in range(8)]
            annotation[0][57] = 'Alcohol'
            annotation[1][1:9] = SCENARIO_CODES
            annotation[1][57:65] = SCENARIO_CODES
            for index in range(6):
                participant = f'P{800+index}'
                annotation[2+index][0] = participant
                annotation[2+index][57] = '1'
                rows = []
                for label, (round_name, code) in enumerate([('R1', '3c'), ('R2', '1a')]):
                    name = f'driving/{code}-fixture'
                    scenario_path = f'{round_name}/{name}/no_task'
                    rows.append({'scenario_index': label, 'scenario_name': name, 'scenario_path': scenario_path,
                                 'round': round_name, 'cognitive_task': 'no_task', 'start_time': 0,
                                 'end_time': 14_000_000_000, 'duration_s': 14, 'duration_frames': 140})
                    path = root/'Resampled_previous_10_derived'/'Participants'/participant/scenario_path
                    path.mkdir(parents=True)
                    seconds = np.arange(140)/10
                    pd.DataFrame({'resampled_epoch_ns': np.arange(140)*100_000_000,
                                  'carla_objects_pose_x': seconds*(3+label),
                                  'carla_objects_pose_y': seconds*0}).to_csv(path/'ego_tracks.csv', index=False)
                directory = root/'Resampled_previous_10'/'Participants'/participant
                directory.mkdir(parents=True)
                pd.DataFrame(rows).to_csv(directory/'scenario_index.csv', index=False)
            with (root/'idd_annotation.csv').open('w', encoding='utf-8', newline='') as stream:
                csv.writer(stream).writerows(annotation)
            config = load_config('configs/idd_lstm.json')
            config.update(epochs=1, patience=1, batch_size=16, hidden_size=8, cpu_threads=2, bootstrap_repeats=0)
            output = Path(tmp)/'software_test_results'
            with contextlib.redirect_stdout(io.StringIO()):
                report = run_experiment(root, config, output)
            self.assertEqual(len(report['results']), 3)
            predictor = VehiclePredictor(output/'best')
            self.assertIn(predictor.metadata['window_seconds'], [3, 5, 10])
            for seconds in [3, 5, 10]:
                with np.load(output/f'{seconds}s'/'test_windows.npz', allow_pickle=False) as windows:
                    self.assertEqual(windows['x'].shape[-2:], (seconds*10, 4))
                self.assertTrue((output/f'{seconds}s'/'metrics.json').is_file())
            splits = json.loads((output/'splits.json').read_text(encoding='utf-8'))
            self.assertFalse(set(splits['train']) & set(splits['test']))
            with self.assertRaises(FileExistsError): run_experiment(root, config, output)
            search = {'folds': 2, 'seed': 42, 'stride_seconds': 3, 'epochs': 1, 'patience': 1,
                      'checkpoint_metric': 'macro_auc', 'candidates': [
                          {'name': 'fixture_lstm', 'model_type': 'LSTM', 'hidden_size': 8, 'num_layers': 1,
                           'pooling': 'statistics', 'dropout': .1, 'weight_decay': .001,
                           'transform': 'signed_log1p', 'smooth_points': 11}]}
            search_output = Path(tmp)/'software_search_results'
            with contextlib.redirect_stdout(io.StringIO()):
                selection = run_search(root, config, search, output, search_output)
                improved = finalize_search(root, search_output, output)
            self.assertFalse(selection['test_accessed'])
            self.assertEqual(len(improved['results']), 3)
            predictor = VehiclePredictor(search_output/'final'/'best')
            self.assertEqual(predictor.metadata['normalizer']['transform'], 'signed_log1p')


if __name__ == '__main__': unittest.main()
