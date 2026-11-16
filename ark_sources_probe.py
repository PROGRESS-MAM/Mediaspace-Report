# IMPORTS
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any, Callable

from ark_probe import ProbeError, connect_ark, cred_path, format_elapsed, out_root, setup_console, write_csv, write_json


# CONFIG
app_name = "ark_sources_probe"
app_version = "0.1.0"
call_timeout = 180
SUMMARY_HEADER = ["schritt", "aufruf", "status", "http", "sekunden", "aufbau", "groessenfelder", "datei", "fehler"]


# FUNC
@dataclass
class CallOutcome:
    status: str
    result: Any = None
    seconds: float = 0.0
    error: str = ""


def call_with_timeout(
    func: Callable[[], Any],
    timeout: float,
    on_wait: Callable[[float], None] | None = None,
    wait_report: float = 15.0,
    poll: float = 0.5,
) -> CallOutcome:
    """Run one call in an abandonable daemon thread."""
    completed = threading.Event()
    state: dict[str, Any] = {}
    started = time.monotonic()
    deadline = started + timeout
    next_report = wait_report

    def run() -> None:
        try:
            state["result"] = func()
        except Exception as error:
            state["error"] = f"{type(error).__name__}: {error}"
        finally:
            state["completed_at"] = time.monotonic()
            completed.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    while True:
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            return CallOutcome("timeout", seconds=elapsed)
        # Short joins keep KeyboardInterrupt responsive, including on Windows.
        thread.join(min(poll, timeout - elapsed))
        elapsed = time.monotonic() - started
        if completed.is_set():
            if state["completed_at"] >= deadline:
                return CallOutcome("timeout", seconds=elapsed)
            if "error" in state:
                return CallOutcome("error", seconds=elapsed, error=state["error"])
            result = state.get("result")
            try:
                status = "ok" if 200 <= result.code < 300 else "http"
            except Exception as error:
                return CallOutcome("error", seconds=elapsed, error=f"{type(error).__name__}: {error}")
            return CallOutcome(status, result=result, seconds=elapsed)
        if elapsed >= timeout:
            return CallOutcome("timeout", seconds=elapsed)
        if on_wait is not None and elapsed >= next_report:
            on_wait(elapsed)
            while next_report <= elapsed:
                next_report += wait_report


def size_keys(data: Any, max_nodes: int = 200000) -> list[str]:
    """Return up to ten distinct size-related mapping keys."""
    terms = ("size", "byte", "capacity", "used", "remaining", "free", "length")
    found: list[str] = []
    seen: set[str] = set()
    pending = [iter(((False, data),))]
    visited = 0
    while pending and visited < max_nodes and len(found) < 10:
        try:
            is_key, value = next(pending[-1])
        except StopIteration:
            pending.pop()
            continue
        visited += 1
        if is_key:
            name = str(value)
            folded = name.casefold()
            if name not in seen and any(term in folded for term in terms):
                seen.add(name)
                found.append(name)
        elif isinstance(value, dict):
            pending.append(iter(node for item in value.items() for node in ((True, item[0]), (False, item[1]))))
        elif isinstance(value, list):
            pending.append(iter((False, child) for child in value))
    return found


def shape(data: Any) -> str:
    """Describe the top-level response shape compactly."""
    if isinstance(data, list):
        return f"list[{len(data)}]"
    if isinstance(data, dict):
        keys = ",".join(str(key) for key in islice(data, 8))
        return f"dict{{{keys}}}"
    if isinstance(data, str):
        return f"str[{len(data)}]"
    if data is None:
        return "None"
    return type(data).__name__


def pick_sample(backups: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Choose the latest media-space backup stored on tape."""
    candidates = [
        item for item in backups
        if isinstance(item, dict)
        and item.get("backup_type") == "__ms__"
        and item.get("destination_type") == "__tape__"
        and item.get("backup_id")
    ]
    if not candidates:
        return None, None
    sample = max(candidates, key=lambda item: str(item.get("date")))
    return str(sample["backup_id"]), str(sample["destination_id"]) if sample.get("destination_id") else None


def _summary_row(
    number: int,
    label: str,
    status: str,
    result: Any = None,
    seconds: float = 0.0,
    filename: str = "",
    error: str = "",
) -> list[str]:
    code = getattr(result, "code", "") if result is not None else ""
    data = getattr(result, "data", None) if result is not None else None
    return [
        str(number), label, status, str(code) if code != "" else "",
        f"{seconds:.1f}".replace(".", ","), shape(data) if result is not None else "",
        "|".join(size_keys(data)) if result is not None else "", filename, error,
    ]


def run_sources_probe(
    connect: Callable[[], Any],
    out_dir: Path,
    timeout: float,
    on_progress: Callable[[str], None] = print,
) -> int:
    """Probe the ten approved Ark endpoints and persist each response."""
    rows: list[list[str]] = []
    current_row: list[str] | None = None
    sample_backup_id: str | None = None
    sample_pool_id: str | None = None
    sample_available = False
    steps = [
        ("get_backups", "get_backups()", (), {}),
        ("get_license_status", "get_license_status()", (), {}),
        ("get_file_hash_database_status", "get_file_hash_database_status()", (), {}),
        ("search_backups", "search_backups(exact, kein Treffer)", ("ark_probe_kein_treffer.xyz", "exact"), {"limit": 1, "offset": 0}),
        ("get_pools", "get_pools()", (), {}),
        ("get_tape_library_status", "get_tape_library_status()", (), {}),
        ("get_tape_backups", "get_tape_backups()", (), {}),
        ("get_backup_contents", "", (), {}),
        ("get_pool_contents", "", (), {}),
        ("get_jobs_completed", "get_jobs_completed()", (), {}),
    ]

    def persist_summary() -> None:
        write_csv(out_dir / "sources_summary.csv", SUMMARY_HEADER, rows)

    try:
        for number, (method_name, base_label, args, kwargs) in enumerate(steps, start=1):
            if number == 8:
                label = f"get_backup_contents({sample_backup_id})"
                args = (sample_backup_id,) if sample_backup_id is not None else ()
            elif number == 9:
                label = f"get_pool_contents({sample_pool_id}, 0)"
                args = (sample_pool_id, 0) if sample_pool_id is not None else ()
            else:
                label = base_label

            sample_missing = not sample_available or sample_backup_id is None or sample_pool_id is None
            skipped = number in {8, 9} and sample_missing
            if skipped:
                current_row = _summary_row(number, label, "übersprungen", error="kein Beispiel-Backup")
                rows.append(current_row)
                persist_summary()
                on_progress(f"[{number}/10] {label} ...")
                on_progress("      übersprungen: kein Beispiel-Backup")
                continue

            current_row = _summary_row(number, label, "läuft")
            rows.append(current_row)
            persist_summary()
            on_progress(f"[{number}/10] {label} ...")

            def invoke(method_name: str = method_name, args: tuple[Any, ...] = args, kwargs: dict[str, Any] = kwargs) -> Any:
                # Each endpoint gets a fresh connection, covered by this call's deadline.
                ark = connect()
                if method_name == "get_backups":
                    return ark.get_backups()
                if method_name == "get_license_status":
                    return ark.get_license_status()
                if method_name == "get_file_hash_database_status":
                    return ark.get_file_hash_database_status()
                if method_name == "search_backups":
                    return ark.search_backups(args[0], args[1], **kwargs)
                if method_name == "get_pools":
                    return ark.get_pools()
                if method_name == "get_tape_library_status":
                    return ark.get_tape_library_status()
                if method_name == "get_tape_backups":
                    return ark.get_tape_backups()
                if method_name == "get_backup_contents":
                    return ark.get_backup_contents(args[0])
                if method_name == "get_pool_contents":
                    return ark.get_pool_contents(args[0], args[1])
                if method_name == "get_jobs_completed":
                    return ark.get_jobs_completed()
                raise ValueError(f"Unbekannter Ark-Aufruf: {method_name}")

            outcome = call_with_timeout(
                invoke,
                timeout,
                on_wait=lambda elapsed: on_progress(f"      wartet seit {format_elapsed(elapsed)}"),
            )
            filename = ""
            error = outcome.error
            if outcome.status in {"ok", "http"}:
                filename = f"{number:02d}_{method_name}.json"
                write_json(out_dir / filename, outcome.result)
                on_progress(
                    f"      {outcome.status}, HTTP {outcome.result.code}, {format_elapsed(outcome.seconds)}, "
                    f"{shape(outcome.result.data)}, Größenfelder: {', '.join(size_keys(outcome.result.data)) or '-'}"
                )
            elif outcome.status == "timeout":
                on_progress(f"      timeout nach {format_elapsed(outcome.seconds)}, weiter mit nächstem Schritt")
            else:
                on_progress(f"      Fehler: {outcome.error}")
            current_row = _summary_row(number, label, outcome.status, outcome.result, outcome.seconds, filename, error)
            rows[-1] = current_row
            persist_summary()

            if number == 1:
                data = outcome.result.data if outcome.status == "ok" else None
                if isinstance(data, list):
                    sample_available = True
                    sample_backup_id, sample_pool_id = pick_sample(data)

        ok_count = sum(row[2] in {"ok", "http"} for row in rows)
        on_progress(f"Fertig: {ok_count} von 10 Schritten mit Antwort. Ergebnisse in {out_dir}")
        return 0
    except KeyboardInterrupt:
        if current_row is not None:
            current_row[2] = "abgebrochen"
            current_row[8] = ""
            persist_summary()
        step_number = current_row[0] if current_row is not None else "1"
        try:
            on_progress(f"Abgebrochen in Schritt {step_number}/10. Bisherige Ergebnisse in {out_dir}")
        except KeyboardInterrupt:
            pass
        return 130


# MAIN
def main() -> int:
    """Prepare the output folder and run the Ark source probe."""
    try:
        setup_console()
        out_dir = out_root / (datetime.now().strftime("%Y-%m-%d_%H%M") + "_sources")
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"{app_name} {app_version}", flush=True)
        print(f"Ausgabe: {out_dir}", flush=True)
        if not cred_path.is_file():
            print(f"Zugangsdaten fehlen: {cred_path} mit ARK_HOST, ARK_USER, ARK_PASSWORD anlegen.", file=sys.stderr, flush=True)
            return 1
        connect = lambda: connect_ark(cred_path)
        return run_sources_probe(connect, out_dir, call_timeout, lambda text: print(text, flush=True))
    except ProbeError as error:
        print(str(error), file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("Abgebrochen.", file=sys.stderr, flush=True)
        return 130


# EXEC
if __name__ == "__main__":
    raise SystemExit(main())
