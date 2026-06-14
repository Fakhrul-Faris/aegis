# Oxford Capital Strategies — research seeds (FX-R)

Source: [Oxford Strat Resources](https://oxfordstrat.com/resources/) — systematic reviews of **public-domain** strategies with A/B/C/D ratings per test variant.

**Not live signals.** Use only to seed hypotheses for `aegis-forex-research-goal` + walk-forward. H11c-3 remains frozen on Fly.

## Rating key (their framework)

- **A / B / C / D** — quality tiers from their R&D backtests (equities/futures biased)
- **Bold** in the index = best variant they tested for that pattern family

## Closest to Event Spike Fade (information / post-shock mean reversion)

| Pattern | Oxford rating (best variant) | Aegis relevance |
| ------- | ---------------------------- | --------------- |
| [False Breakout](https://oxfordstrat.com/trading-strategies/false-breakout-1/) | A/B/**C** | Breakout fails → fade; cousin to post-event spike fade |
| [Bull Oops Pattern](https://oxfordstrat.com/trading-strategies/bull-oops-pattern/) | A/B/**C** | Open below prior low then recovery — short-term fade setup |
| [Bear Oops Pattern](https://oxfordstrat.com/trading-strategies/bear-oops-pattern/) | A/B/C/**D** | Mirror of bull oops |
| [Gap Pattern Type A](https://oxfordstrat.com/trading-strategies/gap-pattern/) | **A**/B/C/D | Gap + filter; event gaps on forex need calendar layer |
| [ORBP Counter-Trend](https://oxfordstrat.com/trading-strategies/orbp-countertrend/) | A/B/C/**D** | Opening range fade — session analogue to London/NY |
| [Smash Day Type B](https://oxfordstrat.com/trading-strategies/smash-day-pattern-b1/) | **A**/B/C/D | Reversal day pattern — test as confirm, not replacement |
| [Turtle Soup](https://oxfordstrat.com/trading-strategies/turtle-soup-plus-1/) | A/B/C/**D** | False breakout of Donchian — structural fade |

## Session / momentum (parked SCM family — do not mix mid-clock)

| Pattern | Rating | Note |
| ------- | ------ | ---- |
| [NR7 / Narrow Range](https://oxfordstrat.com/trading-strategies/nr7/) | A/B/**C** | Crabel compression — SCM cousin |
| [Opening Range Breakout](https://oxfordstrat.com/trading-strategies/opening-range-breakout/) | A/B/C/**D** | Momentum, not fade |
| [Dual Momentum + ROC](https://oxfordstrat.com/trading-strategies/dual-momentum-rate-of-change/) | A/B/**C** | Trend, parked |

## How to use in Aegis

1. Pick one pattern → `aegis-forex-research-goal add` with falsifier
2. Map to forex 1h + calendar filter (not copy equity rules verbatim)
3. `aegis-backtest-forex-grid --start … --end …` (dry-run harness first)
4. `aegis-recipe-compare` vs `event_spike_fade` + null control
5. Only promote if 3/3 OOS passes — same bar as H11c-3

## Data analysis (optional context)

- [Volatility Clustering](https://oxfordstrat.com/data/volatility-clustering-1/) — supports event spread multiplier in `forex_execution_model`
- [Global Market Correlations](https://oxfordstrat.com/data/global-market-correlations/) — DXY confirm rationale
