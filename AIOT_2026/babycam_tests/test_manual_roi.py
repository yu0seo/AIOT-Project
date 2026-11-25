import unittest
import numpy as np

from normal_pipeline.manual_roi import manual_roi_override, roi_box
from normal_pipeline.no_motion import validate_records


class ManualRoiTests(unittest.TestCase):
    def test_normalized_box_scales_after_production_resize(self):
        np.testing.assert_allclose(roi_box([.3,.12,.4,.78],180,320),[96,21.6,128,140.4])

    def test_invalid_or_full_frame_boxes_are_rejected(self):
        for box in [[0,0,1,1],[-.1,0,.5,.5],[.8,.1,.5,.5],[0,0,0,.5],[0,float('nan'),.5,.5],[True,0,.5,.5]]:
            with self.assertRaises(ValueError):
                roi_box(box,180,320)

    def test_explicit_override_restores_auto_detector_even_on_failure(self):
        class Pre:
            def get_roi_box(self,frames):
                return 'auto',[]
        pre=Pre();trace=[]
        with self.assertRaisesRegex(RuntimeError,'test failure'):
            with manual_roi_override(pre,[.3,.12,.4,.78],trace.append):
                box,detections=pre.get_roi_box(np.zeros((2,180,320,3)))
                self.assertEqual(detections,[]) # Manual annotation is not a YOLO detection.
                np.testing.assert_allclose(box,trace[0])
                raise RuntimeError('test failure')
        self.assertEqual(pre.get_roi_box(None)[0],'auto')

    def test_manual_annotation_is_source_locked_and_not_normal_training(self):
        row=dict(id='fixture',group_id='STATIC:fixture',split='train',kind='static_real',
                 source='fixture.mp4',source_sha256='a'*64,start_sec=0,end_sec=30,
                 review=dict(approved=True,reviewer='tester',notes='controlled static test'),
                 manual_roi=dict(source_sha256='a'*64,box_xywh_normalized=[.3,.12,.4,.78],reason='YOLO failed on fixed doll'))
        validate_records([row],require_approved=True,verify_files=False)
        row['manual_roi']['source_sha256']='b'*64
        with self.assertRaises(ValueError):
            validate_records([row],require_approved=True,verify_files=False)
        row['manual_roi']['source_sha256']='a'*64;row['kind']='breathing_candidate'
        with self.assertRaises(ValueError):
            validate_records([row],require_approved=True,verify_files=False)


if __name__=='__main__':
    unittest.main()
