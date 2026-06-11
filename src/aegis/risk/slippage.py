"""Slippage gate (P2.1, Concept Guardrail B).

Calculated slippage above 0.08% of notional means the edge is gone before
the trade starts — cancel, don't hope the market improves.
"""

from __future__ import annotations

from aegis.core.models import Side


def limit_slippage_pct(side: Side, limit_price: float, best_bid: float, best_ask: float) -> float:
    """Worst-case slippage for a limit order vs current top of book.

    Buy above ask or sell below bid = immediate adverse selection.
    """
    if limit_price <= 0:
        return 1.0
    if side is Side.BUY:
        return max(0.0, (limit_price - best_ask) / limit_price)
    return max(0.0, (best_bid - limit_price) / limit_price)


def passes_slippage_gate(slippage_pct: float, max_slippage_pct: float) -> bool:
    return slippage_pct <= max_slippage_pct + 1e-12
