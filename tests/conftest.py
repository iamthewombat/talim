"""Shared test fixtures."""

from pathlib import Path

import pytest

from talim.app import hitl_mode


@pytest.fixture(autouse=True)
def _reset_hitl_mode(tmp_path, monkeypatch):
    """Ensure HITL is enabled (default) and isolated from disk state."""
    hitl_mode._state["enabled"] = True
    hitl_mode._state["changed_at"] = None
    hitl_mode._state["changed_by"] = None
    hitl_mode._loaded = True
    monkeypatch.setattr(hitl_mode, "_DEFAULT_PATH", tmp_path / "hitl_mode.json")
