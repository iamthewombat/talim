from __future__ import annotations

from typing import TypedDict

import numpy as np

from talim.models.bar import OHLCVBar
from talim.models.position import Position
from talim.models.signal import Signal
from talim.models.backtest import BacktestRequest, BacktestResult


class TalimState(TypedDict, total=False):
    """Full LangGraph state schema for Talim."""

    # --- Market data (updated by signal_scanner) ---
    current_bar: OHLCVBar | None
    last_tick: OHLCVBar | None  # alias for the most recently observed bar
    instrument: str | None  # primary instrument the scanner is watching
    atr_current: float
    atr_ratio: float  # current ATR vs historical average

    # --- Regime (updated by signal_scanner) ---
    regime: str  # e.g. "momentum", "mean_reversion", "high_vol", "ranging"
    regime_fingerprint: list[float]  # 6-feature vector (serialised from np.ndarray)
    regime_changed: bool

    # --- Signals & trading ---
    pending_signal: Signal | None
    signal_approved: bool | None  # HITL result
    active_positions: list[Position]
    account_balance: float
    open_pnl: float  # mark-to-market P&L of open positions
    daily_pnl: float  # realised P&L for the current trading day
    last_action: str | None  # short tag describing the most recent action

    # --- Strategy ---
    active_strategies: list[str]  # strategy names currently enabled
    strategy_params: dict[str, dict]  # strategy_name -> current params

    # --- Backtest ---
    pending_backtest: BacktestRequest | None
    backtest_result: list[BacktestResult] | None

    # --- Conversation (bridge path) ---
    last_user_message: str | None
    response_message: str | None
    discord_thread_id: str | None
    messages: list[dict]  # rolling chat history [{role, content, ts}, ...]

    # --- Notifications ---
    pending_notification: str | None

    # --- Meta ---
    thread_id: str
    last_scan_time: str | None  # ISO timestamp of last cron scan
    halted: bool  # kill switch — blocks all new signals at the router


# Canonical list of all state fields for completeness checks
TALIM_STATE_FIELDS: set[str] = set(TalimState.__annotations__.keys())
