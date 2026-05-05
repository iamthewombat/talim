"""Position sizing helpers for backtests.

The live engine can keep its own broker/risk sizing path; this module is for
making historical simulations less misleading than the old implicit 1-unit
position size.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BacktestSizingConfig:
    """Controls how each simulated backtest trade is sized.

    Modes:
    - ``fixed_qty``: every accepted trade uses ``fixed_qty``.
    - ``risk_pct``: quantity is based on the configured fraction of available
      capital divided by entry-to-stop risk.

    ``compound`` only affects ``risk_pct`` mode. When true, realised PnL changes
    the available capital used for later trades.
    """

    initial_capital: float = 100_000.0
    mode: str = "fixed_qty"
    fixed_qty: float = 1.0
    risk_per_trade_pct: float = 0.01
    max_position_qty: float | None = None
    max_total_exposure: float | None = None
    compound: bool = True

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.mode not in {"fixed_qty", "risk_pct"}:
            raise ValueError("sizing mode must be 'fixed_qty' or 'risk_pct'")
        if self.fixed_qty <= 0:
            raise ValueError("fixed_qty must be positive")
        if not (0 < self.risk_per_trade_pct <= 1):
            raise ValueError("risk_per_trade_pct must be in (0, 1]")
        if self.max_position_qty is not None and self.max_position_qty <= 0:
            raise ValueError("max_position_qty must be positive when set")
        if self.max_total_exposure is not None and self.max_total_exposure <= 0:
            raise ValueError("max_total_exposure must be positive when set")


def size_trade(
    *,
    entry_price: float,
    stop_price: float,
    available_capital: float,
    config: BacktestSizingConfig,
) -> float:
    """Return the simulated quantity for a trade, or 0 if it cannot be sized."""
    if available_capital <= 0:
        return 0.0

    if config.mode == "fixed_qty":
        qty = config.fixed_qty
    else:
        unit_risk = abs(entry_price - stop_price)
        if unit_risk <= 0:
            return 0.0
        risk_budget = available_capital * config.risk_per_trade_pct
        qty = risk_budget / unit_risk

    if config.max_position_qty is not None:
        qty = min(qty, config.max_position_qty)

    if config.max_total_exposure is not None:
        price = abs(entry_price)
        if price <= 0:
            return 0.0
        qty = min(qty, config.max_total_exposure / price)

    return max(0.0, float(qty))
