"""Talim bridge HTTP API (WP-16).

Two endpoints:
  POST /talim/converse — forward a message into the LangGraph bridge entry point
  POST /talim/resume   — resume a HITL-paused graph with approve/reject

Both require the shared-secret header (see `talim.api.auth`).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from talim.api.auth import require_secret

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


def create_app(
    bridge_message_fn: Callable[..., dict[str, Any]] | None = None,
    resume_fn: Callable[..., dict[str, Any]] | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    Both functions are injectable for tests. Defaults wire up the production
    LangGraph entry points.
    """
    if bridge_message_fn is None:
        from talim.app.entrypoints import bridge_message as _default_bridge
        bridge_message_fn = _default_bridge
    if resume_fn is None:
        from talim.app.resume import resume_graph as _default_resume
        resume_fn = _default_resume

    app = FastAPI(title="Talim Bridge", version="0.1.0")

    @app.get("/talim/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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

    return app
