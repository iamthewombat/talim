"""Signal scanner node — real implementation (WP-09).

Responsibilities:
1. Pull the latest bars for each subscribed instrument.
2. Compute ATR and regime fingerprint.
3. Update market state fields on TalimState.
4. Feed bars to active strategies and collect any resulting signals.
5. Write the first signal found (if any) to `pending_signal`.

Uses dependency injection so tests can supply mocks via `configure_scanner`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from talim.app.state import TalimState
from talim.connectors.pricefeed.base import BasePriceFeed
from talim.models.bar import OHLCVBar
from talim.regime.classifier import RegimeClassifier, classify_regime
from talim.regime.fingerprint import compute_fingerprint, compute_atr
from talim.strategy.base import BaseStrategy
from talim.strategy.loader import load_strategy

logger = logging.getLogger("talim.nodes.signal_scanner")


# ---------------------------------------------------------------------------
# Dependency injection container
# ---------------------------------------------------------------------------

class ScannerContext:
    """Holds injected dependencies for the scanner node."""

    def __init__(self) -> None:
        self.price_feed: BasePriceFeed | None = None
        self.strategies: dict[str, BaseStrategy] = {}
        self.bar_window: int = 50  # bars kept per instrument
        self.regime_classifier: RegimeClassifier | None = None
        self.regime_change_threshold: float = 1.25
        self.regime_persistence_bars: int = 2
        self._bar_history: dict[str, list[OHLCVBar]] = {}

    def set_price_feed(self, feed: BasePriceFeed) -> None:
        self.price_feed = feed

    def add_strategy(self, strategy: BaseStrategy) -> None:
        self.strategies[strategy.name] = strategy

    def record_bar(self, bar: OHLCVBar) -> None:
        """Append a bar to the history window for its instrument."""
        hist = self._bar_history.setdefault(bar.instrument, [])
        if hist and hist[-1].timestamp == bar.timestamp and hist[-1].timeframe == bar.timeframe:
            hist[-1] = bar
            return
        hist.append(bar)
        if len(hist) > self.bar_window * 4:  # keep a bit more than required
            del hist[: len(hist) - self.bar_window * 2]

    def get_history(self, instrument: str) -> list[OHLCVBar]:
        return self._bar_history.get(instrument, [])

    def reset(self) -> None:
        self.price_feed = None
        self.strategies.clear()
        self.regime_classifier = None
        self.regime_change_threshold = 1.25
        self.regime_persistence_bars = 2
        self._bar_history.clear()


# Module-level singleton — real deployments configure this once at startup
_context = ScannerContext()


def configure_scanner(
    price_feed: BasePriceFeed,
    strategies: list[BaseStrategy] | None = None,
    bar_window: int = 50,
    regime_classifier: RegimeClassifier | None = None,
    regime_change_threshold: float = 1.25,
    regime_persistence_bars: int = 2,
) -> ScannerContext:
    """Configure the scanner's injected dependencies."""
    _context.reset()
    _context.bar_window = bar_window
    _context.regime_classifier = regime_classifier
    _context.regime_change_threshold = regime_change_threshold
    _context.regime_persistence_bars = max(1, regime_persistence_bars)
    _context.set_price_feed(price_feed)
    price_feed.on_bar(_context.record_bar)

    if strategies:
        for s in strategies:
            _context.add_strategy(s)
    return _context


def _bars_to_dataframe(bars: list[OHLCVBar]) -> pd.DataFrame:
    return pd.DataFrame([{
        "timestamp": b.timestamp,
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
    } for b in bars])


def _normalise_fingerprint(fingerprint: np.ndarray) -> np.ndarray:
    """Scale mixed-unit fingerprint features before distance comparison."""
    fp = np.asarray(fingerprint, dtype=np.float64)
    return np.array(
        [
            fp[0] / 25.0,
            (fp[1] - 1.0) / 0.35,
            fp[2],
            fp[3] / 0.01,
            (fp[4] - 1.0) / 0.50,
            fp[5] / 0.02,
        ],
        dtype=np.float64,
    )


def _classify_regime_label(fingerprint: np.ndarray) -> str:
    """Classify a fingerprint into a labelled market regime."""
    clf = _context.regime_classifier
    if clf is not None and clf.is_fitted:
        return classify_regime(fingerprint, clf)

    adx, atr_ratio, trend_slope, realised_vol, _volume_ratio, momentum = fingerprint
    trend_strength = abs(trend_slope) + abs(momentum / 0.02)

    if atr_ratio >= 1.35 or realised_vol >= 0.012:
        return "high_vol"
    if adx >= 25.0 and trend_strength >= 0.50:
        return "momentum"
    if adx <= 20.0 and atr_ratio <= 1.15 and abs(momentum) >= 0.004:
        return "mean_reversion"
    return "ranging"


def _detect_regime_transition(state: TalimState, fingerprint: np.ndarray) -> dict:
    """Classify current regime and require persistence before switching."""
    label = _classify_regime_label(fingerprint)
    prev_label = state.get("regime")
    prev_fp = state.get("regime_fingerprint")

    update: dict = {
        "regime_changed": False,
        "regime_candidate": None,
        "regime_candidate_count": 0,
    }

    if not prev_label:
        update["regime"] = label
        return update

    update["regime"] = prev_label
    if label == prev_label:
        return update

    distance_ok = True
    if prev_fp is not None and len(prev_fp) == 6:
        prev_arr = np.array(prev_fp, dtype=np.float64)
        dist = float(np.linalg.norm(_normalise_fingerprint(fingerprint) - _normalise_fingerprint(prev_arr)))
        distance_ok = dist >= _context.regime_change_threshold

    if not distance_ok:
        return update

    prev_candidate = state.get("regime_candidate")
    prev_count = int(state.get("regime_candidate_count") or 0)
    candidate_count = prev_count + 1 if prev_candidate == label else 1

    if candidate_count >= _context.regime_persistence_bars:
        update["regime"] = label
        update["regime_changed"] = True
        return update

    update["regime_candidate"] = label
    update["regime_candidate_count"] = candidate_count
    return update


# ---------------------------------------------------------------------------
# Node implementation
# ---------------------------------------------------------------------------

def signal_scanner(state: TalimState) -> TalimState:
    """Real signal_scanner node.

    Returns a state update dict. LangGraph merges these into the global state.
    """
    update: TalimState = {}  # type: ignore[assignment]

    if _context.price_feed is None:
        logger.warning("signal_scanner: no price feed configured")
        return update

    # Pick the first subscribed instrument (PoC: single instrument at a time)
    instruments = sorted(_context.price_feed.subscriptions)
    if not instruments:
        logger.info("signal_scanner: no subscriptions")
        return update

    instrument = instruments[0]
    bars = _context.get_history(instrument)
    if len(bars) < 20:
        _context.price_feed.prime_history(instrument, min_bars=max(20, _context.bar_window))
        bars = _context.get_history(instrument)
    _context.price_feed.poll_once(instrument)
    bars = _context.get_history(instrument)
    if len(bars) < 20:
        logger.info(
            "signal_scanner: insufficient bars (%d) for %s", len(bars), instrument
        )
        update["last_scan_time"] = datetime.now(tz=timezone.utc).isoformat()
        return update

    # Use the most recent `bar_window` bars
    window = bars[-_context.bar_window :]
    df = _bars_to_dataframe(window)

    # Current bar + ATR
    latest_bar = window[-1]
    atr_series = compute_atr(df, period=14)
    atr_current = float(atr_series.iloc[-1])
    atr_mean = float(atr_series.mean())
    atr_ratio = atr_current / atr_mean if atr_mean > 0 else 1.0

    # Regime fingerprint
    fingerprint = compute_fingerprint(df)

    update["current_bar"] = latest_bar
    update["last_tick"] = latest_bar
    update["instrument"] = instrument
    update["atr_current"] = atr_current
    update["atr_ratio"] = atr_ratio
    update["regime_fingerprint"] = fingerprint.tolist()
    update["last_scan_time"] = datetime.now(tz=timezone.utc).isoformat()

    # Label the regime and require a persistent, normalised change before
    # triggering strategy_update.
    update.update(_detect_regime_transition(state, fingerprint))

    # Check active strategies for signals. Distinguish "key missing" (use all
    # loaded) from "key set to []" (operator disabled everything — WP-70).
    if "active_strategies" in state:
        active_names = list(state.get("active_strategies") or [])
    else:
        active_names = list(_context.strategies.keys())
    pending_signal = None
    for name in active_names:
        strat = _context.strategies.get(name)
        if strat is None:
            try:
                strat = load_strategy(name)
                _context.add_strategy(strat)
            except Exception as e:
                logger.warning("signal_scanner: failed to load %s: %s", name, e)
                continue

        # Feed all bars through the strategy to warm up state, then inspect last signal
        strat.reset()
        last_signal = None
        for bar in window:
            sig = strat.on_bar(bar)
            if sig is not None:
                last_signal = sig
        if last_signal is not None:
            # Attach regime context now that we have the fingerprint
            regime_label = update.get("regime") or state.get("regime", "")
            pending_signal = last_signal
            if not pending_signal.regime_context and regime_label:
                # Signal is frozen dataclass — create a new one with updated context
                from dataclasses import replace
                pending_signal = replace(last_signal, regime_context=regime_label)
            break

    update["pending_signal"] = pending_signal
    return update
