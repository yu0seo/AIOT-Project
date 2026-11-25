import unittest

from normal_pipeline.respiration_presence import classify_motion, fit_calibration, combine_decisions


def feature(amplitude=.5, **kwargs):
    return dict(quality_ok=True, quality_reasons=[], amplitude_px=amplitude,
                periodic_concentration=.8, respiratory_energy_fraction=.9,
                spatial_coherence=.9, candidate_bpm=30., method='farneback_bg_translation_v1',
                frame_size=[320,180], fs=15., window_seconds=10., **kwargs)


def record(name, group, split, label, amp):
    return dict(id=name, group_id=group, split=split, label=label, source_sha256=name*64,
                windows=[feature(amp)], roi_mode='fixed_manual', development_exposed=True)


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.records = [record('a','AIR_125:S05','train','normal_reviewed_motion',.5),
                        record('b','STATIC:one','train','static_simulation',.01),
                        record('c','AIR_125:S02','valid','normal_reviewed_motion',.4),
                        record('d','STATIC:two','valid','static_simulation',.02)]

    def test_low_motion_has_no_forced_bpm_and_bad_quality_is_not_absence(self):
        calibration = fit_calibration(self.records)
        self.assertTrue(calibration['development_usable'])
        self.assertFalse(calibration['production_ready'])
        still = classify_motion(feature(.01), calibration, allow_development=True)
        self.assertEqual(still['respiration_state'], 'no_motion_detected')
        self.assertIsNone(still['pred_rr_bpm'])
        self.assertIs(still['movement_absence_candidate'], True)
        invalid = feature(.01)
        invalid.update(quality_ok=False, quality_reasons=['frozen'])
        result = classify_motion(invalid, calibration, allow_development=True)
        self.assertEqual(result['respiration_state'], 'unassessable')
        self.assertIsNone(result['movement_absence_candidate'])

    def test_motion_alone_without_periodicity_is_unassessable(self):
        calibration = fit_calibration(self.records)
        f = feature(.7)
        f['periodic_concentration'] = .01
        result = classify_motion(f, calibration, allow_development=True)
        self.assertEqual(result['respiration_state'], 'unassessable')
        self.assertIsNone(result['pred_rr_bpm'])

    def test_no_separation_or_failed_validation_disables_calibration(self):
        self.records[1]['windows'][0]['amplitude_px'] = .9
        calibration = fit_calibration(self.records)
        self.assertFalse(calibration['development_usable'])
        self.assertEqual(classify_motion(feature(), calibration)['respiration_state'], 'unassessable')
        self.records[1]['windows'][0]['amplitude_px'] = .01
        self.records[2]['windows'][0]['amplitude_px'] = .001
        self.assertFalse(fit_calibration(self.records)['development_usable'])

    def test_test_labels_and_values_cannot_change_threshold(self):
        a = fit_calibration(self.records)
        b = fit_calibration(self.records+[record('e','AIR_400:S09','test','normal_assumed',999)])
        self.assertEqual(a, b)

    def test_valid_selects_threshold_but_is_not_independent_performance_evidence(self):
        self.records[2]['windows'][0]['amplitude_px'] = .04
        calibration = fit_calibration(self.records)
        self.assertTrue(calibration['development_usable'])
        self.assertTrue(calibration['validation_used_for_threshold_selection'])
        self.assertFalse(calibration['production_ready'])
        self.assertLess(calibration['amplitude_threshold_px'], .04)

    def test_leakage_string_bool_and_wrong_feature_contract_rejected(self):
        self.records[2]['group_id'] = 'AIR_125:S05'
        with self.assertRaises(ValueError):
            fit_calibration(self.records)
        self.records[2]['group_id'] = 'AIR_125:S02'
        self.records[0]['windows'][0]['quality_ok'] = 'False'
        with self.assertRaises(ValueError):
            fit_calibration(self.records)
        self.records[0]['windows'][0]['quality_ok'] = True
        calibration = fit_calibration(self.records)
        f = feature()
        f['frame_size'] = [640,360]
        self.assertEqual(classify_motion(f, calibration, allow_development=True)['respiration_state'], 'unassessable')
        self.assertEqual(classify_motion(feature(), calibration)['respiration_state'], 'unassessable')
        calibration['production_ready']='False'
        with self.assertRaises(ValueError):
            classify_motion(feature(),calibration)

    def test_test_subject_leakage_is_rejected_even_though_test_is_not_fitted(self):
        duplicate=record('e','AIR_125:S05','test','normal_assumed',.4)
        with self.assertRaisesRegex(ValueError,'누수'):
            fit_calibration(self.records+[duplicate])

    def test_no_movement_and_quality_failure_cannot_become_normal_ae_results(self):
        legacy=dict(anomaly_score=.01,is_anomaly=False,pred_rr_bpm=29.88)
        no_motion=[dict(respiration_state='no_motion_detected')]
        result=combine_decisions(no_motion,legacy,roi_calibrated=True,allow_development=True)
        self.assertIsNone(result['is_anomaly'])
        self.assertIsNone(result['anomaly_score'])
        self.assertIsNone(result['pred_rr_bpm'])
        self.assertIs(result['movement_absence_candidate'],True)
        self.assertEqual(result['status'],'unscored')
        unknown=combine_decisions([dict(respiration_state='unassessable')],legacy,
                                 roi_calibrated=True,allow_development=True)
        self.assertIsNone(unknown['movement_absence_candidate'])
        present=[dict(respiration_state='motion_present')]
        self.assertEqual(combine_decisions(present,legacy)['status'],'unscored')
        self.assertEqual(combine_decisions(present,legacy,roi_calibrated=True,
                         allow_development=True)['status'],'below_threshold')
        legacy['is_anomaly']='False'
        with self.assertRaises(ValueError):
            combine_decisions(present,legacy,roi_calibrated=True,allow_development=True)
        with self.assertRaises(ValueError):
            combine_decisions(present,None,roi_calibrated='False')


if __name__ == '__main__':
    unittest.main()
