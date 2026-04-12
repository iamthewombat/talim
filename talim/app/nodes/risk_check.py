"""risk_check node (WP-17).

Validates a `pending_signal` against configured risk rules. On rejection it
clears the pending signal and writes a `pending_notification` explaining
why; on pass-through the signal continues to the HITL node unchanged.
"""

from __future__ import annotations

import logging

from talim.app.state import TalimState
from talim.models.position import Position
from talim.models.signal import Signal
from talim.metrics import METRICS
from talim.risk.rules import RiskRules

logger = logging.getLogger("talim.nodes.risk_check")


# Module-level configurable rules — production wires this once at startup.
_rules: RiskRules = RiskRules()


def configure_risk_rules(rules: RiskRules) -> None:
    global _rules
    _rules = rules


def get_risk_rules() -> RiskRules:
    return _rules


def _correlated_count(
    instrument: str, positions: list[Position], rules: RiskRules
) -> int:
    groups = [g for g in rules.correlation_groups if instrument in g]
    if not groups:
        return 0
    related = set().union(*groups)
    return sum(1 for p in positions if p.instrument in related)


def check_signal(
    signal: Signal,
    positions: list[Position],
    daily_pnl: float,
    rules: RiskRules,
    qty: float = 1.0,
) -> tuple[bool, str | None]:
    """Return (passed, reason). reason is None on pass."""
    # 1) Position size
    if qty > rules.max_position_qty:
        return False, f"qty {qty} exceeds max_position_qty {rules.max_position_qty}"

    # 2) Daily drawdown — already at/below the floor
    if daily_pnl <= rules.max_daily_drawdown:
        return False, (
            f"daily PnL {daily_pnl:.2f} at/below max_daily_drawdown "
            f"{rules.max_daily_drawdown:.2f}"
        )

    # 3) Total exposure (existing + this trade)
    existing = sum(abs(p.qty * p.entry_price) for p in positions)
    incoming = abs(qty * signal.entry_price)
    if existing + incoming > rules.max_total_exposure:
        return False, (
            f"total exposure {existing + incoming:.2f} would exceed "
            f"max_total_exposure {rules.max_total_exposure:.2f}"
        )

    # 4) Same-instrument stacking
    if rules.block_on_existing_same_instrument:
        if any(p.instrument == signal.instrument for p in positions):
            return False, f"already exposed to {signal.instrument}"

    # 5) Correlation
    correlated = _correlated_count(signal.instrument, positions, rules)
    # +1 for the pending trade itself
    if correlated + 1 > rules.max_correlated_positions:
        return False, (
            f"{correlated} correlated position(s) already open; max allowed "
            f"is {rules.max_correlated_positions}"
        )

    return True, None


def risk_check(state: TalimState) -> TalimState:
    sig = state.get("pending_signal")
    if sig is None:
        logger.info("risk_check: no pending_signal, passing through")
        return {}

    if state.get("halted"):
        logger.info("risk_check: halted — blocking %s %s", sig.strategy, sig.side)
        METRICS.inc("talim_risk_blocks_total")
        return {
            "pending_signal": None,
            "signal_approved": False,
            "pending_notification": (
                f"HALTED: blocked {sig.side} {sig.instrument} ({sig.strategy})"
            ),
        }

    positions = list(state.get("active_positions") or [])
    daily_pnl = float(state.get("daily_pnl", 0.0)) if isinstance(
        state.get("daily_pnl", 0.0), (int, float)
    ) else 0.0

    passed, reason = check_signal(sig, positions, daily_pnl, _rules)
    if passed:
        logger.info("risk_check: %s %s passed", sig.strategy, sig.side)
        METRICS.inc("talim_signals_emitted_total")
        return {}

    logger.info("risk_check: blocked — %s", reason)
    METRICS.inc("talim_risk_blocks_total")
    return {
        "pending_signal": None,
        "signal_approved": False,
        "pending_notification": (
            f"Risk check blocked {sig.side} {sig.instrument} "
            f"({sig.strategy}): {reason}"
        ),
    }
