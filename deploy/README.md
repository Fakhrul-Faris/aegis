# Deployment

## macOS (current Phase 0 home: this machine)

```bash
./deploy/install-launchd.sh
```

Installs four launchd agents (ingest, scanner, portfolio, kpi). **Telegram
/commands** (`/status`, `/paper`, …) run on **Fly** inside `aegis-collector` —
do not load `com.aegis.telegrambot` locally while Fly is polling (one listener
per bot token).

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
