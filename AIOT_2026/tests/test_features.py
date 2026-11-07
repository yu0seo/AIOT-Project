"""분석해가 있는 궤적으로 특징 정의와 온라인 처리 계약을 검증한다."""
import unittest

import numpy as np

from idd_classifier.features import FeatureConfig, FeatureStream, extract_segments


class FeatureTests(unittest.TestCase):
    def trajectory(self, xy, hz=10):
        t = np.arange(len(xy), dtype=np.int64) * round(1e9 / hz)
        return t, np.asarray(xy)

    def test_constant_velocity_and_translation(self):
        t = np.arange(80) / 10
        ts, xy = self.trajectory(np.column_stack([3*t, 4*t]))
        a, _ = extract_segments(ts, xy, FeatureConfig())
        b, _ = extract_segments(ts, xy + [1e4, -2e4], FeatureConfig())
        np.testing.assert_allclose(a[0].values, np.tile([5, 0, 0, 0], (70, 1)), atol=1e-7)
        np.testing.assert_allclose(a[0].values, b[0].values, atol=1e-7)

    def test_signed_deceleration_and_vector_jerk(self):
        t = np.arange(70) / 10
        ts, xy = self.trajectory(np.column_stack([20*t-t*t+0.05*t**3, np.zeros(len(t))]))
        segments, _ = extract_segments(ts, xy, FeatureConfig())
        u=t[10:]
        expected=np.column_stack([20-2*u+0.15*u*u, -2+0.3*u, np.full(len(u),0.3), np.zeros(len(u))])
        np.testing.assert_allclose(segments[0].values, expected, atol=1e-7)

    def test_circle_has_vector_jerk_but_near_zero_speed_derivative(self):
        t=np.arange(100)/10
        ts,xy=self.trajectory(np.column_stack([20*np.cos(0.2*t),20*np.sin(0.2*t)]))
        seg,_=extract_segments(ts,xy,FeatureConfig())
        np.testing.assert_allclose(seg[0].values[:,0],4,atol=0.005)
        np.testing.assert_allclose(seg[0].values[:,1],0,atol=0.005)
        np.testing.assert_allclose(seg[0].values[:,2],0.16,atol=0.005)
        np.testing.assert_allclose(seg[0].values[:,3],0.2,atol=0.005)

    def test_stationary_finite_and_zero(self):
        ts,xy=self.trajectory(np.tile([400,300],(50,1)))
        seg,_=extract_segments(ts,xy,FeatureConfig())
        np.testing.assert_allclose(seg[0].values,0,atol=1e-9)

    def test_position_smoothing_reduces_derivative_noise(self):
        rng = np.random.default_rng(42)
        seconds = np.arange(300)/10
        xy = np.column_stack([seconds*5, seconds*0]) + rng.normal(0, .03, (300, 2))
        timestamps, xy = self.trajectory(xy)
        segments, _ = extract_segments(timestamps, xy, FeatureConfig())
        raw_jerk = np.linalg.norm(np.diff(xy, n=3, axis=0)/.1**3, axis=1)
        self.assertLess(np.mean(segments[0].values[:, 2]), np.mean(raw_jerk)/5)

    def test_invalid_configuration_and_ns_range(self):
        for settings in ({'smooth_points': 3}, {'smooth_points': 11.5}, {'max_gap_s': .01}, {'sample_hz': True}):
            with self.assertRaises(ValueError): FeatureConfig(**settings)
        for timestamp in (-1, 2**63):
            with self.assertRaises(ValueError): FeatureStream(FeatureConfig()).update(timestamp, 0, 0)

    def test_no_window_across_gap_missing_or_jump(self):
        ts,xy=self.trajectory(np.column_stack([np.arange(80)/10,np.zeros(80)]))
        ts[40:]+=1_000_000_000
        xy[20]=np.nan
        xy[60:]+=1000
        segments,audit=extract_segments(ts,xy,FeatureConfig())
        self.assertGreaterEqual(len(segments),4)
        self.assertEqual(audit['missing_coordinates'],1)
        self.assertEqual(audit['gaps'],1)
        self.assertEqual(audit['jumps'],1)
        for s in segments: self.assertTrue(np.all(np.diff(s.timestamps_ns)==100_000_000))

    def test_duplicate_and_reverse_timestamps_rejected(self):
        for ts in ([0,0,100],[200,100,300]):
            with self.assertRaises(ValueError): extract_segments(np.array(ts),np.zeros((3,2)),FeatureConfig())

    def test_batch_online_and_prefix_equivalence_with_bounded_delay(self):
        t=np.arange(150,dtype=np.int64)*33_333_333
        xy=np.column_stack([t/1e9*4,np.sin(t/1e9)])
        seg,_=extract_segments(t,xy,FeatureConfig())
        stream=FeatureStream(FeatureConfig()); points=[]
        for stamp,p in zip(t,xy):
            for out in stream.update(int(stamp),*p):
                self.assertLessEqual(out.timestamp_ns,int(stamp))
                self.assertLessEqual(int(stamp)-out.timestamp_ns,200_000_000)
                points.append(out.values)
        np.testing.assert_array_equal(seg[0].values,np.asarray(points))
        partial,_=extract_segments(t[:90],xy[:90],FeatureConfig())
        np.testing.assert_array_equal(partial[0].values,seg[0].values[:len(partial[0].values)])


if __name__=='__main__': unittest.main()
