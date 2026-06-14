"""Date-grid backtest harness with dry-run stub (FX-R2)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from aegis.config_forex import load_forex_config
from aegis.data.as_of import parse_as_of
from aegis.research.run_manifest import complete_run, fail_run, start_run, update_checkpoint


def _date_grid(start: datetime, end: datetime, *, freq: str) -> list[datetime]:
    days = {"daily": 1, "weekly": 7, "monthly": 30}[freq]
    out: list[datetime] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=days)
    return out


def run_grid(
    *,
    start: str,
    end: str,
    freq: str = "weekly",
    dry_run: bool = True,
    hypothesis_id: str | None = None,
) -> dict:
    cfg = load_forex_config()
    start_dt = parse_as_of(start)
    end_dt = parse_as_of(end)
    if start_dt is None or end_dt is None:
        raise ValueError("start and end required (YYYY-MM-DD)")

    run_dir, manifest = start_run(
        "forex_backtest_grid",
        hypothesis_id=hypothesis_id,
        config_hash=None,
        as_of=end,
    )
    dates = _date_grid(start_dt, end_dt, freq=freq)
    update_checkpoint(run_dir, "grid_dates_built")

    if dry_run:
        metrics = {
            "mode": "dry_run",
            "dates": len(dates),
            "freq": freq,
            "strategy": cfg.active_strategy,
            "pairs": list(cfg.event_spike_fade.pairs),
            "message": "harness OK — run aegis-backtest-forex-realistic for full sim",
        }
        complete_run(run_dir, metrics)
        return {"run_id": manifest.run_id, **metrics}

    try:
        update_checkpoint(run_dir, "realistic_backtest_pending")
        metrics = {
            "mode": "live",
            "dates": len(dates),
            "freq": freq,
            "note": "wire aegis-backtest-forex-realistic per grid date in FX-R2.1",
        }
        complete_run(run_dir, metrics)
        return {"run_id": manifest.run_id, **metrics}
    except Exception as exc:
        fail_run(run_dir, str(exc))
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Forex backtest date grid (FX-R2)")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--freq", default="weekly", choices=["daily", "weekly", "monthly"])
    parser.add_argument("--live", action="store_true", help="run full grid (FX-R2.1)")
    parser.add_argument("--hypothesis-id", default=None)
    args = parser.parse_args()

    result = run_grid(
        start=args.start,
        end=args.end,
        freq=args.freq,
        dry_run=not args.live,
        hypothesis_id=args.hypothesis_id,
    )
    print(result)


if __name__ == "__main__":
    main()
