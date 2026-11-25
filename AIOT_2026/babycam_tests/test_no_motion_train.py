import unittest
import json
import tempfile
from pathlib import Path

import numpy as np
import torch

from normal_pipeline.no_motion_train import freeze_teacher, preservation_metrics, train_epoch


class TrainTests(unittest.TestCase):
    def test_chunked_gradient_matches_full_sequence_mean(self):
        model = torch.nn.Linear(1, 1, bias=False)
        with torch.no_grad():
            model.weight.fill_(1.)
        cases = [dict(kind='breathing_candidate', inputs=np.array([[1.],[2.],[3.]], np.float32),
                      target_raw=np.array([1.,2.,3.], np.float32)),
                 dict(kind='static_real', inputs=np.array([[2.],[3.],[4.]], np.float32),
                      target_raw=np.zeros(3, np.float32))]
        opt = torch.optim.SGD(model.parameters(), lr=.01)
        train_epoch(model, cases, opt, torch.device('cpu'), 2, 1.)
        expected = 1.-.01*2.*(4.+9.+16.)/3.
        self.assertAlmostEqual(model.weight.item(), expected, places=6)

    def test_teacher_is_fixed_and_dropout_disabled(self):
        teacher = freeze_teacher(torch.nn.Sequential(torch.nn.Linear(2, 2), torch.nn.Dropout(.9)))
        self.assertFalse(teacher.training)
        self.assertTrue(all(not p.requires_grad for p in teacher.parameters()))
        x=torch.ones(2,2)
        self.assertTrue(torch.equal(teacher(x),teacher(x)))

    def test_metrics_detect_collapsed_breathing(self):
        reference = np.array([-1.,1.,-1.,1.])
        good = preservation_metrics(reference, reference)
        bad = preservation_metrics(np.zeros(4),reference)
        self.assertAlmostEqual(good['relative_mse'],0.)
        self.assertAlmostEqual(good['correlation'],1.)
        self.assertGreater(bad['relative_mse'],.1)
        self.assertIsNone(bad['correlation'])

    def test_incomplete_string_cache_is_not_accepted(self):
        from train_no_motion import load_caches
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'cache.json').write_text(json.dumps(dict(schema=1,complete='False')))
            with self.assertRaises(ValueError):
                load_caches([folder])


if __name__ == '__main__':
    unittest.main()
