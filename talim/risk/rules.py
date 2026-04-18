"""Configurable risk rules (WP-17).

A `RiskRules` instance is loaded from JSON / YAML / dict and consumed by the
`risk_check` node. All values are absolute units of the account currency
unless suffixed with `_pct` (fraction of equity).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


# Instruments that move together — used for correlation checks. Each entry
# lists symbols that should not stack on top of each other in the same
# direction without explicit override.
CORRELATION_GROUPS: list[set[str]] = [
    {"ES", "NQ", "YM", "RTY"},      # US equity index futures
    {"GC", "SI"},                    # precious metals
    {"CL", "NG", "RB"},              # energy
    {"6E", "6B", "6J"},              # G10 FX futures
]


@dataclass
class RiskRules:
    max_position_qty: float = 5.0
    max_total_exposure: float = 100_000.0   # sum(|qty * entry_price|) cap
    max_daily_drawdown: float = -2_000.0    # negative number
    max_correlated_positions: int = 1       # incl. the pending one
    max_margin_utilization_pct: float = 1.0
    cfd_financing_annual_rate: float = 0.08
    enforce_cfd_session_windows: bool = True
    block_on_existing_same_instrument: bool = True
    correlation_groups: list[set[str]] = field(default_factory=lambda: [set(g) for g in CORRELATION_GROUPS])

    @classmethod
    def from_dict(cls, d: dict) -> "RiskRules":
        data = dict(d)
        if "correlation_groups" in data:
            data["correlation_groups"] = [set(g) for g in data["correlation_groups"]]
        return cls(**data)


DEFAULT_RULES = RiskRules()


def load_rules(path: str | Path | None = None) -> RiskRules:
    """Load rules from a JSON file. Returns defaults if path is None/missing."""
    if path is None:
        return DEFAULT_RULES
    p = Path(path)
    if not p.exists():
        return DEFAULT_RULES
    return RiskRules.from_dict(json.loads(p.read_text()))
