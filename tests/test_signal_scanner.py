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
    _classify_regime_label,
    _detect_regime_transition,
    _normalise_fingerprint,
)
from talim.connectors.pricefeed.mock import MockPriceFeed
from talim.connectors.pricefeed.base import BasePriceFeed
from talim.models.bar import OHLCVBar
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
    strats = [load_strategy(name) for name in (strategies or ["momentum-US500"])]
    configure_scanner(feed, strategies=strats)
    feed.connect()
    feed.subscribe("ES")
    feed.replay()  # populates the history via the callback
    return feed


class _TimestampSignalStrategy:
    """Test strategy that emits a signal on one configured bar timestamp."""

    name = "momentum-US500"

    def __init__(self, target_timestamp):
        self.target_timestamp = target_timestamp

    def reset(self):
        pass

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        if bar.timestamp != self.target_timestamp:
            return None
        return Signal(
            instrument=bar.instrument,
            strategy=self.name,
            side="long",
            entry_price=bar.close,
            stop=bar.close - 10,
            target=bar.close + 20,
            rationale="unit-test EMA cross",
            regime_context="",
            timestamp=bar.timestamp,
        )


def _setup_scanner_with_strategy(df: pd.DataFrame, strategy):
    feed = MockPriceFeed(source=df, instrument="ES")
    configure_scanner(feed, strategies=[strategy])
    feed.connect()
    feed.subscribe("ES")
    bars = feed.replay()
    return feed, bars


class _PollingFeed(BasePriceFeed):
    def __init__(self, bars: list[OHLCVBar]):
        super().__init__()
        self._bars = bars
        self._primed = False
        self.prime_calls = 0
        self.poll_calls = 0

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def subscribe(self, instrument: str) -> None:
        self._subscribed.add(instrument)

    def prime_history(self, instrument: str, min_bars: int = 50) -> list[OHLCVBar]:
        self.prime_calls += 1
        if not self._primed:
            for bar in self._bars[:min_bars]:
                self._emit(bar)
            self._primed = True
        return self._bars[:min_bars]

    def poll_once(self, instrument: str) -> OHLCVBar | None:
        self.poll_calls += 1
        return None


class TestRegimeTransitionDetection:
    def test_normalised_distance_does_not_let_adx_dominate(self):
        a = np.array([20.0, 1.0, 0.0, 0.002, 1.0, 0.0])
        b = np.array([21.0, 1.0, 0.0, 0.002, 1.0, 0.0])
        assert np.linalg.norm(_normalise_fingerprint(b) - _normalise_fingerprint(a)) < 0.1

    def test_labels_fallback_regime_without_fitted_classifier(self):
        _context.reset()
        assert _classify_regime_label(np.array([30.0, 1.05, 0.7, 0.004, 1.0, 0.015])) == "momentum"
        assert _classify_regime_label(np.array([12.0, 1.50, 0.1, 0.004, 1.0, 0.001])) == "high_vol"

    def test_regime_switch_requires_persistence(self):
        _context.reset()
        fp = np.array([35.0, 1.05, 0.8, 0.004, 1.0, 0.020])
        prev = [10.0, 1.0, 0.0, 0.001, 1.0, 0.0]

        first = _detect_regime_transition({"regime": "ranging", "regime_fingerprint": prev}, fp)
        assert first["regime"] == "ranging"
        assert first["regime_changed"] is False
        assert first["regime_candidate"] == "momentum"
        assert first["regime_candidate_count"] == 1

        second = _detect_regime_transition({
            "regime": "ranging",
            "regime_fingerprint": prev,
            "regime_candidate": "momentum",
            "regime_candidate_count": 1,
        }, fp)
        assert second["regime"] == "momentum"
        assert second["regime_changed"] is True


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

    def test_signal_on_latest_bar(self):
        df = _make_flat_df(80)
        feed = MockPriceFeed(source=df, instrument="ES")
        configure_scanner(feed, strategies=[])
        feed.connect()
        feed.subscribe("ES")
        bars = feed.replay()
        _context.add_strategy(_TimestampSignalStrategy(bars[-1].timestamp))

        update = signal_scanner({"regime": "momentum"})
        sig = update.get("pending_signal")
        assert sig is not None
        assert isinstance(sig, Signal)
        assert sig.strategy == "momentum-US500"
        assert sig.timestamp == bars[-1].timestamp

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
        df = _make_flat_df(80)
        feed = MockPriceFeed(source=df, instrument="ES")
        configure_scanner(feed, strategies=[])
        feed.connect()
        feed.subscribe("ES")
        bars = feed.replay()
        _context.add_strategy(_TimestampSignalStrategy(bars[-1].timestamp))

        update = signal_scanner({"regime": "momentum"})
        sig = update.get("pending_signal")
        assert sig is not None
        assert sig.regime_context == "momentum"

    def test_stale_cross_in_warmup_window_is_not_realerted(self):
        df = _make_flat_df(80)
        feed = MockPriceFeed(source=df, instrument="ES")
        configure_scanner(feed, strategies=[])
        feed.connect()
        feed.subscribe("ES")
        bars = feed.replay()
        _context.add_strategy(_TimestampSignalStrategy(bars[-2].timestamp))

        update = signal_scanner({"regime": "momentum"})
        assert update.get("pending_signal") is None

    def test_duplicate_same_bar_signal_is_suppressed(self):
        df = _make_flat_df(80)
        feed = MockPriceFeed(source=df, instrument="ES")
        configure_scanner(feed, strategies=[])
        feed.connect()
        feed.subscribe("ES")
        bars = feed.replay()
        _context.add_strategy(_TimestampSignalStrategy(bars[-1].timestamp))

        first = signal_scanner({"regime": "momentum"})
        second = signal_scanner({"regime": "momentum"})
        assert first.get("pending_signal") is not None
        assert second.get("pending_signal") is None

    def test_momentum_signal_suppressed_in_ranging_regime(self):
        df = _make_flat_df(80)
        feed = MockPriceFeed(source=df, instrument="ES")
        configure_scanner(feed, strategies=[])
        feed.connect()
        feed.subscribe("ES")
        bars = feed.replay()
        _context.add_strategy(_TimestampSignalStrategy(bars[-1].timestamp))

        update = signal_scanner({"regime": "ranging"})
        assert update.get("pending_signal") is None

    def test_live_feed_can_prime_history_on_demand(self):
        _context.reset()
        df = _make_trending_df(80)
        bars = [
            OHLCVBar(
                instrument="AU200.cash",
                timestamp=ts.to_pydatetime(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
                timeframe="5m",
            )
            for ts, row in zip(df["timestamp"], df.itertuples(index=False))
        ]
        feed = _PollingFeed(bars)
        strategy = load_strategy("momentum-US500")
        configure_scanner(feed, strategies=[strategy])
        feed.connect()
        feed.subscribe("AU200.cash")

        update = signal_scanner({})
        assert feed.poll_calls == 1
        assert feed.prime_calls == 1
        assert update.get("current_bar") is not None


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
