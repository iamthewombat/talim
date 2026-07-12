"""Performance metrics for backtests (WP-12)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Trade:
    side: str            # "long" | "short"
    entry_price: float   # fill price (already includes spread/slippage if modelled)
    exit_price: float
    qty: float = 1.0
    fees: float = 0.0    # flat account-currency costs (commissions), subtracted from pnl

    @property
    def pnl(self) -> float:
        direction = 1.0 if self.side == "long" else -1.0
        return (self.exit_price - self.entry_price) * direction * self.qty - self.fees


def compute_metrics(trades: list[Trade]) -> dict:
    """Compute summary performance metrics for a backtest.

    Sharpe/Sortino are computed on per-trade returns (not annualised) — adequate
    for PoC ranking. Max drawdown is the worst trough on the cumulative PnL
    curve. Profit factor is gross wins divided by gross losses.
    """
    if not trades:
        return {
            "net_pnl": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_trades": 0,
        }

    pnls = np.array([t.pnl for t in trades], dtype=np.float64)
    net = float(pnls.sum())

    mean = float(pnls.mean())
    std = float(pnls.std(ddof=1)) if len(pnls) > 1 else 0.0
    sharpe = float(mean / std) if std > 0 else 0.0
    downside = pnls[pnls < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = float(mean / downside_std) if downside_std > 0 else 0.0

    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = equity - peak
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0

    wins = int((pnls > 0).sum())
    win_rate = float(wins / len(pnls))
    gross_wins = float(pnls[pnls > 0].sum())
    gross_losses = abs(float(pnls[pnls < 0].sum()))
    profit_factor = float(gross_wins / gross_losses) if gross_losses > 0 else (gross_wins if gross_wins > 0 else 0.0)

    return {
        "net_pnl": net,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": len(trades),
    }
