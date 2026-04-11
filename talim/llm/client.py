"""LLMClient — wraps Claude (reasoning) and Ollama (classification). WP-13.

Design:
- `reason(prompt, context=None)` → uses Claude API for high-quality reasoning.
- `classify(prompt)` → uses Ollama for fast local classification, falling
  back to Claude if Ollama is unreachable.

Both methods return an `LLMResponse` with the text plus metadata. Failures
raise `LLMUnavailable` so callers can decide whether to degrade gracefully.

External dependencies are imported lazily so the package stays importable
even when neither `anthropic` nor `requests` is installed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("talim.llm.client")


class LLMUnavailable(RuntimeError):
    """Raised when no configured LLM backend can satisfy a request."""


@dataclass
class LLMResponse:
    text: str
    backend: str          # "claude" | "ollama" | "mock"
    model: str
    metadata: dict[str, Any]


class LLMClient:
    """Production client wrapping Claude API + Ollama."""

    def __init__(
        self,
        claude_model: str = "claude-opus-4-6",
        ollama_model: str = "llama3.2",
        ollama_url: str | None = None,
        anthropic_api_key: str | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self.claude_model = claude_model
        self.ollama_model = ollama_model
        self.ollama_url = ollama_url or os.environ.get(
            "OLLAMA_URL", "http://localhost:11434"
        )
        self.anthropic_api_key = anthropic_api_key or os.environ.get(
            "ANTHROPIC_API_KEY"
        )
        self.request_timeout = request_timeout

    # ------------------------------------------------------------------
    # Reasoning (Claude)
    # ------------------------------------------------------------------
    def reason(self, prompt: str, context: dict | None = None) -> LLMResponse:
        if not self.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY not configured")

        try:
            import anthropic  # type: ignore
        except ImportError as e:
            raise LLMUnavailable(f"anthropic SDK not installed: {e}")

        client = anthropic.Anthropic(api_key=self.anthropic_api_key)
        full_prompt = prompt
        if context:
            ctx = "\n".join(f"{k}: {v}" for k, v in context.items())
            full_prompt = f"Context:\n{ctx}\n\n{prompt}"

        try:
            msg = client.messages.create(
                model=self.claude_model,
                max_tokens=1024,
                messages=[{"role": "user", "content": full_prompt}],
            )
        except Exception as e:
            raise LLMUnavailable(f"Claude API call failed: {e}") from e

        # anthropic returns a list of content blocks; pull the text out.
        parts = getattr(msg, "content", [])
        text = "".join(getattr(p, "text", "") for p in parts).strip()
        return LLMResponse(
            text=text,
            backend="claude",
            model=self.claude_model,
            metadata={"stop_reason": getattr(msg, "stop_reason", None)},
        )

    # ------------------------------------------------------------------
    # Classification (Ollama, falls back to Claude)
    # ------------------------------------------------------------------
    def classify(self, prompt: str) -> LLMResponse:
        try:
            return self._classify_ollama(prompt)
        except LLMUnavailable as e:
            logger.warning("ollama unavailable (%s), falling back to Claude", e)
            try:
                return self.reason(prompt)
            except LLMUnavailable as e2:
                raise LLMUnavailable(
                    f"Both Ollama and Claude unavailable: {e2}"
                ) from e2

    def _classify_ollama(self, prompt: str) -> LLMResponse:
        try:
            import requests  # type: ignore
        except ImportError as e:
            raise LLMUnavailable(f"requests not installed: {e}")

        url = f"{self.ollama_url.rstrip('/')}/api/generate"
        try:
            r = requests.post(
                url,
                json={"model": self.ollama_model, "prompt": prompt, "stream": False},
                timeout=self.request_timeout,
            )
            r.raise_for_status()
        except Exception as e:
            raise LLMUnavailable(f"Ollama unreachable at {url}: {e}") from e

        data = r.json()
        return LLMResponse(
            text=str(data.get("response", "")).strip(),
            backend="ollama",
            model=self.ollama_model,
            metadata={"done": data.get("done")},
        )
