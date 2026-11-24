import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

import pipeline as p


class PipelineTests(unittest.TestCase):
    def test_dataset_namespaces_and_label_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('AIR_125', 'AIR_400'):
                sub = root / name / 'S01'
                sub.mkdir(parents=True)
                (sub / '001.mp4').touch()
                labels = sub if name == 'AIR_125' else sub / 'out'
                labels.mkdir(exist_ok=True)
                (labels / '001.hdf5').touch()
            clips = p.discover(root / 'AIR_125', root / 'AIR_400')
            self.assertEqual({x['subject'] for x in clips}, {'AIR_125:S01', 'AIR_400:S01'})
            self.assertTrue(clips[1]['label'].endswith('out/001.hdf5'))

    def test_only_complete_approved_windows(self):
        self.assertEqual(p.window_starts(60, [(0, 60)]), [0, 5, 10, 15, 20, 25, 30])
        self.assertEqual(p.window_starts(29.99, [(0, 29.99)]), [])
        self.assertEqual(p.window_starts(60, [(3, 34)]), [])
        self.assertEqual(p.window_starts(60, [(0, 20), (20, 60)]), [20, 25, 30])

    def test_polyphase_preserves_seconds_and_rejects_short_output(self):
        signal = np.sin(2 * np.pi * .5 * np.arange(900) / 30)
        actual = p.to_10hz(signal, 30)
        self.assertEqual(actual.shape, (300,))
        np.testing.assert_allclose(actual[15:-15], np.sin(2*np.pi*.5*np.arange(300)[15:-15]/10), atol=.003)
        with self.assertRaises(ValueError):
            p.to_10hz(signal[:899], 30)
        with self.assertRaises(ValueError):
            p.to_10hz(np.full(900, np.nan), 30)

    def test_split_is_subject_wise_and_reproducible(self):
        subjects = ['AIR_125:S01', 'AIR_400:S01', 'AIR_400:S02', 'AIR_400:S03']
        a = p.subject_split(subjects, 7)
        self.assertEqual(a, p.subject_split(subjects[::-1], 7))
        self.assertEqual(set(a), set(subjects))
        self.assertEqual(set(a.values()), {'train', 'val', 'test'})
        with self.assertRaises(ValueError):
            p.subject_split(subjects[:2], 7)

    def test_train_statistics_ignore_validation(self):
        train = np.array([[[1, 2, 3]]], dtype=np.float32)
        stats = p.fit_scaler(train)
        np.testing.assert_allclose(p.normalize(train, stats).mean(), 0, atol=1e-6)
        self.assertEqual(stats['mean'], 2)
        self.assertGreater(p.normalize(np.full((1,1,3), 1000), stats).mean(), 100)

    def test_labels_use_actual_key_and_no_fake_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'label.hdf5'
            with h5py.File(path, 'w') as f:
                f['respiration'] = np.arange(60).reshape(-1, 1)
            t, y, mode, keys = p.read_label(path, 60)
            self.assertEqual(mode, 'duration_mapped_requires_alignment_review')
            self.assertEqual(y.shape, (60,))
            self.assertIn('respiration', keys)
            with self.assertRaises(ValueError):
                p.read_label(path, 60, time_key='time_sec')

    def test_known_extractor_training_subject_leak_is_rejected(self):
        with self.assertRaises(ValueError):
            p.check_provenance({'status':'known', 'training_subjects':['AIR_400:S02']},
                               {'AIR_400:S01':'train', 'AIR_400:S02':'test'}, False)
        with self.assertRaises(ValueError):
            p.check_provenance({'status':'unknown'}, {'AIR_400:S01':'train'}, False)
        with self.assertRaises(ValueError):
            p.check_provenance({'status':'known','training_subjects':['S01']}, {'AIR_400:S01':'train'}, False)

    def test_review_requires_every_explicit_confirmation(self):
        clip = {'id':'AIR_400_S01_1', 'duration':60, 'video_sha256':'v', 'label_sha256':'l'}
        review = {'normal_intervals':[[0,60]], 'reviewer':'human', 'video_sha256':'v', 'label_sha256':'l',
                  'video_reviewed':True, 'label_reviewed':True, 'alignment_confirmed':True, 'quality_acceptable':True}
        self.assertEqual(p.approved_intervals(clip, review), [[0,60]])
        for key in ('video_reviewed','label_reviewed','alignment_confirmed','quality_acceptable'):
            with self.assertRaises(ValueError):
                p.approved_intervals(clip, {**review, key: False})
        with self.assertRaises(ValueError):
            p.approved_intervals(clip, {**review, 'normal_intervals':[[0,61]]})
        with self.assertRaises(ValueError):
            p.approved_intervals(clip, {**review, 'video_sha256':'changed'})

    def test_build_refuses_unreviewed_data_and_stale_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p.save_json(root/'manifest.json', {'clips':[]})
            p.save_json(root/'approvals.json', {'manifest_sha256':p.digest(root/'manifest.json'),'approvals':{}})
            with self.assertRaisesRegex(ValueError, 'No explicitly approved'):
                p.plan_windows(root)
            p.save_json(root/'manifest.json', {'clips':[], 'changed':True})
            with self.assertRaisesRegex(ValueError, 'Manifest changed'):
                p.verified_reviews(root)

    def test_end_to_end_build_keeps_subject_split_and_train_only_scaling(self):
        # Only the expensive model boundary is substituted. HDF5 caching,
        # approvals, hashes, split assignment and NumPy outputs are real.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clips, approvals = [], {}
            splits = {'AIR_400:S01':'train', 'AIR_400:S02':'val', 'AIR_400:S03':'test'}
            for i, subject in enumerate(splits, 1):
                video, label = root/f'{i}.mp4', root/f'{i}.hdf5'
                video.write_bytes(f'unique source {i}'.encode())
                with h5py.File(label, 'w') as f:
                    f['respiration'] = np.arange(600)
                c = {'id':str(i), 'subject':subject,'video':str(video),'label':str(label),'duration':60,
                     'status':'pending_review','video_sha256':p.digest(video),'label_sha256':p.digest(label)}
                clips.append(c)
                approvals[c['id']] = {'normal_intervals':[[0,35]],'reviewer':'synthetic-test',
                    'video_reviewed':True,'label_reviewed':True,'alignment_confirmed':True,'quality_acceptable':True,
                    'video_sha256':c['video_sha256'],'label_sha256':c['label_sha256']}
            p.save_json(root/'manifest.json', {'clips':clips})
            p.save_json(root/'approvals.json', {'manifest_sha256':p.digest(root/'manifest.json'),'approvals':approvals})
            p.save_json(root/'splits.json', {'subjects':splits})
            checkpoint = root/'model.pth'
            checkpoint.write_bytes(b'test checkpoint')

            class ExtractorBoundary:
                receipt = {'synthetic_test_only': True}
                def __init__(self, *args):
                    pass
                def predict_video(self, video, start):
                    offset = 100 * int(Path(video).stem)
                    x = offset + np.sin(np.arange(300)/10)
                    return {'raw_model':x,'respiration':x,'time_sec':np.arange(300)/10,
                            'x_10hz':x.astype('float32'),'fs':10,'pred_rr_bpm':30}

            args = SimpleNamespace(workdir=root, dest=root/'dataset', repo=root, config=root/'unused.yaml',
                                   checkpoint=checkpoint,provenance=None,allow_unknown_extractor_training=True)
            with patch('inference_adapter.AirExtractor', ExtractorBoundary):
                p.build(args)
            train = np.load(root/'dataset/X_train.npy')
            self.assertEqual(train.shape, (2,1,300))
            self.assertAlmostEqual(float(train.mean()), 0, places=5)
            self.assertGreater(float(np.load(root/'dataset/X_val.npy').mean()), 50)
            rows = p.load_json(root/'dataset/windows.json')
            for row in rows:
                self.assertEqual(row['split'], splits[row['subject']])
            self.assertFalse(p.load_json(root/'dataset/build_report.json')['heldout_extractor_subjects_verified'])


if __name__ == '__main__':
    unittest.main()
