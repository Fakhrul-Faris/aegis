"""Point-in-time helpers for research backtests (FX-R2)."""

from __future__ import annotations

from datetime import UTC, datetime


def parse_as_of(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = value.strip()
    if len(text) == 10:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def assert_bar_before_as_of(open_time: datetime, as_of: datetime, *, label: str = "bar") -> None:
    ot = open_time.astimezone(UTC) if open_time.tzinfo else open_time.replace(tzinfo=UTC)
    if ot > as_of:
        raise ValueError(f"{label} {ot.isoformat()} is after as_of {as_of.isoformat()}")


def filter_rows_before_as_of(rows: list, as_of: datetime | None, *, time_attr: str = "open_time"):
    if as_of is None:
        return rows
    out = []
    for row in rows:
        ts = getattr(row, time_attr)
        if (ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)) <= as_of:
            out.append(row)
    return out
