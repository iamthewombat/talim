"""LLM integration layer (WP-13)."""

from talim.llm.client import LLMClient, LLMResponse, LLMUnavailable
from talim.llm.mock import MockLLMClient
from talim.llm import prompts

__all__ = ["LLMClient", "LLMResponse", "LLMUnavailable", "MockLLMClient", "prompts"]
