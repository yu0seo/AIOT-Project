import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from normal_pipeline.respiration_bench import efficient_raw, summarize_decisions


class BenchTests(unittest.TestCase):
    def test_motion_only_report_renders_a_single_axis(self):
        from respiration_pipeline import render_case
        with tempfile.TemporaryDirectory() as folder:
            render_case(Path(folder),'motion-only',dict(motion_pixels=np.zeros(450),
                        background_velocity=np.zeros((449,2))))
            self.assertTrue((Path(folder)/'signals.png').is_file())

    def test_efficient_temporal_boundaries_are_explicit_and_all_450_samples_retained(self):
        class Difference(torch.nn.Module):
            def forward(self, x):
                return torch.diff(x[:,0,0,0]).reshape(-1,1)
        inputs = np.zeros((450,6,2,2), np.float32)
        inputs[:,0,0,0] = np.arange(450)
        result = efficient_raw(inputs, Difference().eval(), 'cpu')
        self.assertEqual(result.shape, (450,))
        expected=np.ones(450); expected[[179,359,449]]=0
        np.testing.assert_equal(result,expected)

    def test_incompatible_temporal_shape_and_training_mode_rejected(self):
        with self.assertRaises(ValueError):
            efficient_raw(np.zeros((449,6,2,2), np.float32), torch.nn.Identity().eval(), 'cpu')
        with self.assertRaises(ValueError):
            efficient_raw(np.zeros((450,6,2,2), np.float32), torch.nn.Identity(), 'cpu')

    def test_absence_duration_does_not_double_count_overlapping_windows_or_gaps(self):
        decisions = [dict(start_sec=0.,end_sec=10.,respiration_state='no_motion_detected'),
                     dict(start_sec=5.,end_sec=15.,respiration_state='no_motion_detected'),
                     dict(start_sec=10.,end_sec=20.,respiration_state='unassessable'),
                     dict(start_sec=15.,end_sec=25.,respiration_state='no_motion_detected')]
        result = summarize_decisions(decisions)
        self.assertEqual([d['absence_evidence_seconds'] for d in result], [10.,15.,None,10.])
        self.assertTrue(all(d['clinical_apnea'] is None for d in result))


if __name__ == '__main__':
    unittest.main()
