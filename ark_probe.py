# IMPORTS
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


# CONFIG
app_name = "ark_probe"
app_version = "0.1.0"
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
    pass


@dataclass
class ScanStats:
    total: int = 0
    pages: int = 0
    files: int = 0
    complete: bool = False
    interrupted: bool = False
    stop_reason: str = ""


def connect_ark(cred_path: Path) -> Any:
    if not cred_path.is_file():
        raise ProbeError(f"Zugangsdaten fehlen: {cred_path} mit ARK_HOST, ARK_USER, ARK_PASSWORD anlegen.")
    # Lazy import keeps tests free of FlowAPI.
    from toolbox import tb_link_api

    ark = tb_link_api(cred_path, "ark")
    if ark is None:
        raise ProbeError("Keine Ark-Verbindung, cred.env prüfen.")
    return ark


def result_dict(result: Any) -> dict[str, Any]:
    return {"code": result.code, "error": result.error, "message": result.message, "data": result.data}


def write_json(path: Path, result: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(result_dict(result), handle, ensure_ascii=False, indent=2, default=str)


def write_csv(path: Path, header: list[str], rows: Iterable[list[Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


def format_tb(num_bytes: int) -> str:
    return f"{num_bytes / 10**12:.4f}".replace(".", ",")


def backup_index(backups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(backup["backup_id"]): backup for backup in backups if isinstance(backup, dict) and backup.get("backup_id")}


def file_key(item: dict[str, Any]) -> str:
    flow_hash = str(item.get("flow_hash") or "").strip()
    return flow_hash or f"{item.get('path', '')}/{item.get('filename', '')}|{item.get('size', '')}"


class SizeTotals:
    def __init__(self, index: dict[str, dict[str, Any]]):
        self.index = index
        self.unmatched: set[str] = set()
        self._backups: dict[str, dict[str, Any]] = {}
        self._spaces: dict[tuple[str, str], dict[str, Any]] = {}

    def add(self, results: list[dict[str, Any]]) -> None:
        for item in results:
            backup_id = str(item.get("backup_id") or "")
            size = int(item.get("size") or 0)
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
        rows = [[backup_id, total["name"], total["kind"], total["destination_name"], total["date"], "ja" if total["matched"] else "nein", total["files"], total["bytes"], format_tb(total["bytes"])] for backup_id, total in self._backups.items()]
        return sorted(rows, key=lambda row: (str(row[1]).casefold(), str(row[4]), str(row[0])))

    def space_rows(self) -> list[list[Any]]:
        rows = [[total["name"], total["uuid"], total["kind"], len(total["backups"]), total["files"], total["bytes"], format_tb(total["bytes"]), total["unique_files"], total["unique_bytes"], format_tb(total["unique_bytes"])] for total in self._spaces.values()]
        return sorted(rows, key=lambda row: (str(row[0]).casefold(), str(row[2])))


def scan_files(ark: Any, page_limit: int, max_pages: int, on_page: Callable[[list[dict[str, Any]]], None], on_progress: Callable[[str], None] = print) -> ScanStats:
    stats = ScanStats()
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
            on_page(results)
            on_progress(f"Seite {stats.pages}: {stats.files} von {stats.total} Dateien")
            if stats.files >= stats.total:
                stats.complete = True
                stats.stop_reason = "fertig"
                return stats
    except KeyboardInterrupt:
        stats.interrupted = True
        stats.stop_reason = "abgebrochen"
        return stats


def sample_backup_id(backups: list[dict[str, Any]]) -> str | None:
    for backup in backups:
        if backup.get("destination_type") == "__tape__" and backup.get("backup_id"):
            return str(backup["backup_id"])
    for backup in backups:
        if backup.get("backup_id"):
            return str(backup["backup_id"])
    return None


def _write_summary(path: Path, values: list[tuple[str, Any]], on_progress: Callable[[str], None]) -> None:
    lines = [f"{key}: {value}" for key, value in values]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for line in lines:
        on_progress(line)


def run_probe(ark: Any, out_dir: Path, page_limit: int, max_pages: int, on_progress: Callable[[str], None] = print) -> int:
    if not 1 <= page_limit <= 10000 or max_pages < 1:
        raise ProbeError("page_limit muss zwischen 1 und 10000 und max_pages mindestens 1 sein.")
    out_dir.mkdir(parents=True, exist_ok=True)
    backups_result = ark.get_backups()
    write_json(out_dir / "backups.json", backups_result)
    backups: list[dict[str, Any]] = []
    totals = SizeTotals({})
    stats = ScanStats()
    contents_status = "nicht ausgeführt"
    if backups_result.code != 200:
        on_progress(f"get_backups fehlgeschlagen: HTTP {backups_result.code} {backups_result.message}")
        _write_summary(out_dir / "summary.txt", [
            ("app", f"{app_name} {app_version}"), ("ausgabe", str(out_dir)), ("backups", "-"),
            ("suche", "nicht ausgeführt"), ("total_matches", "-"), ("seiten", "-"), ("dateien", "-"),
            ("vollständig", "-"), ("stopgrund", "-"), ("backup_ids ohne zuordnung", "-"), ("inhalt_backup", "nicht ausgeführt"),
        ], on_progress)
        return 1

    backups = [item for item in (backups_result.data if isinstance(backups_result.data, list) else []) if isinstance(item, dict)]
    backup_rows = [[item.get(key, "") for key in BACKUPS_HEADER] for item in sorted(backups, key=lambda item: (str(item.get("media_space_name") or "").casefold(), str(item.get("date") or "")))]
    write_csv(out_dir / "backups.csv", BACKUPS_HEADER, backup_rows)
    index = backup_index(backups)

    search_result = ark.search_backups("*", "wildcard", limit=1, offset=0)
    write_json(out_dir / "search_sample.json", search_result)
    if search_result.code == 200:
        totals = SizeTotals(index)
        try:
            with (out_dir / "files.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(FILE_HEADER)

                def on_page(results: list[dict[str, Any]]) -> None:
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
                    totals.add(results)

                stats = scan_files(ark, page_limit, max_pages, on_page, on_progress)
        finally:
            write_csv(out_dir / "sizes_by_backup.csv", BACKUP_HEADER, totals.backup_rows())
            write_csv(out_dir / "sizes_by_space.csv", SPACE_HEADER, totals.space_rows())

    backup_summary = f"{len(backups)} (tape: {sum(item.get('destination_type') == '__tape__' for item in backups)}, disk: {sum(item.get('destination_type') == '__disk__' for item in backups)})"
    if search_result.code == 200:
        search_status = f"HTTP {search_result.code} {search_result.message}"
        total_matches: Any = stats.total
        pages: Any = stats.pages
        files: Any = stats.files
        complete = "ja" if stats.complete else "nein"
        stop_reason = stats.stop_reason or "-"
    else:
        search_status = f"HTTP {search_result.code} {search_result.message}"
        total_matches = pages = files = complete = stop_reason = "-"

    if not stats.interrupted:
        bid = sample_backup_id(backups)
        if bid:
            contents = ark.get_backup_contents(bid)
            write_json(out_dir / "backup_contents_sample.json", contents)
            contents_status = f"{bid} HTTP {contents.code}"
        else:
            contents_status = "kein Backup"

    _write_summary(out_dir / "summary.txt", [
        ("app", f"{app_name} {app_version}"), ("ausgabe", str(out_dir)), ("backups", backup_summary),
        ("suche", search_status), ("total_matches", total_matches), ("seiten", pages), ("dateien", files),
        ("vollständig", complete), ("stopgrund", stop_reason),
        ("backup_ids ohne zuordnung", ", ".join(sorted(totals.unmatched, key=str.casefold)) or "-"), ("inhalt_backup", contents_status),
    ], on_progress)
    return 130 if stats.interrupted else 0


# MAIN
def main() -> int:
    out_dir = out_root / datetime.now().strftime("%Y-%m-%d_%H%M")
    try:
        ark = connect_ark(cred_path)
        return run_probe(ark, out_dir, page_limit, max_pages)
    except ProbeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Abgebrochen.", file=sys.stderr)
        return 130


# EXEC
if __name__ == "__main__":
    raise SystemExit(main())
