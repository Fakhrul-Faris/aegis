# Aegis

Autonomous crypto trading system. Staged two-strategy bot:

- **Strategy B - statistical arbitrage** (Hyperliquid perps): Kalman-filtered
  hedge ratios, FDR-corrected cointegration screening, Z-score entries with
  time stops. Goes live first.
- **Strategy A - swing momentum** (Kraken spot): EMA/RSI plus a volume anomaly
  scanner. Paper-only until promoted on logged evidence.

Both governed by a risk-based sizing engine (0.5-1.0% of equity per trade),
a per-asset regime detector, correlation guards, and Monte Carlo-calibrated
circuit breakers.

The full specification lives in [`docs/`](docs/):

- [`docs/Aegis Concept.md`](docs/Aegis%20Concept.md) v3.0 — architecture and math
- [`docs/Aegis Tasks & Milestones.md`](docs/Aegis%20Tasks%20%26%20Milestones.md) — crypto main track M0–M9
- [`docs/Aegis Forex Tasks & Milestones.md`](docs/Aegis%20Forex%20Tasks%20%26%20Milestones.md) — parallel forex track
- [`docs/Aegis Intraday Tasks & Milestones.md`](docs/Aegis%20Intraday%20Tasks%20%26%20Milestones.md) — day-trading Strategy C/D

## Setup

Requires [uv](https://docs.astral.sh/uv/) (manages Python 3.12 automatically):

```bash
uv sync --dev          # create venv + install deps
cp .env.example .env   # then fill in secrets (never committed)
```

## Development

```bash
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
```

## Architecture rules (enforced by tests)

1. **Venue boundary:** only `aegis/execution/` may import exchange client
   libraries. Everything else talks to venues through the interfaces in
   `aegis/core/` (`MarketData`, `OrderExecutor`, `AccountState`).
   `tests/test_core_boundary.py` fails the build on violations.
2. **Config safety:** the bot refuses to start in `live` mode until the
   kill-switch drawdown threshold has been calibrated from the Monte Carlo
   envelope (deliberately `null` in `config/config.yaml`).
3. **Secrets:** environment/`.env` only. The config loader never reads
   secrets from YAML.

## Layout

```
docs/          strategy spec, milestone trackers, study notes
config/        non-secret runtime configuration
deploy/        ops runbook, launchd, Fly.io
research/      offline studies — crypto/, forex/, goals/, runs/
src/aegis/
  core/        domain models + venue-agnostic interfaces
  data/        candle ingestion, anomaly scanner, SQLite persistence
  strategy/    Strategy B (pairs) and Strategy A (momentum, paper)
  risk/        sizing, correlation guard, breakers
  execution/   venue adapters, maker-then-IOC two-leg execution
  portfolio/   signal ranking and risk budget allocation
  monitor/     Telegram alerts, daily summaries
tests/
data/          runtime SQLite + research DBs (gitignored)
logs/          JSON logs, launchd output (gitignored)
```

Phase 2 complete; Phase 3 paper trading in progress. See
[`docs/Aegis Tasks & Milestones.md`](docs/Aegis%20Tasks%20%26%20Milestones.md) for gates.

- **M0, M2, M4, M5:** passed
- **M3 (Strategy B cointegration):** failed — Strategy A is the primary path
- **M6:** in progress (8-week paper clock, ≥40 trades needed)
- **Intraday ID1:** backtest failed (0 trades) — params/history review needed

Mode: `paper`. Ops:

```bash
uv run aegis-doctor              # health check
uv run aegis-portfolio --loop 14400
./deploy/install-launchd.sh      # ingest + scanner + portfolio
./deploy/sync-collector-db.sh    # pull Fly DB for local paper
```

Runbook: `deploy/ops.md`
