"""Forex session labels and SCM setup detection (FX1 spine).

Session-Confirmed Momentum v1: Asian range formation, London breakout entry.
Confirmation layers (ADR, DXY, calendar) arrive in FX2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import StrEnum

import pandas as pd

from aegis.config_forex import ForexConfig, ScmConfig, SessionWindow, SessionsConfig


class SessionName(StrEnum):
    ASIAN = "asian"
    LONDON = "london"
    NEW_YORK = "new_york"
    OFF = "off"


@dataclass(frozen=True)
class AsianRange:
    date: object  # pandas Timestamp (UTC day)
    high: float
    low: float
    bars: int


@dataclass(frozen=True)
class BreakoutSignal:
    date: object
    direction: str  # "long" | "short"
    entry_bar_ts: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    asian_high: float
    asian_low: float
    event_code: str | None = None


def _parse_hhmm(value: str) -> time:
    hour, minute = (int(p) for p in value.split(":"))
    return time(hour, minute)


def _in_window(t: time, window: SessionWindow) -> bool:
    start = _parse_hhmm(window.start)
    end = _parse_hhmm(window.end)
    if start < end:
        return start <= t < end
    # Overnight wrap (not used in default SCM config).
    return t >= start or t < end


def session_at(ts: pd.Timestamp, sessions: SessionsConfig) -> SessionName:
    t = ts.time()
    if _in_window(t, sessions.asian):
        return SessionName.ASIAN
    if _in_window(t, sessions.london):
        return SessionName.LONDON
    if _in_window(t, sessions.new_york):
        return SessionName.NEW_YORK
    return SessionName.OFF


def label_sessions(index: pd.DatetimeIndex, sessions: SessionsConfig) -> pd.Series:
    return pd.Series([session_at(ts, sessions).value for ts in index], index=index)


def compute_asian_ranges(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
) -> dict[object, AsianRange]:
    """Daily Asian high/low from 1h OHLC (UTC). Keys are normalized UTC dates."""
    if ohlc.empty:
        return {}
    df = ohlc.copy()
    df["session"] = label_sessions(df.index, sessions)
    asian = df[df["session"] == SessionName.ASIAN.value]
    if asian.empty:
        return {}
    asian = asian.copy()
    asian["utc_date"] = asian.index.normalize()
    ranges: dict[object, AsianRange] = {}
    for utc_date, group in asian.groupby("utc_date"):
        if len(group) < 3:
            continue
        ranges[utc_date] = AsianRange(
            date=utc_date,
            high=float(group["high"].max()),
            low=float(group["low"].min()),
            bars=len(group),
        )
    return ranges


def _london_entry_bars(
    day_df: pd.DataFrame,
    sessions: SessionsConfig,
    entry_window_minutes: int,
) -> pd.DataFrame:
    london_start = _parse_hhmm(sessions.london.start)
    start_minutes = london_start.hour * 60 + london_start.minute
    end_minutes = start_minutes + entry_window_minutes

    mask = []
    for ts in day_df.index:
        bar_minutes = ts.hour * 60 + ts.minute
        mask.append(start_minutes <= bar_minutes < end_minutes)
    return day_df.loc[mask]


def detect_london_breakout(
    ohlc: pd.DataFrame,
    cfg: ScmConfig,
    sessions: SessionsConfig,
    *,
    asian_ranges: dict[object, AsianRange] | None = None,
) -> list[BreakoutSignal]:
    """One signal max per UTC day — first close outside Asian range in London window."""
    if ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []

    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()

    for utc_date, day_df in df.groupby("utc_date"):
        asian = ranges.get(utc_date)
        if asian is None or asian.high <= asian.low:
            continue
        window = _london_entry_bars(day_df, sessions, cfg.london_entry_window_minutes)
        if window.empty:
            continue

        for ts, row in window.iterrows():
            close = float(row["close"])
            if close > asian.high:
                risk = close - asian.low
                if risk <= 0:
                    continue
                target = close + cfg.min_reward_risk * risk
                signals.append(
                    BreakoutSignal(
                        date=utc_date,
                        direction="long",
                        entry_bar_ts=ts,
                        entry_price=close,
                        stop_price=asian.low,
                        target_price=target,
                        asian_high=asian.high,
                        asian_low=asian.low,
                    )
                )
                break
            if close < asian.low:
                risk = asian.high - close
                if risk <= 0:
                    continue
                target = close - cfg.min_reward_risk * risk
                signals.append(
                    BreakoutSignal(
                        date=utc_date,
                        direction="short",
                        entry_bar_ts=ts,
                        entry_price=close,
                        stop_price=asian.high,
                        target_price=target,
                        asian_high=asian.high,
                        asian_low=asian.low,
                    )
                )
                break
    return signals


def detect_london_continuation(
    ohlc: pd.DataFrame,
    cfg: ScmConfig,
    sessions: SessionsConfig,
    *,
    asian_ranges: dict[object, AsianRange] | None = None,
) -> list[BreakoutSignal]:
    """Compressed Asian range → trade London open bar direction (no breakout chase)."""
    if ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []

    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()
    london_start = _parse_hhmm(sessions.london.start)

    for utc_date, day_df in df.groupby("utc_date"):
        asian = ranges.get(utc_date)
        if asian is None or asian.high <= asian.low:
            continue
        window = _london_entry_bars(day_df, sessions, cfg.london_entry_window_minutes)
        if window.empty:
            continue
        # First London bar only for continuation.
        ts = window.index[0]
        if ts.hour != london_start.hour:
            continue
        row = window.iloc[0]
        open_p = float(row["open"])
        close = float(row["close"])
        mid = (asian.high + asian.low) / 2.0

        if close > open_p and close > mid:
            direction = "long"
            stop = asian.low
            risk = close - stop
            if risk <= 0:
                continue
            target = close + cfg.min_reward_risk * risk
        elif close < open_p and close < mid:
            direction = "short"
            stop = asian.high
            risk = stop - close
            if risk <= 0:
                continue
            target = close - cfg.min_reward_risk * risk
        else:
            continue

        signals.append(
            BreakoutSignal(
                date=utc_date,
                direction=direction,
                entry_bar_ts=ts,
                entry_price=close,
                stop_price=stop,
                target_price=target,
                asian_high=asian.high,
                asian_low=asian.low,
            )
        )
    return signals


def _adr_on_date(ohlc: pd.DataFrame, utc_date, lookback: int) -> float | None:
    from aegis.strategy.forex_confirms import build_adr_series, daily_ranges_from_1h

    daily = daily_ranges_from_1h(ohlc)
    adr = build_adr_series(daily, lookback)
    key = pd.Timestamp(utc_date).normalize()
    if key not in adr.index:
        return None
    val = adr.loc[key]
    return None if pd.isna(val) or val <= 0 else float(val)


def detect_ny_fade(
    ohlc: pd.DataFrame,
    cfg: ScmConfig,
    sessions: SessionsConfig,
    *,
    asian_ranges: dict[object, AsianRange] | None = None,
) -> list[BreakoutSignal]:
    """Fade London extension into NY open when move exceeds ADR threshold."""
    if ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    ny_start = _parse_hhmm(sessions.new_york.start)
    signals: list[BreakoutSignal] = []

    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()

    for utc_date, day_df in df.groupby("utc_date"):
        asian = ranges.get(utc_date)
        if asian is None:
            continue
        adr = _adr_on_date(ohlc, utc_date, cfg.adr_lookback_days)
        if adr is None:
            continue
        mid = (asian.high + asian.low) / 2.0
        london_bars = day_df.loc[
            (day_df.index.hour >= 7) & (day_df.index.hour < ny_start.hour)
        ]
        if london_bars.empty:
            continue
        london_close = float(london_bars.iloc[-1]["close"])
        move = london_close - mid
        if abs(move) < cfg.ny_fade_london_adr_pct * adr:
            continue
        ny_bars = day_df.loc[day_df.index.hour == ny_start.hour]
        if ny_bars.empty:
            continue
        ts = ny_bars.index[0]
        entry = float(ny_bars.iloc[0]["close"])
        day_high = float(day_df.loc[day_df.index <= ts]["high"].max())
        day_low = float(day_df.loc[day_df.index <= ts]["low"].min())

        if move > 0:
            direction = "short"
            stop = day_high
            risk = stop - entry
            if risk <= 0:
                continue
            target = entry - cfg.min_reward_risk * risk
        else:
            direction = "long"
            stop = day_low
            risk = entry - stop
            if risk <= 0:
                continue
            target = entry + cfg.min_reward_risk * risk

        signals.append(
            BreakoutSignal(
                date=utc_date,
                direction=direction,
                entry_bar_ts=ts,
                entry_price=entry,
                stop_price=stop,
                target_price=target,
                asian_high=asian.high,
                asian_low=asian.low,
            )
        )
    return signals


def detect_event_aftermath(
    ohlc: pd.DataFrame,
    cfg: ScmConfig,
    sessions: SessionsConfig,
    *,
    event_times_ms: list[int],
    asian_ranges: dict[object, AsianRange] | None = None,
) -> list[BreakoutSignal]:
    """Post-event consolidation break (2h wait + 2h box)."""
    if ohlc.empty or not event_times_ms:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []

    for event_ms in event_times_ms:
        event_ts = pd.Timestamp(event_ms, unit="ms", tz="UTC")
        utc_date = event_ts.normalize()
        box_start = event_ts + pd.Timedelta(hours=cfg.event_wait_hours)
        box_end = box_start + pd.Timedelta(hours=cfg.event_box_hours)
        day_df = ohlc.loc[
            (ohlc.index.normalize() == utc_date) & (ohlc.index >= box_start) & (ohlc.index < box_end)
        ]
        if len(day_df) < 2:
            continue
        box_high = float(day_df["high"].max())
        box_low = float(day_df["low"].min())
        if box_high <= box_low:
            continue
        after = ohlc.loc[ohlc.index >= box_end]
        after = after.loc[after.index.normalize() == utc_date]
        if after.empty:
            continue
        asian = ranges.get(utc_date)
        asian_high = asian.high if asian else box_high
        asian_low = asian.low if asian else box_low

        for ts, row in after.iterrows():
            close = float(row["close"])
            if close > box_high:
                risk = close - box_low
                if risk <= 0:
                    break
                signals.append(
                    BreakoutSignal(
                        date=utc_date,
                        direction="long",
                        entry_bar_ts=ts,
                        entry_price=close,
                        stop_price=box_low,
                        target_price=close + cfg.min_reward_risk * risk,
                        asian_high=asian_high,
                        asian_low=asian_low,
                    )
                )
                break
            if close < box_low:
                risk = box_high - close
                if risk <= 0:
                    break
                signals.append(
                    BreakoutSignal(
                        date=utc_date,
                        direction="short",
                        entry_bar_ts=ts,
                        entry_price=close,
                        stop_price=box_high,
                        target_price=close - cfg.min_reward_risk * risk,
                        asian_high=asian_high,
                        asian_low=asian_low,
                    )
                )
                break
    return signals


def detect_scm_signals(
    ohlc: pd.DataFrame,
    cfg: ScmConfig,
    sessions: SessionsConfig,
    *,
    asian_ranges: dict[object, AsianRange] | None = None,
    event_times_ms: list[int] | None = None,
) -> list[BreakoutSignal]:
    if cfg.setup == "london_continuation":
        return detect_london_continuation(ohlc, cfg, sessions, asian_ranges=asian_ranges)
    if cfg.setup == "ny_fade":
        return detect_ny_fade(ohlc, cfg, sessions, asian_ranges=asian_ranges)
    if cfg.setup == "event_aftermath":
        return detect_event_aftermath(
            ohlc,
            cfg,
            sessions,
            event_times_ms=event_times_ms or [],
            asian_ranges=asian_ranges,
        )
    return detect_london_breakout(ohlc, cfg, sessions, asian_ranges=asian_ranges)
