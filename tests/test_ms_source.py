import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Event
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import ms_source


def install_fakes(
    monkeypatch,
    *,
    result=None,
    return_code=200,
    error=None,
    wait_event=None,
):
    calls = []

    class FakeGateway:
        def get_mediaspaces(self, as_admin=False):
            calls.append(("get_mediaspaces", as_admin))
            if wait_event is not None:
                wait_event.wait()
            if error is not None:
                raise error
            return result

        def lastReturnCode(self):
            return return_code

    def create_gateway_instance(username, password, ip_addr):
        calls.append(("create_gateway_instance", username, password, ip_addr))
        return FakeGateway()

    flow_api = ModuleType("FlowAPI")
    flow_api.Admin = SimpleNamespace(create_gateway_instance=create_gateway_instance)
    monkeypatch.setitem(sys.modules, "FlowAPI", flow_api)

    dotenv = ModuleType("dotenv")
    dotenv.load_dotenv = lambda path: None
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)
    monkeypatch.setenv("FLOW_HOST", "127.0.0.1")
    monkeypatch.setenv("FLOW_USER", "test-user")
    monkeypatch.setenv("FLOW_PASSWORD", "test-password")
    return calls


def test_parse_spaces():
    raw = [
        {
            "uuid": "u1",
            "name": "1989 Onlining",
            "created": "2026-01-22T10:32:57Z",
            "removed": None,
            "mount_used_bytes": 17023247657680,
            "credentials": {"password": "secret"},
        },
        {
            "uuid": "u2",
            "name": "afghanistan archiv",
            "created": "2018-03-05T13:47:49Z",
            "removed": "2023-07-17T09:39:27Z",
            "mount_used_bytes": None,
        },
        {"name": "ohne uuid", "created": "2020-01-01T00:00:00Z"},
    ]

    result = ms_source.parse_spaces(raw)

    assert len(result) == 2
    assert result[0].uuid == "u1"
    assert result[0].created == datetime(2026, 1, 22, 11, 32, 57, tzinfo=ZoneInfo("Europe/Berlin"))
    assert result[1].removed.hour == 11
    assert result[1].used_bytes == 0
    assert "secret" not in repr(result)


def test_parse_spaces_invalid_bytes():
    raw = [
        {"uuid": "u1", "name": "one", "created": "2026-01-22T10:32:57Z", "mount_used_bytes": "abc"},
        {"uuid": "u2", "name": "two", "created": "2026-01-22T10:32:57Z", "mount_used_bytes": -5},
    ]

    assert [space.used_bytes for space in ms_source.parse_spaces(raw)] == [0, 0]


def test_parse_spaces_invalid_removed():
    raw = [{
        "uuid": "u1",
        "name": "one",
        "created": "2026-01-22T10:32:57Z",
        "removed": "not-a-timestamp",
    }]

    assert ms_source.parse_spaces(raw) == []


def test_fetch_ok(tmp_path, monkeypatch):
    expected = [{"uuid": "u1"}]
    calls = install_fakes(monkeypatch, result=expected)

    assert ms_source.fetch_spaces(tmp_path / "cred.env", 1.0) == expected
    assert ("get_mediaspaces", True) in calls


def test_fetch_timeout(tmp_path, monkeypatch):
    never = Event()
    install_fakes(monkeypatch, result=[], wait_event=never)

    started = time.monotonic()
    try:
        with pytest.raises(ms_source.FetchError) as error:
            ms_source.fetch_spaces(tmp_path / "cred.env", 0.2)
        assert str(error.value) == "Keine Antwort der Admin-API nach 0.2 s"
        assert time.monotonic() - started < 1
    finally:
        never.set()


def test_fetch_http_error(tmp_path, monkeypatch):
    install_fakes(monkeypatch, result={}, return_code=401)

    with pytest.raises(ms_source.FetchError) as error:
        ms_source.fetch_spaces(tmp_path / "cred.env", 1.0)

    assert str(error.value) == "Admin-API antwortet mit HTTP 401"


def test_fetch_exception(tmp_path, monkeypatch):
    install_fakes(monkeypatch, error=RuntimeError("down"))

    with pytest.raises(ms_source.FetchError) as error:
        ms_source.fetch_spaces(tmp_path / "cred.env", 1.0)

    assert str(error.value) == "Admin-API-Fehler: RuntimeError: down"


def test_fetch_empty(tmp_path, monkeypatch):
    install_fakes(monkeypatch, result=[])

    with pytest.raises(ms_source.FetchError) as error:
        ms_source.fetch_spaces(tmp_path / "cred.env", 1.0)

    assert str(error.value) == "Admin-API liefert keine Spaces"


def test_fetch_not_list(tmp_path, monkeypatch):
    install_fakes(monkeypatch, result={"a": 1})

    with pytest.raises(ms_source.FetchError) as error:
        ms_source.fetch_spaces(tmp_path / "cred.env", 1.0)

    assert str(error.value) == "Admin-API liefert keine Liste"


def test_fetch_missing_creds(tmp_path, monkeypatch):
    calls = install_fakes(monkeypatch, result=[])
    monkeypatch.delenv("FLOW_USER")

    with pytest.raises(ms_source.FetchError) as error:
        ms_source.fetch_spaces(tmp_path / "cred.env", 1.0)

    assert str(error.value) == "Fehlt in cred.env: FLOW_USER"

    assert not any(call[0] == "create_gateway_instance" for call in calls)


def test_fetch_error_does_not_expose_credentials(tmp_path, monkeypatch):
    install_fakes(monkeypatch, error=RuntimeError("rejected test-password"))

    with pytest.raises(ms_source.FetchError) as error:
        ms_source.fetch_spaces(tmp_path / "cred.env", 1.0)

    assert "test-password" not in str(error.value)


def test_timeout_does_not_prevent_process_exit(tmp_path):
    script = """import os, sys, threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
import ms_source
flow = ModuleType("FlowAPI")
class Gateway:
    def get_mediaspaces(self, as_admin=False): threading.Event().wait()
    def lastReturnCode(self): return 200
flow.Admin = SimpleNamespace(create_gateway_instance=lambda *args: Gateway())
sys.modules["FlowAPI"] = flow
sys.modules["dotenv"] = SimpleNamespace(load_dotenv=lambda *args: None)
os.environ.update(FLOW_USER="user", FLOW_PASSWORD="password", FLOW_HOST="host")
try:
    ms_source.fetch_spaces(Path("cred.env"), 0.05)
except ms_source.FetchError:
    pass
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
