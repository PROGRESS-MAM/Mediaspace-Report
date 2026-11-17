import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import ms_state as state_module
from ms_state import (
    StateError,
    add_snapshot,
    closable_months,
    drop_month,
    group_snapshot_mean,
    last_snapshot_day,
    load_state,
    month_totals,
    new_state,
    save_state,
    snapshot_count,
    snapshot_day,
)


BER = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class Space:
    uuid: str
    name: str
    created: datetime
    removed: datetime | None
    used_bytes: int


def make_space(uuid, used_bytes, *, name=None, created=None, removed=None):
    return Space(
        uuid,
        name or uuid,
        created or datetime(2026, 1, 1, tzinfo=BER),
        removed,
        used_bytes,
    )


def test_snapshot_day():
    assert snapshot_day(datetime(2026, 12, 1, 0, 1, tzinfo=BER)) == date(2026, 11, 30)
    assert snapshot_day(datetime(2026, 11, 17, 0, 1)) == date(2026, 11, 16)
    assert snapshot_day(datetime(2026, 11, 30, 23, 1, tzinfo=timezone.utc)) == date(2026, 11, 30)


def test_first_snapshot():
    state = new_state()
    removed = datetime(2026, 11, 15, tzinfo=BER)
    add_snapshot(state, date(2026, 11, 16), [make_space("A", 100), make_space("B", 5, removed=removed)])
    assert state["months"]["2026-11"]["snapshots"] == [
        {"day": "2026-11-16", "interpolated": False, "values": {"A": 100}}
    ]
    assert "B" not in state["months"]["2026-11"]["spaces"]
    assert state["last"]["day"] == "2026-11-16"


def test_same_day_replaces():
    state = new_state()
    add_snapshot(state, date(2026, 11, 16), [make_space("A", 100)])
    add_snapshot(state, date(2026, 11, 16), [make_space("A", 200)])
    assert state["months"]["2026-11"]["snapshots"] == [
        {"day": "2026-11-16", "interpolated": False, "values": {"A": 200}}
    ]


def test_one_missing_night():
    state = new_state()
    add_snapshot(state, date(2026, 11, 10), [make_space("A", 100)])
    add_snapshot(state, date(2026, 11, 12), [make_space("A", 200)])
    assert snapshot_count(state, "2026-11") == 2


def test_interpolation_linear():
    state = new_state()
    add_snapshot(state, date(2026, 11, 10), [make_space("A", 100)])
    add_snapshot(state, date(2026, 11, 14), [make_space("A", 500)])
    snapshots = state["months"]["2026-11"]["snapshots"]
    assert [(item["day"], item["values"], item["interpolated"]) for item in snapshots] == [
        ("2026-11-10", {"A": 100}, False),
        ("2026-11-11", {"A": 200}, True),
        ("2026-11-12", {"A": 300}, True),
        ("2026-11-13", {"A": 400}, True),
        ("2026-11-14", {"A": 500}, False),
    ]


def test_interpolation_created_removed():
    state = new_state()
    removed = datetime(2026, 11, 12, 10, 0, tzinfo=BER)
    created = datetime(2026, 11, 12, 8, 0, tzinfo=BER)
    add_snapshot(
        state,
        date(2026, 11, 10),
        [make_space("A", 100), make_space("B", 50)],
    )
    add_snapshot(
        state,
        date(2026, 11, 14),
        [make_space("A", 100, removed=removed), make_space("B", 50), make_space("C", 70, created=created)],
    )
    snapshots = {item["day"]: item["values"] for item in state["months"]["2026-11"]["snapshots"]}
    assert snapshots == {
        "2026-11-10": {"A": 100, "B": 50},
        "2026-11-11": {"A": 100, "B": 50},
        "2026-11-12": {"B": 50, "C": 70},
        "2026-11-13": {"B": 50, "C": 70},
        "2026-11-14": {"B": 50, "C": 70},
    }


def test_month_boundary():
    state = new_state()
    add_snapshot(state, date(2026, 11, 28), [make_space("A", 100)])
    add_snapshot(state, date(2026, 12, 2), [make_space("A", 500)])
    november = {item["day"]: item for item in state["months"]["2026-11"]["snapshots"]}
    december = {item["day"]: item for item in state["months"]["2026-12"]["snapshots"]}
    assert november["2026-11-29"]["values"] == {"A": 200}
    assert november["2026-11-30"]["values"] == {"A": 300}
    assert december["2026-12-01"]["values"] == {"A": 400}
    assert december["2026-12-02"]["values"] == {"A": 500}
    assert closable_months(state, date(2026, 12, 2)) == ["2026-11"]


def test_closable_last_day():
    state = new_state()
    add_snapshot(state, date(2026, 11, 16), [make_space("A", 100)])
    assert closable_months(state, date(2026, 11, 30)) == ["2026-11"]
    assert closable_months(state, date(2026, 11, 29)) == []


def test_month_totals_and_mean():
    state = {
        "version": 1,
        "months": {
            "2026-11": {
                "snapshots": [
                    {"day": "2026-11-10", "interpolated": False, "values": {"A": 100, "B": 10}},
                    {"day": "2026-11-11", "interpolated": False, "values": {"A": 200}},
                    {"day": "2026-11-12", "interpolated": True, "values": {"A": 300}},
                ],
                "spaces": {
                    "A": {"name": "Alpha", "created": None, "removed": None},
                    "B": {"name": "Beta", "created": None, "removed": None},
                },
            }
        },
        "last": None,
        "extra": {},
    }
    totals = {item.uuid: item for item in month_totals(state, "2026-11")}
    assert (totals["A"].value_sum, totals["A"].snapshots, totals["A"].interpolated) == (600, 3, True)
    assert (totals["B"].value_sum, totals["B"].snapshots, totals["B"].interpolated) == (10, 1, False)
    assert snapshot_count(state, "2026-11") == 3
    assert last_snapshot_day(state, "2026-11") == date(2026, 11, 12)
    assert group_snapshot_mean(state, "2026-11", {"A", "B"}) == pytest.approx(610 / 3)
    assert group_snapshot_mean(state, "2026-11", {"B"}) == 10.0
    assert group_snapshot_mean(state, "2026-11", {"X"}) is None


def test_day_before_last_raises():
    state = new_state()
    add_snapshot(state, date(2026, 11, 16), [make_space("A", 100)])
    before = deepcopy(state)
    with pytest.raises(StateError, match=r"Snapshot-Tag 2026-11-15 liegt vor dem letzten Snapshot 2026-11-16"):
        add_snapshot(state, date(2026, 11, 15), [make_space("A", 200)])
    assert state == before


def test_load_save(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    assert load_state(path) == new_state()
    state = new_state()
    add_snapshot(state, date(2026, 11, 16), [make_space("A", 100)])
    save_state(path, state)
    assert load_state(path) == state

    path.write_text("{bad json", encoding="utf-8")
    original = path.read_text(encoding="utf-8")
    with pytest.raises(StateError, match="Zustandsdatei"):
        load_state(path)
    assert path.read_text(encoding="utf-8") == original

    def fail_replace(source, destination):
        raise PermissionError("denied")

    monkeypatch.setattr(state_module.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="denied"):
        save_state(path, state)
    assert list(tmp_path.iterdir()) == [path]


def test_load_rejects_version_and_missing_keys_without_modifying_file(tmp_path):
    for payload in ({"version": 2, "months": {}, "last": None, "extra": {}}, {"version": 1, "months": {}}):
        path = tmp_path / "invalid.json"
        original = json.dumps(payload)
        path.write_text(original, encoding="utf-8")
        with pytest.raises(StateError, match="Zustandsdatei"):
            load_state(path)
        assert path.read_text(encoding="utf-8") == original


def test_unknown_months_and_drop_month():
    state = new_state()
    assert snapshot_count(state, "2026-11") == 0
    assert last_snapshot_day(state, "2026-11") is None
    assert month_totals(state, "2026-11") == []
    assert group_snapshot_mean(state, "2026-11", {"A"}) is None
    add_snapshot(state, date(2026, 11, 16), [make_space("A", 100)])
    drop_month(state, "2026-11")
    assert "2026-11" not in state["months"]
    drop_month(state, "2026-11")


def test_metadata_updates_across_months():
    state = new_state()
    add_snapshot(state, date(2026, 10, 31), [make_space("A", 100, name="Old name")])
    add_snapshot(state, date(2026, 11, 2), [make_space("A", 200, name="New name")])
    assert state["months"]["2026-10"]["spaces"]["A"]["name"] == "New name"


def test_add_snapshot_stores_integer_values():
    state = new_state()
    add_snapshot(state, date(2026, 11, 16), [make_space("A", 12.75)])

    value = state["months"]["2026-11"]["snapshots"][0]["values"]["A"]
    assert value == 12
    assert type(value) is int


def test_uuid_missing_from_api_is_not_interpolated():
    state = new_state()
    add_snapshot(state, date(2026, 11, 10), [make_space("A", 100)])
    add_snapshot(state, date(2026, 11, 14), [make_space("B", 50)])

    snapshots = {item["day"]: item["values"] for item in state["months"]["2026-11"]["snapshots"]}
    assert snapshots["2026-11-11"] == {"B": 50}
    assert snapshots["2026-11-12"] == {"B": 50}
    assert snapshots["2026-11-13"] == {"B": 50}
