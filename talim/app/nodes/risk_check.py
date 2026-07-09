"""risk_check node (WP-17).

Validates a `pending_signal` against configured risk rules. On rejection it
clears the pending signal and writes a `pending_notification` explaining
why; on pass-through the signal continues to the HITL node unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from talim.app.execute_context import get_execute_context
from talim.app.state import TalimState
from talim.models.position import Position
from talim.models.signal import Signal
from talim.metrics import METRICS
from talim.risk.cfd import (
    exposure_for_position,
    exposure_for_trade,
    is_instrument_tradeable,
    same_cfd_family,
    select_account_balance,
)
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
    explicit_related = set().union(*groups) if groups else set()

    count = 0
    for position in positions:
        if position.instrument in explicit_related:
            count += 1
            continue
        if same_cfd_family(instrument, position.instrument):
            count += 1
    return count


def _position_exposure(position: Position) -> float:
    snapshot = exposure_for_position(position)
    if snapshot is not None:
        return snapshot.notional
    return abs(position.qty * position.entry_price)


def _incoming_exposure(signal: Signal, qty: float) -> float:
    snapshot = exposure_for_trade(signal.instrument, qty=qty, price=signal.entry_price)
    if snapshot is not None:
        return snapshot.notional
    return abs(qty * signal.entry_price)


def check_signal(
    signal: Signal,
    positions: list[Position],
    daily_pnl: float,
    rules: RiskRules,
    qty: float = 1.0,
    account_balance: float | None = None,
    evaluated_at: datetime | None = None,
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

    evaluated_at = evaluated_at or signal.timestamp or datetime.now(tz=timezone.utc)

    # 3) Total exposure (existing + this trade)
    if rules.enforce_cfd_session_windows and not is_instrument_tradeable(
        signal.instrument,
        at=evaluated_at,
    ):
        return False, f"{signal.instrument} session is closed"

    existing = sum(_position_exposure(position) for position in positions)
    incoming = _incoming_exposure(signal, qty)
    if existing + incoming > rules.max_total_exposure:
        return False, (
            f"total exposure {existing + incoming:.2f} would exceed "
            f"max_total_exposure {rules.max_total_exposure:.2f}"
        )

    # 4) Margin utilisation for CFDs
    if account_balance is not None and account_balance > 0:
        existing_margin = sum(
            snapshot.required_margin
            for position in positions
            if (snapshot := exposure_for_position(position)) is not None
        )
        incoming_snapshot = exposure_for_trade(
            signal.instrument,
            qty=qty,
            price=signal.entry_price,
        )
        if incoming_snapshot is not None:
            required_margin = existing_margin + incoming_snapshot.required_margin
            allowed_margin = account_balance * rules.max_margin_utilization_pct
            if required_margin > allowed_margin:
                return False, (
                    f"required margin {required_margin:.2f} would exceed "
                    f"allowed margin {allowed_margin:.2f}"
                )

    # 5) Same-instrument stacking
    if rules.block_on_existing_same_instrument:
        if any(p.instrument == signal.instrument for p in positions):
            return False, f"already exposed to {signal.instrument}"

    # 6) Correlation
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

    if sig.action == "exit":
        logger.info("risk_check: allowing protective exit %s %s", sig.side, sig.instrument)
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
    ctx = get_execute_context()
    qty = float(ctx.default_qty or 1.0)
    account_balance: float | None = None
    if isinstance(state.get("account_balance"), (int, float)):
        account_balance = float(state["account_balance"])
    elif ctx.exchange is not None:
        try:
            _, account_balance = select_account_balance(
                ctx.exchange.get_account_balance(),
                positions,
            )
        except Exception:  # noqa: BLE001
            logger.warning("risk_check: failed to fetch account balance", exc_info=True)

    evaluated_at = sig.timestamp
    current_bar = state.get("current_bar")
    if current_bar is not None:
        evaluated_at = current_bar.timestamp

    passed, reason = check_signal(
        sig,
        positions,
        daily_pnl,
        _rules,
        qty=qty,
        account_balance=account_balance,
        evaluated_at=evaluated_at,
    )
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
