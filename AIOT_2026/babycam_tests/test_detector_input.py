import unittest
from types import SimpleNamespace

import numpy as np

from normal_pipeline.detector_input import correct_detector_color,verify_roi_contract


class DetectorInputTests(unittest.TestCase):
    def test_only_detector_receives_bgr_and_original_video_remains_rgb(self):
        seen=[]
        class Detector:
            def __call__(self,frame,**kwargs):
                seen.append(frame.copy());return 'result'
        original=Detector()
        pre=SimpleNamespace(body_detector=original,face_detector=Detector())
        frames=np.array([[[255,70,10]]],dtype=np.float32)
        correct_detector_color(pre)
        self.assertEqual(pre.body_detector(frames),'result')
        np.testing.assert_equal(seen[0],np.array([[[10,70,255]]],np.uint8))
        np.testing.assert_equal(frames,np.array([[[255,70,10]]],np.float32))
        correct_detector_color(pre)
        pre.body_detector(frames)
        np.testing.assert_equal(seen[-1],seen[0])

    def test_ae_contract_rejects_a_different_detector_or_color_path(self):
        checkpoint=dict(feature_contract=dict(body_detector_sha256='new',detector_color_corrected=True))
        verify_roi_contract(checkpoint,'new',True)
        for body,color in [('old',True),('new',False),('new','False')]:
            with self.assertRaises(ValueError):
                verify_roi_contract(checkpoint,body,color)


if __name__=='__main__':
    unittest.main()
