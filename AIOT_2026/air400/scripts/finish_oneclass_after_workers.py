"""Coordinate remaining public AIR-125 sources, then finalize after both workers finish."""
import json
import subprocess
import time

from air400_paths import PROJECT, PYTHON
from download_oneclass_sources import save

OUT = PROJECT/"06_단일클래스_학습데이터"


def wait_status(filename, minimum_sources):
    path = OUT/"configs"/filename
    while True:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["source_count"] >= minimum_sources and state["finished_sources"] == state["source_count"] and "all_exported_segments" in state:
                return state
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(5)


def phase(name):
    save(OUT/"configs/coordinator_status.json", {"phase": name, "complete": name == "complete"})
    print("Coordinator:", name, flush=True)


def main():
    phase("waiting_for_initial_air125_worker")
    wait_status("extraction_status_air-125.json", 1)
    phase("extracting_newly_available_or_incomplete_air125_sources")
    subprocess.run([str(PYTHON), str(PROJECT/"scripts/extract_oneclass_30s.py"), "--dataset", "air-125",
                    "--workers", "4", "--no-consolidate", "--skip-complete-sources"], check=True)
    phase("waiting_for_air400_worker")
    wait_status("extraction_status.json", 1)
    phase("finalizing_and_verifying_exports")
    subprocess.run([str(PYTHON), str(PROJECT/"scripts/finalize_oneclass_collection.py")], check=True)
    result = json.loads((OUT/"configs/collection_summary.json").read_text(encoding="utf-8"))
    if result["sources_without_exports"]:
        phase("incomplete_sources_need_review")
        raise RuntimeError([r["id"] for r in result["sources_without_exports"]])
    phase("complete")


if __name__ == "__main__":
    main()
