"""Runtime bootstrap for live/paper Talim deployments.

This module is the production composition root: it reads environment/config,
creates the selected exchange and price feed, subscribes instruments, loads
strategies, and wires the module-level node contexts used by the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
from typing import Any

from talim.app.checkpointer import create_checkpointer
from talim.app.entrypoints import bridge_message as invoke_bridge_message
from talim.app.entrypoints import cron_trigger as invoke_cron_trigger
from talim.app.execute_context import configure_execute
from talim.app.graph import build_graph
from talim.app.nodes.reconcile import format_repair_notification, reconcile_positions
from talim.app.nodes.risk_check import configure_risk_rules
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
from talim.strategy.loader import load_strategy

logger = logging.getLogger("talim.app.runtime")


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
        positions = self._safe_positions()
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

    def resume(self, *, thread_id: str, approved: bool) -> TalimState:
        return resume_graph(
            thread_id=thread_id,
            approved=approved,
            checkpointer=self.checkpointer,
        )

    def snapshot(self, *, thread_id: str) -> Any:
        """Return the LangGraph state snapshot for a thread, or None."""
        graph = build_graph(checkpointer=self.checkpointer)
        return graph.get_state({"configurable": {"thread_id": thread_id}})

    def pending_signal_status(self, *, thread_id: str) -> dict[str, Any]:
        """Return operator-facing HITL state for a graph thread."""
        snapshot = self.snapshot(thread_id=thread_id)
        values = dict(snapshot.values) if snapshot is not None else {}
        next_nodes = list(getattr(snapshot, "next", ()) or []) if snapshot is not None else []
        exists = bool(values or next_nodes)
        pending = values.get("pending_signal")
        return {
            "thread_id": thread_id,
            "exists": exists,
            "paused": bool(next_nodes),
            "next_nodes": next_nodes,
            "pending_signal": _jsonable(pending) if pending is not None else None,
            "pending_notification": values.get("pending_notification"),
            "signal_approved": values.get("signal_approved"),
            "last_action": values.get("last_action"),
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
        status: str | None = None,
        timeframe: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return grouped strategy outcomes built from backtest summary rows."""
        return self.backtest_history.list_outcomes(
            strategy=strategy,
            instrument=instrument,
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
        paused = bool(next_nodes)

        positions = list(self.exchange.get_positions())
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
            }
            if notification is not None:
                update["pending_notification"] = notification
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
