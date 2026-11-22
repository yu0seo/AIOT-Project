"""Create separate scoped device credentials. Never prints their plaintext values."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets

DEFAULT_URL = "https://wwkphksqyjqsjouoamly.supabase.co/functions/v1/breathing-video"


def config_dir():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config")) / "AIOT-SupabaseVideo"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=config_dir())
    parser.add_argument("--publishable-key", required=True)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    hashes = {"camera_id": "pi-camera"}
    for role in ("upload", "read"):
        target = args.directory / ("supabase_pi.json" if role == "upload" else "supabase_pc.json")
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8"))
        else:
            data = {"endpoint": DEFAULT_URL, "publishable_key": args.publishable_key,
                    "camera_id": "pi-camera", "device_key": secrets.token_urlsafe(32)}
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        hashes[role + "_key_hash"] = hashlib.sha256(data["device_key"].encode()).hexdigest()
    print(json.dumps(hashes))


if __name__ == "__main__":
    main()
