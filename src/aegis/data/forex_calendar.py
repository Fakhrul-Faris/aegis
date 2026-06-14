"""Economic calendar seed for forex SCM research (FX0).

Generates high-impact USD/EUR event timestamps for backtest calendar filters.
NFP is algorithmic (first Friday). FOMC/CPI/ECB use embedded schedules +
simple rules where exact times are stable.

This is a research seed, not a live economic calendar API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aegis.data.db import CalendarEvent, upsert_calendar_events

# FOMC announcement dates (UTC date; 18:00 UTC release on decision days).
# Source: Federal Reserve public calendars — high-impact tier 3.
FOMC_DATES: tuple[str, ...] = (
    # 2015
    "2015-01-28",
    "2015-03-18",
    "2015-04-29",
    "2015-06-17",
    "2015-07-29",
    "2015-09-17",
    "2015-10-28",
    "2015-12-16",
    # 2016
    "2016-01-27",
    "2016-03-16",
    "2016-04-27",
    "2016-06-15",
    "2016-07-27",
    "2016-09-21",
    "2016-11-02",
    "2016-12-14",
    # 2017
    "2017-02-01",
    "2017-03-15",
    "2017-05-03",
    "2017-06-14",
    "2017-07-26",
    "2017-09-20",
    "2017-11-01",
    "2017-12-13",
    # 2018
    "2018-01-31",
    "2018-03-21",
    "2018-05-02",
    "2018-06-13",
    "2018-08-01",
    "2018-09-26",
    "2018-11-08",
    "2018-12-19",
    # 2019
    "2019-01-30",
    "2019-03-20",
    "2019-05-01",
    "2019-06-19",
    "2019-07-31",
    "2019-09-18",
    "2019-10-30",
    "2019-12-11",
    # 2020
    "2020-01-29",
    "2020-03-15",
    "2020-04-29",
    "2020-06-10",
    "2020-07-29",
    "2020-09-16",
    "2020-11-05",
    "2020-12-16",
    # 2021
    "2021-01-27",
    "2021-03-17",
    "2021-04-28",
    "2021-06-16",
    "2021-07-28",
    "2021-09-22",
    "2021-11-03",
    "2021-12-15",
    # 2022
    "2022-01-26",
    "2022-03-16",
    "2022-05-04",
    "2022-06-15",
    "2022-07-27",
    "2022-09-21",
    "2022-11-02",
    "2022-12-14",
    # 2023
    "2023-02-01",
    "2023-03-22",
    "2023-05-03",
    "2023-06-14",
    "2023-07-26",
    "2023-09-20",
    "2023-11-01",
    "2023-12-13",
    # 2024
    "2024-01-31",
    "2024-03-20",
    "2024-05-01",
    "2024-06-12",
    "2024-07-31",
    "2024-09-18",
    "2024-11-07",
    "2024-12-18",
    # 2025
    "2025-01-29",
    "2025-03-19",
    "2025-05-07",
    "2025-06-18",
    "2025-07-30",
    "2025-09-17",
    "2025-10-29",
    "2025-12-10",
    # 2026 (scheduled / placeholder — verify before live)
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-11-04",
    "2026-12-16",
    # 2027 forward placeholders for watch alerts
    "2027-01-27",
    "2027-03-17",
    "2027-04-28",
    "2027-06-16",
)

# US CPI release dates (approx mid-month Tue/Wed; 12:30 UTC = 08:30 ET).
US_CPI_DATES: tuple[str, ...] = tuple(
    f"{year}-{month:02d}-12"
    for year in range(2015, 2028)
    for month in range(1, 13)
)

# ECB rate decision Thursdays (approx — tier 3 for EUR pairs).
ECB_MONTHS = (1, 3, 4, 6, 7, 9, 10, 12)


def _utc_ms(date_str: str, hour: int, minute: int = 0) -> int:
    y, m, d = (int(p) for p in date_str.split("-"))
    dt = datetime(y, m, d, hour, minute, tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _first_friday(year: int, month: int) -> datetime:
    for day in range(1, 8):
        dt = datetime(year, month, day, tzinfo=UTC)
        if dt.weekday() == 4:  # Friday
            return dt
    raise ValueError(f"no Friday in first week of {year}-{month:02d}")


def _nfp_events(year_start: int, year_end: int) -> list[CalendarEvent]:
    out: list[CalendarEvent] = []
    for year in range(year_start, year_end + 1):
        for month in range(1, 13):
            friday = _first_friday(year, month)
            ts_ms = int(friday.replace(hour=12, minute=30).timestamp() * 1000)
            out.append(
                CalendarEvent(
                    ts_ms=ts_ms,
                    currency="USD",
                    impact_tier=3,
                    event_code="NFP",
                    title="US Non-Farm Payrolls",
                )
            )
    return out


def _fomc_events() -> list[CalendarEvent]:
    return [
        CalendarEvent(
            ts_ms=_utc_ms(d, 18, 0),
            currency="USD",
            impact_tier=3,
            event_code="FOMC",
            title="FOMC rate decision",
        )
        for d in FOMC_DATES
    ]


def _cpi_events(year_start: int, year_end: int) -> list[CalendarEvent]:
    out: list[CalendarEvent] = []
    for date_str in US_CPI_DATES:
        year = int(date_str[:4])
        if year < year_start or year > year_end:
            continue
        y, m, d = (int(p) for p in date_str.split("-"))
        dt = datetime(y, m, d, tzinfo=UTC)
        # Roll forward to next weekday if weekend.
        while dt.weekday() >= 5:
            dt += timedelta(days=1)
        ts_ms = int(dt.replace(hour=12, minute=30).timestamp() * 1000)
        out.append(
            CalendarEvent(
                ts_ms=ts_ms,
                currency="USD",
                impact_tier=3,
                event_code="CPI",
                title="US CPI",
            )
        )
    return out


def _boe_events(year_start: int, year_end: int) -> list[CalendarEvent]:
    """BoE rate decisions — first Thursday of selected months, 12:00 UTC."""
    months = (2, 5, 8, 11)
    out: list[CalendarEvent] = []
    for year in range(year_start, year_end + 1):
        for month in months:
            for day in range(1, 8):
                dt = datetime(year, month, day, tzinfo=UTC)
                if dt.weekday() == 3:
                    ts_ms = int(dt.replace(hour=12, minute=0).timestamp() * 1000)
                    out.append(
                        CalendarEvent(
                            ts_ms=ts_ms,
                            currency="GBP",
                            impact_tier=3,
                            event_code="BOE",
                            title="BoE rate decision",
                        )
                    )
                    break
    return out


def _us_retail_events(year_start: int, year_end: int) -> list[CalendarEvent]:
    """US Retail Sales — ~13th of month 12:30 UTC, tier 2."""
    out: list[CalendarEvent] = []
    for year in range(year_start, year_end + 1):
        for month in range(1, 13):
            dt = datetime(year, month, 13, tzinfo=UTC)
            while dt.weekday() >= 5:
                dt += timedelta(days=1)
            ts_ms = int(dt.replace(hour=12, minute=30).timestamp() * 1000)
            out.append(
                CalendarEvent(
                    ts_ms=ts_ms,
                    currency="USD",
                    impact_tier=2,
                    event_code="RETAIL",
                    title="US Retail Sales",
                )
            )
    return out


def _us_gdp_events(year_start: int, year_end: int) -> list[CalendarEvent]:
    """US GDP advance — quarterly, tier 2."""
    out: list[CalendarEvent] = []
    for year in range(year_start, year_end + 1):
        for month in (1, 4, 7, 10):
            dt = datetime(year, month, 28, tzinfo=UTC)
            while dt.weekday() >= 5:
                dt += timedelta(days=1)
            ts_ms = int(dt.replace(hour=12, minute=30).timestamp() * 1000)
            out.append(
                CalendarEvent(
                    ts_ms=ts_ms,
                    currency="USD",
                    impact_tier=2,
                    event_code="GDP",
                    title="US GDP",
                )
            )
    return out


def _uk_cpi_events(year_start: int, year_end: int) -> list[CalendarEvent]:
    """UK CPI — ~17th of month 06:00 UTC, tier 2."""
    out: list[CalendarEvent] = []
    for year in range(year_start, year_end + 1):
        for month in range(1, 13):
            dt = datetime(year, month, 17, tzinfo=UTC)
            while dt.weekday() >= 5:
                dt += timedelta(days=1)
            ts_ms = int(dt.replace(hour=6, minute=0).timestamp() * 1000)
            out.append(
                CalendarEvent(
                    ts_ms=ts_ms,
                    currency="GBP",
                    impact_tier=2,
                    event_code="UKCPI",
                    title="UK CPI",
                )
            )
    return out


def _ecb_events(year_start: int, year_end: int) -> list[CalendarEvent]:
    out: list[CalendarEvent] = []
    for year in range(year_start, year_end + 1):
        for month in ECB_MONTHS:
            # First Thursday of the month (approx ECB cadence).
            for day in range(1, 8):
                dt = datetime(year, month, day, tzinfo=UTC)
                if dt.weekday() == 3:
                    ts_ms = int(dt.replace(hour=12, minute=15).timestamp() * 1000)
                    out.append(
                        CalendarEvent(
                            ts_ms=ts_ms,
                            currency="EUR",
                            impact_tier=3,
                            event_code="ECB",
                            title="ECB rate decision",
                        )
                    )
                    break
    return out


def build_calendar_seed(year_start: int = 2015, year_end: int = 2027) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    events.extend(_nfp_events(year_start, year_end))
    events.extend(_fomc_events())
    events.extend(_cpi_events(year_start, year_end))
    events.extend(_ecb_events(year_start, year_end))
    events.extend(_boe_events(year_start, year_end))
    events.extend(_us_retail_events(year_start, year_end))
    events.extend(_us_gdp_events(year_start, year_end))
    events.extend(_uk_cpi_events(year_start, year_end))
    return events


def seed_economic_calendar(conn, *, year_start: int = 2015, year_end: int = 2027) -> int:
    events = build_calendar_seed(year_start=year_start, year_end=year_end)
    return upsert_calendar_events(conn, events)
