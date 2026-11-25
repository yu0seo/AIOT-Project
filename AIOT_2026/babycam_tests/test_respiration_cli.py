import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import respiration_pipeline as pipeline


class CliFailureTests(unittest.TestCase):
    def test_short_video_and_roi_failure_keep_null_decisions_in_saved_results(self):
        for count in (449,450):
            with self.subTest(count=count),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);output=root/'out';output.mkdir()
                calibration=root/'calibration.json'
                with patch.object(pipeline,'sha256',return_value='hash'):
                    calibration.write_text(json.dumps(dict(feature_hashes=pipeline.feature_hashes(),
                        decision_source_sha256='hash',detector_color_corrected=False,
                        roi_mode='automatic',development_usable=False,production_ready=False)))
                    def missing_roi(frames):
                        raise ValueError('ROI missing')
                    model=SimpleNamespace(device='cpu',pre=SimpleNamespace(get_roi_box=missing_roi))
                    existing=SimpleNamespace(AnomalyV2=lambda *a:None,InvalidWindow=ValueError,
                                             frame_windows=lambda *a:((n,f) for n,f in [(count,None if count<450 else object())]))
                    args=SimpleNamespace(input=root/'video.mp4',calibration=calibration,output=output,
                                         body_detector=None,correct_detector_color=False,
                                         ae_checkpoint=root/'ae.pt',allow_development_calibration=False,max_windows=None)
                    checkpoint=dict(feature_contract=dict(body_detector_sha256='hash',detector_color_corrected=False))
                    with patch.object(pipeline,'context',return_value=(SimpleNamespace(ffmpeg='unused'),existing,{})), \
                         patch.object(pipeline,'runner',return_value=model), \
                         patch.object(pipeline.torch,'load',return_value=checkpoint):
                        pipeline.video(args)
                row=json.loads((output/'comparison.json').read_text(encoding='utf8'))['records'][0]
                self.assertEqual(row['status'],'unscored')
                self.assertEqual(row['respiration_state'],'unassessable')
                for name in ('anomaly_score','is_anomaly','pred_rr_bpm','movement_absence_candidate','clinical_apnea'):
                    self.assertIsNone(row[name])
                self.assertTrue(row['reason'])


if __name__=='__main__':
    unittest.main()
