"""모델 번들과 품질 검사, 초기화, 동일 전처리 경로를 검증한다."""
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from idd_classifier.features import FeatureConfig, FEATURE_NAMES, extract_segments
from idd_classifier.inference import CoordinateQuality, VehiclePredictor, homography_to_road
from idd_classifier.model import DrivingLSTM, predict_scores


class InferenceTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        Path('.tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir='.tmp')
        self.bundle = Path(self.temp.name)
        self.model = DrivingLSTM(8, 1, 0).eval()
        torch.save(self.model.state_dict(), self.bundle/'model.pt')
        metadata = {'format_version': 1, 'model_type': 'LSTM', 'feature_order': list(FEATURE_NAMES),
                    'feature_config': asdict(FeatureConfig()), 'timesteps': 30, 'window_seconds': 3, 'sample_hz': 10,
                    'normalizer': {'mean': [0]*4, 'std': [1]*4},
                    'architecture': {'hidden_size': 8, 'num_layers': 1, 'dropout': 0}, 'threshold': .5,
                    'coordinate_quality': {'max_control_point_error_m': .5}}
        (self.bundle/'metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
        self.good = CoordinateQuality(metric_scale_verified=True, control_point_error_m=.1,
                                      within_road_roi=True, tracking_ok=True, calibration_id='camera-A-v1')

    def tearDown(self):
        self.temp.cleanup()

    def test_offline_online_scores_match(self):
        predictor = VehiclePredictor(self.bundle)
        ts = np.arange(60, dtype=np.int64)*100_000_000
        xy = np.column_stack([ts/1e9*5, np.zeros(60)])
        segments, _ = extract_segments(ts, xy, FeatureConfig())
        expected = predict_scores(self.model, segments[0].values[-30:][None].astype(np.float32))[0]
        for t, p in zip(ts, xy):
            result = predictor.update('vehicle-1', int(t), *p, quality=self.good)
        self.assertEqual(result['status'], 'ok')
        self.assertAlmostEqual(result['score'], float(expected), places=6)
        self.assertEqual(result['feature_timestamp_ns'], int(ts[-1]))

    def test_bad_quality_gap_and_calibration_change_clear_window(self):
        predictor = VehiclePredictor(self.bundle)
        for i in range(50):
            predictor.update('a', i*100_000_000, i*.5, 0, quality=self.good)
        result = predictor.update('a', 5_000_000_000, 25, 0, quality=CoordinateQuality())
        self.assertEqual(result['status'], 'abstain')
        self.assertIsNone(result['score'])
        result = predictor.update('a', 5_100_000_000, 25.5, 0, quality=self.good)
        self.assertEqual(result['status'], 'warming_up')
        result = predictor.update('a', 7_000_000_000, 35, 0, quality=self.good)
        self.assertNotEqual(result['status'], 'ok')
        changed = CoordinateQuality(True, .1, True, True, 'camera-A-v2')
        result = predictor.update('a', 7_100_000_000, 35.5, 0, quality=changed)
        self.assertEqual(result['status'], 'warming_up')
        predictor.drop_track('a')
        self.assertNotIn('a', predictor.tracks)

    def test_duplicate_timestamp_abstains_and_invalid_metadata_rejected(self):
        predictor = VehiclePredictor(self.bundle)
        predictor.update('a', 0, 0, 0, quality=self.good)
        result = predictor.update('a', 0, 0, 0, quality=self.good)
        self.assertEqual(result['status'], 'abstain')
        path = self.bundle/'metadata.json'
        metadata = json.loads(path.read_text(encoding='utf-8'))
        metadata['feature_order'].reverse()
        path.write_text(json.dumps(metadata), encoding='utf-8')
        with self.assertRaises(ValueError): VehiclePredictor(self.bundle)

    def test_homography_numeric_and_quality_checks(self):
        np.testing.assert_allclose(homography_to_road(np.diag([.1, .1, 1]), 100, 200), [10, 20])
        with self.assertRaises(ValueError): homography_to_road(np.zeros((3, 3)), 1, 2)
        for error in (.6, -1, float('nan'), 'unknown'):
            quality = CoordinateQuality(True, error, True, True, 'camera-A-v1')
            result = VehiclePredictor(self.bundle).update('a', 0, 0, 0, quality=quality)
            self.assertEqual(result['status'], 'abstain')
            self.assertIsNone(result['score'])


if __name__ == '__main__': unittest.main()
