"""Venue-agnostic interfaces (Concept §15).

Strategy/risk/portfolio code depends on these ABCs only. Each venue gets an
adapter in ``aegis.execution`` implementing them; paper trading gets a
simulator implementing the same contracts, which is what makes paper results
comparable to live behaviour.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from aegis.core.models import Balance, Candle, Fill, OrderRequest, Position


class MarketData(ABC):
    """Read-only market data for one venue."""

    @abstractmethod
    async def fetch_candles(self, symbol: str, timeframe: str, limit: int = 500) -> list[Candle]:
        """Most recent ``limit`` closed candles, oldest first."""

    @abstractmethod
    async def fetch_top_of_book(self, symbol: str) -> tuple[float, float]:
        """(best_bid, best_ask). Used by the slippage gate before every order."""


class OrderExecutor(ABC):
    """Order placement and management for one venue."""

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> str:
        """Submit an order; returns the venue order id. Raises on rejection."""

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> None: ...

    @abstractmethod
    async def fetch_fills(self, symbol: str, order_id: str) -> list[Fill]:
        """All fills for an order. Empty list = resting/unfilled."""


class AccountState(ABC):
    """Account introspection for one venue."""

    @abstractmethod
    async def fetch_equity_usd(self) -> float:
        """Total account value in USD terms - the base of all risk sizing."""

    @abstractmethod
    async def fetch_balances(self) -> list[Balance]: ...

    @abstractmethod
    async def fetch_positions(self) -> list[Position]: ...
