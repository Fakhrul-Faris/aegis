# Deployment

## macOS (current Phase 0 home: this machine)

```bash
./deploy/install-launchd.sh
```

Installs three launchd agents that also fire on boot/login:

- `com.aegis.ingest` - candle ingestion (Hyperliquid top-50 + Kraken majors)
- `com.aegis.scanner` - CoinGecko volume anomaly scanner
- `com.aegis.portfolio` - Strategy A paper cycle every 4h (`mode=paper`)

Both alert Telegram on crash. Check health:

```bash
launchctl list | grep com.aegis     # second column 0 = last run OK
tail -f logs/aegis.jsonl            # structured event log
```

The M1 gate (Tasks & Milestones) starts counting from the first uninterrupted
72h of collection. Persistent unfilled gaps or scanner silence are
weekly-KPI items, not annoyances to ignore.

See `deploy/ops.md` for the full runbook (`aegis-doctor`, M1 check, soak,
config freeze).

## Linux VPS (later, equity > RM2,000)

Translate the two agents to systemd timers; everything else is unchanged.
The repo deliberately has no other host dependencies beyond uv + git.
