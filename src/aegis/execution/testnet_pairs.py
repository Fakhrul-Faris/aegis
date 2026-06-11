"""Testnet spread pair helpers (P2.5).

Hyperliquid testnet majors often have L2 books >3% away from the oracle and
reject IOC orders. These alt pairs track oracle closely enough for live drills.
"""

from __future__ import annotations

from dataclasses import dataclass

from aegis.core.models import Side

MAX_BOOK_ORACLE_GAP = 0.02
ORACLE_BAND = 0.019
IOC_BUFFER = 0.002


@dataclass(frozen=True)
class TestnetSpreadPair:
    long_symbol: str
    short_symbol: str
    liquidity_rank: dict[str, float]


# Rotated through the campaign so correlation buckets do not stall on one name.
CAMPAIGN_PAIRS: tuple[TestnetSpreadPair, ...] = (
    TestnetSpreadPair("SOL", "DOGE", {"SOL": 10.0, "DOGE": 1.0}),
    TestnetSpreadPair("SOL", "ARB", {"SOL": 10.0, "ARB": 1.0}),
    TestnetSpreadPair("DOGE", "ARB", {"DOGE": 2.0, "ARB": 1.0}),
)


def book_oracle_gap(ask: float, oracle: float) -> float:
    return abs(ask / oracle - 1.0)


def buy_ioc_price(ask: float, oracle: float) -> float:
    return min(ask * (1 + IOC_BUFFER), oracle * (1 + ORACLE_BAND))


def sell_ioc_price(bid: float, oracle: float) -> float:
    return max(bid * (1 - IOC_BUFFER), oracle * (1 - ORACLE_BAND))


def pair_passes_oracle_check(
    *,
    long_ask: float,
    long_oracle: float,
    short_ask: float,
    short_oracle: float,
) -> bool:
    return (
        book_oracle_gap(long_ask, long_oracle) <= MAX_BOOK_ORACLE_GAP
        and book_oracle_gap(short_ask, short_oracle) <= MAX_BOOK_ORACLE_GAP
    )


def leg_price(side: Side, bid: float, ask: float, oracle: float) -> float:
    if side is Side.BUY:
        return buy_ioc_price(ask, oracle)
    return sell_ioc_price(bid, oracle)
