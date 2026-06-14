# Forex broker & demo data — FX4/FX5

**Decision (updated Jun 2026): Yahoo Finance (`yfinance`) for demo paper. OANDA parked.**

## Demo paper stack (no broker signup required)

| Layer | Source | License / cost |
| ----- | ------ | -------------- |
| **Candles** | Yahoo Finance via `yfinance` | Apache-2.0, free, no API key |
| **Quotes** | Last Yahoo close + Fusion spread model | Modeled bid/ask, not live broker |
| **Fills** | `ForexPaperExecutor` | Fusion RAW + 1–3 pip slip + latency + requote |
| **Research history** | ForexSB CSV / Dukascopy bi5 | Already in `data/forexsb/` |

Config: `demo.data_source: yahoo` in `config/forex.yaml` (default).

Paper trading does **not** need a broker account. You are validating the **frozen recipe behaviour** against realistic costs, not broker UI parity.

## Why not OANDA (for now)

OANDA practice was the original FX4 adapter. If signup/KYC/API access is slow or blocked, **Yahoo is the supported path** — same code path already used in production ingest.

To re-enable OANDA later:

```yaml
# config/forex.yaml
demo:
  data_source: oanda
```

```env
OANDA_API_TOKEN=...
OANDA_ACCOUNT_ID=...
```

## Other options considered

| Option | Open source? | Verdict |
| ------ | ------------- | ------- |
| **Yahoo / yfinance** | Yes (library) | **Default demo** — good enough for ~7 trades/mo event strategy |
| **Dukascopy bi5** | Free data API | Research/backfill only; already have parser in `forex_download.py` |
| **OANDA v20 REST** | Proprietary API | Optional; parked |
| **Fusion cTrader** | Proprietary | **Live target (FX8)** — matches cost model; not needed for paper |
| **MetaTrader 5** | Terminal proprietary | Heavy; skip |
| **Alpha Vantage / Twelve Data** | Freemium APIs | Possible future `demo.data_source`; adds key management |

## Live path (unchanged)

Fusion Markets RAW (`broker: fusion_raw`) after FX6 paper proof. Demo data source does not affect live broker choice.

## Smoke test (no OANDA)

```bash
aegis-forex-ingest
aegis-forex-fx4-check --round-trip
aegis-forex-paper-run
aegis-summary --print-only   # crypto + forex, one message shape
```
