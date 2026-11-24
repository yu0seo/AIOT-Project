"""Local browser test fixture. Reads an actual saved integration result; never writes Supabase."""
import argparse
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from babycam.common import RemoteError, validate_result
from babycam.web import ResultCache, make_server


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    args = p.parse_args()
    control = args.directory / "ui_control.json"
    row = json.loads((args.directory / "real_model_result.json").read_text(encoding="utf-8"))
    class Fixture:
        def results(self, _):
            mode = json.loads(control.read_text(encoding="utf-8"))["mode"]
            if mode == "error":
                raise RemoteError("local fixture offline")
            if mode == "empty":
                return []
            if mode == "unscored":
                return [validate_result(row | {"batch_id":"ui-unscored-fixture", "start_seq":15, "end_seq":29,
                                              "status":"unscored", "reason":"화면 갱신 검증용: ROI 없음"}), row]
            return [row]
    api, cache, stop = Fixture(), ResultCache(), threading.Event()
    def refresh():
        while not stop.is_set():
            cache.refresh(api)
            stop.wait(1)
    threading.Thread(target=refresh, daemon=True).start()
    server = make_server(8765, cache)
    print("UI_FIXTURE_READY", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set(); server.server_close()


if __name__ == "__main__":
    main()
