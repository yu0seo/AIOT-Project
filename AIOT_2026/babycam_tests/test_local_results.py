import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from babycam.common import Config
from babycam.local_results import LocalResults
from test_core import result


def local_row(index=0, **changes):
    return result(batch_id=f"{index:064x}", stream_id="test-session", start_seq=index * 15,
                  end_seq=index * 15 + 14, processing_sec=1.25, **changes)


class LocalResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.cfg = Config("", "", stream_id="test-session", result_dir=self.path)
        self.store = LocalResults(self.cfg)

    def test_saves_readable_csv_latest_summary_and_full_json(self):
        row = local_row()
        self.store.save_result(row)
        latest = json.loads((self.path / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(latest["status"], "below_threshold")
        self.assertIs(latest["is_anomaly"], False)
        self.assertEqual(len(latest["waveform"]["x_10hz"]), 300)
        self.assertTrue((self.path / "records" / f"{row['batch_id']}.json").is_file())
        self.assertIn("임계값 이하", (self.path / "latest.md").read_text(encoding="utf-8"))
        with (self.path / "analysis_results.csv").open(encoding="utf-8-sig", newline="") as fp:
            exported = list(csv.DictReader(fp))
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["판정"], "임계값 이하")

    def test_restart_and_repeated_save_are_idempotent(self):
        self.store.save_result(local_row())
        saved_at = self.store.results()[0]["created_at"]
        resumed = LocalResults(self.cfg)
        resumed.save_result(local_row())
        self.assertEqual(len(resumed.results()), 1)
        self.assertEqual(resumed.results()[0]["created_at"], saved_at)

    def test_latest_is_newest_segment_and_reader_filters_stream(self):
        self.store.save_result(local_row(2))
        self.store.save_result(local_row(1))
        self.assertEqual(self.store.results()[0]["end_seq"], 44)
        other = Config("", "", stream_id="another-session", result_dir=self.path)
        self.assertEqual(LocalResults(other).results(), [])
        self.assertEqual(json.loads((self.path / "latest.json").read_text(encoding="utf-8"))["end_seq"], 44)

    def test_unscored_has_empty_score_and_reason_in_csv(self):
        self.store.save_result(local_row(status="unscored", reason="ROI 없음"))
        row = self.store.results()[0]
        self.assertIsNone(row["is_anomaly"])
        self.assertIsNone(row["anomaly_score"])
        with (self.path / "analysis_results.csv").open(encoding="utf-8-sig", newline="") as fp:
            exported = next(csv.DictReader(fp))
        self.assertEqual(exported["판정"], "분석 불가")
        self.assertEqual(exported["이상 점수"], "")
        self.assertEqual(exported["이유"], "ROI 없음")

    def test_locked_csv_does_not_lose_committed_result(self):
        with patch.object(self.store, "export_csv", side_effect=PermissionError("Excel lock")):
            self.store.save_result(local_row())
        self.assertEqual(len(self.store.results()), 1)
        self.store.save_result(local_row())
        self.assertTrue((self.path / "analysis_results.csv").is_file())

    def test_csv_formula_is_escaped(self):
        self.store.save_result(local_row(status="unscored", reason="=1+1"))
        with (self.path / "analysis_results.csv").open(encoding="utf-8-sig", newline="") as fp:
            self.assertEqual(next(csv.DictReader(fp))["이유"], "'=1+1")

    def test_local_reader_does_not_require_supabase_key(self):
        env = self.path / ".env"
        env.write_text(f"AIR400_ROOT={self.path.as_posix()}\nRESULT_DIR=results\n", encoding="utf-8")
        with patch.dict("os.environ", {}, clear=True):
            cfg = Config.load(env, require_supabase=False)
        self.assertEqual(cfg.result_dir, self.path / "results")

    def test_missing_env_reader_defaults_to_this_repository(self):
        from babycam.common import PROJECT_ROOT
        with patch.dict("os.environ", {}, clear=True):
            cfg = Config.load(self.path / "missing.env", require_supabase=False)
        self.assertEqual(cfg.root, PROJECT_ROOT)
        self.assertEqual(cfg.result_dir, PROJECT_ROOT / "output" / "stream_results")


if __name__ == "__main__":
    unittest.main()
