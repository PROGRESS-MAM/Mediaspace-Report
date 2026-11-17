# IMPORTS
import calendar
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from ms_excel import LtoLine, RawLine, ReportLine, prune_reports, report_path, write_workbook
from ms_source import FetchError, fetch_spaces, parse_spaces
from ms_state import (
    SpaceTotal,
    StateError,
    add_snapshot,
    closable_months,
    drop_month,
    group_snapshot_mean,
    last_snapshot_day,
    load_state,
    month_totals,
    save_state,
    snapshot_count,
    snapshot_day,
)


# CONFIG
app_name = "mediaspace_report"
app_version = "0.5.0"
unit_bytes = 2**40
script_dir = Path(__file__).resolve().parent
cred_path = script_dir / "cred.env"
state_path = script_dir / "mediaspace_state.json"
log_path = script_dir / "mediaspace_report.log"
report_dir = script_dir / "reports"
api_timeout = 120
keep_reports = 24


# FUNC
@dataclass(frozen=True)
class SpaceMonth:
    """Monthly storage usage and lifecycle dates for one space."""

    name: str
    byte_days: int
    start: date | None
    end: date | None


@dataclass(frozen=True)
class ReportRow:
    """One project summary or one unassigned space in the report."""

    name: str
    byte_days: int
    start: date | None
    end: date | None
    owner: str


@dataclass(frozen=True)
class Phase:
    """A continuous project activation period and its member space UUIDs."""

    start: date
    end: date | None
    uuids: frozenset[str]


_PROJECT_PATTERN = re.compile(r"^(.+?)[ _-]+(archiv|archive|render|onlining|rushes|project|projekt)$", re.IGNORECASE)


def resolve_report_dir(output_dir: str | None, output_subdir: str | None) -> tuple[Path, Path | None]:
    """Resolve the report directory and optional mounted destination root."""
    if output_dir is None or not output_dir.strip():
        return report_dir, None

    root = Path(output_dir)
    subdir = (output_subdir or "").replace("\\", "/")
    parts = [part for part in subdir.split("/") if part and part != "."]
    if ".." in parts:
        raise ValueError(f"Ungültiges Unterverzeichnis: {output_subdir}")
    return root.joinpath(*parts), root


def parse_project(space_name: str) -> str | None:
    """Return the project prefix when the space name has a recognized suffix."""
    match = _PROJECT_PATTERN.fullmatch(space_name.strip())
    return match.group(1).strip() or None if match else None


def build_rows(spaces: list[SpaceMonth]) -> list[ReportRow]:
    """Group project spaces, retain unassigned spaces, and sort report rows."""
    project_groups: dict[str, list[tuple[SpaceMonth, str]]] = {}
    rows: list[ReportRow] = []

    for space in spaces:
        project = parse_project(space.name)
        if project is None:
            rows.append(ReportRow(space.name, space.byte_days, space.start, space.end, ""))
            continue
        project_groups.setdefault(project.casefold(), []).append((space, project))

    for group in project_groups.values():
        project_name = min(group, key=lambda item: item[0].name.casefold())[1]
        starts = [space.start for space, _ in group if space.start is not None]
        ends = [space.end for space, _ in group]
        rows.append(
            ReportRow(
                project_name,
                sum(space.byte_days for space, _ in group),
                min(starts) if starts else None,
                None if any(end is None for end in ends) else max(ends),
                "Looks",
            )
        )

    owned_rows = sorted((row for row in rows if row.owner), key=lambda row: row.name.casefold())
    unowned_rows = sorted(
        (row for row in rows if not row.owner),
        key=lambda row: (-row.byte_days, row.name.casefold()),
    )
    return owned_rows + unowned_rows


def project_phases(spaces: Iterable[Any]) -> dict[str, list[Phase]]:
    """Group project spaces into activation phases, merging intervals with gaps under two days."""
    intervals: dict[str, list[tuple[date, date | None, str]]] = {}
    for space in spaces:
        project = parse_project(space.name)
        if project is None:
            continue
        intervals.setdefault(project.casefold(), []).append(
            (space.created.date(), space.removed.date() if space.removed else None, space.uuid)
        )

    result: dict[str, list[Phase]] = {}
    for project, project_intervals in intervals.items():
        project_intervals.sort(key=lambda interval: (interval[0], interval[2]))
        phases: list[Phase] = []
        for start, end, uuid in project_intervals:
            if not phases or (
                phases[-1].end is not None and start - phases[-1].end >= timedelta(days=2)
            ):
                phases.append(Phase(start, end, frozenset({uuid})))
                continue
            previous = phases[-1]
            merged_end = None if previous.end is None or end is None else max(previous.end, end)
            phases[-1] = Phase(previous.start, merged_end, previous.uuids | {uuid})
        result[project] = sorted(phases, key=lambda phase: phase.start)
    return result


def phase_for_month(phases: list[Phase], month: str) -> Phase | None:
    """Return the latest phase that started on or before the month's final day."""
    year, month_number = (int(value) for value in month.split("-"))
    last_day = date(year, month_number, calendar.monthrange(year, month_number)[1])
    eligible = [phase for phase in phases if phase.start <= last_day]
    return max(eligible, key=lambda phase: phase.start) if eligible else None


def month_report(
    totals: list[SpaceTotal],
    snapshot_count: int,
    phases: dict[str, list[Phase]],
    month: str,
) -> tuple[list[ReportLine], list[RawLine]]:
    """Build project summary and per-space raw lines for a monthly snapshot report."""
    if snapshot_count == 0:
        return [], []

    rows = build_rows([
        SpaceMonth(
            total.name,
            total.value_sum,
            total.created.date() if total.created else None,
            total.removed.date() if total.removed else None,
        )
        for total in totals
    ])
    report_lines: list[ReportLine] = []
    for row in rows:
        if row.owner:
            phase = phase_for_month(phases.get(row.name.casefold(), []), month)
            start, end = (phase.start, phase.end) if phase is not None else (row.start, row.end)
            associated = [
                total for total in totals
                if (parse_project(total.name) or "").casefold() == row.name.casefold()
                and parse_project(total.name) is not None
            ]
        else:
            start, end = row.start, row.end
            associated = [
                total for total in totals
                if parse_project(total.name) is None and total.name == row.name
            ]
        note = "interpoliert" if any(total.interpolated for total in associated) else ""
        tib = row.byte_days / snapshot_count / unit_bytes
        report_lines.append(ReportLine(row.name, tib, start, end, row.owner, note))

    raw_projects: list[tuple[str, str, RawLine]] = []
    raw_unassigned: list[tuple[str, RawLine]] = []
    for total in totals:
        project = parse_project(total.name)
        line = RawLine(
            total.name,
            total.uuid,
            project or "",
            "Looks" if project else "",
            total.created.date() if total.created else None,
            total.removed.date() if total.removed else None,
            total.snapshots,
            total.value_sum / snapshot_count / unit_bytes,
            "interpoliert" if total.interpolated else "",
        )
        if project:
            raw_projects.append((project.casefold(), total.name.casefold(), line))
        else:
            raw_unassigned.append((total.name.casefold(), line))

    raw_projects.sort(key=lambda item: (item[0], item[1]))
    raw_unassigned.sort(key=lambda item: item[0])
    raw_lines = [item[2] for item in raw_projects] + [item[1] for item in raw_unassigned]
    return report_lines, raw_lines


def status_line(month: str, last_day: date | None, snapshot_count: int, closed: bool) -> str:
    """Format the monthly report status in German date notation."""
    year, month_number = (int(value) for value in month.split("-"))
    status_month = f"{month_number:02d}.{year:04d}"
    status_day = last_day.strftime("%d.%m.%Y") if last_day else "–"
    completion = "abgeschlossen" if closed else "vorläufig"
    return f"Monat {status_month} · Stand {status_day} · {snapshot_count} Snapshots · {completion}"


# RUN

class _FlowHandler(logging.Handler):
    def __init__(self, message_handler: Callable[[str, str], None]) -> None:
        super().__init__()
        self.message_handler = message_handler

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = "error" if record.levelno >= logging.ERROR else "info"
            self.message_handler(level, self.format(record))
        except Exception:
            self.handleError(record)


def _configure_logger(message_handler: Callable[[str, str], None] | None = None) -> logging.Logger:
    logger = logging.getLogger("mediaspace_report")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        if getattr(handler, "_mediaspace_report_handler", False):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler._mediaspace_report_handler = True
    logger.addHandler(file_handler)

    if message_handler is None:
        flow_handler = logging.StreamHandler()
        flow_handler.setFormatter(formatter)
    else:
        flow_handler = _FlowHandler(message_handler)
        flow_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    flow_handler._mediaspace_report_handler = True
    logger.addHandler(flow_handler)
    return logger


def _month_end(month: str) -> date:
    year, month_number = (int(value) for value in month.split("-"))
    return date(year, month_number, calendar.monthrange(year, month_number)[1])


def _update_lto(state: dict, phases: dict[str, list[Phase]], month: str) -> None:
    extra = state.setdefault("extra", {})
    project_means = extra.setdefault("project_means", {})
    lto = extra.setdefault("lto", [])
    grouped: dict[str, list[Any]] = {}
    for total in month_totals(state, month):
        project = parse_project(total.name)
        if project is not None:
            grouped.setdefault(project.casefold(), []).append((total, project))

    for key, totals in grouped.items():
        uuids = {total.uuid for total, _ in totals}
        mean = group_snapshot_mean(state, month, uuids)
        if mean is None:
            continue
        name = min(totals, key=lambda item: item[0].name.casefold())[1]
        project_means[key] = {"month": month, "tib": mean / unit_bytes, "name": name}

    month_end = _month_end(month)
    for key, mean in project_means.items():
        key_phases = phases.get(key, [])
        if not key_phases:
            continue
        phase = key_phases[-1]
        if phase.end is None or phase.end > month_end or mean["month"] < phase.start.strftime("%Y-%m"):
            continue
        start_text = phase.start.isoformat()
        if any(item["key"] == key and item["start"] == start_text for item in lto):
            continue
        lto.append({
            "key": key,
            "project": mean["name"],
            "tib": mean["tib"],
            "start": start_text,
            "end": phase.end.isoformat(),
            "month": phase.end.strftime("%m.%Y"),
        })


def _lto_lines(state: dict) -> list[LtoLine]:
    entries = state.get("extra", {}).get("lto", [])
    lines = [
        LtoLine(
            item["project"],
            item["tib"],
            date.fromisoformat(item["start"]),
            date.fromisoformat(item["end"]),
            item["month"],
            "Looks",
        )
        for item in entries
    ]
    return sorted(lines, key=lambda line: (line.project.casefold(), line.start))


def _write_month(
    state: dict,
    phases: dict[str, list[Phase]],
    month: str,
    closed: bool,
    target_dir: Path,
) -> None:
    totals = month_totals(state, month)
    count = snapshot_count(state, month)
    report_lines, raw_lines = month_report(totals, count, phases, month)
    write_workbook(
        report_path(target_dir, month),
        status_line(month, last_snapshot_day(state, month), count, closed),
        report_lines,
        raw_lines,
        _lto_lines(state),
    )


def _try_write_month(
    logger: logging.Logger,
    state: dict,
    phases: dict[str, list[Phase]],
    month: str,
    closed: bool,
    target_dir: Path,
) -> tuple[bool, bool]:
    path = report_path(target_dir, month)
    try:
        _write_month(state, phases, month, closed, target_dir)
    except OSError:
        logger.exception("Bericht %s konnte nicht geschrieben werden", path.name)
        return False, True
    return True, False


def run(
    now: datetime,
    fetch: Callable[[], list[dict]],
    message_handler: Callable[[str, str], None] | None = None,
    extra_args: str | None = None,
    output_dir: str | None = None,
    output_subdir: str | None = None,
) -> int:
    """Fetch, store and report the nightly Media Space snapshot."""
    logger = _configure_logger(message_handler)
    logger.info("%s %s gestartet", app_name, app_version)
    if extra_args:
        logger.info("Zusatzargumente: %s", extra_args)
    try:
        target_dir, mount_root = resolve_report_dir(output_dir, output_subdir)
    except ValueError as error:
        logger.error("%s", error)
        target_dir = mount_root = None
    else:
        logger.info("Berichtsordner: %s", target_dir)
    try:
        state = load_state(state_path)
    except StateError as error:
        logger.error("%s", error)
        return 1

    try:
        raw = fetch()
    except FetchError as error:
        logger.error("%s", error)
        return 1

    try:
        spaces = parse_spaces(raw)
        day = snapshot_day(now)
        add_snapshot(state, day, spaces)
    except StateError as error:
        logger.error("%s", error)
        return 1

    phases = project_phases(spaces)
    next_day = day + timedelta(days=1)
    open_month = next_day.strftime("%Y-%m") if next_day.day == 1 else day.strftime("%Y-%m")
    write_failed = False
    report_dir_ready = True
    if target_dir is None:
        report_dir_ready = False
        write_failed = True
    elif mount_root is not None and not mount_root.is_dir():
        logger.error("Ziel-Space nicht verfügbar: %s – Berichte werden beim nächsten Lauf geschrieben", mount_root)
        report_dir_ready = False
        write_failed = True
    else:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.exception("Berichtsordner %s konnte nicht angelegt werden", target_dir)
            report_dir_ready = False
            write_failed = True

    closed_months: list[str] = []
    if report_dir_ready:
        for month in closable_months(state, day):
            _update_lto(state, phases, month)
            written, failed = _try_write_month(logger, state, phases, month, True, target_dir)
            write_failed = write_failed or failed
            if written:
                drop_month(state, month)
                closed_months.append(month)

        written, failed = _try_write_month(logger, state, phases, open_month, False, target_dir)
        write_failed = write_failed or failed

    try:
        save_state(state_path, state)
    except OSError:
        logger.exception("Zustand konnte nicht gespeichert werden: %s", state_path)
        write_failed = True

    if report_dir_ready:
        try:
            prune_reports(target_dir, keep_reports)
        except OSError:
            logger.warning("Berichte in %s konnten nicht bereinigt werden", target_dir, exc_info=True)

    active_spaces = sum(space.removed is None for space in spaces)
    closed_text = ", ".join(closed_months) if closed_months else "–"
    logger.info(
        "Snapshot %s: %s aktive Spaces, Bericht %s aktualisiert, abgeschlossen: %s",
        day.strftime("%d.%m.%Y"),
        active_spaces,
        open_month,
        closed_text,
    )
    return 1 if write_failed else 0


# MAIN

def update_mediaspace_report(
    message_handler: Callable[[str, str], None] | None = None,
    extra_args: str | None = None,
    output_dir: str | None = None,
    output_subdir: str | None = None,
) -> int:
    try:
        return run(
            datetime.now(ZoneInfo("Europe/Berlin")),
            lambda: fetch_spaces(cred_path, api_timeout),
            message_handler,
            extra_args,
            output_dir=output_dir,
            output_subdir=output_subdir,
        )
    except KeyboardInterrupt:
        return 130
    except Exception:
        logging.getLogger("mediaspace_report").exception("Unerwarteter Fehler im Mediaspace-Bericht")
        return 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    return update_mediaspace_report(extra_args=" ".join(argv) or None)


# EXEC
if __name__ == "__main__":
    sys.exit(main())
