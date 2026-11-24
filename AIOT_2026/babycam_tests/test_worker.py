import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from babycam.common import Config, RemoteError
from babycam.worker import SourceChanged, Worker


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg = Config("http://localhost", "sb_secret_test", work_dir=Path(self.temp.name))
        self.api = Mock()
        self.api.list_segments.return_value = [{"name": f"{n:012}.ts"} for n in range(30)]
        self.process = Mock(return_value={"status": "unscored", "reason": "test invalid ROI"})

    def worker(self):
        return Worker(self.cfg, self.api, self.process, "signature")

    def test_upload_failure_restarts_without_reinference_or_cursor_advance(self):
        worker = self.worker()
        self.api.save_result.side_effect = RemoteError("offline")
        with self.assertRaises(RemoteError):
            worker.tick()
        self.assertEqual(worker.state["next_seq"], 0)
        self.assertEqual(self.process.call_count, 1)
        self.api.save_result.side_effect = None
        resumed = self.worker()
        self.assertEqual(resumed.tick(), "saved")
        self.assertEqual(resumed.state["next_seq"], 15)
        self.assertEqual(self.process.call_count, 1)
        self.assertIsNone(resumed.state["pending"])
        self.assertEqual(self.api.save_result.call_args_list[0].args[0]["batch_id"],
                         self.api.save_result.call_args_list[1].args[0]["batch_id"])

    def test_gap_is_not_skipped(self):
        self.api.list_segments.return_value = self.api.list_segments.return_value[1:]
        self.cfg.start_seq = 0
        worker = self.worker()
        self.assertEqual(worker.tick(), "waiting")
        self.process.assert_not_called()
        self.api.save_result.assert_not_called()

    def test_transient_download_error_does_not_count_as_bad_breathing(self):
        self.process.side_effect = RemoteError("download failure")
        worker = self.worker()
        with self.assertRaises(RemoteError):
            worker.tick()
        self.api.save_result.assert_not_called()
        self.assertEqual(worker.state["attempts"], 0)

    def test_failed_media_is_unscored_after_three_attempts(self):
        self.process.side_effect = ValueError("bad media")
        worker = self.worker()
        self.assertEqual(worker.tick(), "retry")
        self.assertEqual(worker.tick(), "retry")
        self.assertEqual(worker.tick(), "saved")
        row = self.api.save_result.call_args.args[0]
        self.assertEqual(row["status"], "unscored")
        self.assertIsNone(row["is_anomaly"])
        self.assertIsNone(row["anomaly_score"])
        self.assertEqual(worker.state["next_seq"], 15)

    def test_changed_configuration_refuses_existing_cursor(self):
        self.worker()
        with self.assertRaises(ValueError):
            Worker(self.cfg, self.api, self.process, "different model")

    def test_replaced_source_stops_without_skipping(self):
        self.process.side_effect = SourceChanged("replaced TS")
        worker = self.worker()
        with self.assertRaises(SourceChanged):
            worker.tick()
        self.assertEqual(worker.state["next_seq"], 0)
        self.api.save_result.assert_not_called()


if __name__ == "__main__":
    unittest.main()
