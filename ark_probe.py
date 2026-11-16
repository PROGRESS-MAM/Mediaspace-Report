# IMPORTS
import csv
import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


# CONFIG
app_name = "ark_probe"
app_version = "0.2.0"
script_dir = Path(__file__).resolve().parent
cred_path = script_dir / "cred.env"
out_root = script_dir / "probe_output"
page_limit = 10000
max_pages = 1000

BACKUPS_HEADER = ["backup_id", "media_space_name", "media_space_uuid", "backup_type", "destination_type", "destination_name", "date", "job_name", "backup_path"]
FILE_HEADER = ["backup_id", "backup_type", "space_name", "media_space_name", "path", "filename", "size", "flow_hash", "backup_date_unix", "tapes"]
BACKUP_HEADER = ["backup_id", "media_space_name", "backup_type", "destination_name", "date", "matched", "files", "bytes", "tb"]
SPACE_HEADER = ["media_space_name", "media_space_uuid", "backup_type", "backups", "files", "bytes", "tb", "unique_files", "unique_bytes", "unique_tb"]


# FUNC
class ProbeError(Exception):
    """Raised when probe configuration is invalid."""


@dataclass
class ScanStats:
    """Counts and completion state for a file scan."""

    total: int = 0
    pages: int = 0
    files: int = 0
    complete: bool = False
    interrupted: bool = False
    stop_reason: str = ""


@dataclass
class ProbeState:
    """Values persisted in the current run summary."""

    out_dir: Path
    started: float = field(default_factory=time.monotonic)
    status: str = "läuft"
    step: str = "-"
    error: str = "-"
    backups: str = "-"
    search: str = "nicht ausgeführt"
    total_matches: Any = "-"
    pages: Any = "-"
    files: Any = "-"
    complete: str = "-"
    stop_reason: str = "-"
    unmatched: Any = "-"
    invalid_sizes: Any = "-"
    contents: str = "nicht ausgeführt"


def connect_ark(cred_path: Path) -> Any:
    """Create the Ark connection using the local credential file."""
    if not cred_path.is_file():
        raise ProbeError(f"Zugangsdaten fehlen: {cred_path} mit ARK_HOST, ARK_USER, ARK_PASSWORD anlegen.")
    # Lazy import keeps tests free of FlowAPI.
    from toolbox import tb_link_api

    ark = tb_link_api(cred_path, "ark")
    if ark is None:
        raise ProbeError("Keine Ark-Verbindung, cred.env prüfen.")
    return ark


def result_dict(result: Any) -> dict[str, Any]:
    """Return an Ark result in a JSON-serializable mapping."""
    return {"code": result.code, "error": result.error, "message": result.message, "data": result.data}


def write_json(path: Path, result: Any) -> None:
    """Write an Ark response as UTF-8 JSON."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(result_dict(result), handle, ensure_ascii=False, indent=2, default=str)


def write_csv(path: Path, header: list[str], rows: Iterable[list[Any]]) -> None:
    """Write a semicolon-delimited CSV with a UTF-8 BOM."""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


def format_tb(num_bytes: int) -> str:
    """Format bytes as decimal terabytes using a decimal comma."""
    return f"{num_bytes / 10**12:.4f}".replace(".", ",")


def format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as minutes and seconds."""
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d} min"


def backup_index(backups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index backups by their identifier."""
    return {str(backup["backup_id"]): backup for backup in backups if isinstance(backup, dict) and backup.get("backup_id")}


def file_key(item: dict[str, Any]) -> str:
    """Return the deduplication key for a file record."""
    flow_hash = str(item.get("flow_hash") or "").strip()
    return flow_hash or f"{item.get('path', '')}/{item.get('filename', '')}|{item.get('size', '')}"


class SizeTotals:
    """Accumulate backup and media-space file sizes."""

    def __init__(self, index: dict[str, dict[str, Any]]) -> None:
        """Create totals using the available backup index."""
        self.index = index
        self.unmatched: set[str] = set()
        self.invalid_sizes: int = 0
        self._backups: dict[str, dict[str, Any]] = {}
        self._spaces: dict[tuple[str, str], dict[str, Any]] = {}

    def add(self, results: list[dict[str, Any]]) -> None:
        """Add file records, treating invalid sizes as zero bytes."""
        for item in results:
            backup_id = str(item.get("backup_id") or "")
            raw_size = item.get("size")
            try:
                if isinstance(raw_size, bool):
                    raise ValueError
                size = int(raw_size)
            except (TypeError, ValueError):
                size = 0
                self.invalid_sizes += 1
            kind = str(item.get("backup_type") or "")
            backup = self.index.get(backup_id)
            name = str((backup or {}).get("media_space_name") or item.get("space_name") or "")
            uuid = str(backup.get("media_space_uuid") or "") if backup else ""
            if backup is None:
                self.unmatched.add(backup_id)

            backup_total = self._backups.setdefault(backup_id, {
                "name": name,
                "kind": kind,
                "destination_name": backup.get("destination_name", "") if backup else "",
                "date": backup.get("date", "") if backup else "",
                "matched": backup is not None,
                "files": 0,
                "bytes": 0,
            })
            backup_total["files"] += 1
            backup_total["bytes"] += size

            space_key = (uuid or name, kind)
            space_total = self._spaces.setdefault(space_key, {
                "name": name,
                "uuid": uuid,
                "kind": kind,
                "backups": set(),
                "files": 0,
                "bytes": 0,
                "file_keys": set(),
                "unique_files": 0,
                "unique_bytes": 0,
            })
            space_total["backups"].add(backup_id)
            space_total["files"] += 1
            space_total["bytes"] += size
            key = file_key(item)
            if key not in space_total["file_keys"]:
                space_total["file_keys"].add(key)
                space_total["unique_files"] += 1
                space_total["unique_bytes"] += size

    def backup_rows(self) -> list[list[Any]]:
        """Return size totals grouped by backup."""
        rows = [[backup_id, total["name"], total["kind"], total["destination_name"], total["date"], "ja" if total["matched"] else "nein", total["files"], total["bytes"], format_tb(total["bytes"])] for backup_id, total in self._backups.items()]
        return sorted(rows, key=lambda row: (str(row[1]).casefold(), str(row[4]), str(row[0])))

    def space_rows(self) -> list[list[Any]]:
        """Return size totals grouped by media space and type."""
        rows = [[total["name"], total["uuid"], total["kind"], len(total["backups"]), total["files"], total["bytes"], format_tb(total["bytes"]), total["unique_files"], total["unique_bytes"], format_tb(total["unique_bytes"])] for total in self._spaces.values()]
        return sorted(rows, key=lambda row: (str(row[0]).casefold(), str(row[2])))


def scan_files(
    ark: Any,
    page_limit: int,
    max_pages: int,
    on_page: Callable[[list[dict[str, Any]], ScanStats], None],
    on_progress: Callable[[str], None] = print,
) -> ScanStats:
    """Scan files page by page and report updated scan progress."""
    stats = ScanStats()
    scan_started = time.monotonic()
    try:
        while True:
            if stats.pages >= max_pages:
                stats.stop_reason = f"max_pages {max_pages} erreicht"
                return stats
            page = ark.search_backups("*", "wildcard", limit=page_limit, offset=stats.files)
            if page.code != 200:
                stats.stop_reason = f"HTTP {page.code}: {page.message}"
                return stats
            data = page.data if isinstance(page.data, dict) else {}
            results = [item for item in (data.get("results") or []) if isinstance(item, dict)]
            stats.total = int(data.get("total_matches") or 0)
            if not results:
                stats.complete = stats.files >= stats.total
                stats.stop_reason = "fertig" if stats.complete else "leere Seite vor Ende"
                return stats
            stats.pages += 1
            stats.files += len(results)
            on_page(results, stats)
            pct = stats.files * 100 // stats.total if stats.total else 100
            elapsed = format_elapsed(time.monotonic() - scan_started)
            on_progress(f"      Seite {stats.pages}: {stats.files} von {stats.total} Dateien ({pct} %), {elapsed}")
            if stats.files >= stats.total:
                stats.complete = True
                stats.stop_reason = "fertig"
                return stats
    except KeyboardInterrupt:
        stats.interrupted = True
        stats.stop_reason = "abgebrochen"
        return stats


def sample_backup_id(backups: list[dict[str, Any]]) -> str | None:
    """Choose a tape backup first, falling back to any available backup."""
    for backup in backups:
        if backup.get("destination_type") == "__tape__" and backup.get("backup_id"):
            return str(backup["backup_id"])
    for backup in backups:
        if backup.get("backup_id"):
            return str(backup["backup_id"])
    return None


def summary_lines(state: ProbeState) -> list[str]:
    """Return summary entries in their stable display order."""
    values = [
        ("app", f"{app_name} {app_version}"),
        ("status", state.status),
        ("schritt", state.step),
        ("fehler", state.error),
        ("ausgabe", state.out_dir),
        ("backups", state.backups),
        ("suche", state.search),
        ("total_matches", state.total_matches),
        ("seiten", state.pages),
        ("dateien", state.files),
        ("vollständig", state.complete),
        ("stopgrund", state.stop_reason),
        ("backup_ids ohne zuordnung", state.unmatched),
        ("ungültige größen", state.invalid_sizes),
        ("inhalt_backup", state.contents),
        ("laufzeit", format_elapsed(time.monotonic() - state.started)),
    ]
    return [f"{key}: {value}" for key, value in values]


def write_summary(state: ProbeState) -> None:
    """Persist the current run summary without console output."""
    path = state.out_dir / "summary.txt"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(summary_lines(state)) + "\n")


def setup_console(streams: Iterable[Any] | None = None) -> None:
    """Configure available output streams for visible UTF-8 progress."""
    # VS Code output panels may use cp1252 pipes with block buffering.
    for stream in (sys.stdout, sys.stderr) if streams is None else streams:
        try:
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            continue


def run_probe(
    ark: Any,
    out_dir: Path,
    page_limit: int,
    max_pages: int,
    on_progress: Callable[[str], None] = print,
) -> int:
    """Run the read-only Ark probe and persist each completed step."""
    if not 1 <= page_limit <= 10000 or max_pages < 1:
        raise ProbeError("page_limit muss zwischen 1 und 10000 und max_pages mindestens 1 sein.")
    out_dir.mkdir(parents=True, exist_ok=True)
    state = ProbeState(out_dir)
    result_code = 0

    try:
        write_summary(state)
        backups: list[dict[str, Any]] = []
        totals = SizeTotals({})
        stats = ScanStats()
        state.step = "1/4 Backups lesen"
        write_summary(state)
        on_progress("[1/4] Backups lesen ...")
        backups_result = ark.get_backups()
        write_json(out_dir / "backups.json", backups_result)
        if backups_result.code != 200:
            state.status = "get_backups fehlgeschlagen"
            state.error = f"HTTP {backups_result.code} {backups_result.message}"
            result_code = 1
            on_progress(f"      get_backups fehlgeschlagen: HTTP {backups_result.code} {backups_result.message}")
            write_summary(state)
        else:
            backups = [item for item in (backups_result.data if isinstance(backups_result.data, list) else []) if isinstance(item, dict)]
            backup_rows = [[item.get(key, "") for key in BACKUPS_HEADER] for item in sorted(backups, key=lambda item: (str(item.get("media_space_name") or "").casefold(), str(item.get("date") or "")))]
            write_csv(out_dir / "backups.csv", BACKUPS_HEADER, backup_rows)
            backup_count = len(backups)
            tape_count = sum(item.get("destination_type") == "__tape__" for item in backups)
            disk_count = sum(item.get("destination_type") == "__disk__" for item in backups)
            state.backups = f"{backup_count} (tape: {tape_count}, disk: {disk_count})"
            on_progress(f"      {state.backups}")
            write_summary(state)

            index = backup_index(backups)
            state.step = "2/4 Dateisuche testen"
            write_summary(state)
            on_progress("[2/4] Dateisuche testen ...")
            search_result = ark.search_backups("*", "wildcard", limit=1, offset=0)
            write_json(out_dir / "search_sample.json", search_result)
            search_data = search_result.data if isinstance(search_result.data, dict) else {}
            raw_total_matches = search_data.get("total_matches")
            total_matches = "-" if raw_total_matches is None else raw_total_matches
            state.search = f"HTTP {search_result.code} {search_result.message}, total_matches: {total_matches}"
            state.total_matches = total_matches if search_result.code == 200 else "-"
            on_progress(f"      {state.search}")
            write_summary(state)

            if search_result.code == 200:
                totals = SizeTotals(index)
                state.unmatched = 0
                state.invalid_sizes = 0
                state.pages = 0
                state.files = 0
                locked_size_csvs: set[str] = set()
                scan_error: BaseException | None = None
                try:
                    with (out_dir / "files.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                        writer = csv.writer(handle, delimiter=";")
                        writer.writerow(FILE_HEADER)
                        handle.flush()
                        state.step = "3/4 Alle Dateien lesen"
                        write_summary(state)
                        on_progress("[3/4] Alle Dateien lesen ...")

                        def on_page(results: list[dict[str, Any]], page_stats: ScanStats) -> None:
                            rows = []
                            for item in results:
                                backup = index.get(str(item.get("backup_id") or ""))
                                rows.append([
                                    item.get("backup_id", ""), item.get("backup_type", ""), item.get("space_name", ""),
                                    backup.get("media_space_name", "") if backup else "", item.get("path", ""), item.get("filename", ""),
                                    item.get("size", ""), item.get("flow_hash", ""), item.get("backup_date_unix", ""),
                                    "|".join(str(tape) for tape in (item.get("tapes") or [])),
                                ])
                            writer.writerows(rows)
                            handle.flush()
                            totals.add(results)
                            state.pages = page_stats.pages
                            state.files = page_stats.files
                            state.total_matches = page_stats.total
                            state.unmatched = len(totals.unmatched)
                            state.invalid_sizes = totals.invalid_sizes
                            for name, header, rows in (
                                ("sizes_by_backup.csv", BACKUP_HEADER, totals.backup_rows()),
                                ("sizes_by_space.csv", SPACE_HEADER, totals.space_rows()),
                            ):
                                try:
                                    write_csv(out_dir / name, header, rows)
                                except PermissionError:
                                    if name not in locked_size_csvs:
                                        locked_size_csvs.add(name)
                                        on_progress(f"      Hinweis: {name} ist gesperrt (in Excel geöffnet?) und wird erst am Ende geschrieben.")
                            write_summary(state)

                        stats = scan_files(ark, page_limit, max_pages, on_page, on_progress)
                except BaseException as error:
                    scan_error = error
                    raise
                finally:
                    for name, header, rows in (
                        ("sizes_by_backup.csv", BACKUP_HEADER, totals.backup_rows()),
                        ("sizes_by_space.csv", SPACE_HEADER, totals.space_rows()),
                    ):
                        try:
                            write_csv(out_dir / name, header, rows)
                        except Exception:
                            if scan_error is None:
                                raise

                state.pages = stats.pages
                state.files = stats.files
                state.total_matches = stats.total
                state.complete = "ja" if stats.complete else "nein"
                state.stop_reason = stats.stop_reason or "-"
                state.unmatched = len(totals.unmatched)
                state.invalid_sizes = totals.invalid_sizes
                write_summary(state)
                if stats.interrupted:
                    state.status = "abgebrochen"
                    result_code = 130

            if not stats.interrupted:
                state.step = "4/4 Inhalt eines Tape-Backups lesen"
                write_summary(state)
                on_progress("[4/4] Inhalt eines Tape-Backups lesen ...")
                bid = sample_backup_id(backups)
                if bid:
                    on_progress("      Kann dauern; Strg+C bricht ab, alle bisherigen Ergebnisse sind gespeichert.")
                    contents = ark.get_backup_contents(bid)
                    write_json(out_dir / "backup_contents_sample.json", contents)
                    state.contents = f"{bid} HTTP {contents.code}"
                    on_progress(f"      {state.contents}")
                else:
                    state.contents = "kein Backup"
                    on_progress("[4/4] Inhalt eines Tape-Backups lesen - kein Backup vorhanden")
                write_summary(state)

    except KeyboardInterrupt:
        state.status = "abgebrochen"
        result_code = 130
    except Exception as error:
        state.status = "fehler"
        state.error = f"{type(error).__name__}: {error}"
        result_code = 1
        with (out_dir / "traceback.txt").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(traceback.format_exc())

    if state.status == "läuft":
        state.status = "fertig"
    write_summary(state)
    for line in summary_lines(state):
        on_progress(line)

    if state.status == "fertig":
        on_progress(f"Fertig: Ergebnisse in {out_dir}")
    elif state.status == "abgebrochen":
        on_progress(f"Abgebrochen in Schritt {state.step}. Bisherige Ergebnisse in {out_dir}")
    elif state.status == "get_backups fehlgeschlagen":
        on_progress(f"FEHLER in Schritt {state.step}: {state.error}")
    else:
        on_progress(f"FEHLER in Schritt {state.step}: {state.error}. Details in {out_dir / 'traceback.txt'}")
    return result_code


# MAIN
def main() -> int:
    """Configure the console, connect to Ark, and run the probe."""
    setup_console()
    out_dir = out_root / datetime.now().strftime("%Y-%m-%d_%H%M")
    on_progress = lambda text: print(text, flush=True)
    on_progress(f"{app_name} {app_version}")
    on_progress(f"Ausgabe: {out_dir}")
    on_progress("Verbinde mit Ark ...")
    try:
        ark = connect_ark(cred_path)
        on_progress("Verbunden.")
        return run_probe(ark, out_dir, page_limit, max_pages, on_progress)
    except ProbeError as error:
        print(str(error), file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("Abgebrochen.", file=sys.stderr, flush=True)
        return 130
    except Exception as error:
        print(f"FEHLER beim Verbinden: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return 1


# EXEC
if __name__ == "__main__":
    raise SystemExit(main())
