"""Import and packaging smoke tests for the production namespace skeleton."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAMES = (
    "mytradingalpha",
    "mytradingalpha.contracts",
    "mytradingalpha.data",
    "mytradingalpha.research",
    "mytradingalpha.quant",
    "mytradingalpha.portfolio",
    "mytradingalpha.risk",
    "mytradingalpha.backtest",
    "mytradingalpha.execution",
    "mytradingalpha.experiments",
    "mytradingalpha.ops",
)


def test_production_namespace_packages_import() -> None:
    for package_name in PACKAGE_NAMES:
        module = importlib.import_module(package_name)
        assert module.__doc__, package_name


def test_initializers_contain_only_module_docstrings() -> None:
    for package_name in PACKAGE_NAMES:
        initializer = REPOSITORY_ROOT / Path(*package_name.split(".")) / "__init__.py"
        tree = ast.parse(initializer.read_text(encoding="utf-8"), filename=str(initializer))
        assert len(tree.body) == 1, initializer
        assert isinstance(tree.body[0], ast.Expr), initializer
        assert isinstance(tree.body[0].value, ast.Constant), initializer
        assert isinstance(tree.body[0].value.value, str), initializer


def test_setuptools_discovers_production_namespace() -> None:
    pyproject = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'include = ["tradingagents*", "mytradingalpha*", "cli*"]' in pyproject


def test_existing_public_imports_remain_available() -> None:
    importlib.import_module("tradingagents")
    importlib.import_module("cli.main")
