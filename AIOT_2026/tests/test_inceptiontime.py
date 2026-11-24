"""소형 InceptionTime의 네 피처 계약, 학습과 저장/온라인 추론을 검증한다."""
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from idd_classifier.features import FEATURE_NAMES, FeatureConfig, extract_segments
from idd_classifier.inception import SmallInceptionTime
from idd_classifier.inception_cv import select_refit_epochs
from idd_classifier.inference import CoordinateQuality, VehiclePredictor
from idd_classifier.model import create_model, model_architecture, predict_scores


class InceptionTimeTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        Path('.tmp').mkdir(exist_ok=True)

    def test_four_features_three_lengths_and_gradients(self):
        model = SmallInceptionTime()
        self.assertLess(sum(p.numel() for p in model.parameters()), 60000)
        for steps in (30, 50, 100):
            model.zero_grad(set_to_none=True)
            logits = model(torch.randn(3, steps, 4))
            self.assertEqual(logits.shape, (3,))
            torch.nn.functional.binary_cross_entropy_with_logits(logits, torch.tensor([0., 1., 0.])).backward()
            self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters()))
        with self.assertRaises(ValueError): model(torch.zeros(3, 30, 5))

    def test_invalid_architecture_and_refit_epoch_selection(self):
        for kwargs in ({'depth': 2}, {'filters': 0}, {'bottleneck': 0}, {'kernels': [40, 20, 10]}, {'dropout': 1.}):
            with self.assertRaises(ValueError): SmallInceptionTime(**kwargs)
        self.assertEqual(select_refit_epochs([2, 7, 4]), 4)
        with self.assertRaises(ValueError): select_refit_epochs([0, 4, 5])

    def test_saved_network_matches_coordinate_stream(self):
        config = json.loads(Path('configs/idd_inceptiontime.json').read_text(encoding='utf-8'))
        architecture = model_architecture({**config, 'model_type': 'InceptionTime'})
        model = create_model('InceptionTime', architecture).eval()
        feature_config = FeatureConfig(smooth_points=7)
        times = np.arange(150, dtype=np.int64)*100_000_000
        t = times/1e9
        xy = np.column_stack((4*t+.1*np.sin(t), .3*np.cos(t)))
        segments, _ = extract_segments(times, xy, feature_config)
        expected = float(predict_scores(model, segments[0].values[-30:][None].astype(np.float32))[0])
        with tempfile.TemporaryDirectory(dir='.tmp') as tmp:
            directory = Path(tmp)
            torch.save(model.state_dict(), directory/'model.pt')
            metadata = {'format_version': 1, 'model_type': 'InceptionTime', 'window_seconds': 3,
                        'timesteps': 30, 'sample_hz': 10, 'feature_order': list(FEATURE_NAMES),
                        'feature_config': asdict(feature_config), 'threshold': .5, 'architecture': architecture,
                        'normalizer': {'mean': [0]*4, 'std': [1]*4, 'transform': 'identity'},
                        'coordinate_quality': {'max_control_point_error_m': .5}}
            (directory/'metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
            predictor = VehiclePredictor(directory)
            quality = CoordinateQuality(True, 0., True, True, 'fixture')
            for stamp, point in zip(times, xy):
                result = predictor.update('car', int(stamp), *point, quality=quality)
            self.assertEqual(result['status'], 'ok')
            self.assertAlmostEqual(result['score'], expected, places=6)


if __name__ == '__main__': unittest.main()
