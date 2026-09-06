"""Import installed artifacts, never silently validate checkout-shadowed modules.

Run using the installed environment's Python -I from outside the source tree.
This imports definitions only; it never constructs a graph or contacts a provider.
"""

from __future__ import annotations

import importlib
import json
import sysconfig
from pathlib import Path

MODULES = (
    "tradingagents",
    "mytradingalpha",
    "mytradingalpha.contracts",
    "mytradingalpha.contracts.research",
    "mytradingalpha.ops.config",
    "mytradingalpha.data.bundle",
    "mytradingalpha.data.replay_guard",
    "mytradingalpha.research.cached_response",
    "mytradingalpha.research.evidence_tools",
    "mytradingalpha.research.notes",
    "mytradingalpha.research.tradingagents_adapter",
    "tradingagents.graph.historical",
    "cli.main",
)


def check_modules(names: tuple[str, ...] = MODULES) -> dict[str, str]:
    """Fail if a requested module is missing or originates outside this install."""
    roots = {Path(sysconfig.get_path(kind)).resolve() for kind in ("purelib", "platlib")}
    origins = {}
    for name in names:
        module = importlib.import_module(name)
        origin = getattr(module, "__file__", None)
        if not origin or not any(Path(origin).resolve().is_relative_to(root) for root in roots):
            raise RuntimeError(f"module {name!r} is outside installed site-packages: {origin!r}")
        origins[name] = str(Path(origin).resolve())
    return origins


if __name__ == "__main__":
    print(json.dumps(check_modules(), sort_keys=True, indent=2))
