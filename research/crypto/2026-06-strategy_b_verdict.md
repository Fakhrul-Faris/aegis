# Strategy B Cointegration Research Verdict

*June 2026 · P1.6 go/no-go memo · Companion to `data/backtest_report.txt`*

## Question

Does Engle-Granger pairs trading with FDR correction, stability windows, OU
half-life bounds, and out-of-sample stationarity produce ≥300 walk-forward
trades with positive net expectancy on liquid crypto perps (2021–2026)?

## Data

| Panel | Symbols | Hourly bars | Source |
|-------|---------|-------------|--------|
| Majors | 30 | 1.28M | Binance USDT-perp archives |
| Widened | 116 | 4.26M | + sector alts (DeFi, L2, memes, gaming, AI) |

Hyperliquid live ingestion holds ~208 days — insufficient for the 180d
selection + 30d OOS window; research uses Binance archives (`aegis-download`).

## Results

### 30-major walk-forward (production config)

- **253 weekly refits**, **0 trades**
- Funnel: up to 54/435 pairs pass FDR in-sample; **0** pass stability + OOS
- Sensitivity: log prices, 60/90/180d windows, alphas 0.05–0.15, 2-of-3
  stability relaxations — conclusion unchanged

### 116-symbol funnel diagnostic (end of sample)

| Stage | Count |
|-------|-------|
| Pairs tested | 6,490 |
| Post-FDR | 784 |
| Stability | 22 |
| Half-life | 18 |
| **OOS survivors** | **1** (`1INCH/BB`) |

Earlier eras (bar 20k, 35k): **0** survivors.

## Verdict: NO-GO for cointegration Strategy B

Persistent tradeable cointegration in the 4–72h half-life band does **not**
exist at scale among liquid crypto majors or sector alts, 2021–2026. In-sample
relationships are episodic and fail out-of-sample — exactly the failure mode
the hardened pipeline was designed to reject.

**The screen worked.** Loosening gates to force trades would manufacture edge
from noise.

## M3 gate status

| Criterion | Result |
|-----------|--------|
| ≥300 walk-forward trades | **FAIL** (0) |
| Expectancy 90% CI > 0 net of costs | **N/A** |
| Max DD inside MC envelope | **N/A** |
| No pair >30% of profit | **N/A** |

Kill-switch calibration (`risk.kill_switch_drawdown_pct`) remains **unset**
until a strategy produces ≥30 backtest trades for Monte Carlo resampling.

## Recommended next steps

1. **Strategy A promotion research** — EMA/RSI swing on Kraken 4h (backtestable);
   volume-anomaly confirmation remains paper-only via the live scanner log.
2. **Optional Strategy B pivot** — cross-sectional mean reversion (rank laggards
   vs leaders, market-neutral basket); requires new math engine, not gate relaxation.
3. **Phase 2** — risk engine + execution stack is strategy-agnostic; proceed
   with whichever signal engine passes its gate.

## Artifacts

- `aegis-backtest --db data/research.sqlite --venue binance` (30-symbol report)
- Funnel diagnostics: Jun 11 2026, terminal logs
- Code: `src/aegis/strategy/screening.py`, `src/aegis/backtest/engine.py`
