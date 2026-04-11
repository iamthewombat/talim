"""Dynamic strategy loader — imports strategy classes from the strategies/ directory."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from talim.strategy.base import BaseStrategy

# Root of the strategies directory (project_root/strategies/)
_STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent / "strategies"


def load_strategy(name: str, strategies_dir: Path | None = None) -> BaseStrategy:
    """Load a strategy by name from strategies/{name}/strategy.py.

    The module must define a class that subclasses BaseStrategy.

    Args:
        name: Strategy directory name (e.g. 'momentum-ES').
        strategies_dir: Override for the strategies root directory.

    Returns:
        An instance of the strategy.
    """
    root = strategies_dir or _STRATEGIES_DIR
    module_path = root / name / "strategy.py"

    if not module_path.exists():
        raise FileNotFoundError(f"Strategy module not found: {module_path}")

    # Build a unique module name to avoid collisions
    module_name = f"talim_strategies.{name.replace('-', '_')}"

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module spec from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Find the BaseStrategy subclass in the module
    strategy_cls = None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, BaseStrategy)
            and attr is not BaseStrategy
        ):
            strategy_cls = attr
            break

    if strategy_cls is None:
        raise TypeError(f"No BaseStrategy subclass found in {module_path}")

    return strategy_cls()
