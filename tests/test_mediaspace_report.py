from datetime import date

import pytest

from mediaspace_report import ReportRow, SpaceMonth, build_rows, parse_project, write_report_csv


@pytest.mark.parametrize(
    ("space_name", "expected"),
    [
        ("Iran Archiv", "Iran"),
        ("Iran Archive", "Iran"),
        ("iran_render", "iran"),
        ("Iran-Onlining", "Iran"),
        ("Iran Rushes", "Iran"),
        ("Iran Project", "Iran"),
        ("Iran Projekt", "Iran"),
        ("Big Film 2 RENDER", "Big Film 2"),
        ("Render", None),
        ("Iran Render Old", None),
        ("Misc", None),
    ],
)
def test_parse_project(space_name, expected):
    assert parse_project(space_name) == expected


def test_build_rows_groups():
    t = 10**12
    spaces = [
        SpaceMonth("Iran Archiv", 600 * t, date(2026, 10, 3), None),
        SpaceMonth("iran render", 30 * t, date(2026, 9, 1), date(2026, 10, 20)),
        SpaceMonth("Misc", 150 * t, None, None),
        SpaceMonth("Temp", 30 * t, date(2026, 10, 5), date(2026, 10, 10)),
    ]

    assert build_rows(spaces) == [
        ReportRow("Iran", 630 * t, date(2026, 9, 1), None, "Looks"),
        ReportRow("Misc", 150 * t, None, None, ""),
        ReportRow("Temp", 30 * t, date(2026, 10, 5), date(2026, 10, 10), ""),
    ]


def test_build_rows_end_when_all_deleted():
    spaces = [
        SpaceMonth("Film Project", 1, None, date(2026, 10, 10)),
        SpaceMonth("film Render", 2, None, date(2026, 10, 20)),
    ]

    assert build_rows(spaces)[0].end == date(2026, 10, 20)


def test_build_rows_sort():
    spaces = [
        SpaceMonth("beta project", 1, None, None),
        SpaceMonth("Alpha archive", 1, None, None),
        SpaceMonth("low", 1, None, None),
        SpaceMonth("high", 5, None, None),
    ]

    assert [row.name for row in build_rows(spaces)] == ["Alpha", "beta", "high", "low"]


def test_write_report_csv(tmp_path):
    t = 10**12
    rows = [
        ReportRow("Iran", 630 * t, date(2026, 9, 1), None, "Looks"),
        ReportRow("Misc", 150 * t, None, None, ""),
        ReportRow("Temp", 30 * t, date(2026, 10, 5), date(2026, 10, 10), ""),
    ]
    path = tmp_path / "report.csv"

    write_report_csv(path, rows, 30)

    content = path.read_bytes()
    assert content.startswith(b"\xef\xbb\xbf")
    assert content.decode("utf-8-sig").splitlines() == [
        "Name;TB;Anfangsdatum;Enddatum;Zuordnung",
        "Iran;21,0000;01.09.2026;;Looks",
        "Misc;5,0000;;;",
        "Temp;1,0000;05.10.2026;10.10.2026;",
    ]


def test_write_report_csv_permission(tmp_path, monkeypatch):
    import mediaspace_report

    def deny_replace(source, target):
        raise PermissionError("denied")

    monkeypatch.setattr(mediaspace_report.os, "replace", deny_replace)
    target = tmp_path / "report.csv"

    with pytest.raises(PermissionError, match="denied"):
        write_report_csv(target, [], 30)

    assert list(tmp_path.iterdir()) == []


def test_write_report_csv_rounding_and_decimal_comma(tmp_path):
    row = ReportRow("Rounded", 3_703_680_000_000, None, None, "")
    path = tmp_path / "rounded.csv"

    write_report_csv(path, [row], 30)

    assert path.read_text(encoding="utf-8-sig").splitlines()[1] == "Rounded;0,1235;;;"
