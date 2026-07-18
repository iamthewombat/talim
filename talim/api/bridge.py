"""Talim bridge HTTP API (WP-16, WP-38, WP-39)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from talim.api.auth import (
    clear_session_cookie,
    require_secret,
    session_max_age_seconds,
    set_session_cookie,
    verify_secret,
    verify_session_token,
)
from talim.metrics import METRICS

_STATIC_DIR = Path(__file__).resolve().parent / "static"

logger = logging.getLogger("talim.api.bridge")


class ConverseRequest(BaseModel):
    message: str = Field(..., min_length=1)
    thread_id: str = Field(default="bridge-main")


class ConverseResponse(BaseModel):
    thread_id: str
    response_message: str | None = None
    state_keys: list[str] = Field(default_factory=list)


class ResumeRequest(BaseModel):
    thread_id: str
    approved: bool


class ResumeResponse(BaseModel):
    thread_id: str
    approved: bool
    pending_signal_cleared: bool


class TriggerResponse(BaseModel):
    thread_id: str
    triggered: bool
    state_keys: list[str] = Field(default_factory=list)


class SyncResponse(BaseModel):
    thread_id: str
    snapshot_exists: bool
    paused: bool
    next_nodes: list[str] = Field(default_factory=list)
    state_updated: bool
    position_count: int
    positions: list[dict[str, Any]] = Field(default_factory=list)
    pnl: dict[str, Any]
    repair_count: int
    repairs: list[dict[str, Any]] = Field(default_factory=list)
    pending_notification: str | None = None


class HaltResponse(BaseModel):
    halted: bool


class DashboardLoginRequest(BaseModel):
    secret: str = Field(..., min_length=1)


class DashboardSessionResponse(BaseModel):
    authenticated: bool
    max_age_seconds: int


class OperatorStatusResponse(BaseModel):
    halted: bool
    runtime: dict[str, Any]


class PendingSignalResponse(BaseModel):
    thread_id: str
    exists: bool
    paused: bool
    next_nodes: list[str] = Field(default_factory=list)
    signal_id: str | None = None
    dashboard_url: str | None = None
    validation: dict[str, Any] | None = None
    pending_signal: dict[str, Any] | None = None
    pending_notification: str | None = None
    signal_approved: bool | None = None
    last_action: str | None = None


class OperatorSignalResponse(BaseModel):
    signal: dict[str, Any]


class OperatorSignalChartResponse(BaseModel):
    signal_id: str | None = None
    status: str
    source: str
    timeframe: str
    requested: dict[str, Any]
    signal: dict[str, Any]
    candles: list[dict[str, Any]] = Field(default_factory=list)
    indicators: dict[str, Any] = Field(default_factory=dict)
    levels: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class OperatorDecisionRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    approved: bool
    signal_id: str | None = None


class OperatorDecisionResponse(BaseModel):
    thread_id: str
    approved: bool
    pending_signal_cleared: bool
    last_action: str | None = None


class OperatorPositionsResponse(BaseModel):
    positions: list[dict[str, Any]] = Field(default_factory=list)


class OperatorPositionsDashboardResponse(BaseModel):
    summary: dict[str, Any] = Field(default_factory=dict)
    positions: list[dict[str, Any]] = Field(default_factory=list)


class OperatorPositionChartResponse(BaseModel):
    position_id: str | None = None
    status: str
    source: str
    timeframe: str
    requested: dict[str, Any]
    position: dict[str, Any]
    candles: list[dict[str, Any]] = Field(default_factory=list)
    indicators: dict[str, Any] = Field(default_factory=dict)
    levels: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class OperatorDecisionsResponse(BaseModel):
    decisions: list[dict[str, Any]] = Field(default_factory=list)


class OperatorStrategyParamsResponse(BaseModel):
    strategy: str
    schema_: list[dict[str, Any]] = Field(default_factory=list, alias="schema")
    current: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class OperatorBacktestsResponse(BaseModel):
    runs: list[dict[str, Any]] = Field(default_factory=list)
    limit: int
    offset: int


class OperatorBacktestOutcomesResponse(BaseModel):
    outcomes: list[dict[str, Any]] = Field(default_factory=list)
    limit: int


class OperatorBacktestResponse(BaseModel):
    run: dict[str, Any]


class OperatorStrategiesListResponse(BaseModel):
    active: list[str] = Field(default_factory=list)
    available: list[str] = Field(default_factory=list)


class OperatorStrategyToggleResponse(BaseModel):
    strategy: str
    action: str
    active: list[str] = Field(default_factory=list)
    available: list[str] = Field(default_factory=list)


# Module-level halt flag shared across all requests in this process.
_halt_state: dict[str, bool] = {"halted": False}


def is_halted() -> bool:
    return _halt_state["halted"]


def set_halted(value: bool) -> None:
    _halt_state["halted"] = value


def create_app(
    bridge_message_fn: Callable[..., dict[str, Any]] | None = None,
    resume_fn: Callable[..., dict[str, Any]] | None = None,
    cron_trigger_fn: Callable[..., dict[str, Any]] | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    All functions are injectable for tests. Defaults wire up the production
    LangGraph entry points.
    """
    runtime = None
    if bridge_message_fn is None and resume_fn is None and cron_trigger_fn is None:
        from talim.app.runtime import bootstrap_runtime

        runtime = bootstrap_runtime()
        bridge_message_fn = runtime.bridge_message
        resume_fn = runtime.resume
        cron_trigger_fn = runtime.cron_trigger

    if bridge_message_fn is None:
        from talim.app.entrypoints import bridge_message as _default_bridge
        bridge_message_fn = _default_bridge
    if resume_fn is None:
        from talim.app.resume import resume_graph as _default_resume
        resume_fn = _default_resume
    if cron_trigger_fn is None:
        from talim.app.entrypoints import cron_trigger as _default_cron
        cron_trigger_fn = _default_cron

    app = FastAPI(title="Talim Bridge", version="0.1.0")
    app.state.talim_runtime = runtime

    def require_runtime():
        current = getattr(app.state, "talim_runtime", None)
        if current is None:
            raise HTTPException(status_code=503, detail="Talim runtime is not bootstrapped")
        return current

    @app.get("/talim/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/talim/auth/session", response_model=DashboardSessionResponse)
    def dashboard_session(
        talim_dashboard_session: str | None = Cookie(default=None, alias="talim_dashboard_session"),
    ) -> DashboardSessionResponse:
        return DashboardSessionResponse(
            authenticated=verify_session_token(talim_dashboard_session),
            max_age_seconds=session_max_age_seconds(),
        )

    @app.post("/talim/auth/login", response_model=DashboardSessionResponse)
    def dashboard_login(req: DashboardLoginRequest, response: Response) -> DashboardSessionResponse:
        if not verify_secret(req.secret):
            raise HTTPException(status_code=401, detail="invalid Talim bridge secret")
        set_session_cookie(response)
        return DashboardSessionResponse(
            authenticated=True,
            max_age_seconds=session_max_age_seconds(),
        )

    @app.post("/talim/auth/logout", response_model=DashboardSessionResponse)
    def dashboard_logout(response: Response) -> DashboardSessionResponse:
        clear_session_cookie(response)
        return DashboardSessionResponse(
            authenticated=False,
            max_age_seconds=session_max_age_seconds(),
        )

    if _STATIC_DIR.is_dir():
        app.mount(
            "/talim/dashboard",
            StaticFiles(directory=_STATIC_DIR, html=True),
            name="dashboard",
        )

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return METRICS.render()

    @app.post(
        "/talim/converse",
        response_model=ConverseResponse,
        dependencies=[Depends(require_secret)],
    )
    def converse(req: ConverseRequest) -> ConverseResponse:
        logger.info("converse: thread=%s", req.thread_id)
        final = bridge_message_fn(message=req.message, thread_id=req.thread_id)
        return ConverseResponse(
            thread_id=req.thread_id,
            response_message=final.get("response_message"),
            state_keys=sorted(final.keys()),
        )

    @app.post(
        "/talim/resume",
        response_model=ResumeResponse,
        dependencies=[Depends(require_secret)],
    )
    def resume(req: ResumeRequest) -> ResumeResponse:
        logger.info("resume: thread=%s approved=%s", req.thread_id, req.approved)
        final = resume_fn(thread_id=req.thread_id, approved=req.approved)
        cleared = (final or {}).get("pending_signal") is None
        return ResumeResponse(
            thread_id=req.thread_id,
            approved=req.approved,
            pending_signal_cleared=cleared,
        )

    @app.post(
        "/talim/trigger",
        response_model=TriggerResponse,
        dependencies=[Depends(require_secret)],
    )
    def trigger(thread_id: str = "cron-main") -> TriggerResponse:
        """Trigger a cron scan via HTTP (used by the scheduler container)."""
        logger.info("trigger: thread=%s", thread_id)
        final = cron_trigger_fn(
            thread_id=thread_id,
            initial_state={"halted": is_halted()},
        )
        return TriggerResponse(
            thread_id=thread_id,
            triggered=True,
            state_keys=sorted(final.keys()) if final else [],
        )

    @app.post(
        "/talim/sync",
        response_model=SyncResponse,
        dependencies=[Depends(require_secret)],
    )
    def sync(thread_id: str = "cron-main") -> SyncResponse:
        """Refresh broker positions/P&L and reconcile runtime state."""
        logger.info("sync: thread=%s", thread_id)
        rt = require_runtime()
        return SyncResponse(**rt.sync_state(thread_id=thread_id))

    @app.post(
        "/talim/halt",
        response_model=HaltResponse,
        dependencies=[Depends(require_secret)],
    )
    def halt() -> HaltResponse:
        """Emergency kill switch — blocks all new signals."""
        logger.warning("HALT activated")
        set_halted(True)
        return HaltResponse(halted=True)

    @app.post(
        "/talim/resume-trading",
        response_model=HaltResponse,
        dependencies=[Depends(require_secret)],
    )
    def resume_trading() -> HaltResponse:
        """Clear the kill switch — resume normal signal processing."""
        logger.info("HALT cleared — resuming trading")
        set_halted(False)
        return HaltResponse(halted=False)

    @app.get("/talim/halt-status")
    def halt_status() -> HaltResponse:
        """Check whether the kill switch is active (no auth required)."""
        return HaltResponse(halted=is_halted())

    @app.get(
        "/talim/operator/status",
        response_model=OperatorStatusResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_status() -> OperatorStatusResponse:
        """Return runtime health/config for an operator client such as OpenClaw."""
        rt = require_runtime()
        return OperatorStatusResponse(
            halted=is_halted(),
            runtime=rt.operator_status(),
        )

    @app.get(
        "/talim/operator/pending",
        response_model=PendingSignalResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_pending(thread_id: str = "cron-main") -> PendingSignalResponse:
        """Return pending HITL signal details for one graph thread."""
        rt = require_runtime()
        return PendingSignalResponse(**rt.pending_signal_status(thread_id=thread_id))

    @app.get(
        "/talim/operator/signals/{signal_id}/chart",
        response_model=OperatorSignalChartResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_signal_chart(
        signal_id: str,
        before: int = 50,
        after: int = 20,
    ) -> OperatorSignalChartResponse:
        """Return chart candles and indicator overlays around one signal."""
        rt = require_runtime()
        chart = rt.operator_signal_chart(
            signal_id=signal_id,
            before=before,
            after=after,
        )
        if chart is None:
            raise HTTPException(status_code=404, detail="signal not found")
        return OperatorSignalChartResponse(**chart)

    @app.get(
        "/talim/operator/signals/{signal_id}",
        response_model=OperatorSignalResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_signal(signal_id: str) -> OperatorSignalResponse:
        """Return one durable signal lifecycle row."""
        rt = require_runtime()
        signal = rt.operator_signal(signal_id=signal_id)
        if signal is None:
            raise HTTPException(status_code=404, detail="signal not found")
        return OperatorSignalResponse(signal=signal)

    @app.post(
        "/talim/operator/decision",
        response_model=OperatorDecisionResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_decision(req: OperatorDecisionRequest) -> OperatorDecisionResponse:
        """Approve or reject the pending signal for one graph thread."""
        rt = require_runtime()
        final = rt.resume(
            thread_id=req.thread_id,
            approved=req.approved,
            signal_id=req.signal_id,
        )
        return OperatorDecisionResponse(
            thread_id=req.thread_id,
            approved=req.approved,
            pending_signal_cleared=(final or {}).get("pending_signal") is None,
            last_action=(final or {}).get("last_action"),
        )

    @app.get(
        "/talim/operator/positions",
        response_model=OperatorPositionsResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_positions() -> OperatorPositionsResponse:
        """Return current broker positions."""
        rt = require_runtime()
        return OperatorPositionsResponse(positions=rt.operator_positions())

    @app.get(
        "/talim/operator/positions/dashboard",
        response_model=OperatorPositionsDashboardResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_positions_dashboard() -> OperatorPositionsDashboardResponse:
        """Return open positions enriched with live mark/P&L data."""
        rt = require_runtime()
        return OperatorPositionsDashboardResponse(**rt.operator_positions_dashboard())

    @app.get(
        "/talim/operator/positions/{position_id}/chart",
        response_model=OperatorPositionChartResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_position_chart(
        position_id: str,
        bars: int = Query(default=240, ge=20, le=500),
    ) -> OperatorPositionChartResponse:
        """Return recent chart candles for one open position."""
        rt = require_runtime()
        chart = rt.operator_position_chart(position_id=position_id, bars=bars)
        if chart is None:
            raise HTTPException(status_code=404, detail="position not found")
        return OperatorPositionChartResponse(**chart)

    @app.get(
        "/talim/operator/decisions",
        response_model=OperatorDecisionsResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_decisions(
        limit: int = 20,
        instrument: str | None = None,
        strategy: str | None = None,
    ) -> OperatorDecisionsResponse:
        """Return recent episodic decisions, newest first."""
        rt = require_runtime()
        bounded_limit = min(max(limit, 1), 200)
        return OperatorDecisionsResponse(
            decisions=rt.operator_decisions(
                limit=bounded_limit,
                instrument=instrument,
                strategy=strategy,
            )
        )

    @app.get(
        "/talim/operator/backtests",
        response_model=OperatorBacktestsResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_backtests(
        strategy: str | None = None,
        instrument: str | None = None,
        triggered_by: str | None = None,
        status: str | None = None,
        timeframe: str | None = None,
        since: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> OperatorBacktestsResponse:
        """Return recent backtest runs, newest first."""
        rt = require_runtime()
        bounded_limit = min(max(limit, 1), 200)
        bounded_offset = max(offset, 0)
        runs = rt.operator_backtests(
            strategy=strategy,
            instrument=instrument,
            triggered_by=triggered_by,
            status=status,
            timeframe=timeframe,
            since=since,
            limit=bounded_limit,
            offset=bounded_offset,
        )
        return OperatorBacktestsResponse(
            runs=runs, limit=bounded_limit, offset=bounded_offset
        )

    @app.get(
        "/talim/operator/backtests/outcomes",
        response_model=OperatorBacktestOutcomesResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_backtest_outcomes(
        strategy: str | None = None,
        instrument: str | None = None,
        exclude_triggered_by: str | None = None,
        status: str | None = None,
        timeframe: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> OperatorBacktestOutcomesResponse:
        """Return grouped strategy outcome summaries, not raw run rows."""
        rt = require_runtime()
        bounded_limit = min(max(limit, 1), 500)
        return OperatorBacktestOutcomesResponse(
            outcomes=rt.operator_backtest_outcomes(
                strategy=strategy,
                instrument=instrument,
                exclude_triggered_by=exclude_triggered_by,
                status=status,
                timeframe=timeframe,
                since=since,
                limit=bounded_limit,
            ),
            limit=bounded_limit,
        )

    @app.get(
        "/talim/operator/backtests/{run_id}",
        response_model=OperatorBacktestResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_backtest(run_id: int) -> OperatorBacktestResponse:
        """Return one backtest run by id."""
        rt = require_runtime()
        try:
            row = rt.operator_backtest(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"backtest run {run_id} not found")
        return OperatorBacktestResponse(run=row)

    @app.get(
        "/talim/operator/strategies",
        response_model=OperatorStrategiesListResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_strategies_list() -> OperatorStrategiesListResponse:
        """Return active + available strategies."""
        rt = require_runtime()
        payload = rt.operator_strategies()
        return OperatorStrategiesListResponse(**payload)

    @app.post(
        "/talim/operator/strategies/{name}/enable",
        response_model=OperatorStrategyToggleResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_strategy_enable(name: str) -> OperatorStrategyToggleResponse:
        rt = require_runtime()
        try:
            payload = rt.enable_strategy(name)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"strategy module not found for {name!r}"
            )
        return OperatorStrategyToggleResponse(
            strategy=name, action="enable", **payload
        )

    @app.post(
        "/talim/operator/strategies/{name}/disable",
        response_model=OperatorStrategyToggleResponse,
        dependencies=[Depends(require_secret)],
    )
    def operator_strategy_disable(name: str) -> OperatorStrategyToggleResponse:
        rt = require_runtime()
        payload = rt.disable_strategy(name)
        return OperatorStrategyToggleResponse(
            strategy=name, action="disable", **payload
        )

    @app.get(
        "/talim/operator/strategies/{name}/params",
        response_model=OperatorStrategyParamsResponse,
        response_model_by_alias=True,
        dependencies=[Depends(require_secret)],
    )
    def operator_strategy_params(name: str) -> OperatorStrategyParamsResponse:
        """Return the parameter schema and current values for one strategy."""
        rt = require_runtime()
        try:
            payload = rt.operator_strategy_params(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"strategy {name!r} is not active")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"strategy module not found for {name!r}")
        return OperatorStrategyParamsResponse(
            strategy=payload["strategy"],
            schema=payload["schema"],
            current=payload["current"],
        )

    return app
