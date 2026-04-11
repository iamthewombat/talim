"""MockLLMClient — canned responses for tests (WP-13)."""

from __future__ import annotations

from typing import Callable

from talim.llm.client import LLMResponse, LLMUnavailable


class MockLLMClient:
    """In-memory LLM stand-in.

    Two ways to configure responses:
    - `responses`: a list consumed in FIFO order on each call.
    - `responder`: a callable `(method, prompt) -> str` for dynamic responses.

    `record` keeps every (method, prompt) call for assertions.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        responder: Callable[[str, str], str] | None = None,
        unavailable: bool = False,
    ) -> None:
        self.responses = list(responses or [])
        self.responder = responder
        self.unavailable = unavailable
        self.calls: list[tuple[str, str]] = []

    def _next(self, method: str, prompt: str) -> str:
        if self.unavailable:
            raise LLMUnavailable("mock client marked unavailable")
        if self.responder is not None:
            return self.responder(method, prompt)
        if self.responses:
            return self.responses.pop(0)
        return f"[mock {method} response]"

    def reason(self, prompt: str, context: dict | None = None) -> LLMResponse:
        full = prompt
        if context:
            full = f"{context}\n{prompt}"
        self.calls.append(("reason", full))
        text = self._next("reason", full)
        return LLMResponse(text=text, backend="mock", model="mock", metadata={})

    def classify(self, prompt: str) -> LLMResponse:
        self.calls.append(("classify", prompt))
        text = self._next("classify", prompt)
        return LLMResponse(text=text, backend="mock", model="mock", metadata={})
