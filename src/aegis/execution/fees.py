"""Live fee schedule verification (P1.5).

Config defaults are starting points; venues change tiers. At engine startup,
fetch the current schedule and warn (or fail in live mode) when reality
drifts from what the cost model assumes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aegis.config import AegisConfig, ExchangeFees

logger = logging.getLogger(__name__)

_REL_TOLERANCE = 0.20  # warn if live fee differs by >20% relative


@dataclass(frozen=True)
class FeeMismatch:
    venue: str
    leg: str  # maker | taker
    configured: float
    live: float


async def fetch_hyperliquid_fees(testnet: bool = False) -> ExchangeFees:
    import ccxt.async_support as ccxt

    exchange = ccxt.hyperliquid({"enableRateLimit": True})
    if testnet:
        exchange.set_sandbox_mode(True)
    try:
        await exchange.load_markets()
        fees = await exchange.fetch_trading_fees()
        sample = fees.get("BTC/USDC:USDC") or next(iter(fees.values()))
        return ExchangeFees(
            maker_fee=float(sample.get("maker", 0.00015)),
            taker_fee=float(sample.get("taker", 0.00045)),
        )
    finally:
        await exchange.close()


async def fetch_kraken_fees(exchange) -> ExchangeFees:
    """``exchange`` is a ccxt.kraken instance with markets loaded."""
    trading_fees = await exchange.fetch_trading_fees()
    # Spot default tier - Strategy A venue.
    spot = trading_fees.get("BTC/USD") or trading_fees.get("BTC/USDT") or {}
    return ExchangeFees(
        maker_fee=float(spot.get("maker", 0.0025)),
        taker_fee=float(spot.get("taker", 0.0040)),
    )


def compare_fees(venue: str, configured: ExchangeFees, live: ExchangeFees) -> list[FeeMismatch]:
    mismatches = []
    for leg in ("maker", "taker"):
        cfg_val = getattr(configured, f"{leg}_fee")
        live_val = getattr(live, f"{leg}_fee")
        if cfg_val <= 0:
            continue
        rel = abs(live_val - cfg_val) / cfg_val
        if rel > _REL_TOLERANCE:
            mismatches.append(FeeMismatch(venue, leg, cfg_val, live_val))
    return mismatches


async def verify_fees_at_startup(cfg: AegisConfig) -> list[FeeMismatch]:
    """Fetch live fees and compare to config. Returns mismatches for logging."""
    mismatches: list[FeeMismatch] = []

    try:
        hl_live = await fetch_hyperliquid_fees(testnet=cfg.hyperliquid.testnet)
        mismatches.extend(compare_fees("hyperliquid", cfg.hyperliquid.fees, hl_live))
    except Exception as exc:
        logger.warning("hyperliquid fee fetch failed", extra={"error": repr(exc)})

    if cfg.secrets.kraken_api_key:
        import ccxt.async_support as ccxt

        exchange = ccxt.kraken(
            {
                "apiKey": cfg.secrets.kraken_api_key,
                "secret": cfg.secrets.kraken_api_secret,
                "enableRateLimit": True,
            }
        )
        try:
            await exchange.load_markets()
            kr_live = await fetch_kraken_fees(exchange)
            mismatches.extend(compare_fees("kraken", cfg.kraken_fees, kr_live))
        except Exception as exc:
            logger.warning("kraken fee fetch failed", extra={"error": repr(exc)})
        finally:
            await exchange.close()

    for m in mismatches:
        logger.warning(
            "fee schedule drift",
            extra={
                "venue": m.venue,
                "leg": m.leg,
                "configured": m.configured,
                "live": m.live,
            },
        )
    if cfg.mode == "live" and mismatches:
        raise RuntimeError(
            f"Live fee schedule differs from config ({len(mismatches)} mismatches). "
            "Update config.yaml before trading."
        )
    return mismatches
