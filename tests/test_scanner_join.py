"""Scanner join tests."""

from aegis.data import db
from aegis.data.scanner_join import has_anomaly_in_window, latest_anomaly_in_window


def test_flag_in_4h_window(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    bar_open = 1_700_000_000_000
    db.insert_scanner_flag(
        conn,
        ts_ms=bar_open + 3_600_000,
        coin_id="bitcoin",
        symbol="BTC",
        vol_1h_usd=1e6,
        vol_avg_1h_usd=1e5,
        volume_multiple=10.0,
        price_change_1h_pct=6.0,
        price_change_24h_pct=12.0,
        variant="price_up_5",
        on_kraken=True,
        context_json="{}",
    )
    assert has_anomaly_in_window(conn, "BTC", bar_open, "4h")
    assert not has_anomaly_in_window(conn, "BTC", bar_open + 14_400_000, "4h")

    latest = latest_anomaly_in_window(conn, "BTC", bar_open, "4h")
    assert latest is not None
    assert latest.volume_multiple == 10.0
