"""Tests for the Monte Carlo equity-curve bootstrap."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from talim.backtest.metrics import compute_equity_metrics
from talim.backtest.monte_carlo import (
    daily_equity_changes,
    monte_carlo_summary,
    stationary_bootstrap_indices,
)


def _curve(daily_pnls: list[float]) -> list[tuple]:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    cum = 0.0
    curve = []
    for i, pnl in enumerate(daily_pnls):
        cum += pnl
        curve.append((start + timedelta(days=i), cum))
    return curve


class TestDailyEquityChanges:
    def test_matches_equity_metrics_convention(self):
        curve = _curve([10.0, -5.0, 3.0, 0.0, 7.0])
        changes = daily_equity_changes(curve)
        assert changes.tolist() == [10.0, -5.0, 3.0, 0.0, 7.0]

    def test_intraday_bars_collapse_to_last_per_day(self):
        ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
        curve = [
            (ts, 5.0),
            (ts + timedelta(hours=6), 8.0),
            (ts + timedelta(days=1), 2.0),
        ]
        changes = daily_equity_changes(curve)
        assert changes.tolist() == [8.0, -6.0]

    def test_empty_curve(self):
        assert daily_equity_changes([]).size == 0


class TestStationaryBootstrapIndices:
    def test_length_and_range(self):
        rng = np.random.default_rng(0)
        idx = stationary_bootstrap_indices(500, 20.0, rng)
        assert len(idx) == 500
        assert idx.min() >= 0 and idx.max() < 500

    def test_blocks_are_consecutive_runs(self):
        rng = np.random.default_rng(1)
        idx = stationary_bootstrap_indices(1000, 50.0, rng)
        consecutive = sum(
            1 for a, b in zip(idx, idx[1:]) if b == (a + 1) % 1000
        )
        # mean block 50 -> ~98% of steps continue the block
        assert consecutive > 900


class TestMonteCarloSummary:
    def test_seed_reproducible(self):
        curve = _curve(list(np.random.default_rng(3).normal(1.0, 10.0, 300)))
        a = monte_carlo_summary(curve, 100_000, n_sims=50, seed=42)
        b = monte_carlo_summary(curve, 100_000, n_sims=50, seed=42)
        assert a == b

    def test_all_positive_days_have_zero_drawdown_everywhere(self):
        curve = _curve([5.0] * 100)
        s = monte_carlo_summary(curve, 100_000, n_sims=100, seed=1)
        assert s["max_dd_pct"]["p5"] == 0.0
        assert s["max_dd_pct"]["p95"] == 0.0
        assert s["prob_net_pnl_below_0"] == 0.0

    def test_percentiles_ordered(self):
        curve = _curve(list(np.random.default_rng(5).normal(0.5, 20.0, 400)))
        s = monte_carlo_summary(curve, 100_000, n_sims=200, seed=2)
        for metric in ("net_pnl", "annualised_sharpe", "max_dd_pct"):
            vals = [s[metric][f"p{p}"] for p in (5, 25, 50, 75, 95)]
            assert vals == sorted(vals)

    def test_observed_matches_scorecard_metrics(self):
        curve = _curve(list(np.random.default_rng(7).normal(1.0, 15.0, 250)))
        s = monte_carlo_summary(curve, 100_000, n_sims=10, seed=3)
        em = compute_equity_metrics(curve, 100_000)
        assert s["observed"]["annualised_sharpe"] == pytest.approx(
            em["annualised_sharpe"], abs=1e-4
        )
        assert s["observed"]["max_dd_pct"] == pytest.approx(
            em["max_drawdown_pct"], abs=1e-6
        )

    def test_losing_series_flagged(self):
        curve = _curve(list(np.random.default_rng(9).normal(-2.0, 5.0, 300)))
        s = monte_carlo_summary(curve, 100_000, n_sims=100, seed=4)
        assert s["prob_net_pnl_below_0"] > 0.95
        assert s["prob_sharpe_below_0"] > 0.95

    def test_too_short_curve(self):
        assert "error" in monte_carlo_summary(_curve([1.0]), 100_000)
