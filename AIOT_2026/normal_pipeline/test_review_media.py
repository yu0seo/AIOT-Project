import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

import review_media as r
import pipeline as p


class ReviewMediaTests(unittest.TestCase):
    @patch('review_media.find_ffmpeg',return_value=None)
    def test_browser_preview_keeps_original_bytes_and_timing(self, unused_backend):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / 'source.mp4'
            writer = cv2.VideoWriter(str(original), cv2.VideoWriter_fourcc(*'mp4v'), 15, (64,48))
            self.assertTrue(writer.isOpened())
            for i in range(30):
                writer.write(np.full((48,64,3), i*5, dtype=np.uint8))
            writer.release()
            before = hashlib.sha256(original.read_bytes()).hexdigest()
            media = r.prepare_media({'id':'AIR_125_S01_001','video':str(original),'video_sha256':before}, root/'review')
            self.assertTrue(media['converted'])
            self.assertEqual(media['mime'], 'video/webm')
            preview = root/'review'/media['src']
            cap = cv2.VideoCapture(str(preview))
            self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 30)
            self.assertEqual(cap.get(cv2.CAP_PROP_FPS), 15)
            cap.release()
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), before)
            self.assertEqual(r.prepare_media({'id':'AIR_125_S01_001','video':str(original),'video_sha256':before}, root/'review'), media)

    def test_review_distinguishes_annotations_from_model_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            clip={'id':'AIR_125_S01_001','video':str(root/'video.mp4'),'duration':60,
                  'label_time_mode':'duration_mapped_requires_alignment_review'}
            r.write_page(clip, root, {'src':'media/preview.webm','mime':'video/webm','poster':'media/poster.jpg','converted':True})
            page=(root/'AIR_125_S01_001.html').read_text(encoding='utf-8')
            self.assertIn('preload="metadata"',page)
            self.assertIn('media/preview.webm',page)
            self.assertIn('호흡 시점 주석',page)
            self.assertIn('DeepPhys 추정 파형',page)
            self.assertIn('아직 이 영상의 추론 결과를 생성하지 않았습니다',page)

    def test_new_scan_automatically_creates_a_browser_compatible_review(self):
        import h5py
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            subject=root/'AIR_125'/'S01'
            subject.mkdir(parents=True)
            original=subject/'001.mp4'
            writer=cv2.VideoWriter(str(original),cv2.VideoWriter_fourcc(*'mp4v'),10,(64,48))
            for i in range(300):
                writer.write(np.full((48,64,3),i%255,dtype=np.uint8))
            writer.release()
            with h5py.File(subject/'001.hdf5','w') as f:
                f['respiration']=np.sin(np.arange(300)/10)
            args=SimpleNamespace(air125=root/'AIR_125',air400=None,out=root/'workdir',label_key='respiration',
                                 time_key=None,label_fs=None,refresh_unreviewed=False)
            p.scan(args)
            page=(args.out/'review/AIR_125_S01_001.html').read_text(encoding='utf-8')
            self.assertIn('media/AIR_125_S01_001.',page)
            self.assertEqual(p.load_json(args.out/'approvals.json')['approvals'],{})
            self.assertEqual(p.load_json(args.out/'manifest.json')['clips'][0]['status'],'pending_review')

    def test_another_videos_prediction_cannot_be_displayed_as_this_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip={'id':'AIR_125_S01_001','video_sha256':'this-video'}
            with self.assertRaisesRegex(ValueError,'Prediction does not belong'):
                r.write_page(clip,Path(tmp),{},prediction={'video_sha256':'another-video'})


if __name__=='__main__':
    unittest.main()
