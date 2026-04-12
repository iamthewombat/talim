"""Risk config loader with validation (WP-39)."""

from __future__ import annotations

import json
from pathlib import Path

from talim.risk.rules import RiskRules

REQUIRED_FIELDS = {
    "max_position_qty",
    "max_total_exposure",
    "max_daily_drawdown",
    "max_correlated_positions",
}


class RiskConfigError(ValueError):
    """Raised when a risk config file is invalid."""


def validate_config(data: dict) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: list[str] = []

    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        errors.append(f"missing required fields: {sorted(missing)}")

    if "max_position_qty" in data:
        v = data["max_position_qty"]
        if not isinstance(v, (int, float)) or v <= 0:
            errors.append(f"max_position_qty must be a positive number, got {v!r}")

    if "max_total_exposure" in data:
        v = data["max_total_exposure"]
        if not isinstance(v, (int, float)) or v <= 0:
            errors.append(f"max_total_exposure must be a positive number, got {v!r}")

    if "max_daily_drawdown" in data:
        v = data["max_daily_drawdown"]
        if not isinstance(v, (int, float)) or v >= 0:
            errors.append(f"max_daily_drawdown must be a negative number, got {v!r}")

    if "max_correlated_positions" in data:
        v = data["max_correlated_positions"]
        if not isinstance(v, int) or v < 0:
            errors.append(f"max_correlated_positions must be a non-negative int, got {v!r}")

    if "correlation_groups" in data:
        v = data["correlation_groups"]
        if not isinstance(v, list):
            errors.append("correlation_groups must be a list of lists")
        elif not all(isinstance(g, list) for g in v):
            errors.append("each correlation group must be a list of strings")

    return errors


def load_validated_config(path: str | Path) -> RiskRules:
    """Load and validate a risk config JSON file.

    Raises RiskConfigError on validation failure or missing file.
    """
    p = Path(path)
    if not p.exists():
        raise RiskConfigError(f"config file not found: {p}")

    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise RiskConfigError(f"invalid JSON: {e}") from e

    errors = validate_config(data)
    if errors:
        raise RiskConfigError(f"validation failed: {'; '.join(errors)}")

    return RiskRules.from_dict(data)
