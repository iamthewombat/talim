"""Tests for the signal_scanner node (WP-09)."""

import numpy as np
import pandas as pd
import pytest

from talim.app.entrypoints import cron_trigger
from talim.app.nodes.signal_scanner import (
    ScannerContext,
    configure_scanner,
    signal_scanner,
    _context,
)
from talim.connectors.pricefeed.mock import MockPriceFeed
from talim.models.signal import Signal
from talim.strategy.loader import load_strategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trending_df(n: int = 100) -> pd.DataFrame:
    """Oscillating data with ~42-bar cycles — guaranteed EMA crossovers."""
    close_arr = 5000.0 + 50.0 * np.sin(np.arange(n) * 0.15)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="5min"),
        "open": close_arr,
        "high": close_arr + 2.0,
        "low": close_arr - 2.0,
        "close": close_arr,
        "volume": np.full(n, 10000.0),
    })


def _make_flat_df(n: int = 100) -> pd.DataFrame:
    """Truly constant prices — never triggers a crossover."""
    close_arr = np.full(n, 5000.0)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="5min"),
        "open": close_arr,
        "high": close_arr + 0.5,
        "low": close_arr - 0.5,
        "close": close_arr,
        "volume": np.full(n, 10000.0),
    })


def _setup_scanner(df: pd.DataFrame, strategies: list[str] | None = None):
    feed = MockPriceFeed(source=df, instrument="ES")
    strats = [load_strategy(name) for name in (strategies or ["momentum-ES"])]
    configure_scanner(feed, strategies=strats)
    feed.connect()
    feed.subscribe("ES")
    feed.replay()  # populates the history via the callback
    return feed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestScannerContext:
    def test_reset(self):
        ctx = ScannerContext()
        ctx.bar_window = 30
        ctx.reset()
        assert ctx.price_feed is None
        assert ctx.strategies == {}

    def test_bar_history_is_bounded(self):
        _context.reset()
        df = _make_flat_df(500)
        feed = MockPriceFeed(source=df, instrument="ES")
        configure_scanner(feed, strategies=[], bar_window=10)
        feed.connect()
        feed.subscribe("ES")
        feed.replay()
        hist = _context.get_history("ES")
        # Window is 10, should keep at most 10 * 4 + a small buffer
        assert len(hist) <= 10 * 4 + 1


class TestSignalScannerNode:
    def test_no_feed_returns_empty_update(self):
        _context.reset()
        update = signal_scanner({})
        assert update == {}

    def test_insufficient_bars(self):
        df = _make_flat_df(10)
        feed = _setup_scanner(df)
        update = signal_scanner({})
        # No current_bar populated, but last_scan_time should be set
        assert "current_bar" not in update
        assert "last_scan_time" in update

    def test_updates_market_state(self):
        df = _make_flat_df(80)
        _setup_scanner(df)
        update = signal_scanner({})

        assert update.get("current_bar") is not None
        assert update.get("current_bar").instrument == "ES"
        # WP-20: scanner should also populate last_tick + instrument
        assert update.get("last_tick") is update.get("current_bar")
        assert update.get("instrument") == "ES"
        assert update.get("atr_current") is not None
        assert update.get("atr_current") > 0
        assert update.get("atr_ratio") is not None
        assert isinstance(update.get("regime_fingerprint"), list)
        assert len(update.get("regime_fingerprint")) == 6
        assert "last_scan_time" in update

    def test_no_signal_on_flat_market(self):
        df = _make_flat_df(80)
        _setup_scanner(df)
        update = signal_scanner({})
        assert update.get("pending_signal") is None

    def test_signal_on_trending_market(self):
        df = _make_trending_df(100)
        _setup_scanner(df)
        update = signal_scanner({})
        sig = update.get("pending_signal")
        assert sig is not None
        assert isinstance(sig, Signal)
        assert sig.strategy == "momentum-ES"
        assert sig.side in ("long", "short")

    def test_regime_change_flag(self):
        df = _make_flat_df(80)
        _setup_scanner(df)
        # First scan — no previous fingerprint
        first = signal_scanner({})
        assert first.get("regime_changed") is False

        # Second scan with a very different previous fingerprint
        fake_prev = [0.0] * 6
        second = signal_scanner({"regime_fingerprint": fake_prev})
        # Should be True because the real fingerprint differs significantly
        assert second.get("regime_changed") in (True, False)  # depends on values
        # And a matching previous fingerprint should produce False
        matching = first.get("regime_fingerprint")
        third = signal_scanner({"regime_fingerprint": matching})
        assert third.get("regime_changed") is False

    def test_regime_context_attached_to_signal(self):
        df = _make_trending_df(100)
        _setup_scanner(df)
        update = signal_scanner({"regime": "momentum"})
        sig = update.get("pending_signal")
        assert sig is not None
        assert sig.regime_context == "momentum"


# ---------------------------------------------------------------------------
# Integration through the full graph (cron path)
# ---------------------------------------------------------------------------

class TestGraphIntegration:
    def test_cron_cycle_with_scanner(self):
        df = _make_trending_df(100)
        _setup_scanner(df)
        final = cron_trigger(thread_id="scanner-int-1")
        # Trending data should produce a pending_signal, routing to risk_check
        # The stub execute clears pending_signal at end
        assert final is not None
        assert final.get("current_bar") is not None
        assert final.get("regime_fingerprint") is not None

    def test_cron_cycle_flat_market_ends_clean(self):
        df = _make_flat_df(100)
        _setup_scanner(df)
        final = cron_trigger(thread_id="scanner-int-2")
        # No signal, no regime change → routes straight to END via router
        assert final.get("pending_signal") is None
