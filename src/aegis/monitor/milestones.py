"""Milestone Telegram notifications (P2.4) — informational, never hard-stop trading."""

from __future__ import annotations

from aegis.config import AegisConfig


async def notify_milestone(cfg: AegisConfig, headline: str, detail: str = "") -> bool:
    from aegis.monitor.telegram import notifier_from_config

    text = f"Aegis milestone — {headline}"
    if detail:
        text += f"\n{detail}"
    notifier = notifier_from_config(cfg)
    try:
        return await notifier.send(text)
    finally:
        await notifier.close()


async def notify_m1_passed(cfg: AegisConfig, *, span_hours: float, flag_count: int) -> bool:
    return await notify_milestone(
        cfg,
        "M1 gate PASSED",
        f"Collection span: {span_hours:.1f}h\nScanner flags: {flag_count}\nMark checklist in Tasks & Milestones.",
    )


async def notify_breaker_drill_passed(cfg: AegisConfig, result) -> bool:
    return await notify_milestone(
        cfg,
        "M4 breaker drill PASSED",
        "Daily halt blocked trading; manual resume cleared halt; kill switch requires restart.",
    )


async def notify_soak_verdict(
    cfg: AegisConfig,
    *,
    passed: bool,
    elapsed_days: float,
    spreads_ok: int,
    spreads_fail: int,
    anomalies: int,
) -> bool:
    verdict = "PASS" if passed else "NEEDS REVIEW"
    return await notify_milestone(
        cfg,
        f"M4 soak verdict: {verdict}",
        (
            f"Elapsed: {elapsed_days:.1f} days\n"
            f"Spreads: {spreads_ok} ok / {spreads_fail} fail\n"
            f"Anomalies: {anomalies}"
        ),
    )
