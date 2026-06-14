"""Post-trade reflection for closed forex demo positions (FX-R3)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

REFLECTIONS_DIR = Path("research/reflections")


@dataclass
class TradeReflection:
    position_id: int
    symbol: str
    strategy: str
    opened_ts_ms: int
    closed_ts_ms: int
    realized_pnl_usd: float
    expected_r: float | None
    realized_r: float | None
    slippage_note: str
    event_code: str | None
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def write_reflection(ref: TradeReflection) -> Path:
    REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = REFLECTIONS_DIR / f"pos-{ref.position_id}.json"
    path.write_text(json.dumps(ref.to_dict(), indent=2))
    return path


def reflect_closed_position(
    conn,
    *,
    position_id: int,
    strategy: str,
    venue: str,
) -> TradeReflection | None:
    row = conn.execute(
        """
        SELECT symbol, opened_ts_ms, closed_ts_ms, realized_pnl, risk_amount_usd, context_json
        FROM positions WHERE id = ? AND strategy = ? AND venue = ?
        """,
        (position_id, strategy, venue),
    ).fetchone()
    if not row or row[2] is None:
        return None

    ctx = json.loads(row[5]) if row[5] else {}
    risk = float(row[4] or 0.0)
    pnl = float(row[3] or 0.0)
    expected_r = None
    realized_r = pnl / risk if risk > 0 else None
    if ctx.get("target") and ctx.get("stop") and row[4]:
        # rough planned R from context if present
        expected_r = 1.0

    ref = TradeReflection(
        position_id=position_id,
        symbol=row[0],
        strategy=strategy,
        opened_ts_ms=int(row[1]),
        closed_ts_ms=int(row[2]),
        realized_pnl_usd=pnl,
        expected_r=expected_r,
        realized_r=realized_r,
        slippage_note="compare fill vs forex_execution_model on weekly KPI",
        event_code=ctx.get("event_code") or (ctx.get("situation") or {}).get("event_code"),
        created_at=datetime.now(tz=UTC).isoformat(),
    )
    write_reflection(ref)
    return ref


def list_recent_reflections(limit: int = 5) -> list[TradeReflection]:
    if not REFLECTIONS_DIR.exists():
        return []
    paths = sorted(REFLECTIONS_DIR.glob("pos-*.json"), reverse=True)[:limit]
    out: list[TradeReflection] = []
    for p in paths:
        data = json.loads(p.read_text())
        out.append(TradeReflection(**data))
    return out
