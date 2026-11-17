from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from mediaspace_report import (
    ReportRow,
    SpaceMonth,
    build_rows,
    month_report,
    parse_project,
    phase_for_month,
    project_phases,
    status_line,
)
from ms_excel import RawLine, ReportLine
from ms_source import SpaceInfo
from ms_state import SpaceTotal


BER = ZoneInfo("Europe/Berlin")
T = 2**40


def _space(uuid, name, created, removed=None):
    return SpaceInfo(
        uuid,
        name,
        datetime.combine(created, datetime.min.time(), tzinfo=BER),
        datetime.combine(removed, datetime.min.time(), tzinfo=BER) if removed else None,
        0,
    )


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




def test_project_phases_reactivation():
    phases = project_phases([
        _space("u1", "Charles Project", date(2022, 12, 6), date(2024, 3, 27)),
        _space("u2", "Charles Render", date(2023, 1, 1), date(2024, 3, 20)),
        _space("u3", "Charles Project", date(2024, 6, 25), date(2024, 11, 25)),
    ])

    assert [(phase.start, phase.end) for phase in phases["charles"]] == [
        (date(2022, 12, 6), date(2024, 3, 27)),
        (date(2024, 6, 25), date(2024, 11, 25)),
    ]


def test_project_phases_gap_rules():
    joined = project_phases([
        _space("a", "Tschernobyl Archiv", date(2020, 12, 10), date(2023, 3, 27)),
        _space("b", "Tschernobyl Archiv", date(2023, 3, 27), date(2024, 2, 1)),
    ])
    one_day_gap = project_phases([
        _space("c", "X Render", date(2024, 1, 1), date(2025, 1, 10)),
        _space("d", "X Project", date(2025, 1, 11), date(2025, 2, 1)),
    ])
    two_day_gap = project_phases([
        _space("e", "X Render", date(2024, 1, 1), date(2025, 1, 10)),
        _space("f", "X Project", date(2025, 1, 12), date(2025, 2, 1)),
        _space("g", "Misc", date(2024, 1, 1), None),
    ])

    assert [(phase.start, phase.end) for phase in joined["tschernobyl"]] == [
        (date(2020, 12, 10), date(2024, 2, 1))
    ]
    assert [(phase.start, phase.end) for phase in one_day_gap["x"]] == [
        (date(2024, 1, 1), date(2025, 2, 1))
    ]
    assert [(phase.start, phase.end) for phase in two_day_gap["x"]] == [
        (date(2024, 1, 1), date(2025, 1, 10)),
        (date(2025, 1, 12), date(2025, 2, 1)),
    ]
    assert "misc" not in two_day_gap


def test_project_phases_open():
    phases = project_phases([
        _space("a", "Y Archive", date(2024, 1, 1)),
        _space("b", "Y Render", date(2024, 2, 1), date(2024, 3, 1)),
        _space("c", "Y Rushes", date(2025, 6, 1)),
    ])

    assert len(phases["y"]) == 1
    assert phases["y"][0].end is None
    assert phases["y"][0].uuids == frozenset({"a", "b", "c"})


def test_phase_for_month():
    phases = project_phases([
        _space("u1", "Charles Project", date(2022, 12, 6), date(2024, 3, 27)),
        _space("u2", "Charles Project", date(2024, 6, 25), date(2024, 11, 25)),
    ])["charles"]

    assert phase_for_month(phases, "2024-07") == phases[1]
    assert phase_for_month(phases, "2023-05") == phases[0]
    assert phase_for_month(phases, "2022-11") is None


def test_month_report():
    totals = [
        SpaceTotal("u1", "Iran Archive", datetime(2026, 9, 1, tzinfo=BER), None, 4 * T, 2, False),
        SpaceTotal("u2", "iran render", datetime(2026, 10, 1, tzinfo=BER), datetime(2026, 11, 10, tzinfo=BER), 1 * T, 1, True),
        SpaceTotal("u3", "Misc", datetime(2026, 1, 1, tzinfo=BER), None, 6 * T, 2, False),
    ]
    phases = project_phases([
        _space("u1", "Iran Archive", date(2026, 9, 1)),
        _space("u2", "iran render", date(2026, 10, 1), date(2026, 11, 10)),
        _space("u0", "Iran Rushes", date(2020, 1, 1), date(2020, 6, 1)),
    ])

    report, raw = month_report(totals, 2, phases, "2026-11")

    assert report == [
        ReportLine("Iran", 2.5, date(2026, 9, 1), None, "Looks", "interpoliert"),
        ReportLine("Misc", 3.0, date(2026, 1, 1), None, "", ""),
    ]
    assert raw == [
        RawLine("Iran Archive", "u1", "Iran", "Looks", date(2026, 9, 1), None, 2, 2.0, ""),
        RawLine("iran render", "u2", "iran", "Looks", date(2026, 10, 1), date(2026, 11, 10), 1, 0.5, "interpoliert"),
        RawLine("Misc", "u3", "", "", date(2026, 1, 1), None, 2, 3.0, ""),
    ]


def test_month_report_empty():
    assert month_report([], 0, {}, "2026-11") == ([], [])


def test_status_line():
    assert status_line("2026-11", date(2026, 11, 16), 16, False) == (
        "Monat 11.2026 · Stand 16.11.2026 · 16 Snapshots · vorläufig"
    )
    assert status_line("2026-12", None, 0, False) == "Monat 12.2026 · Stand – · 0 Snapshots · vorläufig"
    assert status_line("2026-11", date(2026, 11, 30), 30, True).endswith("abgeschlossen")
