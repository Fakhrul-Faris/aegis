# Forex SCM FX1 Baseline — Asian → London Breakout

*June 2026 · Spine-only backtest (no ADR/DXY/calendar confirms)*

## Setup

| Parameter | Value |
| --------- | ----- |
| Pair | EURUSD |
| Data | Yahoo 1h · `data/forex_research.sqlite` · ~Aug 2023 – Jun 2026 |
| Session | Asian 00:00–07:00 UTC · London entry 07:00 + 90m |
| Entry | First **close** outside Asian range in London window |
| Stop | Opposite side of Asian range |
| Target | 1.5R (min_reward_risk from `config/forex.yaml`) |
| Costs | Fusion RAW · 0.01 lot · spread + commission + slippage |
| Equity / risk | $100 start · 0.75% per trade |

## OOS windows (auto-split on available hourly span)

| Window | Period | Trades | Win rate | Expectancy | 90% CI (R) | FX1 pass? |
| ------ | ------ | ------ | -------- | ---------- | ---------- | --------- |
| W1-oldest | 2023-08-28 → 2024-08-02 | 139 | 46.0% | -0.076R | [-0.220, +0.068] | FAIL |
| W2-mid | 2024-08-02 → 2025-07-08 | 122 | 41.8% | -0.034R | [-0.173, +0.105] | FAIL |
| W3-newest | 2025-07-08 → 2026-06-12 | 115 | 47.8% | -0.093R | [-0.246, +0.059] | FAIL |

**Summary:** 0/3 windows passed FX1 gates (need ≥2).

## Verdict

**Asian range → London breakout (close trigger) is not tradeable on EUR/USD at FX1 spine.**
Win rate ~42–48% with negative expectancy — comparable to Strategy A EMA baseline before anomaly confirms.

## Next fork (per milestone)

1. **FX2 first:** Add ADR compression filter + DXY confirm + calendar watch-only on same setup — confirms may lift win rate.
2. **Pivot setup:** London **continuation** only (skip compression breakouts) — one allowed pivot before parking lot.
3. **Data:** Import HistData 1h for 2015–2022 windows to test if edge is era-specific (optional).

## Reproduce

```bash
aegis-backtest-forex-scm
aegis-backtest-forex-scm --window 2024-01-01 2024-12-31
```
