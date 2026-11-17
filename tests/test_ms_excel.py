from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

import ms_excel
from ms_excel import LtoLine, RawLine, ReportLine, prune_reports, report_path, write_workbook


def test_report_path():
    assert report_path(Path("r"), "2026-11") == Path("r/Mediaspace-Report_2026-11.xlsx")


def test_write_workbook(tmp_path):
    status = "Monat 11.2026 · Stand 16.11.2026 · 16 Snapshots · vorläufig"
    report_rows = [ReportLine("Iran", 21.5, date(2026, 9, 1), None, "Looks", "interpoliert")]
    raw_rows = [RawLine("Iran Archive", "u1", "Iran", "Looks", date(2026, 9, 1), None, 16, 12.25, "")]
    lto_rows = [LtoLine("Afghanistan", 3.5, date(2018, 3, 5), date(2023, 7, 17), "07.2023", "Looks")]
    path = tmp_path / "report.xlsx"

    write_workbook(path, status, report_rows, raw_rows, lto_rows)

    workbook = load_workbook(path)
    assert workbook.sheetnames == ["Bericht", "Rohdaten", "LTO-Bestand"]
    report = workbook["Bericht"]
    assert report["A1"].value == status
    assert [report.cell(3, column).value for column in range(1, 7)] == ["Name", "TiB", "Anfangsdatum", "Enddatum", "Zuordnung", "Hinweis"]
    assert report["B4"].value == 21.5
    assert report["B4"].number_format == "0.00"
    assert report["C4"].value.date() == date(2026, 9, 1)
    assert report["C4"].number_format == "DD.MM.YYYY"
    assert report["D4"].value is None
    assert report["E4"].value == "Looks"
    assert report["F4"].value == "interpoliert"
    assert report["A3"].font.bold

    raw = workbook["Rohdaten"]
    assert [raw.cell(1, column).value for column in range(1, 10)] == ["Space", "Kennung", "Projekt (ermittelt)", "Zuordnung", "Erstellt", "Gelöscht", "Snapshots", "TiB", "Hinweis"]
    assert raw["H2"].value == 12.25
    assert raw["E2"].number_format == "DD.MM.YYYY"
    assert raw["F2"].number_format == "DD.MM.YYYY"

    lto = workbook["LTO-Bestand"]
    assert lto["A1"].value == "Enthält nur Looks-Projekte, deren Spaces gelöscht wurden – nicht den gesamten LTO-Bestand. TiB-Werte sind Näherungen (~): Durchschnitt der Snapshots im letzten Monat vor der Löschung."
    assert lto["B4"].value == 3.5
    assert lto["B4"].number_format == '"~"0.00'
    assert lto["F4"].value == "Looks"
    workbook.close()


def test_write_empty(tmp_path):
    path = tmp_path / "empty.xlsx"
    write_workbook(path, "Status", [], [], [])

    workbook = load_workbook(path)
    assert workbook.sheetnames == ["Bericht", "Rohdaten", "LTO-Bestand"]
    assert [workbook["Bericht"].cell(3, column).value for column in range(1, 7)] == ["Name", "TiB", "Anfangsdatum", "Enddatum", "Zuordnung", "Hinweis"]
    assert workbook["Bericht"].max_row == 3
    assert [workbook["Rohdaten"].cell(1, column).value for column in range(1, 10)] == ["Space", "Kennung", "Projekt (ermittelt)", "Zuordnung", "Erstellt", "Gelöscht", "Snapshots", "TiB", "Hinweis"]
    assert workbook["Rohdaten"].max_row == 1
    assert [workbook["LTO-Bestand"].cell(3, column).value for column in range(1, 7)] == ["Projekt", "TiB (~)", "Anfangsdatum", "Enddatum", "Monat der Löschung", "Zuordnung"]
    assert workbook["LTO-Bestand"].max_row == 3
    workbook.close()


def test_write_permission(tmp_path, monkeypatch):
    path = tmp_path / "report.xlsx"
    existing = tmp_path / "notes.txt"
    existing.write_text("keep", encoding="utf-8")

    def deny_replace(source, destination):
        raise PermissionError("denied")

    monkeypatch.setattr(ms_excel.os, "replace", deny_replace)
    with pytest.raises(PermissionError):
        write_workbook(path, "Status", [], [], [])
    assert sorted(item.name for item in tmp_path.iterdir()) == ["notes.txt"]


def test_prune_reports(tmp_path):
    months = []
    year, month = 2024, 10
    for _ in range(26):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    for value in months:
        (tmp_path / f"Mediaspace-Report_{value}.xlsx").touch()
    notes = tmp_path / "notes.txt"
    notes.touch()

    deleted = prune_reports(tmp_path)

    assert [item.name for item in deleted] == ["Mediaspace-Report_2024-10.xlsx", "Mediaspace-Report_2024-11.xlsx"]
    assert len(list(tmp_path.glob("Mediaspace-Report_*.xlsx"))) == 24
    assert notes.exists()
    with pytest.raises(ValueError):
        prune_reports(tmp_path, keep=0)


def test_public_models_have_docstrings():
    assert "monthly report" in ReportLine.__doc__
    assert "raw Media Space" in RawLine.__doc__
    assert "deleted-space" in LtoLine.__doc__


def test_save_failure_removes_temporary_file(tmp_path, monkeypatch):
    def fail_save(self, filename):
        raise OSError("save failed")

    monkeypatch.setattr(ms_excel.Workbook, "save", fail_save)
    with pytest.raises(OSError, match="save failed"):
        write_workbook(tmp_path / "report.xlsx", "Status", [], [], [])

    assert list(tmp_path.iterdir()) == []
