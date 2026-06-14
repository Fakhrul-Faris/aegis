"""Forex trade cost model — Fusion Markets RAW (FX0).

Prices round-trip cost in USD for a standard lot fraction so SCM backtests
and demo gates use the same assumptions as the milestone doc.
"""

from __future__ import annotations

from dataclasses import dataclass

from aegis.config_forex import ForexCostsConfig, load_forex_config


@dataclass(frozen=True)
class ForexTradeCostsUsd:
    pair: str
    lots: float
    spread_usd: float
    commission_usd: float
    slippage_usd: float
    pip_value_per_lot: float
    spread_pips: float
    slippage_pips: float
    event_multiplier: float = 1.0

    @property
    def total_usd(self) -> float:
        return (self.spread_usd + self.commission_usd + self.slippage_usd) * self.event_multiplier


def forex_round_trip_costs(
    costs: ForexCostsConfig,
    pair: str,
    lots: float = 0.01,
    *,
    near_high_impact_event: bool = False,
) -> ForexTradeCostsUsd:
    """Round-trip cost for ``lots`` standard lots (0.01 = micro)."""
    spread_pips = costs.spread_pips_for(pair)
    slippage_pips = costs.slippage_pips
    pip_value = costs.usd_per_pip_for(pair)

    spread_usd = spread_pips * pip_value * lots * 2  # in + out
    slippage_usd = slippage_pips * pip_value * lots * 2
    commission_usd = costs.commission_usd_per_lot_round_turn * lots
    multiplier = costs.event_spread_multiplier if near_high_impact_event else 1.0

    return ForexTradeCostsUsd(
        pair=pair,
        lots=lots,
        spread_usd=spread_usd,
        commission_usd=commission_usd,
        slippage_usd=slippage_usd,
        pip_value_per_lot=pip_value,
        spread_pips=spread_pips,
        slippage_pips=slippage_pips,
        event_multiplier=multiplier,
    )


def cost_pct_of_notional(costs: ForexTradeCostsUsd, notional_usd: float) -> float:
    if notional_usd <= 0:
        return 0.0
    return costs.total_usd / notional_usd


def load_fusion_costs(config_path: str = "config/forex.yaml") -> ForexCostsConfig:
    return load_forex_config(config_path).costs
