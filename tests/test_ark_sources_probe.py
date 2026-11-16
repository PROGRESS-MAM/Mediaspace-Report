import csv
import threading
import time
from types import SimpleNamespace

import ark_sources_probe as probe


def result(data=None, code=200):
    return SimpleNamespace(code=code, data=data, message="ok", error="")


def test_call_ok():
    outcome = probe.call_with_timeout(lambda: result({"x": 1}), 1, poll=0.01)
    assert outcome.status == "ok"
    assert outcome.result.data == {"x": 1}
    assert outcome.seconds >= 0


def test_call_http():
    outcome = probe.call_with_timeout(lambda: result(code=500), 1, poll=0.01)
    assert outcome.status == "http"
    assert outcome.result.code == 500


def test_call_error():
    def fail():
        raise ValueError("x")

    outcome = probe.call_with_timeout(fail, 1, poll=0.01)
    assert (outcome.status, outcome.error) == ("error", "ValueError: x")


def test_call_timeout():
    release = threading.Event()
    waits = []

    def wait_forever():
        release.wait()
        return result()

    try:
        started = time.monotonic()
        outcome = probe.call_with_timeout(wait_forever, 0.3, waits.append, wait_report=0.1, poll=0.05)
        elapsed = time.monotonic() - started
        assert outcome.status == "timeout"
        assert elapsed <= 1.3
        assert waits
    finally:
        release.set()


def test_call_interrupt():
    release = threading.Event()

    def interrupt(_elapsed):
        raise KeyboardInterrupt

    try:
        try:
            probe.call_with_timeout(lambda: (release.wait(), result())[1], 1, interrupt, wait_report=0.01, poll=0.01)
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("KeyboardInterrupt was swallowed")
    finally:
        release.set()


def test_size_keys():
    data = {"a": [{"file_size": 1, "x": {"bytes_used": 2}}], "free": 3}
    keys = probe.size_keys(data)
    assert set(keys) == {"file_size", "bytes_used", "free"}
    assert len(keys) == 3
    many_keys = {f"size_{index}": index for index in range(20)}
    assert len(probe.size_keys(many_keys)) == 10
    assert probe.size_keys([0] * 10**6, max_nodes=1000) == []
    large_mapping = {f"field_{index}": index for index in range(2000)}
    large_mapping["final_bytes_used"] = 0
    assert "final_bytes_used" not in probe.size_keys(large_mapping, max_nodes=1000)


def test_shape():
    assert probe.shape([1, 2]) == "list[2]"
    assert probe.shape({"a": 1}) == "dict{a}"
    assert probe.shape(None) == "None"


def test_pick_sample():
    backups = [
        {"backup_id": "old", "backup_type": "__ms__", "destination_type": "__tape__", "date": "2024-01", "destination_id": "pool-old"},
        {"backup_id": "project", "backup_type": "__project__", "destination_type": "__tape__", "date": "2026-01", "destination_id": "wrong"},
        {"backup_id": "latest", "backup_type": "__ms__", "destination_type": "__tape__", "date": "2025-01", "destination_id": "pool-latest"},
    ]
    assert probe.pick_sample(backups) == ("latest", "pool-latest")
    assert probe.pick_sample([]) == (None, None)


class FakeArk:
    def __init__(self, overrides=None, on_pools=None):
        self.calls = []
        self.overrides = overrides or {}
        self.on_pools = on_pools

    def _call(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        override = self.overrides.get(name)
        if callable(override):
            return override(*args, **kwargs)
        if override is not None:
            return override
        if name == "get_backups":
            data = [{"backup_id": "b-latest", "backup_type": "__ms__", "destination_type": "__tape__", "date": "2025", "destination_id": "pool-1"}]
        else:
            data = {"items": []}
        return result(data)

    def get_backups(self):
        return self._call("get_backups")

    def get_license_status(self):
        return self._call("get_license_status")

    def get_file_hash_database_status(self):
        return self._call("get_file_hash_database_status")

    def search_backups(self, *args, **kwargs):
        return self._call("search_backups", *args, **kwargs)

    def get_pools(self):
        if self.on_pools:
            self.on_pools()
        return self._call("get_pools")

    def get_tape_library_status(self):
        return self._call("get_tape_library_status")

    def get_tape_backups(self):
        return self._call("get_tape_backups")

    def get_backup_contents(self, backup_id):
        return self._call("get_backup_contents", backup_id)

    def get_pool_contents(self, pool_id, offset):
        return self._call("get_pool_contents", pool_id, offset)

    def get_jobs_completed(self):
        return self._call("get_jobs_completed")


def make_connect(ark):
    calls = []

    def connect():
        calls.append(1)
        return ark

    connect.calls = calls
    return connect


def read_summary(out_dir):
    with (out_dir / "sources_summary.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def test_run_all_ok(tmp_path):
    ark = FakeArk()
    connect = make_connect(ark)
    assert probe.run_sources_probe(connect, tmp_path, 1, lambda _text: None) == 0
    files = sorted(path.name for path in tmp_path.glob("*.json"))
    assert files == [
        "01_get_backups.json", "02_get_license_status.json", "03_get_file_hash_database_status.json",
        "04_search_backups.json", "05_get_pools.json", "06_get_tape_library_status.json",
        "07_get_tape_backups.json", "08_get_backup_contents.json", "09_get_pool_contents.json",
        "10_get_jobs_completed.json",
    ]
    rows = read_summary(tmp_path)
    assert len(rows) == 10
    assert list(rows[0]) == probe.SUMMARY_HEADER
    assert len(connect.calls) == 10
    assert ("get_backup_contents", ("b-latest",), {}) in ark.calls
    assert ("get_pool_contents", ("pool-1", 0), {}) in ark.calls


def test_run_timeout_continues(tmp_path):
    release = threading.Event()

    def hanging():
        release.wait()
        return result()

    ark = FakeArk(overrides={"get_tape_backups": hanging})
    try:
        assert probe.run_sources_probe(make_connect(ark), tmp_path, 0.3, lambda _text: None) == 0
        row = read_summary(tmp_path)[6]
        assert row["status"] == "timeout"
        assert not (tmp_path / "07_get_tape_backups.json").exists()
        assert any(call[0] == "get_backup_contents" for call in ark.calls)
        assert any(call[0] == "get_pool_contents" for call in ark.calls)
        assert any(call[0] == "get_jobs_completed" for call in ark.calls)
        release.set()
        time.sleep(0.5)
        assert not (tmp_path / "07_get_tape_backups.json").exists()
    finally:
        release.set()


def test_run_without_sample(tmp_path):
    ark = FakeArk(overrides={"get_backups": result(code=500)})
    assert probe.run_sources_probe(make_connect(ark), tmp_path, 1, lambda _text: None) == 0
    rows = read_summary(tmp_path)
    assert rows[7]["status"] == "übersprungen"
    assert rows[8]["status"] == "übersprungen"
    assert not any(call[0] in {"get_backup_contents", "get_pool_contents"} for call in ark.calls)
    called = {call[0] for call in ark.calls}
    assert called == {
        "get_backups", "get_license_status", "get_file_hash_database_status", "search_backups",
        "get_pools", "get_tape_library_status", "get_tape_backups", "get_jobs_completed",
    }


def test_summary_before_call(tmp_path):
    observed = {}

    def inspect_summary():
        observed["rows"] = read_summary(tmp_path)

    ark = FakeArk(on_pools=inspect_summary)
    assert probe.run_sources_probe(make_connect(ark), tmp_path, 1, lambda _text: None) == 0
    rows = observed["rows"]
    assert len(rows) == 5
    assert [row["status"] for row in rows[:4]] == ["ok"] * 4
    assert rows[4]["status"] == "läuft"


def test_run_interrupt(tmp_path):
    ark = FakeArk()

    def progress(text):
        if text.startswith("[6/10]"):
            raise KeyboardInterrupt

    assert probe.run_sources_probe(make_connect(ark), tmp_path, 1, progress) == 130
    rows = read_summary(tmp_path)
    assert rows[5]["status"] == "abgebrochen"
    assert not any(call[0] in {"get_tape_library_status", "get_tape_backups", "get_jobs_completed"} for call in ark.calls)


def test_call_timeout_caps_join_to_remaining(monkeypatch):
    release = threading.Event()
    requested = []
    original_join = threading.Thread.join

    def recording_join(thread, timeout=None):
        requested.append(timeout)
        return original_join(thread, min(timeout or 0, 0.005))

    monkeypatch.setattr(threading.Thread, "join", recording_join)
    try:
        outcome = probe.call_with_timeout(lambda: (release.wait(), result())[1], 0.04, poll=0.5)
    finally:
        release.set()
    assert outcome.status == "timeout"
    assert requested and all(wait <= 0.04 for wait in requested)


def test_run_incomplete_sample_skips_both_contents_calls(tmp_path):
    backups = [{
        "backup_id": "b-latest",
        "backup_type": "__ms__",
        "destination_type": "__tape__",
        "date": "2025",
    }]
    ark = FakeArk(overrides={"get_backups": result(backups)})
    assert probe.run_sources_probe(make_connect(ark), tmp_path, 1, lambda _text: None) == 0
    rows = read_summary(tmp_path)
    assert rows[7]["status"] == rows[8]["status"] == "übersprungen"
    assert not any(call[0] in {"get_backup_contents", "get_pool_contents"} for call in ark.calls)


def test_connect_is_fresh_and_inside_timeout(tmp_path):
    caller_thread = threading.get_ident()
    connect_threads = []
    connections = []

    def connect():
        connect_threads.append(threading.get_ident())
        ark = FakeArk()
        connections.append(ark)
        if len(connections) == 1:
            time.sleep(0.5)
        return ark

    assert probe.run_sources_probe(connect, tmp_path, 0.15, lambda _text: None) == 0
    rows = read_summary(tmp_path)
    assert rows[0]["status"] == "timeout"
    assert len(connections) == 8
    assert len({id(connection) for connection in connections}) == len(connections)
    assert all(thread_id != caller_thread for thread_id in connect_threads)
    assert not (tmp_path / "01_get_backups.json").exists()


def test_interrupt_during_wait_marks_step_aborted(tmp_path, monkeypatch):
    release = threading.Event()
    ark = FakeArk(overrides={"get_backups": lambda: (release.wait(), result())[1]})
    original_call = probe.call_with_timeout

    def quick_wait(func, timeout, on_wait=None):
        return original_call(func, timeout, on_wait, wait_report=0.01, poll=0.005)

    monkeypatch.setattr(probe, "call_with_timeout", quick_wait)

    def progress(text):
        if text.startswith("      wartet seit"):
            raise KeyboardInterrupt

    try:
        assert probe.run_sources_probe(make_connect(ark), tmp_path, 1, progress) == 130
        rows = read_summary(tmp_path)
        assert rows[0]["status"] == "abgebrochen"
        assert not (tmp_path / "01_get_backups.json").exists()
    finally:
        release.set()
