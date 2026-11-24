import json
import tempfile
import unittest
from pathlib import Path

from babycam.common import ResultError, select_batch, validate_result


def result(**changes):
    row = dict(status="below_threshold", is_anomaly=False, anomaly_score=0.2,
               threshold=1.0, pred_rr_bpm=30.0, wave_mse=0.1, bpm_mse=0.5,
               waveform={"x_10hz": [0.0, 1.0] * 150}, reason="")
    row.update(changes)
    return row


class SelectionTests(unittest.TestCase):
    def test_fifteen_consecutive_numeric_names_in_order(self):
        objects = [{"name": f"{n:012}.ts", "id": str(n)} for n in range(30, 9, -1)]
        batch = select_batch(objects, 10)
        self.assertEqual([x["name"] for x in batch], [f"{n:012}.ts" for n in range(10, 25)])

    def test_missing_segment_waits_without_skipping(self):
        objects = [{"name": f"{n:012}.ts", "id": str(n)} for n in range(10, 35) if n != 15]
        self.assertIsNone(select_batch(objects, 10))

    def test_short_batch_waits(self):
        self.assertIsNone(select_batch([{"name": f"{n:012}.ts"} for n in range(14)], 0))

    def test_auto_starts_at_oldest_and_ignores_other_paths(self):
        objects = [{"name": f"{n:012}.ts"} for n in range(210, 225)]
        objects += [{"name": "../000000000001.ts"}, {"name": "notes.txt"}, {"name": "folder"}]
        self.assertEqual(select_batch(objects, None)[0]["name"], "000000000210.ts")


class ResultTests(unittest.TestCase):
    def test_false_string_is_false(self):
        self.assertIs(validate_result(result(is_anomaly="False"))["is_anomaly"], False)

    def test_unscored_cannot_carry_safe_flag_or_score(self):
        row = validate_result(result(status="unscored", reason="ROI 없음"))
        self.assertIsNone(row["is_anomaly"])
        self.assertIsNone(row["anomaly_score"])
        self.assertIsNone(row["pred_rr_bpm"])
        self.assertIsNone(row["waveform"])

    def test_rejects_inconsistent_status(self):
        with self.assertRaises(ResultError):
            validate_result(result(status="anomaly_candidate"))

    def test_rejects_nonfinite_and_short_wave(self):
        for change in ({"anomaly_score": float("nan")}, {"waveform": {"x_10hz": [1.0]}}):
            with self.subTest(change=change), self.assertRaises(ResultError):
                validate_result(result(**change))


if __name__ == "__main__":
    unittest.main()
