"""Shared LLM client injection for nodes (WP-14).

Production wires up a real `LLMClient`; tests inject `MockLLMClient`. Nodes
call `get_llm_client()` lazily so the dependency can be swapped per test.
"""

from __future__ import annotations

from typing import Any

_llm_client: Any = None


def configure_llm_client(client: Any) -> None:
    global _llm_client
    _llm_client = client


def get_llm_client() -> Any:
    return _llm_client


def reset_llm_client() -> None:
    global _llm_client
    _llm_client = None
