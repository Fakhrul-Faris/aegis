"""Architecture boundary test (Concept §15, §18).

Strategy, risk, and portfolio code must never import exchange client
libraries directly - only aegis.execution adapters may. This test makes the
rule mechanical instead of aspirational, from day one.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "aegis"

FORBIDDEN_PREFIXES = ("ccxt", "hyperliquid", "websockets", "krakenex", "ib_insync")
GUARDED_PACKAGES = ("strategy", "risk", "portfolio", "data", "monitor", "core", "backtest")


def _imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_only_execution_layer_touches_exchange_libraries():
    violations = []
    for package in GUARDED_PACKAGES:
        for py_file in (SRC / package).rglob("*.py"):
            for name in _imports_of(py_file):
                if name.split(".")[0] in FORBIDDEN_PREFIXES:
                    violations.append(f"{py_file.relative_to(SRC)} imports {name}")
    assert not violations, "Exchange libraries outside aegis.execution:\n" + "\n".join(violations)
