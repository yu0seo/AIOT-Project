"""공식 규칙, 오류 처리, 분할 누출 방지를 검증한다."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from idd_classifier.data import label_for, load_track, read_annotations, split_participants, fit_normalizer, make_windows, Track
from idd_classifier.features import FeatureSegment


class DataTests(unittest.TestCase):
    def test_official_label(self):
        self.assertEqual(label_for('P702','R2'),1)
        self.assertEqual(label_for('P702','R1'),0)
        self.assertEqual(label_for('7201','R2'),0)
        for p,r in [('other','R2'),('P702','R3')]:
            with self.assertRaises(ValueError): label_for(p,r)

    def test_ns_precision_and_invalid_timestamp(self):
        Path('.tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='.tmp') as tmp:
            p=Path(tmp)/'ego_tracks.csv'
            p.write_text('resampled_epoch_ns,carla_objects_pose_x,carla_objects_pose_y\n1700000000000000000,1,2\n1700000000100000000,2,3\n',encoding='utf-8')
            t,xy,audit=load_track(p)
            self.assertEqual(int(t[1]-t[0]),100_000_000)
            p.write_text('resampled_epoch_ns,carla_objects_pose_x,carla_objects_pose_y\n0,1,2\n0,2,3\n',encoding='utf-8')
            with self.assertRaises(ValueError): load_track(p)

    def test_short_annotation_header_has_clear_error(self):
        Path('.tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='.tmp') as tmp:
            root = Path(tmp)
            (root/'idd_annotation.csv').write_text('short\nheader\n', encoding='utf-8')
            with self.assertRaises(ValueError): read_annotations(root)

    def test_split_before_windows_and_train_only_normalizer(self):
        rows=pd.DataFrame([{'participant':f'P{i}', 'label':label, 'scenario_id':f'P{i}/{label}'} for i in range(12) for label in (0,1)])
        splits=split_participants(rows,42,.2,.2)
        sets=[set(v) for v in splits.values()]
        self.assertFalse(sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2])
        self.assertEqual(splits,split_participants(rows,42,.2,.2))
        tracks=[Track('P0','a',0,[FeatureSegment(np.arange(120)*100_000_000,np.ones((120,4))*3,0)]),
                Track('P1','b',1,[FeatureSegment(np.arange(120)*100_000_000,np.ones((120,4))*999,0)])]
        normalizer=fit_normalizer(tracks,['P0'])
        np.testing.assert_array_equal(normalizer['mean'],[3]*4)
        np.testing.assert_array_equal(normalizer['std'],[1]*4)
        w=make_windows(tracks,['P0'],30,10,100)
        self.assertEqual(w['x'].shape,(3,30,4))
        self.assertTrue(np.all(w['participant']=='P0'))
        self.assertEqual(int(w['end_ns'][0]),9_900_000_000)


if __name__=='__main__': unittest.main()
