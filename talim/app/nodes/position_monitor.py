"""Position monitor node — watches open positions for stop/target hits (WP-34).

Called on every scanner tick. Reads `active_positions` and the latest bar,
checks each position's stop and target against the bar's low/high, and
emits an exit signal for the first position that should close.
"""

from __future__ import annotations

import logging
from dataclasses import replace as dc_replace
from datetime import datetime, timezone

from talim.app.state import TalimState
from talim.models.bar import OHLCVBar
from talim.models.position import Position
from talim.models.signal import Signal

logger = logging.getLogger("talim.nodes.position_monitor")


def _check_exit(position: Position, bar: OHLCVBar) -> Signal | None:
    """Return an exit Signal if the bar's price range hits the position's
    stop or target, or None if the position is still within bounds.

    For longs:  stop hit when bar.low <= stop;  target hit when bar.high >= target.
    For shorts: stop hit when bar.high >= stop; target hit when bar.low <= target.
    """
    if position.stop <= 0 and position.target <= 0:
        return None

    hit_stop = False
    hit_target = False
    exit_price = bar.close  # fallback

    if position.side == "long":
        if position.stop > 0 and bar.low <= position.stop:
            hit_stop = True
            exit_price = position.stop
        elif position.target > 0 and bar.high >= position.target:
            hit_target = True
            exit_price = position.target
    else:  # short
        if position.stop > 0 and bar.high >= position.stop:
            hit_stop = True
            exit_price = position.stop
        elif position.target > 0 and bar.low <= position.target:
            hit_target = True
            exit_price = position.target

    if not hit_stop and not hit_target:
        return None

    reason = "stop" if hit_stop else "target"
    return Signal(
        instrument=position.instrument,
        strategy=position.strategy,
        side=position.side,
        entry_price=exit_price,
        stop=0.0,
        target=0.0,
        rationale=f"{reason} hit at {exit_price:.2f}",
        regime_context="",
        timestamp=bar.timestamp,
        action="exit",
    )


def position_monitor(state: TalimState) -> TalimState:
    """Check open positions for stop/target exits.

    If a pending_signal already exists (from the scanner), skip — entry
    signals take priority so we don't clobber an unprocessed trade.
    """
    update: TalimState = {}  # type: ignore[assignment]

    if state.get("pending_signal") is not None:
        logger.debug("position_monitor: pending_signal exists, skipping")
        return update

    positions: list[Position] = state.get("active_positions") or []
    if not positions:
        return update

    bar: OHLCVBar | None = state.get("last_tick") or state.get("current_bar")
    if bar is None:
        return update

    for pos in positions:
        if pos.instrument != bar.instrument:
            continue
        exit_signal = _check_exit(pos, bar)
        if exit_signal is not None:
            logger.info(
                "position_monitor: %s %s %s — %s",
                exit_signal.rationale,
                pos.side,
                pos.instrument,
                exit_signal.action,
            )
            update["pending_signal"] = exit_signal
            break  # one exit per tick

    return update
