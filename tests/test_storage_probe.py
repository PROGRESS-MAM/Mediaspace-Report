import csv
import json
import threading
import time

import pytest
from types import ModuleType, SimpleNamespace

import storage_probe as probe


def install_fakes(monkeypatch, *, details_result=None, return_code=200, hang_details=None):
    calls = []

    class FakeGateway:
        def __init__(self, kind):
            self.kind = kind

        def get_spaces(self, details=False):
            calls.append(("get_spaces", details))
            if details and hang_details is not None:
                hang_details.wait()
            if details_result is not None and details:
                return details_result
            return []

        def get_space(self, name):
            calls.append(("get_space", name))
            return {"name": name, "used": 1}

        def get_mediaspaces(self, as_admin=False):
            calls.append(("get_mediaspaces", as_admin))
            return [{"name": "admin-space"}]

        def lastReturnCode(self):
            return return_code

    def create(kind):
        def factory(username, password, ip_addr):
            calls.append(("connect", kind, username, password, ip_addr))
            return FakeGateway(kind)
        return factory

    flow_api = ModuleType("FlowAPI")
    flow_api.EditShare = SimpleNamespace(create_gateway_instance=create("editshare"))
    flow_api.Admin = SimpleNamespace(create_gateway_instance=create("admin"))
    monkeypatch.setitem(__import__("sys").modules, "FlowAPI", flow_api)

    dotenv = ModuleType("dotenv")
    dotenv.load_dotenv = lambda path: None
    monkeypatch.setitem(__import__("sys").modules, "dotenv", dotenv)
    monkeypatch.setenv("FLOW_HOST", "127.0.0.1")
    monkeypatch.setenv("FLOW_USER", "probe-user")
    monkeypatch.setenv("FLOW_PASSWORD", "probe-password")
    return calls


def output_dir(tmp_path):
    matches = list(tmp_path.glob("*_storage"))
    assert len(matches) == 1
    return matches[0]


def read_summary(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def test_key_paths():
    assert probe.key_paths([{"a": {"b": 1}}, {"c": 2}]) == ["[].a", "[].a.b", "[].c"]


def test_run_call_timeout():
    never = threading.Event()
    started = time.monotonic()
    status, result, error_text, duration = probe.run_call(lambda: never.wait(), 0.2)
    assert status == "timeout"
    assert duration < 1


def test_run_call_error():
    def fail():
        raise RuntimeError("x")

    status, result, error_text, duration = probe.run_call(fail, 0.2)
    assert status == "error"
    assert "x" in error_text


def test_main_all_steps(monkeypatch, tmp_path):
    calls = install_fakes(monkeypatch, details_result=[{"name": "Iran Archiv", "used": 1}])
    monkeypatch.setattr(probe, "out_root", tmp_path)
    monkeypatch.setattr(probe, "call_timeout", 0.2)

    assert probe.main() == 0

    result_dir = output_dir(tmp_path)
    json_files = sorted(result_dir.glob("*.json"))
    assert len(json_files) == 4
    rows = read_summary(result_dir / "storage_summary.csv")
    assert len(rows) == 4
    assert ("get_space", "Iran Archiv") in calls
    connections = [call for call in calls if call[0] == "connect"]
    assert [call[1] for call in connections] == ["editshare", "editshare", "editshare", "admin"]
    assert [call for call in calls if call[0] in {"get_spaces", "get_space", "get_mediaspaces"}] == [
        ("get_spaces", True),
        ("get_spaces", False),
        ("get_space", "Iran Archiv"),
        ("get_mediaspaces", True),
    ]
    assert [path.name for path in json_files] == [
        "01_storage_get_spaces_details.json",
        "02_storage_get_spaces.json",
        "03_storage_get_space.json",
        "04_admin_get_mediaspaces.json",
    ]


def test_main_timeout_continues(monkeypatch, tmp_path):
    release = threading.Event()
    calls = install_fakes(monkeypatch, hang_details=release)
    monkeypatch.setattr(probe, "out_root", tmp_path)
    monkeypatch.setattr(probe, "call_timeout", 0.2)

    try:
        assert probe.main() == 0
        result_dir = output_dir(tmp_path)
        rows = read_summary(result_dir / "storage_summary.csv")
        assert [row["status"] for row in rows] == ["timeout", "empty", "skipped", "ok"]
        assert ("get_spaces", False) in calls
        assert ("get_mediaspaces", True) in calls
    finally:
        release.set()


def test_main_http_error(monkeypatch, tmp_path):
    install_fakes(monkeypatch, return_code=403)
    monkeypatch.setattr(probe, "out_root", tmp_path)
    monkeypatch.setattr(probe, "call_timeout", 0.2)

    assert probe.main() == 0
    result_dir = output_dir(tmp_path)
    first = json.loads((result_dir / "01_storage_get_spaces_details.json").read_text(encoding="utf-8"))
    assert first["status"] == "http_error"
    assert first["http_code"] == 403


def test_missing_creds(monkeypatch, tmp_path, capsys):
    calls = install_fakes(monkeypatch)
    monkeypatch.delenv("FLOW_PASSWORD")
    monkeypatch.setattr(probe, "out_root", tmp_path)

    assert probe.main() == 1
    assert calls == []
    assert "FLOW_PASSWORD" in capsys.readouterr().out


def test_configure_console_enables_line_buffering(monkeypatch):
    class Stream:
        def __init__(self):
            self.options = None

        def reconfigure(self, **options):
            self.options = options

    stdout = Stream()
    stderr = Stream()
    monkeypatch.setattr(probe.sys, "stdout", stdout)
    monkeypatch.setattr(probe.sys, "stderr", stderr)

    probe._configure_console()

    for stream in (stdout, stderr):
        assert stream.options == {"encoding": "utf-8", "errors": "replace", "line_buffering": True}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"other": "value"}, None),
        ([{"space_name": "Iran"}], "Iran"),
        ([], None),
        (None, None),
    ],
)
def test_find_space_name_handles_unexpected_shapes(value, expected):
    assert probe._find_space_name(value) == expected


def test_main_error_continues_and_writes_summary(monkeypatch, tmp_path):
    install_fakes(monkeypatch)
    original = probe._call_editshare

    def fail_details(username, password, ip_addr, method, *args, **kwargs):
        if method == "get_spaces" and kwargs.get("details") is True:
            raise RuntimeError("details unavailable")
        return original(username, password, ip_addr, method, *args, **kwargs)

    monkeypatch.setattr(probe, "_call_editshare", fail_details)
    monkeypatch.setattr(probe, "out_root", tmp_path)
    monkeypatch.setattr(probe, "call_timeout", 0.2)

    assert probe.main() == 0

    result_dir = output_dir(tmp_path)
    assert [row["status"] for row in read_summary(result_dir / "storage_summary.csv")] == [
        "error", "empty", "skipped", "ok"
    ]
    first = json.loads((result_dir / "01_storage_get_spaces_details.json").read_text(encoding="utf-8"))
    assert "details unavailable" in first["error"]
