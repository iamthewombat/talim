"""Runtime bootstrap for live/paper Talim deployments.

This module is the production composition root: it reads environment/config,
creates the selected exchange and price feed, subscribes instruments, loads
strategies, and wires the module-level node contexts used by the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace as dc_replace
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import re
from typing import Any

from talim.app.checkpointer import create_checkpointer
from talim.app.entrypoints import bridge_message as invoke_bridge_message
from talim.app.entrypoints import cron_trigger as invoke_cron_trigger
from talim.app.execute_context import configure_execute
from talim.app.graph import build_graph
from talim.app.nodes.reconcile import format_repair_notification, reconcile_positions
from talim.app.nodes.risk_check import risk_check as run_risk_check
from talim.app.nodes.risk_check import configure_risk_rules
from talim.app.nodes.signal_scanner import _context as scanner_context
from talim.app.nodes.signal_scanner import configure_scanner
from talim.app.resume import resume_graph
from talim.app.state import TalimState
from talim.backtest.history import BacktestHistory, default_history_path
from talim.connectors.exchange.factory import create_exchange
from talim.connectors.pricefeed.factory import create_pricefeed
from talim.memory.episodic import EpisodicMemory
from talim.risk.cfd import select_account_balance
from talim.risk.config import RiskConfigError, load_validated_config
from talim.risk.pnl_tracker import PnLSnapshot, PnLTracker
from talim.risk.rules import RiskRules
from talim.models.bar import OHLCVBar
from talim.regime.atr_gate import parse_regime_filters
from talim.strategy.indicators import ema
from talim.strategy.loader import load_strategy

logger = logging.getLogger("talim.app.runtime")

_TIMEFRAME_RE = re.compile(r"^(?P<count>\d+)(?P<unit>[mhd])$")


def _parse_timeframe_delta(timeframe: str) -> timedelta:
    match = _TIMEFRAME_RE.match(timeframe.strip().lower())
    if not match:
        return timedelta(minutes=5)
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    return timedelta(days=count)


def _parse_utc_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bar_time_utc(bar: Any) -> datetime:
    ts = getattr(bar, "timestamp")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


class RuntimeConfigError(ValueError):
    """Raised when runtime configuration cannot be safely bootstrapped."""


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise RuntimeConfigError(f"{name} must be numeric, got {raw!r}") from e


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as e:
        raise RuntimeConfigError(f"{name} must be an integer, got {raw!r}") from e
    if value <= 0:
        raise RuntimeConfigError(f"{name} must be positive, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Environment-derived live runtime configuration."""

    exchange_mode: str = "mock"
    exchange_name: str | None = None
    pricefeed_name: str = "mock"
    pricefeed_timeframe: str = "5m"
    instruments: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()
    default_qty: float = 1.0
    bar_window: int = 50
    regime_filters: tuple[tuple[str, str], ...] = ()
    checkpoint_db: Path = Path("state/talim_checkpoints.db")
    episodic_db: Path = Path("state/episodic.db")
    backtest_history_db: Path = Path("state/backtest_history.db")
    risk_config_path: Path | None = Path("config/risk.json")

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        exchange_mode = os.environ.get("TALIM_EXCHANGE_MODE", "mock").strip().lower()
        exchange_name = os.environ.get("TALIM_EXCHANGE_NAME", "").strip() or None
        pricefeed_name = os.environ.get("TALIM_PRICEFEED", "mock").strip().lower()

        risk_config_raw = os.environ.get("TALIM_RISK_CONFIG", "config/risk.json").strip()
        risk_config_path = Path(risk_config_raw) if risk_config_raw else None

        config = cls(
            exchange_mode=exchange_mode,
            exchange_name=exchange_name,
            pricefeed_name=pricefeed_name,
            pricefeed_timeframe=os.environ.get("TALIM_PRICEFEED_TIMEFRAME", "5m").strip(),
            instruments=tuple(_split_csv(os.environ.get("TALIM_INSTRUMENTS"))),
            strategies=tuple(_split_csv(os.environ.get("TALIM_STRATEGIES"))),
            default_qty=_env_float("TALIM_DEFAULT_QTY", 1.0),
            bar_window=_env_int("TALIM_BAR_WINDOW", 50),
            regime_filters=tuple(
                sorted(parse_regime_filters(os.environ.get("TALIM_REGIME_FILTERS")).items())
            ),
            checkpoint_db=Path(
                os.environ.get("TALIM_CHECKPOINT_DB", "state/talim_checkpoints.db")
            ),
            episodic_db=Path(os.environ.get("TALIM_EPISODIC_DB", "state/episodic.db")),
            backtest_history_db=Path(
                os.environ.get("TALIM_BACKTEST_HISTORY_DB", "state/backtest_history.db")
            ),
            risk_config_path=risk_config_path,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.exchange_mode not in {"mock", "testnet", "live"}:
            raise RuntimeConfigError(
                "TALIM_EXCHANGE_MODE must be one of mock, testnet, live"
            )
        if self.exchange_mode != "mock" and not self.exchange_name:
            raise RuntimeConfigError(
                "TALIM_EXCHANGE_NAME is required when TALIM_EXCHANGE_MODE is "
                f"{self.exchange_mode!r}"
            )
        if self.default_qty <= 0:
            raise RuntimeConfigError("TALIM_DEFAULT_QTY must be positive")
        if self.exchange_mode in {"testnet", "live"}:
            missing: list[str] = []
            if not self.instruments:
                missing.append("TALIM_INSTRUMENTS")
            if not self.strategies:
                missing.append("TALIM_STRATEGIES")
            if missing:
                raise RuntimeConfigError(
                    "live/testnet runtime requires explicit "
                    + ", ".join(missing)
                    + " to avoid accidental default trading"
                )


@dataclass(slots=True)
class Runtime:
    """Bootstrapped live runtime and graph entrypoint wrappers."""

    config: RuntimeConfig
    exchange: Any
    price_feed: Any
    strategies: list[Any]
    episodic: EpisodicMemory
    checkpointer: Any
    pnl_tracker: PnLTracker
    backtest_history: BacktestHistory
    _active_strategies: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Preserve declared order; hot toggles append to the end.
        if not self._active_strategies:
            self._active_strategies = list(self.config.strategies)

    def seed_state(self, extra: TalimState | None = None) -> TalimState:
        """Build the baseline state used for cron/bridge graph invocations."""
        positions = self._positions_with_memory_exit_levels(self._safe_positions())
        state: TalimState = {
            "active_strategies": list(self._active_strategies),
            "active_positions": positions,
        }
        pnl = self._safe_pnl_snapshot()
        if pnl is not None:
            state["account_balance"] = pnl.account_balance
            state["open_pnl"] = pnl.open_pnl
            state["daily_pnl"] = pnl.daily_pnl
        else:
            balance = self._safe_account_balance(positions)
            if balance is not None:
                state["account_balance"] = balance
        if extra:
            state.update(extra)
        return state

    def cron_trigger(
        self,
        *,
        thread_id: str = "cron-main",
        initial_state: TalimState | None = None,
    ) -> TalimState:
        return invoke_cron_trigger(
            initial_state=self.seed_state(initial_state),
            thread_id=thread_id,
            checkpointer=self.checkpointer,
        )

    def bridge_message(self, *, message: str, thread_id: str = "bridge-main") -> TalimState:
        return invoke_bridge_message(
            message=message,
            initial_state=self.seed_state(),
            thread_id=thread_id,
            checkpointer=self.checkpointer,
        )

    def resume(
        self,
        *,
        thread_id: str,
        approved: bool,
        signal_id: str | None = None,
    ) -> TalimState:
        """Resume a pending HITL signal with approval-time safety gates.

        Rejections still clear the pending signal immediately. Approvals first
        refresh broker state, run strategy-specific validation, and rerun risk
        checks before the graph is allowed to continue to execute.
        """
        snapshot = self.snapshot(thread_id=thread_id)
        values = dict(snapshot.values) if snapshot is not None else {}
        pending = values.get("pending_signal")
        pending_json = _jsonable(pending) if pending is not None else None
        current_signal_id = self.episodic.signal_id_for(pending_json) if pending_json else None
        if signal_id and signal_id != current_signal_id:
            message = (
                f"Decision blocked: requested signal {signal_id} is not the "
                f"current pending signal {current_signal_id or 'none'}"
            )
            return {
                "thread_id": thread_id,
                "pending_signal": pending,
                "signal_approved": False,
                "last_action": message,
                "pending_notification": message,
            }  # type: ignore[return-value]
        signal_id = current_signal_id

        if not approved:
            if signal_id:
                self.episodic.update_signal_status(
                    signal_id, status="rejected", actor="operator"
                )
            return resume_graph(
                thread_id=thread_id,
                approved=False,
                checkpointer=self.checkpointer,
            )

        if pending is None or pending_json is None:
            return {
                "thread_id": thread_id,
                "pending_signal": None,
                "signal_approved": False,
                "last_action": "approval blocked: no pending signal",
                "pending_notification": "Approval blocked: no pending signal",
            }  # type: ignore[return-value]

        positions = self._safe_positions()
        pnl = self._safe_pnl_snapshot()
        graph = build_graph(checkpointer=self.checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        validation = self.validate_signal(signal=pending_json, thread_id=thread_id)
        if not validation.get("approval_allowed"):
            status = "expired" if validation.get("status") == "stale" else "invalid"
            reason = validation.get("reason") or "validation blocked approval"
            if signal_id:
                self.episodic.update_signal_status(
                    signal_id,
                    status=status,
                    actor="operator",
                    validation_status=validation.get("status"),
                    validation_reason=reason,
                )
            message = f"Approval blocked for {signal_id or 'pending signal'}: {reason}"
            graph.update_state(config, {
                "pending_notification": message,
                "last_action": message,
            })
            return resume_graph(
                thread_id=thread_id,
                approved=False,
                checkpointer=self.checkpointer,
            )

        risk_state = dict(values)
        risk_state.update({
            "active_positions": positions,
            "pending_signal": pending,
        })
        if pnl is not None:
            risk_state.update({
                "account_balance": pnl.account_balance,
                "open_pnl": pnl.open_pnl,
                "daily_pnl": pnl.daily_pnl,
            })
        risk_update = run_risk_check(risk_state)
        if risk_update.get("pending_signal") is None and risk_update.get("signal_approved") is False:
            reason = risk_update.get("pending_notification") or "risk check blocked approval"
            if signal_id:
                self.episodic.update_signal_status(
                    signal_id,
                    status="invalid",
                    actor="operator",
                    validation_status="risk_changed",
                    validation_reason=reason,
                )
            graph.update_state(config, {
                **risk_update,
                "last_action": reason,
            })
            return resume_graph(
                thread_id=thread_id,
                approved=False,
                checkpointer=self.checkpointer,
            )

        if signal_id:
            self.episodic.update_signal_status(
                signal_id,
                status="approved",
                actor="operator",
                validation_status=validation.get("status"),
                validation_reason=validation.get("reason"),
            )
        graph.update_state(config, {
            "active_positions": positions,
            **({
                "account_balance": pnl.account_balance,
                "open_pnl": pnl.open_pnl,
                "daily_pnl": pnl.daily_pnl,
            } if pnl is not None else {}),
        })
        final = resume_graph(
            thread_id=thread_id,
            approved=True,
            checkpointer=self.checkpointer,
        )
        if signal_id and (final or {}).get("pending_signal") is None:
            last_action = str((final or {}).get("last_action") or "")
            if "executed" in last_action:
                self.episodic.update_signal_status(
                    signal_id, status="executed", actor="operator"
                )
        return final

    def snapshot(self, *, thread_id: str) -> Any:
        """Return the LangGraph state snapshot for a thread, or None."""
        graph = build_graph(checkpointer=self.checkpointer)
        return graph.get_state({"configurable": {"thread_id": thread_id}})

    def _dashboard_url(self, signal_id: str | None = None) -> str | None:
        base = os.environ.get("TALIM_PUBLIC_BASE_URL") or os.environ.get("TALIM_BASE_URL")
        if not base:
            return None
        url = base.rstrip("/") + "/dashboard/"
        if signal_id:
            url += f"signal.html?signal={signal_id}"
        return url

    def pending_signal_status(self, *, thread_id: str) -> dict[str, Any]:
        """Return operator-facing HITL state for a graph thread."""
        snapshot = self.snapshot(thread_id=thread_id)
        values = dict(snapshot.values) if snapshot is not None else {}
        next_nodes = list(getattr(snapshot, "next", ()) or []) if snapshot is not None else []
        exists = bool(values or next_nodes)
        pending = values.get("pending_signal")
        pending_json = _jsonable(pending) if pending is not None else None
        signal_id = None
        dashboard_url = self._dashboard_url()
        if pending_json is not None:
            context = {
                "atr_current": values.get("atr_current"),
                "atr_ratio": values.get("atr_ratio"),
                "regime": values.get("regime"),
                "last_scan_time": values.get("last_scan_time"),
                "pending_notification": values.get("pending_notification"),
            }
            signal_id = self.episodic.record_signal(
                signal=pending_json,
                thread_id=thread_id,
                status="pending",
                context=context,
                dashboard_url=self._dashboard_url(self.episodic.signal_id_for(pending_json)),
            )
            dashboard_url = self._dashboard_url(signal_id)
            pending_json["signal_id"] = signal_id
            try:
                validation = self.validate_signal(signal=pending_json, thread_id=thread_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("runtime: pending signal validation failed", exc_info=True)
                validation = {
                    "status": "data_unavailable",
                    "approval_allowed": False,
                    "reason": f"validation failed: {e}",
                }
            pending_json["validation"] = validation
        else:
            validation = None
        return {
            "thread_id": thread_id,
            "exists": exists,
            "paused": bool(next_nodes and pending is not None),
            "next_nodes": next_nodes,
            "signal_id": signal_id,
            "dashboard_url": dashboard_url,
            "validation": validation,
            "pending_signal": pending_json,
            "pending_notification": values.get("pending_notification"),
            "signal_approved": values.get("signal_approved"),
            "last_action": values.get("last_action"),
        }


    def validate_signal(
        self,
        *,
        signal: Any,
        thread_id: str = "cron-main",
    ) -> dict[str, Any]:
        """Run strategy-specific validation for a pending signal."""
        from talim.models.signal import Signal

        if isinstance(signal, dict):
            payload = {key: value for key, value in signal.items() if key in Signal.__dataclass_fields__}
            sig = Signal.from_dict(payload)
        else:
            sig = signal
        bars = list(scanner_context.get_history(sig.instrument))
        if len(bars) < max(20, self.config.bar_window):
            try:
                self.price_feed.prime_history(sig.instrument, min_bars=max(20, self.config.bar_window))
                self.price_feed.poll_once(sig.instrument)
                bars = list(scanner_context.get_history(sig.instrument))
            except Exception:  # noqa: BLE001
                logger.warning("runtime: failed to refresh bars for signal validation", exc_info=True)
        strat = next((s for s in self.strategies if s.name == sig.strategy), None)
        if strat is None:
            strat = load_strategy(sig.strategy)
        atr = None
        snapshot = self.snapshot(thread_id=thread_id)
        if snapshot is not None:
            values = dict(snapshot.values)
            atr = values.get("atr_current")
        result = strat.validate_signal(sig, bars, atr=atr if isinstance(atr, (int, float)) else None)
        signal_id = self.episodic.signal_id_for(_jsonable(sig))
        self.episodic.update_signal_status(
            signal_id,
            status="pending",
            validation_status=result.status,
            validation_reason=result.reason,
        )
        return result.to_dict()

    def operator_signal(self, *, signal_id: str) -> dict[str, Any] | None:
        """Return one durable signal lifecycle row by public signal id."""
        return self.episodic.get_signal(signal_id)

    def operator_signal_chart(
        self,
        *,
        signal_id: str,
        before: int = 50,
        after: int = 20,
    ) -> dict[str, Any] | None:
        """Return candles and EMA overlays around a durable signal."""
        signal = self.episodic.get_signal(signal_id)
        if signal is None:
            return None

        before = min(max(int(before), 1), 500)
        after = min(max(int(after), 0), 500)
        instrument = str(signal.get("instrument") or "")
        timeframe = self.config.pricefeed_timeframe
        signal_ts = _parse_utc_datetime(
            signal.get("source_bar_timestamp") or signal.get("created_at")
        )
        warnings: list[str] = []
        if signal_ts is None:
            return self._empty_signal_chart(
                signal=signal,
                before=before,
                after=after,
                timeframe=timeframe,
                source="none",
                status="data_unavailable",
                warnings=["signal has no parseable source timestamp"],
            )

        bars, source, source_warnings = self._chart_bars(
            instrument=instrument,
            signal_ts=signal_ts,
            before=before,
            after=after,
            timeframe=timeframe,
        )
        warnings.extend(source_warnings)
        if not bars:
            return self._empty_signal_chart(
                signal=signal,
                before=before,
                after=after,
                timeframe=timeframe,
                source=source,
                status="data_unavailable",
                warnings=warnings or ["no bars available around signal"],
            )

        index = self._signal_bar_index(bars, signal_ts)
        if index is None:
            warnings.append("source bar timestamp was not present in returned bars")
            index = min(range(len(bars)), key=lambda i: abs((_bar_time_utc(bars[i]) - signal_ts).total_seconds()))

        start = max(0, index - before)
        end = min(len(bars), index + after + 1)
        selected = bars[start:end]
        closes = [float(bar.close) for bar in selected]
        ema_fast = ema(closes, 8)
        ema_slow = ema(closes, 21)
        candle_payload = [self._chart_bar_payload(bar) for bar in selected]
        fast_payload = [
            {"time": candle_payload[i]["time"], "value": round(value, 6)}
            for i, value in enumerate(ema_fast)
        ]
        slow_payload = [
            {"time": candle_payload[i]["time"], "value": round(value, 6)}
            for i, value in enumerate(ema_slow)
        ]
        visible_signal_index = index - start
        status = "ok"
        if visible_signal_index < 20:
            status = "partial"
            warnings.append(
                f"only {visible_signal_index} pre-signal bars available; requested at least 20"
            )

        return {
            "signal_id": signal.get("signal_id"),
            "status": status,
            "source": source,
            "timeframe": timeframe,
            "requested": {"before": before, "after": after},
            "signal": {
                "timestamp": signal_ts.isoformat(),
                "visible_index": visible_signal_index,
                "instrument": instrument,
                "strategy": signal.get("strategy"),
                "side": signal.get("side"),
                "entry_price": signal.get("entry_price"),
                "stop": signal.get("stop"),
                "target": signal.get("target"),
                "rationale": signal.get("rationale"),
                "regime": signal.get("regime"),
                "latest_validation_status": signal.get("latest_validation_status"),
                "latest_validation_reason": signal.get("latest_validation_reason"),
            },
            "candles": candle_payload,
            "indicators": {
                "ema_fast": {"period": 8, "values": fast_payload},
                "ema_slow": {"period": 21, "values": slow_payload},
            },
            "levels": {
                "entry": signal.get("entry_price"),
                "stop": signal.get("stop"),
                "target": signal.get("target"),
            },
            "warnings": warnings,
        }

    def _empty_signal_chart(
        self,
        *,
        signal: dict[str, Any],
        before: int,
        after: int,
        timeframe: str,
        source: str,
        status: str,
        warnings: list[str],
    ) -> dict[str, Any]:
        return {
            "signal_id": signal.get("signal_id"),
            "status": status,
            "source": source,
            "timeframe": timeframe,
            "requested": {"before": before, "after": after},
            "signal": {
                "timestamp": signal.get("source_bar_timestamp") or signal.get("created_at"),
                "instrument": signal.get("instrument"),
                "strategy": signal.get("strategy"),
                "side": signal.get("side"),
                "entry_price": signal.get("entry_price"),
                "stop": signal.get("stop"),
                "target": signal.get("target"),
                "rationale": signal.get("rationale"),
                "regime": signal.get("regime"),
                "latest_validation_status": signal.get("latest_validation_status"),
                "latest_validation_reason": signal.get("latest_validation_reason"),
            },
            "candles": [],
            "indicators": {
                "ema_fast": {"period": 8, "values": []},
                "ema_slow": {"period": 21, "values": []},
            },
            "levels": {
                "entry": signal.get("entry_price"),
                "stop": signal.get("stop"),
                "target": signal.get("target"),
            },
            "warnings": warnings,
        }

    def _chart_bars(
        self,
        *,
        instrument: str,
        signal_ts: datetime,
        before: int,
        after: int,
        timeframe: str,
    ) -> tuple[list[Any], str, list[str]]:
        warnings: list[str] = []
        needed = before + after + 1
        history = [
            bar for bar in scanner_context.get_history(instrument)
            if getattr(bar, "instrument", None) == instrument
        ]
        history.sort(key=_bar_time_utc)
        if self._signal_bar_index(history, signal_ts) is not None:
            return history, "scanner_history", warnings

        delta = _parse_timeframe_delta(timeframe)
        fetch_count = max(needed + 30, 100)
        if hasattr(self.price_feed, "fetch_bars_before"):
            try:
                to_ts = int((signal_ts + delta * (after + 1)).timestamp())
                bars = self.price_feed.fetch_bars_before(
                    instrument,
                    to_timestamp_utc=to_ts,
                    count=fetch_count,
                )
                bars = list(bars)
                bars.sort(key=_bar_time_utc)
                if bars:
                    return bars, "broker_history", warnings
            except Exception as e:  # noqa: BLE001
                logger.warning("runtime: failed to fetch broker chart history", exc_info=True)
                warnings.append(f"broker history fetch failed: {e}")

        if hasattr(self.price_feed, "fetch_recent_bars"):
            try:
                bars = self.price_feed.fetch_recent_bars(
                    instrument,
                    total_bars=max(needed, self.config.bar_window),
                )
                bars = list(bars)
                bars.sort(key=_bar_time_utc)
                if bars:
                    return bars, "broker_recent", warnings
            except Exception as e:  # noqa: BLE001
                logger.warning("runtime: failed to fetch recent chart history", exc_info=True)
                warnings.append(f"recent history fetch failed: {e}")

        if history:
            warnings.append("scanner history does not include the signal source bar")
            return history, "scanner_history", warnings
        return [], "none", warnings

    @staticmethod
    def _signal_bar_index(bars: list[Any], signal_ts: datetime) -> int | None:
        for i, bar in enumerate(bars):
            if _bar_time_utc(bar) == signal_ts:
                return i
        return None

    @staticmethod
    def _chart_bar_payload(bar: Any) -> dict[str, Any]:
        return {
            "time": _bar_time_utc(bar).isoformat(),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        }

    def operator_status(self) -> dict[str, Any]:
        """Return a compact runtime status for operator clients."""
        positions = self._safe_positions()
        balance = self._safe_account_balance(positions)
        pnl = self._safe_pnl_snapshot()
        return {
            "exchange_mode": self.config.exchange_mode,
            "exchange_name": self.config.exchange_name or "mock",
            "pricefeed_name": self.config.pricefeed_name,
            "pricefeed_timeframe": self.config.pricefeed_timeframe,
            "instruments": list(self.config.instruments),
            "strategies": list(self.config.strategies),
            "subscriptions": sorted(self.price_feed.subscriptions),
            "pricefeed_connected": bool(self.price_feed.is_connected),
            "default_qty": self.config.default_qty,
            "position_count": len(positions),
            "account_balance": balance,
            "open_pnl": pnl.open_pnl if pnl is not None else None,
            "daily_pnl": pnl.daily_pnl if pnl is not None else None,
        }

    def operator_positions(self) -> list[dict[str, Any]]:
        """Return broker positions serialised for operator clients."""
        return [_jsonable(position) for position in self._safe_positions()]

    def operator_positions_dashboard(self) -> dict[str, Any]:
        """Return broker positions enriched with live quote-derived marks."""
        positions = self._positions_with_memory_exit_levels(self._safe_positions())
        enriched = [self._enrich_position(position) for position in positions]
        total_mark_pnl = sum(
            float(pos.get("mark_open_pnl") or 0.0)
            for pos in enriched
            if pos.get("mark_open_pnl") is not None
        )
        total_broker_pnl = sum(float(pos.get("broker_open_pnl") or 0.0) for pos in enriched)
        return {
            "summary": {
                "position_count": len(enriched),
                "mark_open_pnl": total_mark_pnl,
                "broker_open_pnl": total_broker_pnl,
                "timeframe": self.config.pricefeed_timeframe,
                "pricefeed_connected": bool(self.price_feed.is_connected),
                "exchange_name": self.config.exchange_name or "mock",
                "exchange_mode": self.config.exchange_mode,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "positions": enriched,
        }

    def operator_position_chart(self, *, position_id: str, bars: int = 240) -> dict[str, Any] | None:
        """Return recent candles and EMA overlays for one open position."""
        positions = self._positions_with_memory_exit_levels(self._safe_positions())
        match = None
        for position in positions:
            if str(getattr(position, "position_id", "") or "") == str(position_id):
                match = self._enrich_position(position)
                break
        if match is None:
            return None

        instrument = str(match.get("instrument") or "")
        bars = min(max(int(bars), 20), 500)
        warnings: list[str] = []
        source = "none"
        recent: list[Any] = []
        if hasattr(self.price_feed, "fetch_recent_bars"):
            try:
                recent = list(self.price_feed.fetch_recent_bars(instrument, total_bars=bars))
                recent.sort(key=_bar_time_utc)
                source = "broker_recent" if recent else "none"
            except Exception as e:  # noqa: BLE001
                logger.warning("runtime: failed to fetch open-position chart history", exc_info=True)
                warnings.append(f"recent history fetch failed: {e}")

        if not recent:
            history = [
                bar for bar in scanner_context.get_history(instrument)
                if getattr(bar, "instrument", None) == instrument
            ]
            history.sort(key=_bar_time_utc)
            recent = history[-bars:]
            source = "scanner_history" if recent else source
            if recent:
                warnings.append("using scanner history fallback")

        if not recent:
            recent = self._position_tick_bars(instrument, total_bars=bars)
            source = "broker_ticks" if recent else source
            if recent:
                warnings.append("using FOREX.com tick fallback; candles are tick-derived")

        candle_payload = [self._chart_bar_payload(bar) for bar in recent]
        closes = [float(bar.close) for bar in recent]
        ema_fast = ema(closes, 8) if closes else []
        ema_slow = ema(closes, 21) if closes else []
        fast_payload = [
            {"time": candle_payload[i]["time"], "value": round(value, 6)}
            for i, value in enumerate(ema_fast)
        ]
        slow_payload = [
            {"time": candle_payload[i]["time"], "value": round(value, 6)}
            for i, value in enumerate(ema_slow)
        ]
        if not candle_payload and not warnings:
            warnings.append("no recent bars available for this instrument")

        return {
            "position_id": match.get("position_id"),
            "status": "ok" if candle_payload else "data_unavailable",
            "source": source,
            "timeframe": self.config.pricefeed_timeframe,
            "requested": {"bars": bars},
            "position": match,
            "candles": candle_payload,
            "indicators": {
                "ema_fast": {"period": 8, "values": fast_payload},
                "ema_slow": {"period": 21, "values": slow_payload},
            },
            "levels": {
                "entry": match.get("entry_price"),
                "mark": match.get("mark_price"),
                "stop": match.get("stop"),
                "target": match.get("target"),
            },
            "warnings": warnings,
        }

    def _enrich_position(self, position: Any) -> dict[str, Any]:
        data = _jsonable(position)
        broker_pnl = data.get("open_pnl")
        data["broker_open_pnl"] = broker_pnl
        data["mark_open_pnl"] = broker_pnl
        data["pnl_source"] = "broker"
        instrument = str(data.get("instrument") or "")
        side = str(data.get("side") or "").lower()
        try:
            entry = float(data.get("entry_price") or 0.0)
            qty = float(data.get("qty") or 0.0)
        except (TypeError, ValueError):
            return data
        if not instrument or not side or qty <= 0 or entry <= 0:
            return data

        quote = self._position_quote(instrument)
        if quote is None:
            if broker_pnl in (None, 0, 0.0):
                data["pnl_source"] = "unavailable"
            return data

        bid = getattr(quote, "bid", None)
        offer = getattr(quote, "offer", None)
        data["bid"] = bid
        data["offer"] = offer
        mark_price = offer if side == "short" else bid
        if mark_price is None:
            return data
        mark_price = float(mark_price)
        mark_pnl = (entry - mark_price) * qty if side == "short" else (mark_price - entry) * qty
        data["mark_price"] = mark_price
        data["mark_open_pnl"] = mark_pnl
        data["open_pnl"] = mark_pnl
        data["pnl_source"] = "live_quote"
        return data

    def _position_quote(self, instrument: str) -> Any | None:
        if not hasattr(self.exchange, "get_quote"):
            return None
        try:
            return self.exchange.get_quote(instrument)
        except Exception:  # noqa: BLE001
            logger.warning("runtime: failed to fetch quote for open position %s", instrument, exc_info=True)
            return None

    def _position_tick_bars(self, instrument: str, *, total_bars: int) -> list[OHLCVBar]:
        """Return tick-derived bars for broker connectors without candle history."""
        if not hasattr(self.exchange, "fetch_recent_ticks"):
            return []
        try:
            ticks = self.exchange.fetch_recent_ticks(
                instrument,
                limit=min(max(int(total_bars), 20), 500),
            )
        except Exception:  # noqa: BLE001
            logger.warning("runtime: failed to fetch tick chart for open position %s", instrument, exc_info=True)
            return []

        out: list[OHLCVBar] = []
        for idx, tick in enumerate(ticks):
            ts = tick.timestamp
            if ts is None:
                ts = datetime.now(timezone.utc) - timedelta(seconds=len(ticks) - idx)
            close = tick.price
            out.append(
                OHLCVBar(
                    instrument=instrument,
                    timestamp=ts,
                    open=close,
                    high=max(tick.bid, tick.offer, close),
                    low=min(tick.bid, tick.offer, close),
                    close=close,
                    volume=0.0,
                    timeframe=self.config.pricefeed_timeframe,
                )
            )
        out.sort(key=_bar_time_utc)
        return out[-total_bars:]

    def operator_decisions(
        self,
        *,
        limit: int = 20,
        instrument: str | None = None,
        strategy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent episodic decisions, newest first."""
        rows = self.episodic.query_decisions(instrument=instrument, strategy=strategy)
        return rows[-limit:][::-1]

    def operator_strategies(self) -> dict[str, Any]:
        """Return active + available strategy names for the operator.

        ``active`` reflects the live runtime toggle set; ``available`` lists
        every loadable strategy on disk (whether active or not).
        """
        available = _discover_strategies()
        return {
            "active": list(self._active_strategies),
            "available": available,
        }

    def enable_strategy(self, name: str, *, actor: str = "operator") -> dict[str, Any]:
        """Activate ``name`` in the runtime.

        Raises ``FileNotFoundError`` when the module cannot be loaded. Idempotent
        re-enables are recorded as audit rows with ``notes='noop'``.
        """
        if name not in self._active_strategies:
            # Fail fast: bail before mutating state if the module doesn't load.
            instance = load_strategy(name)
            try:
                from talim.app.nodes.signal_scanner import _context as _scanner_ctx
                _scanner_ctx.add_strategy(instance)
            except Exception:  # noqa: BLE001
                logger.warning("runtime: scanner registration failed", exc_info=True)
            self._active_strategies.append(name)
            notes = ""
        else:
            notes = "noop"
        self.episodic.record_activation(
            strategy=name,
            action="enable",
            actor=actor,
            notes=notes,
        )
        return self.operator_strategies()

    def disable_strategy(self, name: str, *, actor: str = "operator") -> dict[str, Any]:
        """Deactivate ``name``. Does not clear pending HITL signals already in flight."""
        if name in self._active_strategies:
            self._active_strategies.remove(name)
            notes = ""
        else:
            notes = "noop"
        self.episodic.record_activation(
            strategy=name,
            action="disable",
            actor=actor,
            notes=notes,
        )
        return self.operator_strategies()

    def operator_backtests(
        self,
        *,
        strategy: str | None = None,
        instrument: str | None = None,
        triggered_by: str | None = None,
        status: str | None = None,
        timeframe: str | None = None,
        since: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return recent backtest runs, newest first."""
        return self.backtest_history.list_runs(
            strategy=strategy,
            instrument=instrument,
            triggered_by=triggered_by,
            status=status,
            timeframe=timeframe,
            since=since,
            limit=limit,
            offset=offset,
        )

    def operator_backtest_outcomes(
        self,
        *,
        strategy: str | None = None,
        instrument: str | None = None,
        exclude_triggered_by: str | None = None,
        status: str | None = None,
        timeframe: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return grouped strategy outcomes built from backtest summary rows."""
        return self.backtest_history.list_outcomes(
            strategy=strategy,
            instrument=instrument,
            exclude_triggered_by=exclude_triggered_by,
            status=status,
            timeframe=timeframe,
            since=since,
            limit=limit,
        )

    def operator_backtest(self, run_id: int) -> dict[str, Any]:
        """Return one backtest run by id. Raises KeyError if not found."""
        row = self.backtest_history.get_run(run_id)
        if row is None:
            raise KeyError(run_id)
        return row

    def operator_strategy_params(self, strategy_name: str) -> dict[str, Any]:
        """Return the parameter schema and current values for one strategy.

        Raises ``KeyError`` when the strategy is not registered with this
        runtime, and ``FileNotFoundError`` when the module cannot be loaded.
        """
        from talim.strategy.loader import load_strategy

        if strategy_name not in self.config.strategies:
            raise KeyError(strategy_name)
        instance = load_strategy(strategy_name)
        return {
            "strategy": strategy_name,
            "schema": instance.params_schema(),
            "current": instance.current_params(),
        }

    def sync_state(self, *, thread_id: str = "cron-main") -> dict[str, Any]:
        """Refresh broker state, run reconciliation, and persist safe snapshots."""
        graph = build_graph(checkpointer=self.checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = graph.get_state(config)
        values = dict(snapshot.values) if snapshot is not None else {}
        next_nodes = list(getattr(snapshot, "next", ()) or []) if snapshot is not None else []
        paused = bool(next_nodes and values.get("pending_signal") is not None)

        positions = self._positions_with_memory_exit_levels(list(self.exchange.get_positions()))
        pnl = self.pnl_tracker.refresh(self.exchange)
        repairs = reconcile_positions(
            self.exchange,
            self.episodic,
            state_positions=values.get("active_positions") or [],
        )
        notification = format_repair_notification(repairs)

        state_updated = False
        if not paused:
            update: TalimState = {
                "thread_id": thread_id,
                "active_positions": positions,
                "account_balance": pnl.account_balance,
                "open_pnl": pnl.open_pnl,
                "daily_pnl": pnl.daily_pnl,
                "last_action": "synced broker state",
                "pending_notification": notification,
            }
            graph.update_state(config, update)
            state_updated = True

        return {
            "thread_id": thread_id,
            "snapshot_exists": bool(values or next_nodes),
            "paused": paused,
            "next_nodes": next_nodes,
            "state_updated": state_updated,
            "position_count": len(positions),
            "positions": _jsonable(positions),
            "pnl": pnl.to_dict(),
            "repair_count": len(repairs),
            "repairs": [repair.to_dict() for repair in repairs],
            "pending_notification": notification,
        }

    def _safe_positions(self) -> list[Any]:
        try:
            return list(self.exchange.get_positions())
        except Exception:  # noqa: BLE001
            logger.warning("runtime: failed to refresh positions", exc_info=True)
            return []

    def _positions_with_memory_exit_levels(self, positions: list[Any]) -> list[Any]:
        """Overlay approved stop/target levels when the broker omits them.

        FOREX.com open-position lots may report Stop/Limit as absent even when
        Talim's approved signal had protective levels. The position monitor
        needs those original levels to enforce app-side exits.
        """
        if not positions or self.episodic is None:
            return positions
        try:
            decisions = self.episodic.query_decisions(outcome="pending")
        except Exception:  # noqa: BLE001
            logger.warning("runtime: failed to query decision memory for exit levels", exc_info=True)
            return positions

        pending_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for decision in decisions:
            instrument = str(decision.get("instrument") or "")
            side = str(decision.get("side") or "")
            if instrument and side:
                pending_by_key[(instrument, side)] = decision

        enriched: list[Any] = []
        for position in positions:
            instrument = str(getattr(position, "instrument", "") or "")
            side = str(getattr(position, "side", "") or "")
            decision = pending_by_key.get((instrument, side))
            if decision is None:
                enriched.append(position)
                continue
            try:
                memory_stop = float(decision.get("stop") or 0.0)
                memory_target = float(decision.get("target") or 0.0)
            except (TypeError, ValueError):
                enriched.append(position)
                continue
            stop = float(getattr(position, "stop", 0.0) or 0.0)
            target = float(getattr(position, "target", 0.0) or 0.0)
            strategy = str(decision.get("strategy") or getattr(position, "strategy", "") or "")
            updates: dict[str, Any] = {}
            if stop <= 0 and memory_stop > 0:
                updates["stop"] = memory_stop
            if target <= 0 and memory_target > 0:
                updates["target"] = memory_target
            if strategy and not getattr(position, "strategy", ""):
                updates["strategy"] = strategy
            if updates:
                enriched.append(dc_replace(position, **updates))
            else:
                enriched.append(position)
        return enriched

    def _safe_pnl_snapshot(self) -> PnLSnapshot | None:
        try:
            return self.pnl_tracker.refresh(self.exchange)
        except Exception:  # noqa: BLE001
            logger.warning("runtime: failed to refresh pnl snapshot", exc_info=True)
            return None

    def _safe_account_balance(self, positions: list[Any]) -> float | None:
        try:
            _, balance = select_account_balance(
                self.exchange.get_account_balance(),
                positions,
            )
            return balance
        except Exception:  # noqa: BLE001
            logger.warning("runtime: failed to refresh account balance", exc_info=True)
            return None


def _discover_strategies() -> list[str]:
    """List every strategy directory under ``strategies/`` with a ``strategy.py``."""
    root = Path(__file__).resolve().parent.parent.parent / "strategies"
    if not root.is_dir():
        return []
    names = [
        entry.name
        for entry in sorted(root.iterdir())
        if entry.is_dir() and (entry / "strategy.py").exists()
    ]
    return names


def _ensure_parent(path: Path) -> None:
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _load_risk_rules(path: Path | None) -> RiskRules:
    if path is None:
        return RiskRules()
    if not path.exists():
        logger.warning("runtime: risk config %s not found; using defaults", path)
        return RiskRules()
    try:
        return load_validated_config(path)
    except RiskConfigError:
        raise
    except Exception as e:  # noqa: BLE001
        raise RuntimeConfigError(f"failed to load risk config {path}: {e}") from e


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_mock_execution_data(n: int = 180, freq: str = "5min") -> Any:
    """Create deterministic mock bars that make the baseline momentum strategy fire."""
    import numpy as np
    import pandas as pd

    close = 5000.0 + 60.0 * np.sin(np.arange(n) * 0.15)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-06-15 09:30", periods=n, freq=freq),
        "open": close,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(n, 10_000.0),
    })


def _seed_mock_demo_data(config: RuntimeConfig, exchange: Any, price_feed: Any) -> None:
    """Optionally warm the mock runtime so HTTP HITL validation can run end-to-end."""
    if config.exchange_mode != "mock" or config.pricefeed_name != "mock":
        return
    if not _env_bool("TALIM_MOCK_DEMO_DATA"):
        return
    if not all(hasattr(price_feed, name) for name in ("load", "connect", "replay")):
        logger.warning("runtime: TALIM_MOCK_DEMO_DATA requested but price feed is not loadable")
        return

    price_feed.load(_build_mock_execution_data())
    price_feed.connect()
    price_feed.replay()

    if hasattr(exchange, "set_fill_price"):
        fill_price = _env_float("TALIM_MOCK_FILL_PRICE", 5000.0)
        for instrument in config.instruments or ("ES",):
            exchange.set_fill_price(instrument, fill_price)

    logger.info(
        "runtime: loaded deterministic mock demo data for instruments=%s",
        list(config.instruments),
    )


def bootstrap_runtime(config: RuntimeConfig | None = None) -> Runtime:
    """Create and wire the runtime according to env/config."""
    config = config or RuntimeConfig.from_env()

    _ensure_parent(config.checkpoint_db)
    _ensure_parent(config.episodic_db)
    _ensure_parent(config.backtest_history_db)

    exchange = create_exchange(
        mode=config.exchange_mode,
        exchange_name=config.exchange_name,
    )
    price_feed = create_pricefeed(
        config.pricefeed_name,
        timeframe=config.pricefeed_timeframe,
    )
    for instrument in config.instruments:
        price_feed.subscribe(instrument)

    strategies = [load_strategy(name) for name in config.strategies]
    episodic = EpisodicMemory(config.episodic_db)
    backtest_history = BacktestHistory(config.backtest_history_db)
    checkpointer = create_checkpointer(str(config.checkpoint_db))

    configure_scanner(
        price_feed,
        strategies=strategies,
        bar_window=config.bar_window,
        regime_filters=dict(config.regime_filters),
    )
    _seed_mock_demo_data(config, exchange, price_feed)
    configure_execute(
        exchange,
        episodic=episodic,
        default_qty=config.default_qty,
    )
    configure_risk_rules(_load_risk_rules(config.risk_config_path))

    logger.info(
        "runtime: bootstrapped exchange=%s/%s pricefeed=%s timeframe=%s "
        "instruments=%s strategies=%s qty=%s",
        config.exchange_mode,
        config.exchange_name or "mock",
        config.pricefeed_name,
        config.pricefeed_timeframe,
        ",".join(config.instruments) or "-",
        ",".join(config.strategies) or "-",
        config.default_qty,
    )

    return Runtime(
        config=config,
        exchange=exchange,
        price_feed=price_feed,
        strategies=strategies,
        episodic=episodic,
        checkpointer=checkpointer,
        pnl_tracker=PnLTracker(),
        backtest_history=backtest_history,
    )
