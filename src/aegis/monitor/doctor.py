"""Operational health check — run before trusting the stack."""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import subprocess
import sys
from pathlib import Path

from aegis.config import load_config
from aegis.core.models import Venue
from aegis.data import db
from aegis.log import setup_logging


def _check_env(cfg) -> list[str]:
    issues: list[str] = []
    if not Path(".env").exists():
        issues.append(".env missing — copy from .env.example")
    if cfg.monitoring.telegram_enabled:
        if not cfg.secrets.telegram_bot_token or not cfg.secrets.telegram_chat_id:
            issues.append("Telegram enabled but TELEGRAM_BOT_TOKEN/CHAT_ID unset")
    return issues


def _check_db(cfg) -> tuple[list[str], list[str], sqlite3.Connection | None]:
    issues: list[str] = []
    warnings: list[str] = []
    path = Path(cfg.sqlite_path)
    if not path.exists():
        issues.append(f"SQLite not found: {path} (run ingest/scanner or sync-collector-db)")
        return issues, warnings, None
    conn = db.connect(path)
    flags = conn.execute("SELECT COUNT(*) FROM scanner_flags").fetchone()[0]
    candles = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
    snapshots = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
    if candles == 0:
        issues.append("candles empty — run aegis-ingest or sync-collector-db")
    if flags == 0:
        if snapshots >= 48:
            warnings.append(
                "scanner_flags empty — no 3x volume anomalies yet; "
                "AGGRESSIVE paper entries need flags when they appear"
            )
        else:
            issues.append("scanner_flags empty and snapshot history thin — run scanner/ingest")
    return issues, warnings, conn


def _check_launchd() -> list[str]:
    try:
        out = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return ["launchctl unavailable (not macOS?)"]
    notes: list[str] = []
    for label in ("com.aegis.ingest", "com.aegis.scanner", "com.aegis.portfolio", "com.aegis.telegrambot"):
        if label in out:
            line = next(l for l in out.splitlines() if label in l)
            parts = line.split()
            code = parts[1] if len(parts) > 1 else "?"
            if code not in ("0", "-"):
                notes.append(f"{label} last exit {code}")
        else:
            notes.append(f"{label} not loaded — run deploy/install-launchd.sh")
    return notes


async def _check_kraken() -> list[str]:
    from aegis.execution import build_market_data

    md = build_market_data(Venue.KRAKEN)
    try:
        candles = await md.fetch_candles("BTC/USDT", "1h", limit=3)
        if len(candles) < 1:
            return ["Kraken returned no candles"]
        return []
    except Exception as exc:
        return [f"Kraken market data failed: {exc!r}"]
    finally:
        await md.close()


def _check_fly() -> list[str]:
    if not shutil_which("fly"):
        return ["fly CLI not installed (optional)"]
    try:
        out = subprocess.run(
            ["fly", "status", "-a", "aegis-collector"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if out.returncode != 0:
            return ["aegis-collector not reachable via fly CLI"]
        if "started" not in out.stdout.lower():
            return ["aegis-collector machine not started"]
        return []
    except subprocess.SubprocessError as exc:
        return [f"fly status failed: {exc}"]


def shutil_which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


def _paper_status(conn: sqlite3.Connection) -> str:
    open_n = len(db.open_paper_positions(conn))
    signals = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE strategy='A' AND taken=1"
    ).fetchone()[0]
    equity = db.latest_paper_equity(conn)
    return f"paper equity ${equity:,.2f} | open {open_n} | taken signals {signals}"


async def format_doctor_report(cfg, *, check_kraken: bool = True) -> tuple[str, bool]:
    """Text report and True when no critical issues."""
    issues: list[str] = []
    warnings: list[str] = []

    issues.extend(_check_env(cfg))
    db_issues, db_warnings, conn = _check_db(cfg)
    issues.extend(db_issues)
    warnings.extend(db_warnings)
    warnings.extend(_check_launchd())
    warnings.extend(_check_fly())
    if check_kraken:
        issues.extend(await _check_kraken())

    lines = [
        f"mode: {cfg.mode}",
        f"sqlite: {cfg.sqlite_path}",
    ]
    if conn:
        lines.append(f"status: {_paper_status(conn)}")
        conn.close()

    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in warnings:
            lines.append(f"  - {w}")

    if issues:
        lines.append("")
        lines.append("Issues:")
        for i in issues:
            lines.append(f"  - {i}")
        return "\n".join(lines), False

    lines.append("")
    lines.append("All critical checks passed.")
    return "\n".join(lines), True


async def run_doctor(cfg_path: str) -> int:
    cfg = load_config(cfg_path)
    text, ok = await format_doctor_report(cfg, check_kraken=True)
    print("Aegis doctor")
    for line in text.splitlines():
        if line.startswith("  "):
            print(line)
        elif line == "":
            print()
        else:
            print(f"  {line}")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis operational health check")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)
    code = asyncio.run(run_doctor(args.config))
    sys.exit(code)


if __name__ == "__main__":
    main()
