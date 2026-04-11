"""Tests for the strategy framework."""

import inspect
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.loader import load_strategy
from talim.strategy.store import StrategyStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bar(close: float, idx: int = 0, high_delta: float = 5.0, low_delta: float = 5.0) -> OHLCVBar:
    return OHLCVBar(
        instrument="ES",
        timestamp=datetime(2025, 6, 15, 9, 30) + timedelta(minutes=idx),
        open=close - 1,
        high=close + high_delta,
        low=close - low_delta,
        close=close,
        volume=10000.0,
        timeframe="5m",
    )


def _make_trending_up_bars(n: int = 100) -> list[OHLCVBar]:
    """Bars that trend up, then pull back — should trigger EMA crossover."""
    bars = []
    price = 5000.0
    for i in range(n):
        if i < 60:
            price += 2.0  # uptrend
        else:
            price -= 3.0  # pullback/reversal
        bars.append(_make_bar(price, idx=i))
    return bars


def _make_range_bound_bars(n: int = 100) -> list[OHLCVBar]:
    """Bars that oscillate — should trigger Bollinger touches."""
    bars = []
    price = 5000.0
    rng = np.random.RandomState(42)
    for i in range(n):
        # Oscillate with some noise
        price = 5000.0 + 40.0 * np.sin(i * 0.15) + rng.randn() * 2
        bars.append(_make_bar(price, idx=i))
    return bars


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------

class TestLoader:
    def test_load_momentum_es(self):
        strategy = load_strategy("momentum-ES")
        assert isinstance(strategy, BaseStrategy)
        assert strategy.name == "momentum-ES"

    def test_load_mean_reversion_es(self):
        strategy = load_strategy("mean-reversion-ES")
        assert isinstance(strategy, BaseStrategy)
        assert strategy.name == "mean-reversion-ES"

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_strategy("nonexistent-strategy")


# ---------------------------------------------------------------------------
# StrategyStore tests
# ---------------------------------------------------------------------------

class TestStrategyStore:
    def test_list_strategies(self):
        store = StrategyStore()
        names = store.list_strategies()
        assert "momentum-ES" in names
        assert "mean-reversion-ES" in names

    def test_read_strategy(self):
        store = StrategyStore()
        content = store.read("momentum-ES")
        assert "momentum-ES" in content
        assert "EMA" in content

    def test_read_nonexistent_raises(self):
        store = StrategyStore()
        with pytest.raises(FileNotFoundError):
            store.read("nonexistent")

    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StrategyStore(strategies_dir=Path(tmpdir))
            store.write("test-strat", "# test-strat\n\nHello world.")
            content = store.read("test-strat")
            assert "Hello world" in content

    def test_write_and_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StrategyStore(strategies_dir=Path(tmpdir))
            store.write("alpha", "# alpha")
            store.write("beta", "# beta")
            names = store.list_strategies()
            assert names == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Momentum-ES on_bar tests
# ---------------------------------------------------------------------------

class TestMomentumES:
    def test_generates_signals(self):
        strategy = load_strategy("momentum-ES")
        bars = _make_trending_up_bars(100)
        signals = [s for s in (strategy.on_bar(b) for b in bars) if s is not None]
        assert len(signals) > 0, "Expected at least one signal from trending data"

    def test_signal_is_valid(self):
        strategy = load_strategy("momentum-ES")
        bars = _make_trending_up_bars(100)
        signals = [s for s in (strategy.on_bar(b) for b in bars) if s is not None]
        for sig in signals:
            assert isinstance(sig, Signal)
            assert sig.instrument == "ES"
            assert sig.strategy == "momentum-ES"
            assert sig.side in ("long", "short")
            assert sig.stop > 0
            assert sig.target > 0

    def test_no_signal_on_few_bars(self):
        strategy = load_strategy("momentum-ES")
        bars = _make_trending_up_bars(10)
        signals = [s for s in (strategy.on_bar(b) for b in bars) if s is not None]
        assert len(signals) == 0, "Should not signal with insufficient data"

    def test_load_params(self):
        strategy = load_strategy("momentum-ES")
        strategy.load_params({"ema_fast_period": 5, "ema_slow_period": 13})
        assert strategy.ema_fast_period == 5
        assert strategy.ema_slow_period == 13

    def test_reset(self):
        strategy = load_strategy("momentum-ES")
        bars = _make_trending_up_bars(50)
        for b in bars:
            strategy.on_bar(b)
        strategy.reset()
        # After reset, should need warmup again — no immediate signals
        sig = strategy.on_bar(bars[0])
        assert sig is None


# ---------------------------------------------------------------------------
# Mean-Reversion-ES on_bar tests
# ---------------------------------------------------------------------------

class TestMeanReversionES:
    def test_generates_signals(self):
        strategy = load_strategy("mean-reversion-ES")
        bars = _make_range_bound_bars(100)
        signals = [s for s in (strategy.on_bar(b) for b in bars) if s is not None]
        assert len(signals) > 0, "Expected at least one signal from range-bound data"

    def test_signal_is_valid(self):
        strategy = load_strategy("mean-reversion-ES")
        bars = _make_range_bound_bars(100)
        signals = [s for s in (strategy.on_bar(b) for b in bars) if s is not None]
        for sig in signals:
            assert isinstance(sig, Signal)
            assert sig.instrument == "ES"
            assert sig.strategy == "mean-reversion-ES"
            assert sig.side in ("long", "short")

    def test_no_signal_on_few_bars(self):
        strategy = load_strategy("mean-reversion-ES")
        bars = _make_range_bound_bars(15)
        signals = [s for s in (strategy.on_bar(b) for b in bars) if s is not None]
        assert len(signals) == 0

    def test_load_params(self):
        strategy = load_strategy("mean-reversion-ES")
        strategy.load_params({"bb_period": 15, "bb_std": 1.5})
        assert strategy.bb_period == 15
        assert strategy.bb_std == 1.5


# ---------------------------------------------------------------------------
# Parity test — on_bar signature is identical across strategies
# ---------------------------------------------------------------------------

class TestParity:
    def test_on_bar_signature_matches(self):
        momentum = load_strategy("momentum-ES")
        mean_rev = load_strategy("mean-reversion-ES")

        sig_mom = inspect.signature(momentum.on_bar)
        sig_mr = inspect.signature(mean_rev.on_bar)

        # Both should accept (self, bar: OHLCVBar) -> Signal | None
        mom_params = list(sig_mom.parameters.keys())
        mr_params = list(sig_mr.parameters.keys())
        assert mom_params == mr_params

    def test_both_accept_same_bar(self):
        """Both strategies can process the exact same bar without error."""
        momentum = load_strategy("momentum-ES")
        mean_rev = load_strategy("mean-reversion-ES")
        bar = _make_bar(5000.0)

        # Should not raise
        r1 = momentum.on_bar(bar)
        r2 = mean_rev.on_bar(bar)

        assert r1 is None or isinstance(r1, Signal)
        assert r2 is None or isinstance(r2, Signal)


# ---------------------------------------------------------------------------
# WP-25: StrategyStore.commit_change git integration
# ---------------------------------------------------------------------------

class TestStoreGit:
    def _git(self, *args, cwd):
        import subprocess
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    def test_commit_change_creates_commit(self, tmp_path):
        import subprocess
        from talim.strategy.store import StrategyStore

        # Init a git repo at tmp_path and configure identity.
        self._git("init", "-q", cwd=tmp_path)
        self._git("config", "user.email", "test@example.com", cwd=tmp_path)
        self._git("config", "user.name", "Test", cwd=tmp_path)

        store = StrategyStore(strategies_dir=tmp_path, git_enabled=True)
        store.write("foo", "# foo strategy v1\n")
        # Need an initial commit so commit_change isn't the very first.
        self._git("add", "-A", cwd=tmp_path)
        self._git("commit", "-q", "-m", "initial", cwd=tmp_path)

        store.write("foo", "# foo strategy v2\n")
        ok = store.commit_change("foo", "test: bump foo")
        assert ok is True

        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True
        )
        assert "test: bump foo" in log.stdout

    def test_commit_change_disabled_returns_false(self, tmp_path):
        from talim.strategy.store import StrategyStore
        store = StrategyStore(strategies_dir=tmp_path, git_enabled=False)
        store.write("foo", "x")
        assert store.commit_change("foo", "noop") is False
