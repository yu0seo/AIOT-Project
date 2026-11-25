import unittest
import numpy as np

from normal_pipeline.ae_evaluation import classification_metrics, select_threshold, normal_train_statistics, validate_feature_records


class AeEvaluationTests(unittest.TestCase):
    def test_always_normal_is_not_perfect_balanced_accuracy(self):
        r=classification_metrics([.1,.2,.3,.4],[False,False,True,True],1.)
        self.assertEqual(r['accuracy'],.5)
        self.assertEqual(r['balanced_accuracy'],.5)
        self.assertEqual(r['recall'],0.)

    def test_normal_only_cannot_measure_recall(self):
        r=classification_metrics([.1,.2],[False,False],1.)
        self.assertEqual(r['accuracy'],1.)
        self.assertIsNone(r['recall'])
        self.assertIsNone(r['balanced_accuracy'])

    def test_threshold_uses_both_validation_classes_and_fpr_limit(self):
        threshold,r=select_threshold([.1,.2,.3,.4],[False,False,True,True],max_fpr=0.)
        self.assertGreater(threshold,.2);self.assertLess(threshold,.3)
        self.assertEqual(r['balanced_accuracy'],1.)
        self.assertEqual(r['false_positive_rate'],0.)

    def test_identical_scores_cannot_be_reported_as_separable(self):
        threshold,r=select_threshold([.2,.2],[False,True],max_fpr=0.)
        self.assertEqual(r['balanced_accuracy'],.5)
        self.assertEqual(r['recall'],0.)

    def test_both_classes_required_and_strings_rejected(self):
        for labels in [[False,False],['False','True']]:
            with self.assertRaises(ValueError):
                select_threshold([.1,.2],labels,max_fpr=0.)

    def test_statistics_ignore_validation_and_abnormal_training(self):
        waves=np.array([[1.,3.],[100.,200.],[1000.,2000.]])
        bpms=np.array([20.,60.,200.])
        stats=normal_train_statistics(waves,bpms,['train','valid','train'],[False,False,True])
        self.assertAlmostEqual(stats['wave_mean'],2.)
        self.assertAlmostEqual(stats['wave_std'],1.)
        self.assertAlmostEqual(stats['bpm_mean'],20.)
        self.assertAlmostEqual(stats['bpm_std'],1.)

    def record(self,group,split,label,digest):
        return dict(id=group,group_id=group,split=split,label=label,reviewed=True,source_sha256=digest*64)

    def test_assumptions_need_authorization_and_static_never_trains(self):
        r=self.record('AIR_125:S01','train','normal_assumed','a');r['reviewed']=False
        with self.assertRaises(ValueError):
            validate_feature_records([r],allow_assumed=False)
        validate_feature_records([r],allow_assumed=True)
        r['label']='static_simulation'
        with self.assertRaises(ValueError):
            validate_feature_records([r],allow_assumed=True)

    def test_dataset_subject_and_source_split_leakage(self):
        a=self.record('AIR_125:S01','train','normal_reviewed_motion','a')
        b=self.record('AIR_400:S01','valid','normal_reviewed_motion','b')
        validate_feature_records([a,b],allow_assumed=False)
        b['group_id']=a['group_id']
        with self.assertRaises(ValueError):
            validate_feature_records([a,b],allow_assumed=False)
        b['group_id']='AIR_400:S01';b['source_sha256']=a['source_sha256']
        with self.assertRaises(ValueError):
            validate_feature_records([a,b],allow_assumed=False)


if __name__=='__main__':
    unittest.main()
