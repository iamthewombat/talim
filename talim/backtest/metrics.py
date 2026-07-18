"""Performance metrics for backtests (WP-12)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


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


_EMPTY_EQUITY_METRICS = {
    "annualised_sharpe": 0.0,
    "annualised_sortino": 0.0,
    "max_drawdown_pct": 0.0,
    "yearly_pnl": {},
    "profitable_years_frac": 0.0,
    "max_year_contribution": 0.0,
}


def compute_equity_metrics(
    equity_curve: list[tuple], initial_capital: float
) -> dict:
    """Scorecard metrics from a per-bar mark-to-market equity curve.

    `equity_curve` is [(timestamp, cumulative_pnl), ...] marked at every bar
    close (realised + unrealised). Returns annualised Sharpe/Sortino from
    daily equity changes over `initial_capital` (arithmetic, includes flat
    days inside the tested window), max drawdown as a fraction of capital,
    and a calendar-year P&L breakdown.
    """
    if not equity_curve or initial_capital <= 0:
        return dict(_EMPTY_EQUITY_METRICS)

    df = pd.DataFrame(equity_curve, columns=["timestamp", "equity"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    daily = df.groupby(df["timestamp"].dt.date)["equity"].last()
    if len(daily) < 2:
        return dict(_EMPTY_EQUITY_METRICS)

    changes = daily.diff()
    changes.iloc[0] = daily.iloc[0]
    returns = changes.to_numpy(dtype=np.float64) / initial_capital

    mean = float(returns.mean())
    std = float(returns.std(ddof=1))
    ann_sharpe = float(mean / std * np.sqrt(TRADING_DAYS_PER_YEAR)) if std > 0 else 0.0
    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    ann_sortino = (
        float(mean / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR))
        if downside_std > 0
        else 0.0
    )

    equity_arr = daily.to_numpy(dtype=np.float64)
    peak = np.maximum.accumulate(equity_arr)
    max_dd_pct = float((equity_arr - peak).min() / initial_capital)

    years = pd.Series(changes.values, index=pd.to_datetime(daily.index))
    yearly = years.groupby(years.index.year).sum()
    yearly_pnl = {int(y): round(float(v), 2) for y, v in yearly.items()}
    profitable_years_frac = float((yearly > 0).mean()) if len(yearly) else 0.0
    total = float(yearly.sum())
    max_year_contribution = (
        float(yearly.max() / total) if total > 0 and yearly.max() > 0 else 0.0
    )

    return {
        "annualised_sharpe": ann_sharpe,
        "annualised_sortino": ann_sortino,
        "max_drawdown_pct": max_dd_pct,
        "yearly_pnl": yearly_pnl,
        "profitable_years_frac": profitable_years_frac,
        "max_year_contribution": max_year_contribution,
    }
