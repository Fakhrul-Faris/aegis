"""Layer 5 - Execution: venue adapters and maker-then-IOC two-leg logic (P0.2, P2.3).

This is the ONLY package allowed to import exchange client libraries.
"""

from aegis.core.models import Venue


def build_market_data(venue: Venue, testnet: bool = False):
    """Composition-root factory so callers never import venue modules directly."""
    if venue is Venue.HYPERLIQUID:
        from aegis.execution.hyperliquid import HyperliquidMarketData

        return HyperliquidMarketData(testnet=testnet)
    if venue is Venue.KRAKEN:
        from aegis.execution.kraken import KrakenMarketData

        return KrakenMarketData()
    raise ValueError(f"No market data adapter for venue {venue}")
