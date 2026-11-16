# IMPORTS
import csv
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path


# CONFIG
app_name = "mediaspace_report"
app_version = "0.1.0"


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


_PROJECT_PATTERN = re.compile(r"^(.+?)[ _-]+(archiv|archive|render|onlining|rushes|project|projekt)$", re.IGNORECASE)


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


def write_report_csv(path: Path, rows: list[ReportRow], days_in_month: int) -> None:
    """Write the report as UTF-8-BOM CSV using an atomic replacement."""
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            writer = csv.writer(temp_file, delimiter=";")
            writer.writerow(["Name", "TB", "Anfangsdatum", "Enddatum", "Zuordnung"])
            for row in rows:
                writer.writerow(
                    [
                        row.name,
                        f"{row.byte_days / days_in_month / 10**12:.4f}".replace(".", ","),
                        row.start.strftime("%d.%m.%Y") if row.start else "",
                        row.end.strftime("%d.%m.%Y") if row.end else "",
                        row.owner,
                    ]
                )
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


# MAIN
def main() -> int:
    """Run the command-line entry point."""
    return 0


# EXEC
if __name__ == "__main__":
    sys.exit(main())
