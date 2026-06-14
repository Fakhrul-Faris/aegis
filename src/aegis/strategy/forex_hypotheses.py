"""Forex research hypotheses H1–H26 — signal detectors (FX-A.6).

Each detector returns ``BreakoutSignal`` lists compatible with the SCM backtest
simulator. Mean-reversion family targets Asian mid or fixed R; momentum uses
standard range stops.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from aegis.config_forex import ScmConfig, SessionsConfig
from aegis.strategy.forex_session import (
    AsianRange,
    BreakoutSignal,
    _adr_on_date,
    _london_entry_bars,
    _parse_hhmm,
    compute_asian_ranges,
    detect_event_aftermath,
    detect_london_breakout,
    detect_london_continuation,
)

DetectorFn = Callable[
    [pd.DataFrame, SessionsConfig, "HypothesisParams", list[int] | None, dict | None],
    list[BreakoutSignal],
]


@dataclass
class HypothesisParams:
    reward_risk: float = 1.0
    stop_risk_mult: float = 1.0
    asian_max_adr_pct: float = 0.30
    london_spent_adr_pct: float = 0.60
    pre_london_max_adr_pct: float = 0.80
    target_mode: str = "asian_mid"  # asian_mid | fixed_rr | retrace
    entry_hours: tuple[int, ...] = (10, 11)
    london_entry_minutes: int = 90
    event_wait_hours: int = 2
    event_box_hours: int = 2
    spike_wait_minutes: int = 30
    spike_fade_minutes: int = 60
    spike_retrace_pct: float = 0.5
    min_spike_pips: float = 3.0
    box_start_hour: int = 10
    box_end_hour: int = 12
    fade_start_hour: int = 14
    fade_end_hour: int = 16


def _signal(
    utc_date,
    direction: str,
    ts: pd.Timestamp,
    entry: float,
    stop: float,
    target: float,
    asian: AsianRange,
) -> BreakoutSignal:
    return BreakoutSignal(
        date=utc_date,
        direction=direction,
        entry_bar_ts=ts,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        asian_high=asian.high,
        asian_low=asian.low,
    )


def _target_from_mode(
    entry: float,
    stop: float,
    direction: str,
    mid: float,
    params: HypothesisParams,
) -> float:
    risk = abs(entry - stop)
    if risk <= 0:
        return entry
    if params.target_mode == "asian_mid":
        return mid
    if params.target_mode == "retrace":
        if direction == "long":
            return entry + params.reward_risk * risk
        return entry - params.reward_risk * risk
    # fixed_rr
    if direction == "long":
        return entry + params.reward_risk * risk
    return entry - params.reward_risk * risk


def _compressed_asian(asian: AsianRange, adr: float, max_pct: float) -> bool:
    return (asian.high - asian.low) <= max_pct * adr


def detect_ler(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H1/H2/H17 — London exhaustion fade toward Asian mid."""
    if ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    ny_hour = _parse_hhmm(sessions.new_york.start).hour
    signals: list[BreakoutSignal] = []
    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()

    for utc_date, day_df in df.groupby("utc_date"):
        asian = ranges.get(utc_date)
        if asian is None:
            continue
        adr = _adr_on_date(ohlc, utc_date, 20)
        if adr is None or not _compressed_asian(asian, adr, params.asian_max_adr_pct):
            continue
        mid = (asian.high + asian.low) / 2.0
        pre_london = day_df.loc[day_df.index.hour < 7]
        if not pre_london.empty and params.pre_london_max_adr_pct < 0.8:
            pre_move = abs(float(pre_london.iloc[-1]["close"]) - mid)
            if pre_move > params.pre_london_max_adr_pct * adr:
                continue
        london = day_df.loc[(day_df.index.hour >= 7) & (day_df.index.hour < ny_hour)]
        if london.empty:
            continue

        for hour in params.entry_hours:
            bars = day_df.loc[day_df.index.hour == hour]
            if bars.empty:
                continue
            ts = bars.index[0]
            entry = float(bars.iloc[0]["close"])
            move = entry - mid
            if abs(move) < params.london_spent_adr_pct * adr:
                continue
            london_so_far = day_df.loc[(day_df.index.hour >= 7) & (day_df.index <= ts)]
            if london_so_far.empty:
                continue
            if move > 0:
                direction = "short"
                stop = float(london_so_far["high"].max())
            else:
                direction = "long"
                stop = float(london_so_far["low"].min())
            target = _target_from_mode(entry, stop, direction, mid, params)
            signals.append(_signal(utc_date, direction, ts, entry, stop, target, asian))
            break
    return signals


def detect_london_close_fade(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H3 — Fade London morning extension into afternoon."""
    if ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []
    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()

    for utc_date, day_df in df.groupby("utc_date"):
        asian = ranges.get(utc_date)
        if asian is None:
            continue
        adr = _adr_on_date(ohlc, utc_date, 20)
        if adr is None:
            continue
        mid = (asian.high + asian.low) / 2.0
        morning = day_df.loc[(day_df.index.hour >= 7) & (day_df.index.hour < params.fade_start_hour)]
        if morning.empty:
            continue
        morning_close = float(morning.iloc[-1]["close"])
        move = morning_close - mid
        if abs(move) < params.london_spent_adr_pct * adr:
            continue

        fade_bars = day_df.loc[
            (day_df.index.hour >= params.fade_start_hour)
            & (day_df.index.hour <= params.fade_end_hour)
        ]
        if fade_bars.empty:
            continue
        ts = fade_bars.index[0]
        entry = float(fade_bars.iloc[0]["close"])
        day_so_far = day_df.loc[day_df.index <= ts]
        if move > 0:
            direction = "short"
            stop = float(day_so_far["high"].max())
        else:
            direction = "long"
            stop = float(day_so_far["low"].min())
        target = _target_from_mode(entry, stop, direction, mid, params)
        signals.append(_signal(utc_date, direction, ts, entry, stop, target, asian))
    return signals


def detect_asian_box_fade(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H4 — Fade first touch of Asian boundary in London open hour."""
    if ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []
    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()
    london_start = _parse_hhmm(sessions.london.start).hour

    for utc_date, day_df in df.groupby("utc_date"):
        asian = ranges.get(utc_date)
        if asian is None:
            continue
        adr = _adr_on_date(ohlc, utc_date, 20)
        if adr is None or not _compressed_asian(asian, adr, params.asian_max_adr_pct):
            continue
        mid = (asian.high + asian.low) / 2.0
        window = day_df.loc[
            (day_df.index.hour >= london_start)
            & (day_df.index.hour < london_start + 2)
        ]
        for ts, row in window.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
            if high >= asian.high and close < asian.high:
                direction = "short"
                stop = high
                entry = close
                target = _target_from_mode(entry, stop, direction, mid, params)
                signals.append(_signal(utc_date, direction, ts, entry, stop, target, asian))
                break
            if low <= asian.low and close > asian.low:
                direction = "long"
                stop = low
                entry = close
                target = _target_from_mode(entry, stop, direction, mid, params)
                signals.append(_signal(utc_date, direction, ts, entry, stop, target, asian))
                break
    return signals


def detect_double_exhaustion(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H5 — Asian + London both extended same direction → fade."""
    if ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []
    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()
    ny_hour = _parse_hhmm(sessions.new_york.start).hour

    for utc_date, day_df in df.groupby("utc_date"):
        asian = ranges.get(utc_date)
        if asian is None:
            continue
        adr = _adr_on_date(ohlc, utc_date, 20)
        if adr is None:
            continue
        mid = (asian.high + asian.low) / 2.0
        pre_london = day_df.loc[day_df.index.hour < 7]
        if pre_london.empty:
            continue
        pre_close = float(pre_london.iloc[-1]["close"])
        pre_move = pre_close - mid
        if abs(pre_move) < 0.30 * adr:
            continue

        bars = day_df.loc[day_df.index.hour == params.entry_hours[0]]
        if bars.empty:
            continue
        ts = bars.index[0]
        entry = float(bars.iloc[0]["close"])
        london_move = entry - mid
        if abs(london_move) < params.london_spent_adr_pct * adr:
            continue
        if (pre_move > 0) != (london_move > 0):
            continue

        london_so_far = day_df.loc[(day_df.index.hour >= 7) & (day_df.index <= ts)]
        if london_move > 0:
            direction = "short"
            stop = float(london_so_far["high"].max())
        else:
            direction = "long"
            stop = float(london_so_far["low"].min())
        target = _target_from_mode(entry, stop, direction, mid, params)
        signals.append(_signal(utc_date, direction, ts, entry, stop, target, asian))
    return signals


def detect_m15_breakout(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H6 — 15m London first-hour breakout."""
    cfg = ScmConfig(
        setup="london_breakout",
        adr_lookback_days=20,
        asian_range_max_adr_pct=params.asian_max_adr_pct,
        pre_london_max_adr_pct=params.pre_london_max_adr_pct,
        london_entry_window_minutes=params.london_entry_minutes,
        ny_fade_london_adr_pct=0.5,
        event_wait_hours=2,
        event_box_hours=2,
        min_reward_risk=params.reward_risk,
        confirm_score_threshold=3,
        min_confirm_checks=2,
        backtest_min_trades_per_window=80,
        backtest_min_win_rate=0.6,
        demo_min_win_rate=0.55,
    )
    return detect_london_breakout(ohlc, cfg, sessions, asian_ranges=asian_ranges)


def detect_m15_continuation(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H7 — 15m first London bar continuation."""
    cfg = ScmConfig(
        setup="london_continuation",
        adr_lookback_days=20,
        asian_range_max_adr_pct=params.asian_max_adr_pct,
        pre_london_max_adr_pct=params.pre_london_max_adr_pct,
        london_entry_window_minutes=15,
        ny_fade_london_adr_pct=0.5,
        event_wait_hours=2,
        event_box_hours=2,
        min_reward_risk=params.reward_risk,
        confirm_score_threshold=3,
        min_confirm_checks=2,
        backtest_min_trades_per_window=80,
        backtest_min_win_rate=0.6,
        demo_min_win_rate=0.55,
    )
    return detect_london_continuation(ohlc, cfg, sessions, asian_ranges=asian_ranges)


def detect_m15_ler(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H8 — 15m LER at 10–11 UTC."""
    return detect_ler(ohlc, sessions, params, event_times_ms, asian_ranges)


def detect_post_london_box(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H9 — 10–12 UTC box break after noon."""
    if ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []
    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()

    for utc_date, day_df in df.groupby("utc_date"):
        asian = ranges.get(utc_date)
        if asian is None:
            continue
        box = day_df.loc[
            (day_df.index.hour >= params.box_start_hour)
            & (day_df.index.hour < params.box_end_hour)
        ]
        if len(box) < 2:
            continue
        box_high = float(box["high"].max())
        box_low = float(box["low"].min())
        if box_high <= box_low:
            continue
        after = day_df.loc[day_df.index.hour >= params.box_end_hour]
        for ts, row in after.iterrows():
            close = float(row["close"])
            if close > box_high:
                risk = close - box_low
                if risk <= 0:
                    break
                target = close + params.reward_risk * risk
                signals.append(
                    _signal(utc_date, "long", ts, close, box_low, target, asian)
                )
                break
            if close < box_low:
                risk = box_high - close
                if risk <= 0:
                    break
                target = close - params.reward_risk * risk
                signals.append(
                    _signal(utc_date, "short", ts, close, box_high, target, asian)
                )
                break
    return signals


def detect_event_box_rr(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H10 — Event aftermath with custom R profile."""
    if ohlc.empty or not event_times_ms:
        return []
    cfg = ScmConfig(
        setup="event_aftermath",
        adr_lookback_days=20,
        asian_range_max_adr_pct=0.4,
        pre_london_max_adr_pct=0.8,
        london_entry_window_minutes=90,
        ny_fade_london_adr_pct=0.5,
        event_wait_hours=params.event_wait_hours,
        event_box_hours=params.event_box_hours,
        min_reward_risk=params.reward_risk,
        confirm_score_threshold=3,
        min_confirm_checks=2,
        backtest_min_trades_per_window=80,
        backtest_min_win_rate=0.6,
        demo_min_win_rate=0.55,
    )
    raw = detect_event_aftermath(
        ohlc, cfg, sessions, event_times_ms=event_times_ms, asian_ranges=asian_ranges
    )
    if params.stop_risk_mult >= 1.0:
        return raw
    out: list[BreakoutSignal] = []
    for sig in raw:
        risk = abs(sig.entry_price - sig.stop_price)
        tight = params.stop_risk_mult * risk
        if sig.direction == "long":
            stop = sig.entry_price - tight
            target = sig.entry_price + params.reward_risk * tight
        else:
            stop = sig.entry_price + tight
            target = sig.entry_price - params.reward_risk * tight
        out.append(
            _signal(
                sig.date,
                sig.direction,
                sig.entry_bar_ts,
                sig.entry_price,
                stop,
                target,
                AsianRange(sig.date, sig.asian_high, sig.asian_low, 0),
            )
        )
    return out


def detect_event_spike_fade(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H11 — Fade initial post-event spike."""
    if ohlc.empty or not event_times_ms:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []

    for event_ms in event_times_ms:
        event_ts = pd.Timestamp(event_ms, unit="ms", tz="UTC")
        utc_date = event_ts.normalize()
        asian = ranges.get(utc_date)
        if asian is None:
            asian = AsianRange(utc_date, 0.0, 0.0, 0)
        fade_ts = event_ts + pd.Timedelta(minutes=params.spike_fade_minutes)
        spike_end = event_ts + pd.Timedelta(minutes=params.spike_wait_minutes)
        spike = ohlc.loc[(ohlc.index >= event_ts) & (ohlc.index < spike_end)]
        fade_bars = ohlc.loc[ohlc.index >= fade_ts]
        fade_bars = fade_bars.loc[fade_bars.index.normalize() == utc_date]
        if spike.empty or fade_bars.empty:
            continue
        spike_move = float(spike.iloc[-1]["close"]) - float(spike.iloc[0]["open"])
        if abs(spike_move) <= 0:
            continue
        ts = fade_bars.index[0]
        entry = float(fade_bars.iloc[0]["close"])
        if spike_move > 0:
            direction = "short"
            stop = float(spike["high"].max())
        else:
            direction = "long"
            stop = float(spike["low"].min())
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        if direction == "long":
            target = entry + params.reward_risk * risk
        else:
            target = entry - params.reward_risk * risk
        signals.append(_signal(utc_date, direction, ts, entry, stop, target, asian))
    return signals


def _snap_event_bar(ohlc: pd.DataFrame, event_ts: pd.Timestamp) -> pd.Timestamp | None:
    """First bar at or after event time within 30 minutes."""
    window = ohlc.loc[
        (ohlc.index >= event_ts) & (ohlc.index <= event_ts + pd.Timedelta(minutes=30))
    ]
    if window.empty:
        hist = ohlc.loc[ohlc.index <= event_ts]
        if hist.empty:
            return None
        return hist.index[-1]
    return window.index[0]


def detect_event_spike_fade_h11b(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
    *,
    events: list | None = None,
    pip_size: float = 0.0001,
) -> list[BreakoutSignal]:
    """H11b — 15m-capable spike fade with retrace target and event tagging."""
    from aegis.strategy.forex_confirms import CalendarEventRow

    if ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []

    event_rows: list[tuple[int, str | None]] = []
    if events:
        for e in events:
            if isinstance(e, CalendarEventRow):
                event_rows.append((e.ts_ms, e.event_code))
            else:
                event_rows.append((int(e), None))
    elif event_times_ms:
        event_rows = [(ms, None) for ms in event_times_ms]

    if not event_rows:
        return []

    min_spike = params.min_spike_pips * pip_size

    for event_ms, event_code in event_rows:
        event_ts = pd.Timestamp(event_ms, unit="ms", tz="UTC")
        utc_date = event_ts.normalize()
        asian = ranges.get(utc_date) or AsianRange(utc_date, 0.0, 0.0, 0)

        bar_ts = _snap_event_bar(ohlc, event_ts)
        if bar_ts is None:
            continue

        spike_end = bar_ts + pd.Timedelta(minutes=params.spike_wait_minutes)
        fade_ts = bar_ts + pd.Timedelta(minutes=params.spike_fade_minutes)
        spike = ohlc.loc[(ohlc.index >= bar_ts) & (ohlc.index < spike_end)]
        fade_bars = ohlc.loc[ohlc.index >= fade_ts]
        fade_bars = fade_bars.loc[fade_bars.index.normalize() == utc_date]
        if spike.empty or fade_bars.empty:
            continue

        spike_move = float(spike.iloc[-1]["close"]) - float(spike.iloc[0]["open"])
        if abs(spike_move) < min_spike:
            continue

        ts = fade_bars.index[0]
        entry = float(fade_bars.iloc[0]["close"])
        if spike_move > 0:
            direction = "short"
            stop = float(spike["high"].max())
            if params.target_mode == "retrace":
                target = entry - params.spike_retrace_pct * abs(spike_move)
            else:
                risk = stop - entry
                if risk <= 0:
                    continue
                target = entry - params.reward_risk * risk
        else:
            direction = "long"
            stop = float(spike["low"].min())
            if params.target_mode == "retrace":
                target = entry + params.spike_retrace_pct * abs(spike_move)
            else:
                risk = entry - stop
                if risk <= 0:
                    continue
                target = entry + params.reward_risk * risk

        risk = abs(entry - stop)
        if risk <= 0:
            continue
        if direction == "long" and target <= entry:
            continue
        if direction == "short" and target >= entry:
            continue

        sig = _signal(utc_date, direction, ts, entry, stop, target, asian)
        signals.append(
            BreakoutSignal(
                date=sig.date,
                direction=sig.direction,
                entry_bar_ts=sig.entry_bar_ts,
                entry_price=sig.entry_price,
                stop_price=sig.stop_price,
                target_price=sig.target_price,
                asian_high=sig.asian_high,
                asian_low=sig.asian_low,
                event_code=event_code,
            )
        )
    return signals


def detect_dxy_divergence(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
    *,
    dxy_ohlc: pd.DataFrame | None = None,
) -> list[BreakoutSignal]:
    """H14 — EUR up + DXY up → short (divergence fade)."""
    if ohlc.empty or dxy_ohlc is None or dxy_ohlc.empty:
        return []
    ranges = asian_ranges or compute_asian_ranges(ohlc, sessions)
    signals: list[BreakoutSignal] = []
    df = ohlc.copy()
    df["utc_date"] = df.index.normalize()
    london_start = _parse_hhmm(sessions.london.start).hour

    for utc_date, day_df in df.groupby("utc_date"):
        asian = ranges.get(utc_date)
        if asian is None:
            continue
        window = day_df.loc[day_df.index.hour == london_start]
        if window.empty:
            continue
        ts = window.index[0]
        row = window.iloc[0]
        eur_move = float(row["close"]) - float(row["open"])
        dxy_bar = dxy_ohlc.loc[dxy_ohlc.index <= ts]
        if len(dxy_bar) < 2:
            continue
        dxy_move = float(dxy_bar.iloc[-1]["close"]) - float(dxy_bar.iloc[-2]["close"])
        if eur_move <= 0 or dxy_move <= 0:
            continue
        entry = float(row["close"])
        stop = float(day_df.loc[day_df.index <= ts]["high"].max())
        risk = stop - entry
        if risk <= 0:
            continue
        target = entry - params.reward_risk * risk
        signals.append(_signal(utc_date, "short", ts, entry, stop, target, asian))
    return signals


def detect_usdjpy_tokyo_london(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    event_times_ms: list[int] | None = None,
    asian_ranges: dict | None = None,
) -> list[BreakoutSignal]:
    """H16 — USDJPY LER (Tokyo range ≈ Asian UTC)."""
    return detect_ler(ohlc, sessions, params, event_times_ms, asian_ranges)


DETECTORS: dict[str, DetectorFn] = {
    "ler": detect_ler,
    "ny_fade_v2": lambda o, s, p, e, a: detect_ler(
        o, s, HypothesisParams(**{**p.__dict__, "entry_hours": (12,)}), e, a
    ),
    "london_close_fade": detect_london_close_fade,
    "asian_box_fade": detect_asian_box_fade,
    "double_exhaustion": detect_double_exhaustion,
    "m15_breakout": detect_m15_breakout,
    "m15_continuation": detect_m15_continuation,
    "m15_ler": detect_m15_ler,
    "post_london_box": detect_post_london_box,
    "event_box_rr": detect_event_box_rr,
    "event_spike_fade": detect_event_spike_fade,
    "event_spike_fade_h11b": detect_event_spike_fade_h11b,
    "dxy_divergence": detect_dxy_divergence,
    "usdjpy_ler": detect_usdjpy_tokyo_london,
    "breakout_1r": lambda o, s, p, e, a: _h19_breakout(o, s, p, a),
    "continuation_1r": lambda o, s, p, e, a: _h19_continuation(o, s, p, a),
}


def ohlc_is_15m(ohlc: pd.DataFrame) -> bool:
    if len(ohlc) < 3:
        return False
    delta = ohlc.index[1] - ohlc.index[0]
    return delta <= pd.Timedelta(minutes=20)


def _h19_breakout(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    asian_ranges: dict | None,
) -> list[BreakoutSignal]:
    cfg = ScmConfig(
        setup="london_breakout",
        adr_lookback_days=20,
        asian_range_max_adr_pct=0.4,
        pre_london_max_adr_pct=0.8,
        london_entry_window_minutes=90,
        ny_fade_london_adr_pct=0.5,
        event_wait_hours=2,
        event_box_hours=2,
        min_reward_risk=1.0,
        confirm_score_threshold=3,
        min_confirm_checks=2,
        backtest_min_trades_per_window=80,
        backtest_min_win_rate=0.6,
        demo_min_win_rate=0.55,
    )
    return detect_london_breakout(ohlc, cfg, sessions, asian_ranges=asian_ranges)


def _h19_continuation(
    ohlc: pd.DataFrame,
    sessions: SessionsConfig,
    params: HypothesisParams,
    asian_ranges: dict | None,
) -> list[BreakoutSignal]:
    cfg = ScmConfig(
        setup="london_continuation",
        adr_lookback_days=20,
        asian_range_max_adr_pct=0.4,
        pre_london_max_adr_pct=0.8,
        london_entry_window_minutes=90,
        ny_fade_london_adr_pct=0.5,
        event_wait_hours=2,
        event_box_hours=2,
        min_reward_risk=1.0,
        confirm_score_threshold=3,
        min_confirm_checks=2,
        backtest_min_trades_per_window=80,
        backtest_min_win_rate=0.6,
        demo_min_win_rate=0.55,
    )
    return detect_london_continuation(ohlc, cfg, sessions, asian_ranges=asian_ranges)
