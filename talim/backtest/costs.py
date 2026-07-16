"""Standardised trading-cost assumptions for backtests (BR-05 / WP-86).

The on_bar engine historically simulated frictionless fills at signal
prices. This module adds a per-venue/per-instrument cost model so backtest
results stop overstating edge on spread-quoted CFD venues:

- ``spread_points``: full bid/ask spread in instrument points. Bar data is
  treated as mid, so each fill pays half the spread (buy at mid + spread/2,
  sell at mid - spread/2).
- ``slippage_points``: additional adverse points per fill on top of the
  half-spread. One conservative knob for both entries and stop/target exits.
- ``commission_per_side``: flat account-currency commission per fill. Zero
  for the current spread-only index CFDs; present for future venues.

Standard assumption values live in ``config/backtest_costs.json`` keyed by
venue then canonical instrument id. Loading an unknown venue/instrument
fails loudly (same philosophy as the WP-73 data-loader hardening) rather
than silently running frictionless.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_COSTS_PATH = Path("config/backtest_costs.json")


@dataclass(frozen=True, slots=True)
class BacktestCostConfig:
    """Per-trade cost assumptions applied by the backtest engine."""

    spread_points: float = 0.0
    slippage_points: float = 0.0
    commission_per_side: float = 0.0
    source: str = ""

    def __post_init__(self) -> None:
        if self.spread_points < 0:
            raise ValueError("spread_points must be >= 0")
        if self.slippage_points < 0:
            raise ValueError("slippage_points must be >= 0")
        if self.commission_per_side < 0:
            raise ValueError("commission_per_side must be >= 0")

    @property
    def per_fill_points(self) -> float:
        """Adverse price adjustment applied to every fill, in points."""
        return self.spread_points / 2.0 + self.slippage_points

    def entry_fill(self, price: float, side: str) -> float:
        """Fill price for opening a position at mid ``price``."""
        adj = self.per_fill_points
        return price + adj if side == "long" else price - adj

    def exit_fill(self, price: float, side: str) -> float:
        """Fill price for closing a position opened on ``side``."""
        adj = self.per_fill_points
        return price - adj if side == "long" else price + adj

    def round_trip_commission(self, qty: float) -> float:
        """Flat commission for one entry + one exit at quantity ``qty``."""
        return 2.0 * self.commission_per_side * qty

    def to_dict(self) -> dict:
        return {
            "spread_points": self.spread_points,
            "slippage_points": self.slippage_points,
            "commission_per_side": self.commission_per_side,
            "source": self.source,
        }


ZERO_COSTS = BacktestCostConfig(source="frictionless")


def load_cost_config(
    venue: str,
    instrument: str,
    path: str | Path = DEFAULT_COSTS_PATH,
) -> BacktestCostConfig:
    """Load the standardised cost assumptions for ``venue``/``instrument``.

    Raises ``ValueError`` when the venue or instrument has no entry so a
    typo cannot silently produce a frictionless backtest.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"cost config not found: {path}")
    data = json.loads(path.read_text())
    venues = data.get("venues", {})
    if venue not in venues:
        raise ValueError(
            f"no cost assumptions for venue '{venue}' in {path}; "
            f"known venues: {sorted(venues)}"
        )
    instruments = venues[venue].get("instruments", {})
    if instrument not in instruments:
        raise ValueError(
            f"no cost assumptions for instrument '{instrument}' on venue "
            f"'{venue}' in {path}; known instruments: {sorted(instruments)}"
        )
    entry = instruments[instrument]
    return BacktestCostConfig(
        spread_points=float(entry.get("spread_points", 0.0)),
        slippage_points=float(entry.get("slippage_points", 0.0)),
        commission_per_side=float(entry.get("commission_per_side", 0.0)),
        source=f"{venue}/{instrument}@{path}",
    )
