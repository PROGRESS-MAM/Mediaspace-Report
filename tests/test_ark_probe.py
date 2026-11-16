import csv
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ark_probe


class FakeArk:
    def __init__(self, backups=None, results=None, search_overrides=None, backups_result=None):
        self.backups = backups or []
        self.results = results or []
        self.total_matches = len(self.results)
        self.search_overrides = search_overrides or {}
        self.backups_result = backups_result or SimpleNamespace(code=200, data=self.backups, message="ok", error="")
        self.calls = []

    def get_backups(self):
        self.calls.append(("get_backups",))
        return self.backups_result

    def search_backups(self, pattern, mode="contains", *, limit=100, offset=0):
        call_number = 1 + sum(call[0] == "search_backups" for call in self.calls)
        self.calls.append(("search_backups", pattern, mode, limit, offset))
        override = self.search_overrides.get(call_number)
        if override == "interrupt":
            raise KeyboardInterrupt
        if override is not None:
            return override
        selected = self.results[offset:offset + limit]
        return SimpleNamespace(code=200, data={"total_matches": self.total_matches, "limit": limit, "offset": offset, "results": selected}, message="ok", error="")

    def get_backup_contents(self, backup_id):
        self.calls.append(("get_backup_contents", backup_id))
        return SimpleNamespace(code=200, data={"backup_id": backup_id, "contents": []}, message="ok", error="")


def backup(backup_id="b1", **values):
    return {"backup_id": backup_id, "backup_type": "tape", "date": "2025-01-01", "display_date": "2025-01-01", "backup_path": "/backup", "media_space_name": "Atom Rushes", "media_space_uuid": "u1", "destination_id": "d1", "destination_type": "__tape__", "destination_name": "LTO", "job_name": "job", **values}


def file_item(backup_id="b1", flow_hash="2:aa", size=1, **values):
    return {"backup_id": backup_id, "backup_type": "tape", "filename": "x.mov", "path": "/a", "size": size, "flow_hash": flow_hash, "backup_date_unix": 1, "space_name": "Atom Rushes", **values}


def test_format_tb():
    assert ark_probe.format_tb(1_234_500_000_000) == "1,2345"
    assert ark_probe.format_tb(0) == "0,0000"


def test_file_key_fallback():
    assert ark_probe.file_key({"path": "/a", "filename": "x.mov", "size": 5}) == "/a/x.mov|5"
    assert ark_probe.file_key({"flow_hash": " 2:aa "}) == "2:aa"


def test_scan_stops_on_total():
    fake = FakeArk(results=[file_item(str(i)) for i in range(5)])
    search = fake.search_backups
    totals = iter([4, 5, 5])

    def changing_total(*args, **kwargs):
        result = search(*args, **kwargs)
        result.data["total_matches"] = next(totals)
        return result

    fake.search_backups = changing_total
    stats = ark_probe.scan_files(fake, 2, 10, lambda _: None, lambda _: None)
    offsets = [call[4] for call in fake.calls]
    assert offsets == [0, 2, 4]
    assert (stats.pages, stats.files, stats.total, stats.complete, stats.stop_reason) == (3, 5, 5, True, "fertig")


def test_scan_empty_result_set():
    fake = FakeArk()
    stats = ark_probe.scan_files(fake, 2, 10, lambda _: None, lambda _: None)
    assert sum(call[0] == "search_backups" for call in fake.calls) == 1
    assert (stats.pages, stats.complete, stats.stop_reason) == (0, True, "fertig")


def test_scan_empty_page_before_end():
    fake = FakeArk(results=[file_item("1"), file_item("2")])
    fake.total_matches = 10
    stats = ark_probe.scan_files(fake, 2, 10, lambda _: None, lambda _: None)
    assert (stats.pages, stats.files, stats.complete, stats.stop_reason) == (1, 2, False, "leere Seite vor Ende")


def test_scan_error_code():
    fake = FakeArk(results=[file_item("1"), file_item("2"), file_item("3")])
    fake.search_overrides[2] = SimpleNamespace(code=500, data=None, message="oops", error="server")
    stats = ark_probe.scan_files(fake, 2, 10, lambda _: None, lambda _: None)
    assert stats.files == 2
    assert not stats.complete
    assert stats.stop_reason.startswith("HTTP 500")


def test_scan_max_pages():
    fake = FakeArk(results=[file_item(str(i)) for i in range(100)])
    stats = ark_probe.scan_files(fake, 2, 3, lambda _: None, lambda _: None)
    assert sum(call[0] == "search_backups" for call in fake.calls) == 3
    assert (stats.files, stats.complete, stats.stop_reason) == (6, False, "max_pages 3 erreicht")


def test_scan_interrupt():
    fake = FakeArk(results=[file_item("1"), file_item("2"), file_item("3")], search_overrides={2: "interrupt"})
    stats = ark_probe.scan_files(fake, 2, 10, lambda _: None, lambda _: None)
    assert (stats.interrupted, stats.files, stats.complete, stats.stop_reason) == (True, 2, False, "abgebrochen")


def test_totals_dedup():
    index = {"b1": backup("b1"), "b2": backup("b2")}
    totals = ark_probe.SizeTotals(index)
    totals.add([file_item("b1", "2:aa", 100), file_item("b2", "2:aa", 100), file_item("b1", "2:bb", 50)])
    assert totals.space_rows() == [["Atom Rushes", "u1", "tape", 2, 3, 250, "0,0000", 2, 150, "0,0000"]]


def test_totals_unmatched():
    totals = ark_probe.SizeTotals({})
    totals.add([file_item("x", "h", 7, space_name="Atom-abc")])
    assert totals.space_rows()[0][:3] == ["Atom-abc", "", "tape"]
    assert totals.unmatched == {"x"}
    assert totals.backup_rows()[0][5] == "nein"


def test_totals_backup_without_name():
    totals = ark_probe.SizeTotals({"b1": {"backup_id": "b1", "media_space_uuid": "u9"}})
    totals.add([file_item("b1", space_name="Atom-abc")])
    assert totals.space_rows()[0][:2] == ["Atom-abc", "u9"]
    assert totals.unmatched == set()
    assert totals.backup_rows()[0][5] == "ja"


def test_run_probe_full(tmp_path):
    fake = FakeArk(backups=[backup()], results=[file_item("b1", "2:aa", 10**12), file_item("b1", "2:bb", 5 * 10**11)])
    assert ark_probe.run_probe(fake, tmp_path, 100, 10, lambda _: None) == 0
    import csv
    with (tmp_path / "sizes_by_space.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert rows[1] == ["Atom Rushes", "u1", "tape", "1", "2", "1500000000000", "1,5000", "2", "1500000000000", "1,5000"]
    with (tmp_path / "files.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.reader(handle, delimiter=";"))) == 3
    assert any(call == ("get_backup_contents", "b1") for call in fake.calls)
    assert "vollständig: ja" in (tmp_path / "summary.txt").read_text(encoding="utf-8")
    for name in ("files.csv", "sizes_by_space.csv", "sizes_by_backup.csv", "backups.csv"):
        assert (tmp_path / name).read_bytes().startswith(b"\xef\xbb\xbf")


def test_run_probe_search_unavailable(tmp_path):
    fake = FakeArk(backups=[backup()], search_overrides={1: SimpleNamespace(code=404, data=None, message="no", error="")})
    assert ark_probe.run_probe(fake, tmp_path, 100, 10, lambda _: None) == 0
    assert not (tmp_path / "files.csv").exists()
    assert not (tmp_path / "sizes_by_space.csv").exists()
    assert (tmp_path / "backup_contents_sample.json").exists()
    assert "suche: HTTP 404" in (tmp_path / "summary.txt").read_text(encoding="utf-8")


def test_run_probe_backups_fail(tmp_path):
    failed = SimpleNamespace(code=0, data=None, message="unavailable", error="")
    fake = FakeArk(backups_result=failed)
    assert ark_probe.run_probe(fake, tmp_path, 100, 10, lambda _: None) == 1
    assert (tmp_path / "backups.json").exists()
    assert not any(call[0] == "search_backups" for call in fake.calls)


def test_run_probe_interrupt(tmp_path):
    fake = FakeArk(
        backups=[backup()],
        results=[file_item("b1", size=7), file_item("b1", size=9)],
        search_overrides={3: "interrupt"},
    )
    assert ark_probe.run_probe(fake, tmp_path, 1, 10, lambda _: None) == 130
    with (tmp_path / "sizes_by_space.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert rows[1][4:6] == ["1", "7"]
    assert not any(call[0] == "get_backup_contents" for call in fake.calls)
    assert "vollständig: nein" in (tmp_path / "summary.txt").read_text(encoding="utf-8")


def test_run_probe_scan_exception_keeps_totals(tmp_path):
    fake = FakeArk(backups=[backup()], results=[file_item("b1", size=7), file_item("b1", size="abc")])
    with pytest.raises(ValueError):
        ark_probe.run_probe(fake, tmp_path, 1, 10, lambda _: None)
    with (tmp_path / "sizes_by_space.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=";"))
    assert rows[1][4:6] == ["1", "7"]


def test_run_probe_invalid_page_limit(tmp_path):
    fake = FakeArk()
    try:
        ark_probe.run_probe(fake, tmp_path, 0, 10, lambda _: None)
    except ark_probe.ProbeError:
        pass
    else:
        raise AssertionError("ProbeError not raised")
    assert fake.calls == []


def test_connect_ark_missing_cred(tmp_path):
    try:
        ark_probe.connect_ark(tmp_path / "cred.env")
    except ark_probe.ProbeError as error:
        assert "ARK_HOST" in str(error)
    else:
        raise AssertionError("ProbeError not raised")
