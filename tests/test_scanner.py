"""Volume anomaly scanner tests (P0.4) - no network involved."""

import asyncio

import pytest

from aegis.config import load_config
from aegis.data import db
from aegis.data.scanner import (
    VARIANT_PRICE_DOWN,
    VARIANT_PRICE_FLAT,
    VARIANT_PRICE_UP,
    MarketRow,
    classify_variant,
    estimate_hourly_volume,
    scan_once,
)

HOUR_MS = 3_600_000
NOW = 1_700_000_400_000


class FakeCoinGecko:
    def __init__(self, rows: list[MarketRow]):
        self.rows = rows

    async def fetch_top_markets(self, top_n: int) -> list[MarketRow]:
        return self.rows[:top_n]


def _row(coin_id: str, vol24h: float, chg1h: float = 0.5) -> MarketRow:
    return MarketRow(
        coin_id=coin_id,
        symbol=coin_id.upper(),
        price_usd=10.0,
        vol24h_usd=vol24h,
        market_cap_usd=1e9,
        price_change_1h_pct=chg1h,
        price_change_24h_pct=1.0,
    )


def _seed_history(conn, coin_id: str, hours: int, vol24h: float, end_ms: int):
    for i in range(hours, 0, -1):
        db.insert_market_snapshots(
            conn,
            end_ms - i * HOUR_MS,
            [
                {
                    "coin_id": coin_id,
                    "symbol": coin_id.upper(),
                    "price_usd": 10.0,
                    "vol24h_usd": vol24h,
                    "market_cap_usd": 1e9,
                    "price_change_1h_pct": 0.0,
                    "price_change_24h_pct": 0.0,
                }
            ],
        )


@pytest.fixture
def cfg():
    return load_config("config/config.yaml", env_file=None)


# --- Unit pieces -------------------------------------------------------------


def test_classify_variant_boundaries():
    assert classify_variant(6.0, 5.0, -2.0) == VARIANT_PRICE_UP
    assert classify_variant(5.0, 5.0, -2.0) == VARIANT_PRICE_UP
    assert classify_variant(0.0, 5.0, -2.0) == VARIANT_PRICE_FLAT
    assert classify_variant(-1.9, 5.0, -2.0) == VARIANT_PRICE_FLAT
    assert classify_variant(-2.0, 5.0, -2.0) == VARIANT_PRICE_DOWN
    assert classify_variant(None, 5.0, -2.0) == VARIANT_PRICE_FLAT


def test_estimate_hourly_volume_steady_state():
    # Unchanged 24h volume of 2400 -> newest hour ~ rolled-off hour ~ 100/h.
    assert estimate_hourly_volume(2400.0, 2400.0, HOUR_MS) == pytest.approx(100.0)


def test_estimate_hourly_volume_spike():
    # 24h volume jumped 2400 -> 3400: newest hour ~ 1000 + 100 rolled-off.
    assert estimate_hourly_volume(3400.0, 2400.0, HOUR_MS) == pytest.approx(1100.0)


def test_estimate_hourly_volume_never_negative():
    assert estimate_hourly_volume(1000.0, 2400.0, HOUR_MS) == 0.0


# --- End-to-end scan ---------------------------------------------------------


def test_scan_flags_spike_and_skips_quiet_and_new_coins(tmp_path, cfg):
    conn = db.connect(tmp_path / "t.sqlite")

    # 72h of steady history for two coins; none for the brand-new third.
    _seed_history(conn, "steady", hours=72, vol24h=2400.0, end_ms=NOW)
    _seed_history(conn, "spiker", hours=72, vol24h=2400.0, end_ms=NOW)

    current = [
        _row("steady", vol24h=2400.0, chg1h=0.5),
        _row("spiker", vol24h=3400.0, chg1h=8.0),  # est 11x baseline, price +8%
        _row("newcoin", vol24h=9999.0, chg1h=50.0),  # no history -> snapshot only
    ]
    stats = asyncio.run(
        scan_once(cfg, conn, FakeCoinGecko(current), kraken_bases={"SPIKER"}, now_ms=NOW)
    )

    assert stats.snapshots == 3
    assert stats.flags == 1
    assert stats.skipped_no_history == 1

    flags = conn.execute(
        "SELECT coin_id, variant, on_kraken, volume_multiple FROM scanner_flags"
    ).fetchall()
    assert len(flags) == 1
    coin_id, variant, on_kraken, multiple = flags[0]
    assert coin_id == "spiker"
    assert variant == VARIANT_PRICE_UP
    assert on_kraken == 1
    assert multiple == pytest.approx(11.0, rel=0.01)

    # The new coin's snapshot was stored - history starts accumulating now.
    n = conn.execute("SELECT COUNT(*) FROM market_snapshots WHERE coin_id='newcoin'").fetchone()[0]
    assert n == 1


def test_scan_variant_tags_down_move(tmp_path, cfg):
    conn = db.connect(tmp_path / "t.sqlite")
    _seed_history(conn, "dumper", hours=72, vol24h=2400.0, end_ms=NOW)

    stats = asyncio.run(
        scan_once(
            cfg,
            conn,
            FakeCoinGecko([_row("dumper", vol24h=3400.0, chg1h=-6.0)]),
            kraken_bases=set(),
            now_ms=NOW,
        )
    )
    assert stats.flags == 1
    variant = conn.execute("SELECT variant FROM scanner_flags").fetchone()[0]
    assert variant == VARIANT_PRICE_DOWN


def test_no_flags_below_multiple(tmp_path, cfg):
    conn = db.connect(tmp_path / "t.sqlite")
    _seed_history(conn, "mild", hours=72, vol24h=2400.0, end_ms=NOW)

    # 24h volume up only 100 -> est 200/h vs baseline 100/h = 2x < 3x threshold.
    stats = asyncio.run(
        scan_once(
            cfg,
            conn,
            FakeCoinGecko([_row("mild", vol24h=2500.0)]),
            kraken_bases=set(),
            now_ms=NOW,
        )
    )
    assert stats.flags == 0
