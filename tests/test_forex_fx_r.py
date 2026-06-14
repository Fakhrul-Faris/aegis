"""Tests for FX-R research infrastructure."""

from __future__ import annotations

import json

from aegis.data.as_of import assert_bar_before_as_of, parse_as_of
from aegis.research.adversarial_review import review_event_spike_entry
from aegis.research.decision_pipeline import build_entry_proposal, build_skip_proposal
from aegis.research.recipe_compare import compare_recipes, list_recipes
from aegis.research.research_goals import add_goal, append_evidence, list_goals
from aegis.research.run_manifest import start_run, complete_run
from aegis.backtest.forex_backtest_grid import run_grid


def test_adversarial_approves_clean_entry():
    v = review_event_spike_entry(
        pair="EURUSD",
        direction="long",
        has_candles=True,
        has_open_position=False,
    )
    assert v.approved
    assert v.confidence > 0.5


def test_entry_proposal_includes_pipeline_context():
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
    ctx = p.to_context()
    assert "proposal" in ctx
    assert ctx["proposal"]["signal"] == "long"
    assert ctx["situation"]["pair"] == "EURUSD"


def test_skip_proposal():
    p = build_skip_proposal(
        pair="GBPUSD",
        reason="no_candles",
        equity_usd=100.0,
        open_positions=0,
    )
    assert p.signal == "skip"
    assert "no_candles" in p.against_points


def test_as_of_parse_and_guard():
    as_of = parse_as_of("2024-06-01")
    assert as_of is not None
    from datetime import datetime, UTC

    bar = datetime(2024, 5, 31, 12, tzinfo=UTC)
    assert_bar_before_as_of(bar, as_of)
    try:
        assert_bar_before_as_of(datetime(2024, 6, 2, tzinfo=UTC), as_of)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_recipe_zoo_lists_active():
    recipes = list_recipes()
    ids = {r.recipe_id for r in recipes}
    assert "event_spike_fade" in ids
    text = compare_recipes("event_spike_fade", "scm", null_control=True)
    assert "Null control" in text


def test_research_goal_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("aegis.research.research_goals.GOALS_DIR", tmp_path)
    add_goal(
        "H11d-1",
        title="test",
        acceptance_criteria="3/3 OOS",
        falsifier="fail 2 windows",
    )
    append_evidence("H11d-1", "sweep run 1")
    goals = list_goals()
    assert len(goals) == 1
    assert goals[0].evidence == ["sweep run 1"]


def test_run_manifest_and_grid_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr("aegis.research.run_manifest.RUNS_DIR", tmp_path / "runs")
    run_dir, manifest = start_run("test_pipeline", hypothesis_id="H11c-3")
    assert manifest.run_id
    complete_run(run_dir, {"ok": True})
    data = json.loads((run_dir / "manifest.json").read_text())
    assert data["status"] == "complete"

    monkeypatch.setattr("aegis.research.run_manifest.RUNS_DIR", tmp_path / "runs")
    result = run_grid(start="2024-01-01", end="2024-02-01", dry_run=True)
    assert result["mode"] == "dry_run"
    assert result["dates"] >= 1
