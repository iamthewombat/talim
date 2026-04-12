"""Tests for the position monitor node (WP-34)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talim.app.nodes.position_monitor import position_monitor, _check_exit
from talim.models.bar import OHLCVBar
from talim.models.position import Position
from talim.models.signal import Signal


def _bar(
    low: float = 4990.0,
    high: float = 5010.0,
    close: float = 5000.0,
    instrument: str = "ES",
) -> OHLCVBar:
    return OHLCVBar(
        timestamp=datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
        instrument=instrument,
    )


def _position(
    side: str = "long",
    entry_price: float = 5000.0,
    stop: float = 4980.0,
    target: float = 5030.0,
    instrument: str = "ES",
) -> Position:
    return Position(
        instrument=instrument,
        side=side,
        qty=1.0,
        entry_price=entry_price,
        stop=stop,
        target=target,
        strategy="momentum-ES",
    )


# --- _check_exit unit tests ---


class TestCheckExitLong:
    def test_no_exit_within_bounds(self):
        assert _check_exit(_position(), _bar(low=4990, high=5010)) is None

    def test_stop_hit(self):
        sig = _check_exit(_position(stop=4990), _bar(low=4985))
        assert sig is not None
        assert sig.action == "exit"
        assert sig.entry_price == 4990.0
        assert "stop" in sig.rationale

    def test_target_hit(self):
        sig = _check_exit(_position(target=5005), _bar(high=5010))
        assert sig is not None
        assert sig.action == "exit"
        assert sig.entry_price == 5005.0
        assert "target" in sig.rationale

    def test_stop_takes_priority_over_target(self):
        """When both stop and target are hit in the same bar, stop wins."""
        sig = _check_exit(
            _position(stop=4990, target=5005),
            _bar(low=4985, high=5010),
        )
        assert sig is not None
        assert "stop" in sig.rationale

    def test_zero_stop_ignored(self):
        pos = _position(stop=0.0, target=5005)
        sig = _check_exit(pos, _bar(low=4900, high=5010))
        assert sig is not None
        assert "target" in sig.rationale

    def test_zero_stop_and_target_no_exit(self):
        pos = _position(stop=0.0, target=0.0)
        assert _check_exit(pos, _bar(low=4900, high=5100)) is None


class TestCheckExitShort:
    def test_no_exit_within_bounds(self):
        pos = _position(side="short", stop=5020, target=4970)
        assert _check_exit(pos, _bar(low=4980, high=5010)) is None

    def test_stop_hit_short(self):
        pos = _position(side="short", stop=5010, target=4970)
        sig = _check_exit(pos, _bar(high=5015))
        assert sig is not None
        assert sig.action == "exit"
        assert sig.entry_price == 5010.0
        assert "stop" in sig.rationale

    def test_target_hit_short(self):
        pos = _position(side="short", stop=5020, target=4990)
        sig = _check_exit(pos, _bar(low=4985))
        assert sig is not None
        assert sig.action == "exit"
        assert sig.entry_price == 4990.0
        assert "target" in sig.rationale


# --- position_monitor node tests ---


class TestPositionMonitorNode:
    def test_no_positions_noop(self):
        state = {"active_positions": [], "last_tick": _bar()}
        assert position_monitor(state) == {}

    def test_no_bar_noop(self):
        state = {"active_positions": [_position()]}
        assert position_monitor(state) == {}

    def test_pending_signal_skips(self):
        """Don't clobber an existing pending_signal from the scanner."""
        existing = Signal(
            instrument="ES", strategy="momentum-ES", side="long",
            entry_price=5000, stop=4980, target=5030, rationale="test",
            regime_context="", action="enter",
        )
        state = {
            "active_positions": [_position(stop=4990)],
            "last_tick": _bar(low=4985),  # would trigger stop
            "pending_signal": existing,
        }
        result = position_monitor(state)
        assert "pending_signal" not in result

    def test_stop_exit_emitted(self):
        state = {
            "active_positions": [_position(stop=4990)],
            "last_tick": _bar(low=4985),
        }
        result = position_monitor(state)
        sig = result["pending_signal"]
        assert sig.action == "exit"
        assert sig.instrument == "ES"
        assert "stop" in sig.rationale

    def test_target_exit_emitted(self):
        state = {
            "active_positions": [_position(target=5005)],
            "last_tick": _bar(high=5010),
        }
        result = position_monitor(state)
        sig = result["pending_signal"]
        assert sig.action == "exit"
        assert "target" in sig.rationale

    def test_different_instrument_ignored(self):
        """Only check positions matching the bar's instrument."""
        state = {
            "active_positions": [_position(instrument="NQ", stop=4990)],
            "last_tick": _bar(low=4985, instrument="ES"),
        }
        assert position_monitor(state) == {}

    def test_falls_back_to_current_bar(self):
        """Uses current_bar when last_tick is absent."""
        state = {
            "active_positions": [_position(stop=4990)],
            "current_bar": _bar(low=4985),
        }
        result = position_monitor(state)
        assert result["pending_signal"].action == "exit"

    def test_only_first_exit_per_tick(self):
        """Only one exit signal per invocation, even with multiple positions."""
        state = {
            "active_positions": [
                _position(stop=4990),
                _position(target=5005),
            ],
            "last_tick": _bar(low=4985, high=5010),
        }
        result = position_monitor(state)
        assert result["pending_signal"] is not None
        # Only one signal, not two
        assert isinstance(result["pending_signal"], Signal)
