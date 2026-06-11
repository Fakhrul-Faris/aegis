"""Strategy A backtest CLI.

Usage:
    aegis-backtest-swing --db data/research.sqlite --venue binance --symbols BTC ETH
    aegis-backtest-swing --db data/aegis.sqlite --venue kraken --timeframe 4h

Anomaly flags are NOT in historical archives — this measures EMA+RSI baseline
only. Live paper joins scanner flags separately.
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from aegis.backtest.montecarlo import simulate_drawdown_envelope
from aegis.backtest.run import load_close_panel
from aegis.backtest.swing_engine import run_swing_backtest
from aegis.config import load_config
from aegis.log import setup_logging

logger = logging.getLogger(__name__)


def _resample_ohlc(panel: pd.DataFrame, rule: str) -> pd.DataFrame:
    if panel.index.name != "open_time_ms":
        panel = panel.copy()
    return panel.resample(rule, label="right", closed="right").last().dropna(how="all")


def print_report(result, envelope) -> None:
    lo, hi = result.expectancy_ci90()
    print("=" * 64)
    print("STRATEGY A SWING BACKTEST (EMA+RSI baseline, no anomaly history)")
    print("=" * 64)
    print(f"trades:            {len(result.trades)}")
    print(f"win rate:          {result.win_rate:.1%}")
    print(f"expectancy:        {result.expectancy_r:+.3f}R  90% CI [{lo:+.3f}, {hi:+.3f}]")
    print(f"max drawdown:      {result.max_drawdown_pct:.2%}")
    print(
        f"skips:             min-notional {result.skipped_below_min_notional}, "
        f"risk-budget {result.skipped_risk_budget}"
    )
    if envelope is not None:
        print("-" * 64)
        print(f"KILL SWITCH (p99 x 1.25):  {envelope.kill_switch_dd_pct:.1%}")
    print("=" * 64)


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy A swing backtest")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--db", required=True)
    parser.add_argument("--venue", default="binance")
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--equity", type=float, default=1000.0)
    parser.add_argument("--risk-pct", type=float, default=0.0075)
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)

    timeframe = args.timeframe or cfg.strategy_a.signal_timeframe
    panel = load_close_panel(
        args.db, args.venue, "1h" if timeframe == "4h" else timeframe, args.symbols, args.top
    )
    panel.index = pd.to_datetime(panel.index, unit="ms", utc=True)
    if timeframe == "4h":
        panel = _resample_ohlc(panel, "4h")

    logger.info(
        "swing panel loaded",
        extra={"symbols": panel.shape[1], "bars": panel.shape[0], "timeframe": timeframe},
    )

    result = run_swing_backtest(
        panel,
        cfg.strategy_a,
        cfg.risk,
        cfg.kraken_fees,
        initial_equity=args.equity,
        tier_risk_pct=args.risk_pct,
    )

    envelope = None
    if len(result.trades) >= 30:
        envelope = simulate_drawdown_envelope(result.r_multiples, risk_pct=args.risk_pct)
    print_report(result, envelope)


if __name__ == "__main__":
    main()
