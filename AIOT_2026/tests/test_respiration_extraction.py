"""영상에서 30초 DeepPhys 추정 파형/BPM을 추출하는 배치를 검증한다."""
import tempfile
import unittest
import csv
import shutil
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pc import extract_respiration as e


class FakeExtractor:
    """모델 경계를 대체한다. 파일 탐색/배열 저장/캐시는 실제 실행."""
    receipt = {'checkpoint_sha256': 'test-checkpoint', 'preprocess': 'test-path'}

    def __init__(self):
        self.calls = []

    def predict_video(self, path, start):
        self.calls.append((str(path), start))
        wave = np.sin(2*np.pi*.5*np.arange(300)/10).astype(np.float32)
        return {'raw_model': wave, 'respiration': wave, 'fs': 10,
                'time_sec': np.arange(300)/10, 'x_10hz': wave, 'pred_rr_bpm': 30+start/10}


class RespirationExtractionTests(unittest.TestCase):
    def setUp(self):
        # OpenCV/DeepPhys are optional PC tools, not IDD package dependencies.
        # The real video decoder and checkpoint are checked in a separate smoke run.
        probe = patch.object(e, 'probe_video', return_value={'fps':10, 'frames':600})
        probe.start()
        self.addCleanup(probe.stop)

    def make_video(self, root):
        path = root/'data/AIR_400/S01/1.mp4'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'video decoder boundary fixture')
        return path

    def test_window_boundaries_and_optional_overlap(self):
        self.assertEqual(e.window_starts(600, 10, 30), [0, 30])
        self.assertEqual(e.window_starts(600, 10, 5), [0, 5, 10, 15, 20, 25, 30])
        self.assertEqual(e.window_starts(299, 10, 30), [])
        self.assertEqual(e.window_starts(599, 10, 30), [0])
        for stride in (0, -1, 2.5):
            with self.assertRaises(ValueError):
                e.window_starts(600, 10, stride)
        for fps in (9.997, 0, float('nan')):
            with self.assertRaises(ValueError):
                e.window_starts(600, fps, 30)

    def test_discovery_needs_no_labels_and_ignores_mac_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in ('AIR_125/S01/001.mp4', 'AIR_400/S01/001.mp4', '__MACOSX/._001.mp4'):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            videos = e.discover_videos(root)
            self.assertEqual(len(videos), 2)
            identities = [e.video_identity(v) for v in videos]
            self.assertEqual({i[1] for i in identities}, {'AIR_125:S01', 'AIR_400:S01'})
            self.assertEqual(len({i[0] for i in identities}), 2)
            self.assertEqual(e.discover_videos(videos[0]), [videos[0]])

    def test_custom_same_name_videos_do_not_overwrite_each_other(self):
        a, _ = e.video_identity(Path('camera_a/001.mp4').resolve())
        b, subject = e.video_identity(Path('camera_b/001.mp4').resolve())
        self.assertNotEqual(a, b)
        self.assertEqual(subject, '')

    def test_extracts_without_reviews_and_resumes_without_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = self.make_video(root)
            output = root/'output'
            model = FakeExtractor()
            result = e.extract(video, output, model, plots=False)
            self.assertEqual(result['windows'], 2)
            self.assertEqual(len(model.calls), 2)
            self.assertEqual(np.load(output/'X.npy').shape, (2,1,300))
            np.testing.assert_allclose(np.load(output/'bpm.npy'), [30,33])
            with (output/'metadata.csv').open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([r['start_sec'] for r in rows], ['0','30'])
            self.assertTrue(all(r['label_status']=='unreviewed' for r in rows))
            self.assertTrue(all(r['subject_id']=='AIR_400:S01' for r in rows))
            result = e.extract(video, output, model, plots=False)
            self.assertEqual(result['reused'], 2)
            self.assertEqual(len(model.calls), 2)

    def test_failed_window_is_not_saved_as_training_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = self.make_video(root)
            model = FakeExtractor()
            original_predict = model.predict_video
            def predict(path, start):
                result = original_predict(path, start)
                if start == 0:
                    result['x_10hz'] = np.full(300, np.nan)
                return result
            model.predict_video = predict
            report = e.extract(video, root/'output', model, plots=False)
            self.assertEqual(report['windows'], 1)
            self.assertEqual(len(report['errors']), 1)
            self.assertEqual(np.load(root/'output/X.npy').shape, (1,1,300))
            self.assertFalse(list((root/'output/windows').glob('*/*000000*.npz')))

    def test_resume_rejects_changed_model_and_changed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = self.make_video(root)
            model = FakeExtractor()
            e.extract(video, root/'output', model, plots=False)
            other = FakeExtractor()
            other.receipt = {'checkpoint_sha256':'different-checkpoint'}
            with self.assertRaises(ValueError):
                e.extract(video, root/'output', other, plots=False)
            with video.open('ab') as f:
                f.write(b'changed-source')
            with self.assertRaises(ValueError):
                e.extract(video, root/'output', model, plots=False)

    def test_incomplete_native_prediction_is_rejected(self):
        pred = FakeExtractor().predict_video(Path('video.mp4'),0)
        pred['respiration'] = pred['respiration'][:-1]
        with self.assertRaises(ValueError):
            e.validate_prediction(pred)

    def test_resume_rejects_a_cache_file_from_another_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = self.make_video(root)
            model = FakeExtractor()
            e.extract(video, root/'output', model, plots=False)
            folder = root/'output/windows/AIR_400_S01_1'
            shutil.copyfile(folder/'000000.npz', folder/'000030.npz')
            with self.assertRaises(ValueError):
                e.extract(video, root/'output', model, plots=False)


if __name__ == '__main__':
    unittest.main()
