import unittest
from types import SimpleNamespace

import numpy as np
import torch

from normal_pipeline.no_motion_cache import encode_inputs, frozen_frames, raw_prediction


class CacheTests(unittest.TestCase):
    def test_frozen_frames_have_no_observed_temporal_change(self):
        frames = np.arange(450*2*2*3, dtype=np.float32).reshape(450, 2, 2, 3)
        frozen = frozen_frames(frames)
        self.assertEqual(frozen.shape, frames.shape)
        self.assertTrue(np.all(frozen == frames[0]))
        self.assertFalse(np.shares_memory(frames, frozen))

    def test_short_video_rejected(self):
        with self.assertRaises(ValueError):
            frozen_frames(np.zeros((449, 2, 2, 3)))

    def test_same_preprocessor_channels_and_temporal_order(self):
        clips = np.broadcast_to(np.arange(450, dtype=np.float32)[None, :, None, None, None],
                                (1, 450, 2, 2, 6)).copy()
        runner = SimpleNamespace(pre=SimpleNamespace(preprocess=lambda frames, labels, fs: (clips, None)))
        result = encode_inputs(np.zeros((450, 2, 2, 3)), runner)
        self.assertEqual(result.shape, (450, 6, 2, 2))
        np.testing.assert_equal(result[:, 0, 0, 0], np.arange(450))

    def test_bad_preprocessing_and_roi_failure_propagate(self):
        def fail(*args):
            raise ValueError('ROI missing')
        with self.assertRaisesRegex(ValueError, 'ROI missing'):
            encode_inputs(np.zeros((450, 2, 2, 3)), SimpleNamespace(pre=SimpleNamespace(preprocess=fail)))
        runner = SimpleNamespace(pre=SimpleNamespace(preprocess=lambda *args: (np.zeros((1, 449, 2, 2, 6)), None)))
        with self.assertRaises(ValueError):
            encode_inputs(np.zeros((450, 2, 2, 3)), runner)

    def test_constant_teacher_output_is_valid_for_static_control(self):
        class Model(torch.nn.Module):
            def forward(self, x):
                return x[:, 0, 0, 0, None]
        runner = SimpleNamespace(model=Model().eval(), device='cpu', batch_size=16)
        result = raw_prediction(np.ones((450, 6, 2, 2), dtype=np.float32), runner)
        np.testing.assert_equal(result, np.ones(450))
        self.assertFalse(runner.model.training)


if __name__ == '__main__':
    unittest.main()
