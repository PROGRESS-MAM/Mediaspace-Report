# IMPORTS
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


# CONFIG
app_name = "ms_source"
app_version = "0.1.0"


# FUNC
class FetchError(RuntimeError):
    """Raised when the Admin API cannot provide a valid Space response."""


@dataclass(frozen=True)
class SpaceInfo:
    """Parsed lifecycle and storage information for one Media Space."""

    uuid: str
    name: str
    created: datetime
    removed: datetime | None
    used_bytes: int


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Berlin"))
    except (OverflowError, ValueError):
        return None


def parse_spaces(raw: list[dict]) -> list[SpaceInfo]:
    """Convert valid API records to SpaceInfo without retaining other fields."""
    spaces = []
    for record in raw:
        if not isinstance(record, dict):
            continue

        uuid = record.get("uuid")
        name = record.get("name")
        created = _parse_timestamp(record.get("created"))
        if not isinstance(uuid, str) or not uuid.strip() or not isinstance(name, str) or not name.strip() or created is None:
            continue

        removed_value = record.get("removed")
        removed = None if removed_value is None else _parse_timestamp(removed_value)
        if removed_value is not None and removed is None:
            continue

        try:
            used_bytes = int(record.get("mount_used_bytes"))
        except (OverflowError, TypeError, ValueError):
            used_bytes = 0
        if used_bytes < 0:
            used_bytes = 0

        spaces.append(SpaceInfo(uuid, name, created, removed, used_bytes))
    return spaces


def fetch_spaces(cred_path: Path, timeout: float) -> list[dict]:
    """Fetch all Media Spaces through the read-only Admin API with a time limit."""
    from dotenv import load_dotenv

    load_dotenv(cred_path)
    required = ("FLOW_HOST", "FLOW_USER", "FLOW_PASSWORD")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise FetchError(f"Fehlt in cred.env: {', '.join(missing)}")

    username, password, ip_addr = (os.environ[key] for key in ("FLOW_USER", "FLOW_PASSWORD", "FLOW_HOST"))
    completed = threading.Event()
    outcome: dict[str, Any] = {}

    def invoke() -> None:
        try:
            import FlowAPI

            gateway = FlowAPI.Admin.create_gateway_instance(username, password, ip_addr)
            outcome["result"] = gateway.get_mediaspaces(as_admin=True)
            outcome["code"] = gateway.lastReturnCode()
        except BaseException as exc:
            message = f"{type(exc).__name__}: {exc}"
            for secret in sorted({username, password, ip_addr}, key=len, reverse=True):
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            outcome["error"] = message
        finally:
            completed.set()

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    if not completed.wait(timeout):
        raise FetchError(f"Keine Antwort der Admin-API nach {timeout} s")
    if "error" in outcome:
        raise FetchError(f"Admin-API-Fehler: {outcome['error']}")

    code = outcome["code"]
    if code != 200:
        raise FetchError(f"Admin-API antwortet mit HTTP {code}")

    result = outcome["result"]
    if not isinstance(result, list):
        raise FetchError("Admin-API liefert keine Liste")
    if not result:
        raise FetchError("Admin-API liefert keine Spaces")
    return result
