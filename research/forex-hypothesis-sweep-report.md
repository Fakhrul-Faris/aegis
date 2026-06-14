# Forex Hypothesis Sweep (H1–H26)

*Generated 2026-06-14 06:39 UTC*

**Runnable:** 27 · **Passed gate (≥2/3 windows):** 0

## Data imported

- `EURUSD_15m`: 100,000 bars
- `EURUSD_1h`: 0 bars
- `GBPUSD_1h`: 0 bars
- `USDJPY_1h`: 82,958 bars

## Summary (runnable only)

| ID | Hypothesis | Pair | TF | W pass | Trades | Avg WR | Avg Exp |
| -- | ---------- | ---- | -- | ------ | ------ | ------ | ------- |
| H16 | USDJPY Tokyo-London LER | USDJPY | 1h | 0/3 | 26 | 18.4% | +1.286 |
| H26b | LER Tue-Thu Only | EURUSD | 1h | 0/3 | 63 | 13.7% | +0.487 |
| H11 | Event Spike Fade | EURUSD | 1h | 0/3 | 89 | 65.6% | +0.303 |
| H12b | Only Event Days | EURUSD | 1h | 0/3 | 1 | 33.3% | +0.287 |
| H22 | LER + 4h Time Stop | EURUSD | 1h | 0/3 | 102 | 15.4% | +0.166 |
| H12a | Skip Event Days | EURUSD | 1h | 0/3 | 97 | 12.1% | +0.017 |
| H1 | London Exhaustion Reversion | EURUSD | 1h | 0/3 | 102 | 11.5% | -0.011 |
| H24 | LER Pre-London Drift Cap | EURUSD | 1h | 0/3 | 102 | 11.5% | -0.011 |
| H6 | 15m London Breakout | EURUSD | 15m | 0/3 | 623 | 52.1% | -0.071 |
| H17 | GBPUSD LER | GBPUSD | 1h | 0/3 | 153 | 13.6% | -0.147 |
| H7 | 15m London Continuation | EURUSD | 15m | 0/3 | 675 | 48.3% | -0.166 |
| H9 | 15m Post-London Box | EURUSD | 15m | 0/3 | 1025 | 44.8% | -0.189 |
| H14 | DXY Divergence Fade | EURUSD | 1h | 0/3 | 34 | 9.8% | -0.195 |
| H10 | Event Box 1R/0.6R | EURUSD | 1h | 0/3 | 246 | 30.6% | -0.215 |
| H19a | Breakout 1.0R | EURUSD | 1h | 0/3 | 2349 | 45.0% | -0.233 |
| H23 | LER Asian <20% ADR | EURUSD | 1h | 0/3 | 37 | 14.3% | -0.263 |
| H5 | Double Session Exhaustion | EURUSD | 1h | 0/3 | 38 | 22.9% | -0.360 |
| H13 | LER + DXY Mandatory | EURUSD | 1h | 0/3 | 5 | 0.0% | -0.381 |
| H3 | London Close Fade | EURUSD | 1h | 0/3 | 1015 | 41.2% | -0.394 |
| H2 | NY Fade v2 | EURUSD | 1h | 0/3 | 145 | 14.0% | -0.396 |
| H20 | Reversion 0.8R Fixed | EURUSD | 1h | 0/3 | 102 | 37.5% | -0.462 |
| H4 | Asian Box Fade | EURUSD | 1h | 0/3 | 685 | 26.4% | -0.474 |
| H21 | Partial 0.5R Target | EURUSD | 1h | 0/3 | 102 | 40.5% | -0.530 |
| H8 | 15m LER | EURUSD | 15m | 0/3 | 14 | 9.7% | -0.548 |
| H19b | Continuation 1.0R | EURUSD | 1h | 0/3 | 3194 | 38.9% | -0.644 |
| H25 | LER Min Stop 5 Pips | EURUSD | 1h | 0/3 | 64 | 14.6% | -0.671 |
| H26a | LER Mon/Fri Only | EURUSD | 1h | 0/3 | 39 | 7.4% | -0.779 |

## Skipped

- **H15** Risk-on Regime: needs VIX/gold feed
- **H18** EURGBP Cross: no EURGBP data

## Passed gate

None.

## Top 10 by expectancy

### H16 — USDJPY Tokyo-London LER
- W1-oldest: 13 trades, WR 38.5%, +5.465R, pass=False
- W2-mid: 7 trades, WR 0.0%, -1.135R, pass=False
- W3-newest: 6 trades, WR 16.7%, -0.470R, pass=False

### H26b — LER Tue-Thu Only
- W1-oldest: 19 trades, WR 5.3%, +2.281R, pass=False
- W2-mid: 26 trades, WR 19.2%, +0.011R, pass=False
- W3-newest: 18 trades, WR 16.7%, -0.831R, pass=False

### H11 — Event Spike Fade
- W1-oldest: 6 trades, WR 83.3%, +0.707R, pass=False
- W2-mid: 42 trades, WR 47.6%, +0.017R, pass=False
- W3-newest: 41 trades, WR 65.9%, +0.184R, pass=False

### H12b — Only Event Days
- W1-oldest: 0 trades, WR 0.0%, +0.000R, pass=False
- W2-mid: 0 trades, WR 0.0%, +0.000R, pass=False
- W3-newest: 1 trades, WR 100.0%, +0.860R, pass=False

### H22 — LER + 4h Time Stop
- W1-oldest: 32 trades, WR 9.4%, +1.287R, pass=False
- W2-mid: 41 trades, WR 19.5%, -0.114R, pass=False
- W3-newest: 29 trades, WR 17.2%, -0.675R, pass=False

### H12a — Skip Event Days
- W1-oldest: 32 trades, WR 9.4%, +1.235R, pass=False
- W2-mid: 38 trades, WR 15.8%, -0.316R, pass=False
- W3-newest: 27 trades, WR 11.1%, -0.870R, pass=False

### H1 — London Exhaustion Reversion
- W1-oldest: 32 trades, WR 9.4%, +1.235R, pass=False
- W2-mid: 41 trades, WR 14.6%, -0.378R, pass=False
- W3-newest: 29 trades, WR 10.3%, -0.890R, pass=False

### H24 — LER Pre-London Drift Cap
- W1-oldest: 32 trades, WR 9.4%, +1.235R, pass=False
- W2-mid: 41 trades, WR 14.6%, -0.378R, pass=False
- W3-newest: 29 trades, WR 10.3%, -0.890R, pass=False

### H6 — 15m London Breakout
- W1-oldest: 206 trades, WR 48.5%, -0.095R, pass=False
- W2-mid: 231 trades, WR 57.1%, -0.007R, pass=False
- W3-newest: 186 trades, WR 50.5%, -0.112R, pass=False

### H17 — GBPUSD LER
- W1-oldest: 61 trades, WR 14.8%, +0.468R, pass=False
- W2-mid: 66 trades, WR 10.6%, -0.465R, pass=False
- W3-newest: 26 trades, WR 15.4%, -0.444R, pass=False
