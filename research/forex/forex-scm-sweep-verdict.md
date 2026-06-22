# Forex SCM Research Sweep — Verdict

*June 14 2026 · All four FX2 follow-on forks executed*

## Deep history re-sweep (ForexSB, Jun 14)

**Data:** `data/forexsb/EURUSD_H1.csv` + `GBPUSD_H1.csv` — **~100k bars each**, 2010–2026 UTC (Dukascopy via [ForexSB](https://forexsb.com/historical-forex-data)).

**Gate:** **0/16 variants pass** (unchanged).

| Change vs Yahoo-only | Observation |
| -------------------- | ----------- |
| EUR continuation (was best at +0.028R) | **-0.683R**, 34.6% WR — edge was Yahoo-era noise |
| GBP breakout W1 | +3.614R but **23.9% WR** — fat-tail wins, fails WR gate |
| Trade counts | 600–3200 per variant (real sample size now) |

**Verdict unchanged:** SCM v1 dead for demo. Deep history disproved the Yahoo-window hope.

## Forks executed (Yahoo-only sweep, Jun 14)

| Fork | Action | Result |
| ---- | ------ | ------ |
| **HistData 2015–2022** | `try_download_histdata_range` + `import_histdata_directory` | **0 bars** — automated download blocked; no manual zips under `data/histdata/` |
| **GBP/USD** | Yahoo refresh + full sweep matrix | **Worse than EUR/USD** on every setup; best GBP variant -0.116R avg |
| **Tight filters** | 25% ADR cap + confirm score ≥4 | Marginal lift on EUR continuation (+0.028R vs +0.005R default) but **WR still ~47%** |
| **NY fade + event aftermath** | New setups in `forex_session.py` | **Negative expectancy** all windows; insufficient trades on tight NY fade |

CLI: `aegis-forex-research-sweep` → `research/forex/forex-scm-sweep-report.md`

## Gate result

**0/16 variants pass FX3 gate** (need ≥2/3 windows with ≥80 trades, ≥60% WR, expectancy 90% CI > 0).

## Best variant (still fails)

**EURUSD · london_continuation · tight (25% ADR, score ≥4)**

| Window | Trades | Win rate | Expectancy |
| ------ | ------ | -------- | ---------- |
| W1-oldest | 108 | 46.3% | -0.016R |
| W2-mid | 109 | 44.0% | +0.028R |
| W3-newest | 102 | 52.0% | +0.072R |

Avg: **47.4% WR, +0.028R** — positive mean but WR far below 60% gate and no window passes CI.

## Setup ranking (avg expectancy, EURUSD)

1. london_continuation tight — +0.028R
2. london_continuation default — +0.005R
3. london_breakout tight — -0.046R
4. event_aftermath default — -0.057R
5. london_breakout default — -0.060R
6. ny_fade default — -0.404R

## GBP/USD vs EUR/USD

GBP/USD underperforms on every comparable variant. Best GBP: london_breakout default at **-0.116R, 42.2% WR**. No evidence that session personality on cable rescues SCM v1.

## NY fade & event aftermath

- **NY fade:** Fades London extension into NY open when move > 50% ADR. EUR default 82 trades, 29.8% WR, -0.404R. Tight filters collapse to 13 trades.
- **Event aftermath:** 2h wait + 2h box break after calendar events. 33–70 trades per variant; WR 26–36%; negative expectancy. Calendar structure alone does not produce edge at 1.5R target.

## HistData limitation

Yahoo hourly caps at ~730 days. Without manual HistData zips we cannot test whether any edge is era-specific (2015–2019 vs 2020–2022). Automated HistData pull returns empty from this network.

**To unblock:** place monthly zips at `data/histdata/EURUSD/*.zip` and re-run `aegis-forex-research-sweep`.

## Verdict

**SCM v1 family is dead for demo paper.** All requested forks ran; none produce replicable high-win-rate edge.

| Track | Status |
| ----- | ------ |
| FX0 infra | ☑ |
| FX1 breakout | ☒ FAIL |
| FX2 confirms + continuation | ☒ FAIL |
| Research sweep (4 forks) | ☒ FAIL (0/16) |
| FX3 recipe freeze | **BLOCKED** |
| FX4+ demo | **DO NOT START** |

## Recommended next step

**Parking lot** — SCM v1 on 1h session structure does not meet ≥60% WR gate. Before any demo work:

1. **New hypothesis family** — e.g. lower timeframe (15m) with same confirms, or mean-reversion at session boundaries (different R profile)
2. **Manual HistData** — if deep history is acquired, re-sweep with era-split windows (pre-COVID / post-COVID)
3. **Pair selection** — USD/JPY not yet swept; only pursue if hypothesis changes (JPY session dynamics differ)

**Do not** loosen WR gate or start FX4 demo infrastructure until a variant passes 2/3 OOS windows.

## Reproduce

```bash
aegis-forex-research-sweep
aegis-forex-research-sweep --quick   # EURUSD only, 2 windows

# Single variant
aegis-backtest-forex-scm --pair GBPUSD
# Edit config/forex.yaml: setup, asian_range_max_adr_pct, confirm_score_threshold
```
