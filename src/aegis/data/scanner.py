"""Volume anomaly scanner (P0.4) - Strategy A's data collection mission.

Every run:
1. Fetch the top-N coins by market cap from CoinGecko (2 API calls for 300).
2. Store a raw snapshot of every coin - the permanent dataset.
3. Estimate each coin's hourly volume and compare against its rolling
   baseline; flag at ``volume_multiple`` x with a price-action variant tag.

Hourly volume estimation: CoinGecko's free tier only exposes 24h ROLLING
volume. With snapshots one hour apart,

    vol24h(t) - vol24h(t-1h) = vol(newest hour) - vol(hour that rolled off)

so the newest hour is estimated as the delta plus the rolled-off hour,
approximated by the steady-state mean ``vol24h(t-1h) / 24``. The baseline
hourly volume over the window is exactly ``avg(vol24h) / 24``. Raw snapshots
are stored forever, so this estimator can be refined and recomputed later.

Flags are logged for EVERY variant (Concept §7): which one carries edge is
the empirical question this dataset exists to answer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx

from aegis.config import AegisConfig, load_config
from aegis.data import db
from aegis.log import setup_logging

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_PER_PAGE = 250
_RETRIES = 3
_HOUR_MS = 3_600_000

VARIANT_PRICE_UP = "price_up_5"
VARIANT_PRICE_FLAT = "price_flat"
VARIANT_PRICE_DOWN = "price_down"


@dataclass(frozen=True)
class MarketRow:
    coin_id: str
    symbol: str
    price_usd: float | None
    vol24h_usd: float | None
    market_cap_usd: float | None
    price_change_1h_pct: float | None
    price_change_24h_pct: float | None


@dataclass
class ScanStats:
    snapshots: int = 0
    flags: int = 0
    skipped_no_history: int = 0


class CoinGeckoClient:
    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None):
        headers = {"x-cg-demo-api-key": api_key} if api_key else {}
        self._client = client or httpx.AsyncClient(
            timeout=20.0, headers=headers, base_url=COINGECKO_BASE
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict) -> list:
        delay = 2.0
        for attempt in range(_RETRIES):
            try:
                response = await self._client.get(path, params=params)
                if response.status_code == 429:
                    raise httpx.HTTPStatusError(
                        "rate limited", request=response.request, response=response
                    )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPStatusError, httpx.TransportError):
                if attempt == _RETRIES - 1:
                    raise
                logger.warning("coingecko retry", extra={"path": path, "attempt": attempt + 1})
                await asyncio.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")

    async def fetch_top_markets(self, top_n: int) -> list[MarketRow]:
        rows: list[MarketRow] = []
        pages = (top_n + _PER_PAGE - 1) // _PER_PAGE
        for page in range(1, pages + 1):
            data = await self._get(
                "/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": _PER_PAGE,
                    "page": page,
                    "sparkline": "false",
                    "price_change_percentage": "1h,24h",
                },
            )
            for item in data:
                rows.append(
                    MarketRow(
                        coin_id=item["id"],
                        symbol=(item.get("symbol") or "").upper(),
                        price_usd=item.get("current_price"),
                        vol24h_usd=item.get("total_volume"),
                        market_cap_usd=item.get("market_cap"),
                        price_change_1h_pct=item.get("price_change_percentage_1h_in_currency"),
                        price_change_24h_pct=item.get("price_change_percentage_24h_in_currency"),
                    )
                )
        return rows[:top_n]


def classify_variant(
    price_change_1h_pct: float | None, up_threshold: float, down_threshold: float
) -> str:
    if price_change_1h_pct is None:
        return VARIANT_PRICE_FLAT
    if price_change_1h_pct >= up_threshold:
        return VARIANT_PRICE_UP
    if price_change_1h_pct <= down_threshold:
        return VARIANT_PRICE_DOWN
    return VARIANT_PRICE_FLAT


def estimate_hourly_volume(current_vol24h: float, previous_vol24h: float, dt_ms: int) -> float:
    """Newest-hour volume estimate from two rolling-24h readings (see module doc)."""
    dt_hours = dt_ms / _HOUR_MS
    delta_per_hour = (current_vol24h - previous_vol24h) / dt_hours
    rolled_off_estimate = previous_vol24h / 24.0
    return max(0.0, delta_per_hour + rolled_off_estimate)


async def scan_once(
    cfg: AegisConfig,
    conn,
    coingecko: CoinGeckoClient,
    kraken_bases: set[str],
    now_ms: int | None = None,
) -> ScanStats:
    stats = ScanStats()
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    scan_cfg = cfg.scanner

    markets = await coingecko.fetch_top_markets(scan_cfg.top_n_coins)

    usable = [m for m in markets if m.vol24h_usd is not None]
    stats.snapshots = db.insert_market_snapshots(
        conn, now, [m.__dict__ | {"coin_id": m.coin_id} for m in usable]
    )

    baseline_since = now - scan_cfg.average_window_days * 86_400_000
    min_snapshots = scan_cfg.min_history_hours

    for market in usable:
        previous = db.previous_snapshot(
            conn, market.coin_id, before_ms=now, not_older_than_ms=now - 2 * _HOUR_MS
        )
        baseline_avg, baseline_n = db.baseline_vol24h(
            conn, market.coin_id, since_ms=baseline_since, before_ms=now
        )
        if previous is None or baseline_n < min_snapshots or not baseline_avg:
            stats.skipped_no_history += 1
            continue

        prev_ts, prev_vol = previous
        est_1h = estimate_hourly_volume(market.vol24h_usd, prev_vol, now - prev_ts)
        baseline_1h = baseline_avg / 24.0
        if baseline_1h <= 0:
            continue
        multiple = est_1h / baseline_1h
        if multiple < scan_cfg.volume_multiple:
            continue

        variant = classify_variant(
            market.price_change_1h_pct,
            scan_cfg.price_up_threshold_pct,
            scan_cfg.price_down_threshold_pct,
        )
        on_kraken = market.symbol in kraken_bases
        db.insert_scanner_flag(
            conn,
            ts_ms=now,
            coin_id=market.coin_id,
            symbol=market.symbol,
            vol_1h_usd=est_1h,
            vol_avg_1h_usd=baseline_1h,
            volume_multiple=multiple,
            price_change_1h_pct=market.price_change_1h_pct,
            price_change_24h_pct=market.price_change_24h_pct,
            variant=variant,
            on_kraken=on_kraken,
            context_json=json.dumps(
                {
                    "price_usd": market.price_usd,
                    "market_cap_usd": market.market_cap_usd,
                    "baseline_snapshots": baseline_n,
                }
            ),
        )
        stats.flags += 1
        logger.info(
            "volume anomaly flag",
            extra={
                "coin": market.coin_id,
                "symbol": market.symbol,
                "multiple": round(multiple, 2),
                "variant": variant,
                "on_kraken": on_kraken,
            },
        )

    logger.info(
        "scan complete",
        extra={
            "snapshots": stats.snapshots,
            "flags": stats.flags,
            "skipped_no_history": stats.skipped_no_history,
        },
    )
    return stats


async def run(cfg: AegisConfig) -> ScanStats:
    from aegis.core.models import Venue
    from aegis.execution import build_market_data

    conn = db.connect(cfg.sqlite_path)
    coingecko = CoinGeckoClient(api_key=cfg.secrets.coingecko_api_key)
    kraken = build_market_data(Venue.KRAKEN)
    try:
        try:
            kraken_bases = await kraken.fetch_tradable_bases()
        except Exception:
            logger.exception("kraken bases fetch failed; on_kraken will be False")
            kraken_bases = set()
        return await scan_once(cfg, conn, coingecko, kraken_bases)
    finally:
        await coingecko.close()
        await kraken.close()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aegis volume anomaly scanner")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument(
        "--loop", type=int, metavar="SECONDS", help="run continuously every SECONDS"
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.monitoring.log_dir, cfg.monitoring.log_level)

    from aegis.monitor.telegram import notify_crash

    if args.loop:
        while True:
            try:
                asyncio.run(run(cfg))
            except Exception as exc:
                logger.exception("scanner run crashed")
                asyncio.run(notify_crash(cfg, "scanner", exc))
            time.sleep(args.loop)
    else:
        try:
            asyncio.run(run(cfg))
        except Exception as exc:
            asyncio.run(notify_crash(cfg, "scanner", exc))
            raise


if __name__ == "__main__":
    main()
