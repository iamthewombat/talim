"""Performance metrics for backtests (WP-12)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Trade:
    side: str            # "long" | "short"
    entry_price: float
    exit_price: float
    qty: float = 1.0

    @property
    def pnl(self) -> float:
        direction = 1.0 if self.side == "long" else -1.0
        return (self.exit_price - self.entry_price) * direction * self.qty


def compute_metrics(trades: list[Trade]) -> dict:
    """Compute net_pnl, sharpe, max_drawdown, win_rate, total_trades.

    Sharpe is computed on per-trade returns (not annualised) — adequate for
    PoC ranking. Max drawdown is the worst trough on the cumulative PnL curve.
    """
    if not trades:
        return {
            "net_pnl": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "total_trades": 0,
        }

    pnls = np.array([t.pnl for t in trades], dtype=np.float64)
    net = float(pnls.sum())

    mean = float(pnls.mean())
    std = float(pnls.std(ddof=1)) if len(pnls) > 1 else 0.0
    sharpe = float(mean / std) if std > 0 else 0.0

    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = equity - peak
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0

    wins = int((pnls > 0).sum())
    win_rate = float(wins / len(pnls))

    return {
        "net_pnl": net,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "total_trades": len(trades),
    }
