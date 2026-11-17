# IMPORTS
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Protocol
from zoneinfo import ZoneInfo


# CONFIG
app_name = "ms_state"
app_version = "0.1.0"
_BERLIN = ZoneInfo("Europe/Berlin")


# TYPES
class SpaceLike(Protocol):
    uuid: str
    name: str
    created: datetime
    removed: datetime | None
    used_bytes: int


@dataclass(frozen=True)
class SpaceTotal:
    """Monthly usage totals and metadata for one media space."""

    uuid: str
    name: str
    created: datetime | None
    removed: datetime | None
    value_sum: int
    snapshots: int
    interpolated: bool


class StateError(RuntimeError):
    """Raised when the stored state is invalid or snapshots are out of order."""


def new_state() -> dict:
    """Return an empty version-1 state."""
    return {"version": 1, "months": {}, "last": None, "extra": {}}


def load_state(path: Path) -> dict:
    """Load a version-1 state, returning an empty state when the file is absent."""
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return new_state()
    except UnicodeDecodeError as error:
        raise StateError(f"Zustandsdatei {path} ist beschädigt: {error}") from error

    try:
        state = json.loads(content)
    except json.JSONDecodeError as error:
        raise StateError(f"Zustandsdatei {path} ist beschädigt: {error}") from error

    if not isinstance(state, dict):
        raise StateError(f"Zustandsdatei {path} ist beschädigt: Wurzel ist kein Objekt")
    missing = {"version", "months", "last", "extra"} - state.keys()
    if missing:
        raise StateError(f"Zustandsdatei {path} ist beschädigt: fehlende Schlüssel {', '.join(sorted(missing))}")
    if type(state["version"]) is not int or state["version"] != 1:
        raise StateError(f"Zustandsdatei {path} ist beschädigt: Version ist nicht 1")
    return state


def save_state(path: Path, state: dict) -> None:
    """Atomically save a state as sorted, indented UTF-8 JSON."""
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(state, temp_file, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def snapshot_day(run_time: datetime) -> date:
    """Return the Berlin calendar day covered by a run, one day earlier."""
    berlin_time = run_time.replace(tzinfo=_BERLIN) if run_time.tzinfo is None else run_time.astimezone(_BERLIN)
    return berlin_time.date() - timedelta(days=1)


def _month_key(day: date) -> str:
    return day.strftime("%Y-%m")


def _month_for(state: dict, month: str) -> dict:
    return state["months"].setdefault(month, {"snapshots": [], "spaces": {}})


def _add_month_snapshot(state: dict, day: date, values: dict[str, int], interpolated: bool) -> None:
    month = _month_for(state, _month_key(day))
    day_text = day.isoformat()
    month["snapshots"] = [snapshot for snapshot in month["snapshots"] if snapshot["day"] != day_text]
    month["snapshots"].append({"day": day_text, "interpolated": interpolated, "values": values})
    month["snapshots"].sort(key=lambda snapshot: snapshot["day"])


def add_snapshot(state: dict, day: date, spaces: Iterable[SpaceLike]) -> None:
    """Add or replace a nightly snapshot and interpolate sufficiently long gaps."""
    current_spaces = list(spaces)
    current_values = {space.uuid: int(space.used_bytes) for space in current_spaces if space.removed is None}
    last = state["last"]
    last_day = date.fromisoformat(last["day"]) if last is not None else None

    if last_day is not None and day < last_day:
        raise StateError(f"Snapshot-Tag {day.isoformat()} liegt vor dem letzten Snapshot {last_day.isoformat()}")

    if last_day is not None and day > last_day:
        gap_days = (day - last_day).days - 1
        if gap_days >= 2:
            last_values = last["values"]
            by_uuid = {space.uuid: space for space in current_spaces}
            for index in range(1, gap_days + 1):
                missing_day = last_day + timedelta(days=index)
                missing_values: dict[str, int] = {}
                for uuid in sorted(last_values.keys() | current_values.keys()):
                    space = by_uuid.get(uuid)
                    if space is None:
                        exists = uuid in last_values and uuid in current_values
                    else:
                        exists = space.created.date() <= missing_day and (
                            space.removed is None or space.removed.date() > missing_day
                        )
                    if not exists:
                        continue
                    in_last = uuid in last_values
                    in_current = uuid in current_values
                    if in_last and in_current:
                        value = round(last_values[uuid] + (current_values[uuid] - last_values[uuid]) * index / (gap_days + 1))
                    elif in_last:
                        value = last_values[uuid]
                    else:
                        value = current_values[uuid]
                    missing_values[uuid] = value
                _add_month_snapshot(state, missing_day, missing_values, True)

    _add_month_snapshot(state, day, current_values, False)
    state["last"] = {"day": day.isoformat(), "values": current_values}

    metadata = {
        space.uuid: {
            "name": space.name,
            "created": space.created.isoformat() if space.created is not None else None,
            "removed": space.removed.isoformat() if space.removed is not None else None,
        }
        for space in current_spaces
    }
    for month in state["months"].values():
        occurring = {uuid for snapshot in month["snapshots"] for uuid in snapshot["values"]}
        for uuid in occurring & metadata.keys():
            month["spaces"][uuid] = metadata[uuid]


def closable_months(state: dict, day: date) -> list[str]:
    """Return stored months strictly before this month and this month on its last day."""
    current_month = _month_key(day)
    months = [month for month in state["months"] if month < current_month]
    if (day + timedelta(days=1)).day == 1:
        months.append(current_month)
    return sorted(months)


def drop_month(state: dict, month: str) -> None:
    """Remove a month from the state if it exists."""
    state["months"].pop(month, None)


def snapshot_count(state: dict, month: str) -> int:
    """Return the number of snapshots stored for a month."""
    month_state = state["months"].get(month)
    return len(month_state["snapshots"]) if month_state is not None else 0


def last_snapshot_day(state: dict, month: str) -> date | None:
    """Return the latest snapshot day for a month, or None when absent."""
    month_state = state["months"].get(month)
    if month_state is None or not month_state["snapshots"]:
        return None
    return date.fromisoformat(max(snapshot["day"] for snapshot in month_state["snapshots"]))


def _parse_metadata_date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def month_totals(state: dict, month: str) -> list[SpaceTotal]:
    """Aggregate saved values and interpolation flags by UUID for a month."""
    month_state = state["months"].get(month)
    if month_state is None:
        return []

    totals: dict[str, list[int | bool]] = {}
    for snapshot in month_state["snapshots"]:
        for uuid, value in snapshot["values"].items():
            aggregate = totals.setdefault(uuid, [0, 0, False])
            aggregate[0] += value
            aggregate[1] += 1
            aggregate[2] = aggregate[2] or snapshot["interpolated"]

    spaces = month_state["spaces"]
    result = []
    for uuid, (value_sum, snapshots, interpolated) in totals.items():
        metadata = spaces.get(uuid, {})
        result.append(
            SpaceTotal(
                uuid=uuid,
                name=metadata.get("name", uuid),
                created=_parse_metadata_date(metadata.get("created")),
                removed=_parse_metadata_date(metadata.get("removed")),
                value_sum=int(value_sum),
                snapshots=int(snapshots),
                interpolated=bool(interpolated),
            )
        )
    return sorted(result, key=lambda total: (total.name.casefold(), total.uuid))


def group_snapshot_mean(state: dict, month: str, uuids: set[str]) -> float | None:
    """Return the mean per-snapshot sum for the selected UUIDs."""
    month_state = state["months"].get(month)
    if month_state is None:
        return None
    sums = [
        sum(snapshot["values"].get(uuid, 0) for uuid in uuids)
        for snapshot in month_state["snapshots"]
        if any(uuid in snapshot["values"] for uuid in uuids)
    ]
    return sum(sums) / len(sums) if sums else None
