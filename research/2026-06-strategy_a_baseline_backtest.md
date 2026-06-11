# Strategy A Baseline Backtest — Jun 11, 2026

**Scope:** EMA(9/21) cross + RSI(14) < 70 long entries on 4h bars. No volume-anomaly tier (scanner history not backtestable). BTC, ETH, SOL on Binance USDT-perp panel (`data/research.sqlite`, 2021–2026).

**Command:**
```bash
uv run aegis-backtest-swing --db data/research.sqlite --venue binance --symbols BTC ETH SOL --timeframe 4h
```

## Results

| Metric | Value |
|--------|-------|
| Trades | 589 |
| Win rate | 28.7% |
| Expectancy | **-0.213R** (90% CI [-0.314, -0.112]) |
| Max drawdown | 66.38% |
| Kill switch (p99 × 1.25) | 77.8% |

## Interpretation

The **technical baseline alone is not tradeable** — negative expectancy and deep drawdown. This is expected: Concept §7 positions Strategy A as anomaly-confirmed swing trades, not raw EMA/RSI.

**Next steps (not blockers for Phase 2 infra):**
1. Paper pipeline: join live `scanner_flags` to filter entries (Passive/Mid/Aggressive tiers).
2. Re-run backtest once enough scanner history exists locally (M1 gate).
3. Compare paper expectancy vs this baseline to quantify anomaly edge.

**M3 note:** This run does not satisfy M3 (Strategy B cointegration already failed). Strategy A promotion uses Concept §7 three-gate check at M8, not the pairs-trading M3 criteria.
