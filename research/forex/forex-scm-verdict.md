# Forex SCM / Event Fade — Go/No-Go for Demo Paper

*June 2026 · FX3 gate*

## Verdict: **GO (event spike fade only)**

SCM v1 (session momentum) is **parked**. The demo path uses **Event Spike Fade H11b-4** only.

## Frozen recipe (H11c-3)

- **Strategy:** `event_spike_fade` — **EURUSD + GBPUSD** portfolio
- **Config hash:** `6eaf09bf78b0d905`
- **Frequency:** ~6.8 trades/month (~1.6/week)
- **Logic:** unchanged H11b-4 params; events mapped per pair (USD/EUR → EURUSD, USD/GBP → GBPUSD)

## FX3 replication (3/3 PASS — H11c-3)

| Window | Trades | WR | Expectancy | Gate |
| ------ | ------ | -- | ---------- | ---- |
| W1 | 350 (158+192) | 61.4% | +0.144R | ✓ |
| W2 | 486 (222+264) | 60.9% | +0.097R | ✓ |
| W3 | 469 (209+260) | 62.9% | +0.107R | ✓ |

**3/3 windows pass** — upgraded from 2/3 EURUSD-only.

## What failed (do not demo)

| Track | Result |
| ----- | ------ |
| SCM breakout / continuation | FAIL (0/16, 0/27 hypotheses) |
| LER mean-reversion family | FAIL (~11% WR) |
| 15m H11b variants | FAIL (WR ok, CI negative) |

## Demo expectations

- **Frequency:** ~4 trades/month (~50/year)
- **Demo WR gate:** ≥55% (FX6), backtest reference 62% avg
- **Risk:** 0.75% per trade, 0.01 lot research default

## Next steps

1. **FX4** — cTrader/OANDA demo adapter, calendar alerts, event-day watchlist
2. **FX5** — start demo paper with frozen hash; no parameter changes without `--reset-freeze`
3. **FX6** — 8+ weeks, ≥80 trades may take ~20 months at this frequency — consider lowering demo trade gate for event-only strategy

## Reproduce

```bash
aegis-backtest-forex-fx3
aegis-forex-h11b-sweep   # full H11b variant matrix
```
