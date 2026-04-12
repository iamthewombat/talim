"""Talim bridge HTTP API (WP-16, WP-38, WP-39)."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import Depends, FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from talim.api.auth import require_secret
from talim.metrics import METRICS

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


class HaltResponse(BaseModel):
    halted: bool


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

    @app.get("/talim/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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

    return app
