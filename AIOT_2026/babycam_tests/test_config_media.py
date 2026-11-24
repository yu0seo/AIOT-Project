import http.client
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from babycam.common import Config, RemoteError, Supabase
from babycam.worker import BatchProcessor, SingleInstance, SourceChanged, merge_media


class BoundaryTests(unittest.TestCase):
    def test_config_loads_windows_paths_but_does_not_accept_publishable_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env = Path(directory) / ".env"
            env.write_text("SUPABASE_URL=https://example.supabase.co\nSUPABASE_SECRET_KEY=sb_secret_fixture\nAIR400_ROOT=C:\\Users\\OHS\\air-400\n", encoding="utf-8")
            cfg = Config.load(env)
            self.assertEqual(cfg.root.name, "air-400")
            self.assertNotIn("sb_secret_fixture", repr(cfg))
            env.write_text("SUPABASE_URL=https://example.supabase.co\nSUPABASE_SECRET_KEY=sb_publishable_bad\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                Config.load(env)

    def test_short_media_cannot_be_padded_to_thirty_seconds(self):
        cfg = Config("", "")
        with patch("babycam.worker.probe", return_value=dict(duration=1, start=0, codec="h264", width=640, height=480)), patch("babycam.worker.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "30±0.25"):
                merge_media([Path(f"{n:012}.ts") for n in range(15)], Path("unused"), cfg)
            run.assert_not_called()

    def test_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as directory:
            with SingleInstance(Path(directory)):
                with self.assertRaises(ValueError):
                    with SingleInstance(Path(directory)):
                        self.fail("duplicate worker acquired lock")
            with SingleInstance(Path(directory)):
                pass

    def test_interrupted_http_body_is_retryable(self):
        api = Supabase(Config("http://localhost", "sb_secret_fixture"))
        response = Mock()
        response.read.side_effect = http.client.IncompleteRead(b"partial")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        api.open = Mock(return_value=response)
        with self.assertRaises(RemoteError):
            api.request("GET", "/rest/v1/example")

    def test_cached_result_does_not_hide_replaced_segment(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "result.json").write_text('{"status":"unscored"}', encoding="utf-8")
            (folder / "manifest.json").write_text(json.dumps({"objects":[],"sha256":{}}), encoding="utf-8")
            process = BatchProcessor(Config("", ""), Mock(), Mock())
            with self.assertRaises(SourceChanged):
                process([{"name":"000000000000.ts"}], folder, 1)


if __name__ == "__main__":
    unittest.main()
