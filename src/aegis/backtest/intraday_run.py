"""CLI for Strategy C intraday backtest (ID1).

Usage:
    aegis-backtest-intraday --db data/intraday_research.sqlite --symbols BTC ETH SOL
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from aegis.backtest.intraday_engine import merge_backtest_results, run_intraday_backtest
from aegis.config import load_config
from aegis.config_intraday import load_intraday_config
from aegis.core.models import Venue
from aegis.data import db
from aegis.log import setup_logging


def _load_ohlc(conn, symbol: str, timeframe: str) -> pd.DataFrame:
    rows = db.load_candles(conn, Venue.HYPERLIQUID, symbol, timeframe)
    if not rows:
        return pd.DataFrame()
    data = {
        "open": [r.open for r in rows],
        "high": [r.high for r in rows],
        "low": [r.low for r in rows],
        "close": [r.close for r in rows],
        "volume": [r.volume for r in rows],
    }
    idx = pd.to_datetime([r.open_time for r in rows], utc=True)
    return pd.DataFrame(data, index=idx)


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy C intraday backtest (H-C1)")
    parser.add_argument("--db", default="data/intraday_research.sqlite")
    parser.add_argument("--intraday-config", default="config/intraday.yaml")
    parser.add_argument("--symbols", nargs="+", default=None)
    args = parser.parse_args()

    icfg = load_intraday_config(args.intraday_config)
    acfg = load_config()
    setup_logging(acfg.monitoring.log_dir, acfg.monitoring.log_level)
    logger = logging.getLogger(__name__)

    symbols = tuple(args.symbols) if args.symbols else icfg.momentum_day.symbols
    conn = db.connect(args.db)
    try:
        results = []
        for symbol in symbols:
            signal_df = _load_ohlc(conn, symbol, icfg.momentum_day.signal_timeframe)
            regime_df = _load_ohlc(conn, symbol, icfg.momentum_day.regime_timeframe)
            if signal_df.empty:
                logger.warning("no signal data", extra={"symbol": symbol})
                continue
            r = run_intraday_backtest(
                symbol,
                signal_df,
                regime_df,
                icfg.momentum_day,
                icfg.costs,
                icfg.research,
                acfg.regime,
                starting_equity=icfg.demo.equity_usd,
            )
            results.append(r)
            logger.info(
                "symbol backtest",
                extra={
                    "symbol": symbol,
                    "trades": len(r.trades),
                    "expectancy_r": round(r.expectancy_r, 3),
                    "win_rate": round(r.win_rate, 3),
                },
            )
    finally:
        conn.close()

    merged = merge_backtest_results(results)
    ci = merged.expectancy_ci90()
    print("STRATEGY C INTRADAY BACKTEST (H-C1: scanner proxy + 15m breakout)")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Trades: {len(merged.trades)}")
    print(f"Win rate: {merged.win_rate:.1%}")
    print(f"Expectancy: {merged.expectancy_r:+.3f}R")
    print(f"90% CI: [{ci[0]:+.3f}, {ci[1]:+.3f}]")
    print(f"Skipped (min notional): {merged.skipped_below_min}")
    gate = len(merged.trades) >= icfg.research.backtest_min_trades and ci[0] > 0
    print(f"ID1 gate (trades + CI>0): {'PASS' if gate else 'FAIL'}")


if __name__ == "__main__":
    main()
