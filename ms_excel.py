"""Create and retain monthly Media Space report workbooks."""

# IMPORTS
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Font

# CONFIG
app_name = "ms_excel"
app_version = "1.0.0"

_REPORT_PATTERN = re.compile(r"^Mediaspace-Report_(\d{4}-\d{2})\.xlsx$")
_LTO_NOTE = "Enthält nur Looks-Projekte, deren Spaces gelöscht wurden – nicht den gesamten LTO-Bestand. TiB-Werte sind Näherungen (~): Durchschnitt der Snapshots im letzten Monat vor der Löschung."
_REPORT_HEADERS = ("Name", "TiB", "Anfangsdatum", "Enddatum", "Zuordnung", "Hinweis")
_RAW_HEADERS = ("Space", "Kennung", "Projekt (ermittelt)", "Zuordnung", "Erstellt", "Gelöscht", "Snapshots", "TiB", "Hinweis")
_LTO_HEADERS = ("Projekt", "TiB (~)", "Anfangsdatum", "Enddatum", "Monat der Löschung", "Zuordnung")
_DATE_FORMAT = "DD.MM.YYYY"

# MODELS
@dataclass(frozen=True)
class ReportLine:
    """One row in the monthly report sheet."""

    name: str
    tib: float
    start: date | None
    end: date | None
    owner: str
    note: str


@dataclass(frozen=True)
class RawLine:
    """One raw Media Space row for traceability."""

    space: str
    uuid: str
    project: str
    owner: str
    created: date | None
    removed: date | None
    snapshots: int
    tib: float
    note: str


@dataclass(frozen=True)
class LtoLine:
    """One deleted-space row in the LTO approximation sheet."""

    project: str
    tib: float
    start: date | None
    end: date | None
    month: str
    owner: str

# FUNC

def report_path(report_dir: Path, month: str) -> Path:
    """Return the workbook path for the requested month."""
    return report_dir / f"Mediaspace-Report_{month}.xlsx"


def _append_values(sheet, row_index: int, values: Iterable[object]) -> None:
    for column_index, value in enumerate(values, start=1):
        sheet.cell(row=row_index, column=column_index, value=value)


def _set_column_widths(sheet) -> None:
    for column_cells in sheet.iter_cols():
        values = []
        for cell in column_cells:
            value = cell.value
            if value is None:
                continue
            if isinstance(value, (date, datetime)):
                values.append(value.strftime("%d.%m.%Y"))
            elif isinstance(value, (int, float)) and cell.number_format == '"~"0.00':
                values.append(f"~{value:.2f}")
            elif isinstance(value, (int, float)) and cell.number_format == "0.00":
                values.append(f"{value:.2f}")
            else:
                values.append(str(value))
        if values:
            sheet.column_dimensions[column_cells[0].column_letter].width = min(60, max(map(len, values)) + 2)


def _write_header(sheet, row_index: int, headers: tuple[str, ...]) -> None:
    _append_values(sheet, row_index, headers)
    for cell in sheet[row_index][:len(headers)]:
        cell.font = Font(bold=True)


def _write_report_sheet(sheet, status_line: str, rows: list[ReportLine]) -> None:
    sheet["A1"] = status_line
    _write_header(sheet, 3, _REPORT_HEADERS)
    for row_index, row in enumerate(rows, start=4):
        _append_values(sheet, row_index, (row.name, row.tib, row.start, row.end, row.owner, row.note))
        sheet.cell(row_index, 2).number_format = "0.00"
        for column_index in (3, 4):
            sheet.cell(row_index, column_index).number_format = _DATE_FORMAT
    sheet.freeze_panes = "A4"
    _set_column_widths(sheet)


def _write_raw_sheet(sheet, rows: list[RawLine]) -> None:
    _write_header(sheet, 1, _RAW_HEADERS)
    for row_index, row in enumerate(rows, start=2):
        _append_values(sheet, row_index, (row.space, row.uuid, row.project, row.owner, row.created, row.removed, row.snapshots, row.tib, row.note))
        for column_index in (5, 6):
            sheet.cell(row_index, column_index).number_format = _DATE_FORMAT
        sheet.cell(row_index, 8).number_format = "0.00"
    sheet.freeze_panes = "A2"
    _set_column_widths(sheet)


def _write_lto_sheet(sheet, rows: list[LtoLine]) -> None:
    sheet["A1"] = _LTO_NOTE
    _write_header(sheet, 3, _LTO_HEADERS)
    for row_index, row in enumerate(rows, start=4):
        _append_values(sheet, row_index, (row.project, row.tib, row.start, row.end, row.month, row.owner))
        sheet.cell(row_index, 2).number_format = '"~"0.00'
        for column_index in (3, 4):
            sheet.cell(row_index, column_index).number_format = _DATE_FORMAT
    sheet.freeze_panes = "A4"
    _set_column_widths(sheet)


def write_workbook(path: Path, status_line: str, report_rows: list[ReportLine], raw_rows: list[RawLine], lto_rows: list[LtoLine]) -> None:
    """Write all report sheets atomically, preserving the supplied row order."""
    workbook = Workbook()
    del workbook[workbook.sheetnames[0]]
    _write_report_sheet(workbook.create_sheet("Bericht"), status_line, report_rows)
    _write_raw_sheet(workbook.create_sheet("Rohdaten"), raw_rows)
    _write_lto_sheet(workbook.create_sheet("LTO-Bestand"), lto_rows)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
        workbook.save(temporary_path)
        os.replace(temporary_path, path)
    finally:
        workbook.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def prune_reports(report_dir: Path, keep: int = 24) -> list[Path]:
    """Delete reports older than the newest ``keep`` matching months."""
    if keep < 1:
        raise ValueError("keep must be at least 1")

    reports = sorted(
        ((match.group(1), path) for path in report_dir.iterdir() if path.is_file() and (match := _REPORT_PATTERN.fullmatch(path.name))),
        key=lambda item: item[0],
    )
    deleted = [path for _, path in reports[:-keep]]
    for path in deleted:
        path.unlink()
    return deleted

# MAIN

def main() -> None:
    """Provide a no-op entry point for module execution."""

# EXEC
if __name__ == "__main__":
    main()
