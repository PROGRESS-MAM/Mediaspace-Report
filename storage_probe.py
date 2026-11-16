# IMPORTS
import csv
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


# CONFIG
app_name = "storage_probe"
app_version = "0.1.0"
cred_path = Path(__file__).parent / "cred.env"
out_root = Path(__file__).parent / "probe_output"
call_timeout = 180
summary_header = ["step", "call", "status", "http_code", "duration_s", "shape", "fields"]


# FUNC
def run_call(fn: Callable[[], Any], timeout: float) -> tuple[str, Any, str, float]:
    """Run one function in a daemon thread and return when its time limit expires."""
    started = time.monotonic()
    completed = threading.Event()
    outcome: dict[str, Any] = {}

    def invoke() -> None:
        try:
            outcome["result"] = fn()
            outcome["status"] = "ok"
        except BaseException as exc:
            outcome["status"] = "error"
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            completed.set()

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    if not completed.wait(max(0.0, timeout)):
        return "timeout", None, f"Aufrufzeitlimit ({timeout} s) überschritten", time.monotonic() - started
    duration_s = time.monotonic() - started
    return outcome["status"], outcome.get("result"), outcome.get("error", ""), duration_s


def key_paths(obj: Any) -> list[str]:
    """Return all mapping-key paths, using [] for list elements."""
    paths: set[str] = set()
    pending = [(obj, "")]
    while pending:
        value, prefix = pending.pop()
        if isinstance(value, dict):
            items = list(value.items())
            for key, child in items:
                path = f"{prefix}.{key}" if prefix else str(key)
                paths.add(path)
                pending.append((child, path))
        elif isinstance(value, list):
            item_prefix = f"{prefix}[]" if prefix else "[]"
            pending.extend((child, item_prefix) for child in value)
    return sorted(paths)


def _call_editshare(username: str, password: str, ip_addr: str, method: str, *args: Any, **kwargs: Any) -> tuple[Any, int]:
    import FlowAPI

    gateway = FlowAPI.EditShare.create_gateway_instance(username, password, ip_addr)
    result = getattr(gateway, method)(*args, **kwargs)
    return result, gateway.lastReturnCode()


def _call_admin(username: str, password: str, ip_addr: str, method: str, *args: Any, **kwargs: Any) -> tuple[Any, int]:
    import FlowAPI

    gateway = FlowAPI.Admin.create_gateway_instance(username, password, ip_addr)
    result = getattr(gateway, method)(*args, **kwargs)
    return result, gateway.lastReturnCode()


def _shape(result: Any) -> str:
    try:
        return f"{type(result).__name__}[{len(result)}]"
    except TypeError:
        return type(result).__name__


def _write_summary(path: Path, rows: list[list[Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(summary_header)
        writer.writerows(rows)


def _write_step(
    step: int,
    call: str,
    fn: Callable[[], Any] | None,
    output_dir: Path,
    summary_rows: list[list[Any]],
) -> dict[str, Any]:
    if fn is None:
        status, result, error, http_code, duration_s = "skipped", None, "Kein Space-Name in Schritt 1 gefunden", None, 0.0
    else:
        status, call_result, error, duration_s = run_call(fn, call_timeout)
        result = None
        http_code = None
        if status == "ok":
            result, http_code = call_result
            if http_code != 200:
                status = "http_error"
            elif not result:
                status = "empty"
            error = ""

    payload = {
        "call": call,
        "status": status,
        "http_code": http_code,
        "duration_s": duration_s,
        "error": error,
        "result": result,
    }
    json_path = output_dir / f"{step:02d}_{call}.json"
    with json_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")

    summary_rows.append([
        step,
        call,
        status,
        "" if http_code is None else http_code,
        duration_s,
        _shape(result),
        "|".join(key_paths(result)),
    ])
    _write_summary(output_dir / "storage_summary.csv", summary_rows)
    print(f"[{step}/4] {call}: {status} ({duration_s:.1f} s)")
    return payload


def _find_space_name(value: Any) -> str | None:
    name_keys = ("name", "space_name", "mediaspace_name")
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key in name_keys:
                name = current.get(key)
                if isinstance(name, str):
                    return name
            pending.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            pending.extend(reversed(current))
    return None


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except (OSError, ValueError):
                pass


# MAIN
def main() -> int:
    _configure_console()
    from dotenv import load_dotenv

    load_dotenv(cred_path)
    required = ("FLOW_HOST", "FLOW_USER", "FLOW_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        print(f"Fehlt in cred.env: {', '.join(missing)}")
        return 1

    username, password, ip_addr = (os.environ[name] for name in ("FLOW_USER", "FLOW_PASSWORD", "FLOW_HOST"))
    output_dir = out_root / f"{datetime.now():%Y-%m-%d_%H%M}_storage"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[list[Any]] = []

    try:
        first = _write_step(
            1,
            "storage_get_spaces_details",
            lambda: _call_editshare(username, password, ip_addr, "get_spaces", details=True),
            output_dir,
            summary_rows,
        )
        _write_step(
            2,
            "storage_get_spaces",
            lambda: _call_editshare(username, password, ip_addr, "get_spaces"),
            output_dir,
            summary_rows,
        )
        space_name = _find_space_name(first["result"])
        _write_step(
            3,
            "storage_get_space",
            None if space_name is None else lambda: _call_editshare(username, password, ip_addr, "get_space", space_name),
            output_dir,
            summary_rows,
        )
        _write_step(
            4,
            "admin_get_mediaspaces",
            lambda: _call_admin(username, password, ip_addr, "get_mediaspaces", as_admin=True),
            output_dir,
            summary_rows,
        )
    except KeyboardInterrupt:
        return 130
    return 0


# EXEC
if __name__ == "__main__":
    raise SystemExit(main())
