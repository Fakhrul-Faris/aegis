"""Venue-agnostic domain models.

All timestamps are timezone-aware UTC. All monetary amounts are floats in
the venue's quote currency (USD/USDT) - revisit Decimal only if reconciliation
(P2.5) surfaces rounding drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Venue(StrEnum):
    KRAKEN = "kraken"
    HYPERLIQUID = "hyperliquid"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    LIMIT_POST_ONLY = "limit_post_only"  # maker leg; rejected if it would cross
    LIMIT_IOC = "limit_ioc"  # taker leg with a price bound (maker-then-IOC, Concept §8)
    MARKET = "market"  # flatten/emergency only
    STOP = "stop"  # venue-native stop attached on fill


@dataclass(frozen=True, slots=True)
class Candle:
    venue: Venue
    symbol: str
    timeframe: str  # e.g. "1h", "4h"
    open_time: datetime  # UTC, start of the bar
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class OrderRequest:
    venue: Venue
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float  # base units
    price: float | None = None  # required for limit types
    reduce_only: bool = False
    client_order_id: str | None = None  # idempotency key, set by execution layer


@dataclass(frozen=True, slots=True)
class Fill:
    venue: Venue
    symbol: str
    order_id: str
    client_order_id: str | None
    side: Side
    quantity: float
    price: float
    fee: float  # quote currency, positive = paid
    is_maker: bool
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class Position:
    venue: Venue
    symbol: str
    side: Side
    quantity: float
    entry_price: float
    unrealized_pnl: float
    isolated_margin: float | None  # None on spot venues


@dataclass(frozen=True, slots=True)
class Balance:
    venue: Venue
    asset: str
    total: float
    available: float
