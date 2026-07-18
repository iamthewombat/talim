"""Monte Carlo resampling of backtest equity curves.

Stationary block bootstrap (Politis & Romano 1994) on daily equity changes:
resampled paths are built from random-length blocks of consecutive days
(geometric length, mean `mean_block_days`), preserving short-range volatility
clustering that naive per-day/per-trade shuffling destroys. The bootstrap
recycles the observed days — it quantifies path risk (drawdown and Sharpe
dispersion) around an edge, it cannot validate the edge itself.

Daily aggregation, Sharpe and drawdown definitions match
`metrics.compute_equity_metrics` so percentiles are comparable with the
scorecard's observed values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from talim.backtest.metrics import TRADING_DAYS_PER_YEAR

PERCENTILES = (5, 25, 50, 75, 95)


def daily_equity_changes(equity_curve: list[tuple]) -> np.ndarray:
    """Per-day equity changes from a per-bar mark-to-market curve.

    Same convention as `compute_equity_metrics`: last equity value per
    calendar date; the first day's change is its full cumulative P&L.
    """
    if not equity_curve:
        return np.empty(0, dtype=np.float64)
    df = pd.DataFrame(equity_curve, columns=["timestamp", "equity"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    daily = df.groupby(df["timestamp"].dt.date)["equity"].last()
    changes = daily.diff()
    changes.iloc[0] = daily.iloc[0]
    return changes.to_numpy(dtype=np.float64)


def stationary_bootstrap_indices(
    n_days: int, mean_block_days: float, rng: np.random.Generator
) -> np.ndarray:
    """One resampled index path of length `n_days` (blocks wrap around)."""
    p = 1.0 / mean_block_days
    idx = np.empty(n_days, dtype=np.int64)
    restart = rng.random(n_days) < p
    jumps = rng.integers(0, n_days, size=n_days)
    idx[0] = jumps[0]
    for t in range(1, n_days):
        idx[t] = jumps[t] if restart[t] else (idx[t - 1] + 1) % n_days
    return idx


def _path_metrics(changes: np.ndarray, initial_capital: float) -> tuple[float, float, float]:
    cum = np.cumsum(changes)
    peak = np.maximum.accumulate(cum)
    max_dd_pct = float(np.minimum(cum - peak, 0.0).min() / initial_capital)
    returns = changes / initial_capital
    std = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)) if std > 0 else 0.0
    return float(cum[-1]), sharpe, max_dd_pct


def monte_carlo_summary(
    equity_curve: list[tuple],
    initial_capital: float,
    n_sims: int = 2000,
    mean_block_days: float = 20.0,
    seed: int | None = 7,
) -> dict:
    """Bootstrap distributions of net P&L, annualised Sharpe and max drawdown.

    Returns observed metrics plus per-metric percentiles (PERCENTILES) and
    tail probabilities. For drawdown the 5th percentile is the bad tail
    (most negative); `max_dd_pct_p5` is the number to size risk against.
    """
    changes = daily_equity_changes(equity_curve)
    if len(changes) < 2 or initial_capital <= 0:
        return {"error": "need at least 2 days of equity history"}

    rng = np.random.default_rng(seed)
    n = len(changes)
    nets = np.empty(n_sims)
    sharpes = np.empty(n_sims)
    dds = np.empty(n_sims)
    for i in range(n_sims):
        idx = stationary_bootstrap_indices(n, mean_block_days, rng)
        nets[i], sharpes[i], dds[i] = _path_metrics(changes[idx], initial_capital)

    obs_net, obs_sharpe, obs_dd = _path_metrics(changes, initial_capital)

    def pct(arr: np.ndarray) -> dict:
        return {f"p{p}": round(float(np.percentile(arr, p)), 6) for p in PERCENTILES}

    return {
        "n_sims": n_sims,
        "n_days": n,
        "mean_block_days": mean_block_days,
        "seed": seed,
        "observed": {
            "net_pnl": round(obs_net, 2),
            "annualised_sharpe": round(obs_sharpe, 4),
            "max_dd_pct": round(obs_dd, 6),
        },
        "net_pnl": pct(nets),
        "annualised_sharpe": pct(sharpes),
        "max_dd_pct": pct(dds),
        "prob_net_pnl_below_0": round(float((nets <= 0).mean()), 4),
        "prob_sharpe_below_0": round(float((sharpes <= 0).mean()), 4),
    }
