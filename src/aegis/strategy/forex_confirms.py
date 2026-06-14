"""FX2 confirmation layer — ADR, DXY, calendar (SCM).

Filters raw London breakout signals before entry. Score-based gate:
  setup (1) + ADR compression + ADR room + DXY align + clear calendar.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import pandas as pd

from aegis.config_forex import CalendarConfig, ForexConfig, ScmConfig
from aegis.strategy.forex_session import AsianRange, BreakoutSignal


@dataclass
class ConfirmContext:
    adr: pd.Series  # index=utc_date normalized, value=avg daily range
    daily_range: pd.Series
    dxy_4h: pd.DataFrame  # close, ema9
    event_times_ms: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ConfirmBreakdown:
    score: int
    setup: bool
    adr_compression: bool
    adr_room: bool
    dxy_align: bool
    clear_calendar: bool
    near_event: bool


def daily_ranges_from_1h(ohlc_1h: pd.DataFrame) -> pd.Series:
    if ohlc_1h.empty:
        return pd.Series(dtype=float)
    daily = ohlc_1h.resample("1D").agg({"high": "max", "low": "min"})
    daily = daily.dropna(how="all")
    return daily["high"] - daily["low"]


def build_adr_series(daily_range: pd.Series, lookback_days: int) -> pd.Series:
    if daily_range.empty:
        return daily_range
    rolling = daily_range.rolling(lookback_days, min_periods=max(5, lookback_days // 2)).mean()
    # Use prior days only — no same-day lookahead in live/backtest gates.
    return rolling.shift(1)


def build_dxy_4h_panel(dxy_1h: pd.DataFrame, ema_period: int = 9) -> pd.DataFrame:
    if dxy_1h.empty:
        return pd.DataFrame(columns=["close", "ema9"])
    close = dxy_1h["close"].resample("4h", label="right", closed="right").last().dropna()
    out = pd.DataFrame({"close": close})
    out["ema9"] = out["close"].ewm(span=ema_period, adjust=False).mean()
    return out


def load_calendar_event_times(
    db_path: str,
    calendar: CalendarConfig,
    *,
    currencies: tuple[str, ...] = ("USD", "EUR"),
) -> list[int]:
    return [e.ts_ms for e in load_calendar_events(db_path, calendar, currencies=currencies)]


@dataclass(frozen=True)
class CalendarEventRow:
    ts_ms: int
    event_code: str
    currency: str
    impact_tier: int


def load_calendar_events(
    db_path: str,
    calendar: CalendarConfig,
    *,
    currencies: tuple[str, ...] = ("USD", "EUR"),
    tiers: tuple[int, ...] | None = None,
    event_codes: tuple[str, ...] | None = None,
) -> list[CalendarEventRow]:
    tier_list = tiers if tiers is not None else calendar.high_impact_tiers
    tiers_sql = ",".join(str(t) for t in tier_list)
    placeholders = ",".join("?" for _ in currencies)
    conn = sqlite3.connect(db_path)
    try:
        sql = f"""
            SELECT ts_ms, event_code, currency, impact_tier FROM economic_calendar
            WHERE impact_tier IN ({tiers_sql})
              AND currency IN ({placeholders})
        """
        params: list = list(currencies)
        if event_codes:
            codes_sql = ",".join("?" for _ in event_codes)
            sql += f" AND event_code IN ({codes_sql})"
            params.extend(event_codes)
        sql += " ORDER BY ts_ms ASC"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [
        CalendarEventRow(int(r[0]), str(r[1]), str(r[2]), int(r[3])) for r in rows
    ]


def build_confirm_context(
    ohlc_1h: pd.DataFrame,
    dxy_1h: pd.DataFrame,
    cfg: ForexConfig,
    *,
    calendar_times_ms: list[int] | None = None,
) -> ConfirmContext:
    daily_range = daily_ranges_from_1h(ohlc_1h)
    adr = build_adr_series(daily_range, cfg.scm.adr_lookback_days)
    dxy_4h = build_dxy_4h_panel(dxy_1h)
    return ConfirmContext(
        adr=adr,
        daily_range=daily_range,
        dxy_4h=dxy_4h,
        event_times_ms=calendar_times_ms or [],
    )


def _adr_for_date(ctx: ConfirmContext, utc_date) -> float | None:
    key = pd.Timestamp(utc_date).normalize()
    if key not in ctx.adr.index:
        return None
    val = ctx.adr.loc[key]
    if pd.isna(val) or val <= 0:
        return None
    return float(val)


def _pre_london_move(day_df: pd.DataFrame, asian: AsianRange, london_open_ts: pd.Timestamp) -> float:
    """Absolute move from Asian midpoint to last close before London entry bar."""
    pre = day_df.loc[day_df.index < london_open_ts]
    if pre.empty:
        return 0.0
    ref = (asian.high + asian.low) / 2.0
    return abs(float(pre.iloc[-1]["close"]) - ref)


def _dxy_aligns(signal: BreakoutSignal, ctx: ConfirmContext) -> bool:
    if ctx.dxy_4h.empty:
        return False
    ts = signal.entry_bar_ts
    hist = ctx.dxy_4h.loc[ctx.dxy_4h.index <= ts]
    if hist.empty:
        return False
    row = hist.iloc[-1]
    close = float(row["close"])
    ema = float(row["ema9"])
    if signal.direction == "long":
        return close <= ema  # USD weakness supports EUR long
    return close >= ema


def _near_high_impact_event(entry_ts: pd.Timestamp, ctx: ConfirmContext, cal: CalendarConfig) -> bool:
    if not ctx.event_times_ms:
        return False
    entry_ms = int(entry_ts.timestamp() * 1000)
    window_ms = max(cal.watch_minutes_before, cal.watch_minutes_after) * 60_000
    for event_ms in ctx.event_times_ms:
        if abs(entry_ms - event_ms) <= window_ms:
            return True
    return False


def score_signal(
    signal: BreakoutSignal,
    asian: AsianRange,
    day_df: pd.DataFrame,
    ctx: ConfirmContext,
    scm: ScmConfig,
    calendar: CalendarConfig,
) -> ConfirmBreakdown:
    setup = True
    adr_val = _adr_for_date(ctx, signal.date)
    asian_width = asian.high - asian.low

    adr_compression = False
    adr_room = False
    if adr_val is not None and adr_val > 0:
        adr_compression = asian_width <= scm.asian_range_max_adr_pct * adr_val
        pre_move = _pre_london_move(day_df, asian, signal.entry_bar_ts)
        adr_room = pre_move <= scm.pre_london_max_adr_pct * adr_val
    else:
        adr_compression = False
        adr_room = False

    dxy_align = _dxy_aligns(signal, ctx)
    near_event = _near_high_impact_event(signal.entry_bar_ts, ctx, calendar)
    clear_calendar = not near_event

    score = sum((setup, adr_compression, adr_room, dxy_align, clear_calendar))
    return ConfirmBreakdown(
        score=score,
        setup=setup,
        adr_compression=adr_compression,
        adr_room=adr_room,
        dxy_align=dxy_align,
        clear_calendar=clear_calendar,
        near_event=near_event,
    )


def signal_passes_confirms(
    breakdown: ConfirmBreakdown,
    scm: ScmConfig,
    calendar: CalendarConfig,
) -> bool:
    threshold = scm.confirm_score_threshold
    if breakdown.near_event:
        threshold += 1
    return breakdown.score >= threshold


def filter_signals_with_confirms(
    signals: list[BreakoutSignal],
    ohlc_1h: pd.DataFrame,
    asian_ranges: dict,
    ctx: ConfirmContext,
    cfg: ForexConfig,
) -> tuple[list[BreakoutSignal], dict[str, int]]:
    """Return confirmed signals and skip reason counts."""
    skips = {
        "score": 0,
        "adr_compression": 0,
        "adr_room": 0,
        "dxy": 0,
        "calendar": 0,
    }
    out: list[BreakoutSignal] = []
    df = ohlc_1h.copy()
    df["utc_date"] = df.index.normalize()

    for signal in signals:
        asian = asian_ranges.get(signal.date)
        if asian is None:
            continue
        day_df = df.loc[df["utc_date"] == signal.date]
        bd = score_signal(signal, asian, day_df, ctx, cfg.scm, cfg.calendar)
        if not signal_passes_confirms(bd, cfg.scm, cfg.calendar):
            skips["score"] += 1
            if not bd.adr_compression:
                skips["adr_compression"] += 1
            if not bd.adr_room:
                skips["adr_room"] += 1
            if not bd.dxy_align:
                skips["dxy"] += 1
            if not bd.clear_calendar:
                skips["calendar"] += 1
            continue
        out.append(signal)
    return out, skips
