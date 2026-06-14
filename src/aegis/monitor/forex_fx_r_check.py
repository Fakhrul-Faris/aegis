"""FX-R module CLIs — recipe zoo, research goals, gate check."""

from __future__ import annotations

import argparse
import sys

from aegis.research.recipe_compare import compare_recipes, format_recipe_list
from aegis.research.research_goals import add_goal, append_evidence, list_goals, load_goal


def main_recipe_list() -> None:
    print(format_recipe_list())


def main_recipe_list_cli() -> None:
    main_recipe_list()


def main_recipe_compare_cli() -> None:
    raise SystemExit(main_recipe_compare())


def main_research_goal_cli() -> None:
    raise SystemExit(main_research_goal())


def main_fx_r_check_cli() -> None:
    raise SystemExit(main_fx_r_check())


def main_recipe_compare(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare forex recipes (FX-R1)")
    parser.add_argument("recipes", nargs=2, help="recipe ids e.g. event_spike_fade scm")
    parser.add_argument("--null-control", action="store_true")
    args = parser.parse_args(argv)
    print(compare_recipes(args.recipes[0], args.recipes[1], null_control=args.null_control))
    return 0


def main_research_goal(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Research goals (FX-R1)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list goals")
    add_p = sub.add_parser("add")
    add_p.add_argument("hypothesis_id")
    add_p.add_argument("--title", required=True)
    add_p.add_argument("--criteria", required=True)
    add_p.add_argument("--falsifier", required=True)
    add_p.add_argument("--status", default="exploring")

    ev_p = sub.add_parser("evidence")
    ev_p.add_argument("hypothesis_id")
    ev_p.add_argument("note")

    args = parser.parse_args(argv)
    if args.cmd == "list":
        for g in list_goals():
            print(f"{g.hypothesis_id} [{g.status}] — {g.title}")
        return 0
    if args.cmd == "add":
        g = add_goal(args.hypothesis_id, args.title, args.criteria, args.falsifier, status=args.status)
        print(f"saved {g.hypothesis_id}")
        return 0
    if args.cmd == "evidence":
        g = append_evidence(args.hypothesis_id, args.note)
        print(f"evidence count: {len(g.evidence)}")
        return 0
    return 1


def main_fx_r_check() -> int:
    failures: list[str] = []
    print("FX-R infrastructure check")

    try:
        from aegis.research.decision_pipeline import build_entry_proposal

        p = build_entry_proposal(
            pair="EURUSD",
            direction="long",
            stop=1.08,
            target=1.09,
            event_code="US_CPI",
            equity_usd=100.0,
            open_positions=0,
            has_candles=True,
            has_open_position=False,
        )
        if p.signal != "long":
            failures.append("entry proposal should approve sample long")
        print(f"  decision pipeline: OK ({p.stage_reached})")
    except Exception as exc:
        failures.append(f"decision pipeline: {exc}")

    try:
        from aegis.backtest.forex_backtest_grid import run_grid

        r = run_grid(start="2024-01-01", end="2024-03-01", dry_run=True)
        if r.get("mode") != "dry_run":
            failures.append("grid dry-run mode")
        print(f"  backtest grid: OK (run_id={r.get('run_id')})")
    except Exception as exc:
        failures.append(f"backtest grid: {exc}")

    try:
        text = format_recipe_list()
        if "event_spike_fade" not in text:
            failures.append("recipe zoo missing active recipe")
        print("  recipe zoo: OK")
    except Exception as exc:
        failures.append(f"recipe zoo: {exc}")

    if failures:
        print("\nFX-R GATE: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nFX-R GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_fx_r_check())
