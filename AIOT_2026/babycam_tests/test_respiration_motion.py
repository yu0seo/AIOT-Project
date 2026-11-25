import unittest

import cv2
import numpy as np

from normal_pipeline.respiration_motion import motion_features


def scene(mode, n=120, fs=10, amplitude=1.5):
    rng = np.random.default_rng(81)
    image = cv2.GaussianBlur(rng.integers(20, 230, (96, 144), dtype=np.uint8), (3, 3), 0)
    frames = []
    for i in range(n):
        offset = amplitude * np.sin(2 * np.pi * .5 * i / fs)
        frame = image.copy()
        if mode == 'local':
            patch = image[24:72, 48:96]
            frame[24:72, 48:96] = cv2.warpAffine(patch, np.float32([[1, 0, 0], [0, 1, offset]]),
                                                (48, 48), borderMode=cv2.BORDER_REFLECT)
        elif mode == 'camera':
            frame = cv2.warpAffine(image, np.float32([[1, 0, 0], [0, 1, offset]]),
                                   (144, 96), borderMode=cv2.BORDER_REFLECT)
        frames.append(cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB))
    return np.stack(frames)


class MotionTests(unittest.TestCase):
    def test_local_periodic_motion_exceeds_background_compensated_camera(self):
        local = motion_features(scene('local'), [.3333, .25, .3333, .5], 10)
        camera = motion_features(scene('camera'), [.3333, .25, .3333, .5], 10)
        self.assertTrue(local['quality_ok'], local)
        self.assertFalse(camera['quality_ok'])
        self.assertIn('excessive_camera_motion',camera['quality_reasons'])
        self.assertGreater(local['amplitude_px'], .2)
        self.assertLess(camera['amplitude_px'], local['amplitude_px'] * .3)
        self.assertAlmostEqual(local['candidate_bpm'], 30, delta=4)

    def test_digital_freeze_and_textureless_are_unassessable(self):
        frozen = motion_features(scene('still'), [.3333, .25, .3333, .5], 10)
        blank = motion_features(np.full((120, 96, 144, 3), 80, np.uint8), [.3333, .25, .3333, .5], 10)
        self.assertFalse(frozen['quality_ok'])
        self.assertIn('frozen', frozen['quality_reasons'])
        self.assertFalse(blank['quality_ok'])
        self.assertIn('insufficient_texture', blank['quality_reasons'])

    def test_synthetic_subpixel_motion_is_retained_without_amplitude_normalization(self):
        weak=motion_features(scene('local',amplitude=.1), [.3333,.25,.3333,.5],10)
        strong=motion_features(scene('local',amplitude=1.5), [.3333,.25,.3333,.5],10)
        self.assertTrue(weak['quality_ok'])
        self.assertGreater(weak['amplitude_px'],.02)
        self.assertLess(weak['amplitude_px'],strong['amplitude_px']*.15)
        self.assertAlmostEqual(weak['candidate_bpm'],30,delta=4)

    def test_invalid_inputs_rejected(self):
        for frames, box, fs in [(np.zeros((4, 10, 10, 3)), [0, 0, .5, .5], 10),
                                (scene('local'), [0, 0, 1, 1], 10),
                                (scene('local'), [.3, .2, .3, .5], float('nan'))]:
            with self.assertRaises(ValueError):
                motion_features(frames, box, fs)


if __name__ == '__main__':
    unittest.main()
