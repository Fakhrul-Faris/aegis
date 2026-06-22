# Forex SCM FX2 + Continuation Pivot

*June 2026 · ADR/DXY/calendar confirms + London continuation setup*

## Path tested (in order)

1. **FX1 spine** — Asian → London **breakout** (close outside range) → **FAIL** (0/3)
2. **FX2 confirms** on breakout — ADR + DXY + calendar score ≥3 → **FAIL** (no material change; confirms too permissive on breakout)
3. **Pivot setup** — Asian compression → London **continuation** (first bar direction) + FX2 confirms → **FAIL** (0/3) but **improved W1**

## Best result so far (continuation + score confirms)

| Window | Trades | Win rate | Expectancy | 90% CI (R) |
| ------ | ------ | -------- | ---------- | ---------- |
| W1-oldest | 173 | 50.9% | **+0.071R** | [-0.072, +0.215] |
| W2-mid | 171 | 43.9% | -0.011R | [-0.143, +0.122] |
| W3-newest | 176 | 46.0% | -0.046R | [-0.183, +0.091] |

**0/3 windows pass** (need ≥60% WR, expectancy CI > 0, ≥80 trades).

## Ablation notes

| Variant | Effect |
| ------- | ------ |
| Breakout + confirms | ~same as spine (filters barely fired) |
| Continuation + confirms | W1 expectancy flips positive; WR +5pp |
| Mandatory ADR + DXY | Trade count collapses (<80); W3 WR 54% but insufficient sample |

## Verdict

**SCM v1 (breakout OR continuation) on EUR/USD 1h is not demo-ready.**

Closest edge: **London continuation + light confirms** on oldest window only — not replicable across 3 windows.

## Next options (not implemented)

1. **HistData 1h** import 2015–2022 — test if edge is era-specific
2. **Tighter Asian compression** (e.g. 25% ADR) + higher confirm threshold (4)
3. **GBP/USD** — different session personality
4. **Parking lot** — new hypothesis family (NY fade, event aftermath structure)

## Reproduce

```bash
# Current config: london_continuation + confirms (default)
aegis-backtest-forex-scm

# Spine breakout (FX1)
# Edit config/forex.yaml: setup: london_breakout
aegis-backtest-forex-scm --no-confirms

aegis-backtest-forex-scm --ablation --window 2024-01-01 2025-06-01
```

## Frozen config

`config/forex.yaml` → `scm.setup: london_continuation`
