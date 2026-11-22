"""Scoped HTTPS client; only standard-library modules are required on the Pi."""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


class ServiceError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    address = urlparse(config.get("endpoint", ""))
    if address.scheme != "https" or not address.hostname or len(config.get("device_key", "")) < 32:
        raise ValueError("Invalid Supabase client configuration.")
    return config


def call(config, action, body=None, query=None):
    url = config["endpoint"].rstrip("/") + "/" + action
    if query:
        url += "?" + urlencode(query)
    request = Request(url, data=json.dumps(body).encode() if body is not None else None,
                      headers={"content-type": "application/json", "apikey": config["publishable_key"],
                               "x-device-key": config["device_key"]})
    try:
        with urlopen(request, timeout=40) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            message = json.loads(exc.read(8192)).get("error", "Video request failed.")
        except (ValueError, AttributeError):
            message = "Video request failed."
        raise ServiceError(exc.code, message) from None


def check_signed_url(config, url):
    target, base = urlparse(url), urlparse(config["endpoint"])
    if target.scheme != "https" or target.hostname != base.hostname or not target.path.startswith("/storage/v1/object/"):
        raise ValueError("Unexpected signed Storage URL.")


def put_segment(config, signed_url, payload):
    check_signed_url(config, signed_url)
    request = Request(signed_url, data=payload, method="PUT", headers={"content-type": "video/mp2t"})
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            error = json.loads(exc.read(8192))
        except ValueError:
            error = {}
        if exc.code == 409 or str(error.get("statusCode")) == "409" or error.get("error") == "Duplicate":
            # Reuse is allowed only for a retry of our same session/sequence/file.
            return {"duplicate": True}
        raise ServiceError(exc.code, "Storage upload failed.") from None


def get_segment(config, signed_url):
    check_signed_url(config, signed_url)
    with urlopen(signed_url, timeout=30) as response:
        payload = response.read(8 * 1024 * 1024 + 1)
    if not payload or len(payload) > 8 * 1024 * 1024:
        raise ValueError("Invalid segment size.")
    return payload


def reserve(config, session, sequence, start):
    return call(config, "reserve", {"camera_id": config["camera_id"], "session_id": session,
                "first_sequence": sequence, "capture_start": start.astimezone(timezone.utc).isoformat()})
