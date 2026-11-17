import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook

import mediaspace_report as report
from ms_source import FetchError, fetch_spaces

T = 2**40
BERLIN = ZoneInfo("Europe/Berlin")


def _close_logger_handlers() -> None:
    logger = logging.getLogger("mediaspace_report")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()


@pytest.fixture
def paths(monkeypatch, tmp_path):
    _close_logger_handlers()
    state_path = tmp_path / "mediaspace_state.json"
    report_dir = tmp_path / "reports"
    log_path = tmp_path / "mediaspace_report.log"
    monkeypatch.setattr(report, "state_path", state_path)
    monkeypatch.setattr(report, "report_dir", report_dir)
    monkeypatch.setattr(report, "log_path", log_path)
    yield tmp_path
    _close_logger_handlers()


def _space(uuid: str, name: str, used: int = T, removed: str | None = None) -> dict:
    return {
        "uuid": uuid,
        "name": name,
        "created": "2026-09-01T08:00:00Z",
        "removed": removed,
        "mount_used_bytes": used,
    }


def _run(when: tuple[int, int, int], spaces: list[dict]) -> int:
    return report.run(datetime(*when, 0, 1, tzinfo=BERLIN), lambda: spaces)


def _sheet(path: Path, name: str):
    workbook = load_workbook(path, data_only=True)
    return workbook, workbook[name]


def test_first_run(paths):
    assert _run(
        (2026, 11, 17),
        [_space("u1", "Iran Archive", 2 * T), _space("u2", "Misc", T)],
    ) == 0

    report_path = paths / "reports" / "Mediaspace-Report_2026-11.xlsx"
    workbook, sheet = _sheet(report_path, "Bericht")
    assert sheet["A1"].value == "Monat 11.2026 · Stand 16.11.2026 · 1 Snapshots · vorläufig"
    assert (sheet["A4"].value, sheet["B4"].value, sheet["E4"].value) == ("Iran", 2.0, "Looks")
    assert sheet["A5"].value == "Misc"
    workbook.close()
    state = json.loads((paths / "mediaspace_state.json").read_text(encoding="utf-8"))
    assert "2026-11" in state["months"]


def test_month_close(paths):
    spaces = [_space("u1", "Iran Archive", 2 * T)]
    assert _run((2026, 11, 30), spaces) == 0
    assert _run((2026, 12, 1), spaces) == 0

    november = paths / "reports" / "Mediaspace-Report_2026-11.xlsx"
    workbook, sheet = _sheet(november, "Bericht")
    assert sheet["A1"].value.endswith("2 Snapshots · abgeschlossen")
    workbook.close()
    november_bytes = november.read_bytes()

    december = paths / "reports" / "Mediaspace-Report_2026-12.xlsx"
    workbook, sheet = _sheet(december, "Bericht")
    assert sheet["A1"].value == "Monat 12.2026 · Stand – · 0 Snapshots · vorläufig"
    workbook.close()
    state = json.loads((paths / "mediaspace_state.json").read_text(encoding="utf-8"))
    assert "2026-11" not in state["months"]

    assert _run((2026, 12, 2), spaces) == 0
    workbook, sheet = _sheet(december, "Bericht")
    assert "1 Snapshots" in sheet["A1"].value
    workbook.close()
    assert november.read_bytes() == november_bytes


def test_permission_error_on_close_retried(paths, monkeypatch):
    spaces = [_space("u1", "Iran Archive", 2 * T)]
    assert _run((2026, 11, 30), spaces) == 0
    original_write = report.write_workbook
    failed = False

    def write_once_locked(path, *args, **kwargs):
        nonlocal failed
        if path.name == "Mediaspace-Report_2026-11.xlsx" and not failed:
            failed = True
            raise PermissionError("locked")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(report, "write_workbook", write_once_locked)
    assert _run((2026, 12, 1), spaces) == 1
    state = json.loads((paths / "mediaspace_state.json").read_text(encoding="utf-8"))
    assert "2026-11" in state["months"]
    assert "konnte nicht geschrieben werden" in (paths / "mediaspace_report.log").read_text(encoding="utf-8")

    assert _run((2026, 12, 2), spaces) == 0
    workbook, sheet = _sheet(paths / "reports" / "Mediaspace-Report_2026-11.xlsx", "Bericht")
    assert sheet["A1"].value.endswith("abgeschlossen")
    workbook.close()
    state = json.loads((paths / "mediaspace_state.json").read_text(encoding="utf-8"))
    assert "2026-11" not in state["months"]



def test_report_write_error_keeps_month(paths, monkeypatch):
    spaces = [_space("u1", "Iran Archive", 2 * T)]
    assert _run((2026, 11, 30), spaces) == 0
    original_write = report.write_workbook
    failed = False

    def write_once_failing(path, *args, **kwargs):
        nonlocal failed
        if path.name == "Mediaspace-Report_2026-11.xlsx" and not failed:
            failed = True
            raise OSError("disk error")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(report, "write_workbook", write_once_failing)
    assert _run((2026, 12, 1), spaces) == 1
    state = json.loads((paths / "mediaspace_state.json").read_text(encoding="utf-8"))
    assert "2026-11" in state["months"]
    assert (paths / "reports" / "Mediaspace-Report_2026-12.xlsx").exists()
    assert "konnte nicht geschrieben werden" in (paths / "mediaspace_report.log").read_text(encoding="utf-8")

    assert _run((2026, 12, 2), spaces) == 0
    state = json.loads((paths / "mediaspace_state.json").read_text(encoding="utf-8"))
    assert "2026-11" not in state["months"]


def test_fetch_error(paths):
    def fail_fetch():
        raise FetchError("Admin-API antwortet mit HTTP 401")

    assert report.run(datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN), fail_fetch) == 1
    assert not (paths / "mediaspace_state.json").exists()
    assert not (paths / "reports").exists()
    assert "Admin-API antwortet mit HTTP 401" in (paths / "mediaspace_report.log").read_text(encoding="utf-8")


def test_corrupt_state(paths, monkeypatch):
    state_path = paths / "mediaspace_state.json"
    state_path.write_text("{bad", encoding="utf-8")
    called = False

    def fetch():
        nonlocal called
        called = True
        return []

    assert report.run(datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN), fetch) == 1
    assert not called
    assert state_path.read_text(encoding="utf-8") == "{bad"


def test_lto_entry(paths):
    active = [_space("u1", "Iran Archive", 2 * T), _space("u2", "Iran Render", T)]
    removed = [
        _space("u1", "Iran Archive", 2 * T, "2026-11-20T09:00:00Z"),
        _space("u2", "Iran Render", T, "2026-11-20T09:00:00Z"),
    ]
    assert _run((2026, 11, 19), active) == 0
    assert _run((2026, 11, 20), active) == 0
    assert _run((2026, 11, 21), removed) == 0
    assert _run((2026, 12, 1), removed) == 0

    december = paths / "reports" / "Mediaspace-Report_2026-12.xlsx"
    workbook = load_workbook(december, data_only=True)
    lto = workbook["LTO-Bestand"]
    assert (lto["A4"].value, lto["B4"].value, lto["C4"].value, lto["D4"].value, lto["E4"].value, lto["F4"].value) == (
        "Iran", 3.0, datetime(2026, 9, 1), datetime(2026, 11, 20), "11.2026", "Looks"
    )
    report_sheet = workbook["Bericht"]
    assert report_sheet["A4"].value is None
    workbook.close()

    assert _run((2026, 12, 2), removed) == 0
    state = json.loads((paths / "mediaspace_state.json").read_text(encoding="utf-8"))
    assert len(state["extra"]["lto"]) == 1


def test_prune(paths):
    report_dir = paths / "reports"
    report_dir.mkdir()
    for year, month in ((year, month) for year in range(2024, 2027) for month in range(1, 13)):
        if (year, month) < (2024, 10) or (year, month) > (2026, 10):
            continue
        (report_dir / f"Mediaspace-Report_{year:04d}-{month:02d}.xlsx").write_bytes(b"")

    assert _run((2026, 11, 17), []) == 0
    remaining = sorted(path.name for path in report_dir.glob("Mediaspace-Report_*.xlsx"))
    assert len(remaining) == 24
    assert "Mediaspace-Report_2024-10.xlsx" not in remaining
    assert "Mediaspace-Report_2024-11.xlsx" not in remaining


def test_main_without_cred(paths, monkeypatch):
    cred_path = paths / "missing-cred.env"
    monkeypatch.setattr(report, "cred_path", cred_path)
    for key in ("FLOW_HOST", "FLOW_USER", "FLOW_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    try:
        assert report.main([]) == 1
    finally:
        _close_logger_handlers()

    assert "Fehlt in cred.env" in (paths / "mediaspace_report.log").read_text(encoding="utf-8")
    assert not (paths / "mediaspace_state.json").exists()
    assert not (paths / "reports").exists()

def test_gap_across_month_boundary_closes_previous_and_updates_open(paths):
    assert _run((2026, 10, 31), [_space("u1", "Iran Archive", T)]) == 0
    assert _run((2026, 11, 3), [_space("u1", "Iran Archive", 4 * T)]) == 0

    october = paths / "reports" / "Mediaspace-Report_2026-10.xlsx"
    workbook, sheet = _sheet(october, "Bericht")
    assert sheet["A1"].value == "Monat 10.2026 · Stand 31.10.2026 · 2 Snapshots · abgeschlossen"
    assert sheet["B4"].value == 1.5
    workbook.close()

    november = paths / "reports" / "Mediaspace-Report_2026-11.xlsx"
    workbook, sheet = _sheet(november, "Bericht")
    assert sheet["A1"].value == "Monat 11.2026 · Stand 02.11.2026 · 2 Snapshots · vorläufig"
    assert sheet["B4"].value == 3.5
    workbook.close()

    state = json.loads((paths / "mediaspace_state.json").read_text(encoding="utf-8"))
    assert "2026-10" not in state["months"]
    assert len(state["months"]["2026-11"]["snapshots"]) == 2


def test_snapshot_processing_error_does_not_save_state(paths):
    state_path = paths / "mediaspace_state.json"
    original = json.dumps({
        "version": 1,
        "months": {},
        "last": {"day": "2026-11-18", "values": {}},
        "extra": {},
    }, sort_keys=True).encode("utf-8")
    state_path.write_bytes(original)
    fetched = False

    def fetch():
        nonlocal fetched
        fetched = True
        return []

    assert report.run(datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN), fetch) == 1
    assert fetched
    assert state_path.read_bytes() == original
    assert not (paths / "reports").exists()


def test_credentials_are_redacted_from_logs(paths, monkeypatch):
    secrets = {
        "FLOW_HOST": "mediaspace-host-secret",
        "FLOW_USER": "mediaspace-user-secret",
        "FLOW_PASSWORD": "mediaspace-password-secret",
    }
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)

    class Admin:
        @staticmethod
        def create_gateway_instance(username, password, host):
            raise RuntimeError(f"{username} {password} {host}")

    monkeypatch.setitem(sys.modules, "FlowAPI", SimpleNamespace(Admin=Admin))
    assert report.run(
        datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN),
        lambda: fetch_spaces(paths / "cred.env", 1),
    ) == 1

    log = (paths / "mediaspace_report.log").read_text(encoding="utf-8")
    assert "[REDACTED]" in log
    assert all(secret not in log for secret in secrets.values())
    assert not (paths / "mediaspace_state.json").exists()


def test_repeated_runs_do_not_duplicate_log_handlers(paths):
    assert _run((2026, 11, 17), []) == 0
    logger = logging.getLogger("mediaspace_report")
    managed_handlers = lambda: tuple(
        handler for handler in logger.handlers
        if getattr(handler, "_mediaspace_report_handler", False)
    )
    first_handlers = managed_handlers()
    assert len(first_handlers) == 2

    assert _run((2026, 11, 18), []) == 0
    second_handlers = managed_handlers()
    assert len(second_handlers) == 2
    assert not set(first_handlers) & set(second_handlers)


def test_lto_ignores_mean_from_before_latest_phase():
    state = {
        "months": {},
        "extra": {
            "project_means": {"iran": {"month": "2026-09", "tib": 2.0, "name": "Iran"}},
            "lto": [],
        },
    }
    phases = {
        "iran": [
            report.Phase(date(2026, 9, 1), date(2026, 9, 30), frozenset({"old"})),
            report.Phase(date(2026, 10, 10), date(2026, 10, 20), frozenset({"new"})),
        ]
    }

    report._update_lto(state, phases, "2026-10")
    assert state["extra"]["lto"] == []

def test_report_directory_permission_error_is_retryable(paths, monkeypatch):
    original_mkdir = Path.mkdir

    def mkdir_with_report_lock(path, *args, **kwargs):
        if path == paths / "reports":
            raise PermissionError("locked")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_with_report_lock)
    assert _run((2026, 11, 17), []) == 1
    assert "konnte nicht angelegt werden" in (paths / "mediaspace_report.log").read_text(encoding="utf-8")
    assert (paths / "mediaspace_state.json").exists()
    assert not (paths / "reports").exists()



def test_message_handler_receives_info(paths):
    messages = []
    assert report.run(
        datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN),
        lambda: [_space("u1", "Iran Archive")],
        lambda level, text: messages.append((level, text)),
        "x=1",
    ) == 0
    assert any(level == "info" and "Snapshot 16.11.2026" in text for level, text in messages)
    assert any("Zusatzargumente: x=1" in text for _, text in messages)
    assert "Snapshot 16.11.2026" in (paths / "mediaspace_report.log").read_text(encoding="utf-8")
    assert {level for level, _ in messages} <= {"info"}


def test_message_handler_receives_errors(paths):
    messages = []

    def fail_fetch():
        raise FetchError("Keine Antwort der Admin-API nach 1 s")

    assert report.run(
        datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN),
        fail_fetch,
        lambda level, text: messages.append((level, text)),
    ) == 1
    assert any(level == "error" and "Keine Antwort" in text for level, text in messages)


def test_failing_message_handler_does_not_break_run(paths):
    def fail_handler(level, text):
        raise RuntimeError("handler failed")

    assert report.run(
        datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN),
        lambda: [_space("u1", "Iran Archive")],
        fail_handler,
    ) == 0
    assert "Snapshot" in (paths / "mediaspace_report.log").read_text(encoding="utf-8")


def test_update_catches_unexpected_error(monkeypatch):
    def fail_run(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(report, "run", fail_run)
    assert report.update_mediaspace_report() == 1


def test_main_passes_extra_args(monkeypatch):
    calls = []

    def fake_update(**kwargs):
        calls.append(kwargs)
        return 7

    monkeypatch.setattr(report, "update_mediaspace_report", fake_update)
    assert report.main(["--a", "b"]) == 7
    assert calls[-1]["extra_args"] == "--a b"
    assert report.main([]) == 7
    assert calls[-1]["extra_args"] is None


def test_resolve_report_dir_default(paths):
    assert report.resolve_report_dir(None, None) == (report.report_dir, None)
    assert report.resolve_report_dir("  ", "x") == (report.report_dir, None)


def test_resolve_report_dir_normalizes_subdir(paths):
    assert report.resolve_report_dir("/mnt/out", "tmp Claudia\\_Mediaspace Reports") == (
        Path("/mnt/out/tmp Claudia/_Mediaspace Reports"), Path("/mnt/out")
    )
    assert report.resolve_report_dir("/mnt/out", "/a/./b/") == (
        Path("/mnt/out/a/b"), Path("/mnt/out")
    )
    assert report.resolve_report_dir("/mnt/out", None) == (Path("/mnt/out"), Path("/mnt/out"))


def test_resolve_report_dir_rejects_parent(paths):
    with pytest.raises(ValueError, match="Ungültiges Unterverzeichnis"):
        report.resolve_report_dir("/mnt/out", "a/../x")


def test_run_writes_to_output_dir(paths):
    space = paths / "space"
    space.mkdir()
    messages = []
    assert report.run(
        datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN),
        lambda: [_space("u1", "Iran Archive")],
        message_handler=lambda level, text: messages.append((level, text)),
        output_dir=str(space),
        output_subdir="tmp Claudia\\_Mediaspace Reports",
    ) == 0
    assert (space / "tmp Claudia" / "_Mediaspace Reports" / "Mediaspace-Report_2026-11.xlsx").exists()
    assert not (paths / "reports").exists()
    assert any("Berichtsordner:" in text for _, text in messages)


def test_run_missing_output_dir_keeps_state(paths):
    output_dir = paths / "missing"
    assert report.run(
        datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN),
        lambda: [_space("u1", "Iran Archive")],
        output_dir=str(output_dir),
    ) == 1
    state_path = paths / "mediaspace_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "2026-11" in state["months"]
    log = (paths / "mediaspace_report.log").read_text(encoding="utf-8")
    assert "Ziel-Space nicht verfügbar" in log
    assert not output_dir.exists()

    output_dir.mkdir()
    assert report.run(
        datetime(2026, 11, 18, 0, 1, tzinfo=BERLIN),
        lambda: [_space("u1", "Iran Archive")],
        output_dir=str(output_dir),
    ) == 0
    assert (output_dir / "Mediaspace-Report_2026-11.xlsx").exists()


def test_run_invalid_subdir_keeps_state(paths):
    output_dir = paths / "space"
    output_dir.mkdir()
    assert report.run(
        datetime(2026, 11, 17, 0, 1, tzinfo=BERLIN),
        lambda: [_space("u1", "Iran Archive")],
        output_dir=str(output_dir),
        output_subdir="../x",
    ) == 1
    assert (paths / "mediaspace_state.json").exists()
    assert "Ungültiges Unterverzeichnis" in (paths / "mediaspace_report.log").read_text(encoding="utf-8")


def test_update_passes_output_args(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(report, "run", fake_run)
    assert report.update_mediaspace_report(output_dir="/o", output_subdir="s") == 0
    assert calls[-1][1]["output_dir"] == "/o"
    assert calls[-1][1]["output_subdir"] == "s"

