"""Recipe zoo compare — head-to-head + null control (FX-R1)."""

from __future__ import annotations

from dataclasses import dataclass

from aegis.config_forex import ForexConfig, load_forex_config
from aegis.strategy.forex_strategy_registry import REGISTRY, ForexStrategySpec


@dataclass(frozen=True)
class RecipeSummary:
    recipe_id: str
    status: str
    edge_type: str
    hypothesis: str
    falsifier: str


def list_recipes() -> list[RecipeSummary]:
    out: list[RecipeSummary] = []
    for spec in REGISTRY.values():
        out.append(
            RecipeSummary(
                recipe_id=spec.strategy_id,
                status=spec.status,
                edge_type=spec.edge_type.value,
                hypothesis=spec.hypothesis,
                falsifier=spec.falsifier,
            )
        )
    return sorted(out, key=lambda r: (r.status != "active", r.recipe_id))


def format_recipe_list(cfg: ForexConfig | None = None) -> str:
    cfg = cfg or load_forex_config()
    lines = ["Aegis Forex Recipe Zoo", f"Active: {cfg.active_strategy}", ""]
    for r in list_recipes():
        marker = "*" if r.recipe_id == cfg.active_strategy else " "
        lines.append(f"{marker} {r.recipe_id} [{r.status}] — {r.edge_type}")
        lines.append(f"    {r.hypothesis[:90]}...")
    return "\n".join(lines)


def compare_recipes(a: str, b: str, *, null_control: bool = False) -> str:
    spec_a = REGISTRY.get(a)
    spec_b = REGISTRY.get(b)
    if spec_a is None or spec_b is None:
        missing = [x for x, s in ((a, spec_a), (b, spec_b)) if s is None]
        raise KeyError(f"unknown recipe(s): {', '.join(missing)}")

    lines = [
        f"Recipe compare: {a} vs {b}",
        "",
        f"{a}: {spec_a.status} | {spec_a.edge_type.value}",
        f"  hypothesis: {spec_a.hypothesis}",
        f"  falsifier:  {spec_a.falsifier}",
        "",
        f"{b}: {spec_b.status} | {spec_b.edge_type.value}",
        f"  hypothesis: {spec_b.hypothesis}",
        f"  falsifier:  {spec_b.falsifier}",
        "",
        "Gate: run walk-forward on both with identical cost model, then:",
        "  aegis-backtest-forex-realistic (frozen params)",
        "  aegis-backtest-forex-grid --dry-run (harness check)",
    ]
    if null_control:
        lines.extend(
            [
                "",
                "Null control: random-entry baseline on same calendar windows.",
                "Candidate must beat null on expectancy CI lower bound.",
            ]
        )
    return "\n".join(lines)


def get_spec(recipe_id: str) -> ForexStrategySpec:
    spec = REGISTRY.get(recipe_id)
    if spec is None:
        raise KeyError(recipe_id)
    return spec
