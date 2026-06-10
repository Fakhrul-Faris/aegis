"""Core domain models and venue-agnostic interfaces.

Strategy, risk, and portfolio code may import ONLY from this package when
talking to exchanges (Concept §15, §18). Exchange client libraries (ccxt,
Hyperliquid SDK, websockets) are imported exclusively inside
``aegis.execution`` adapters. This boundary is what makes a future
multi-market expansion a connector-writing exercise instead of a rewrite.
"""

from aegis.core.interfaces import AccountState, MarketData, OrderExecutor
from aegis.core.models import (
    Balance,
    Candle,
    Fill,
    OrderRequest,
    OrderType,
    Position,
    Side,
    Venue,
)

__all__ = [
    "AccountState",
    "Balance",
    "Candle",
    "Fill",
    "MarketData",
    "OrderExecutor",
    "OrderRequest",
    "OrderType",
    "Position",
    "Side",
    "Venue",
]
