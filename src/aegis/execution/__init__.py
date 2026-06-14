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
    if venue is Venue.FOREX_DEMO:
        from aegis.execution.forex_market_data import build_forex_market_data

        from aegis.config import load_config
        from aegis.config_forex import load_forex_config

        cfg = load_forex_config()
        return build_forex_market_data(cfg, load_config().secrets)
    raise ValueError(f"No market data adapter for venue {venue}")


def build_trading(venue: Venue, secrets, testnet: bool = True):
    """Authenticated executor + account state for one venue.

    ``secrets`` is aegis.config.Secrets; this factory is the only place that
    maps secret fields to venue clients.
    """
    if venue is Venue.HYPERLIQUID:
        if not (secrets.hyperliquid_wallet_address and secrets.hyperliquid_private_key):
            raise ValueError("Hyperliquid wallet address + private key required in .env")
        from aegis.execution.hyperliquid_trading import HyperliquidTrading

        return HyperliquidTrading(
            wallet_address=secrets.hyperliquid_wallet_address,
            private_key=secrets.hyperliquid_private_key,
            testnet=testnet,
        )
    if venue is Venue.KRAKEN:
        if not (secrets.kraken_api_key and secrets.kraken_api_secret):
            raise ValueError("Kraken API key + secret required in .env")
        from aegis.execution.kraken import KrakenTrading

        return KrakenTrading(api_key=secrets.kraken_api_key, api_secret=secrets.kraken_api_secret)
    raise ValueError(f"No trading adapter for venue {venue}")
