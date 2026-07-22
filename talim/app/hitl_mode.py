"""HITL mode toggle with file-backed persistence.

Defaults to enabled (fail-safe). State is persisted to a JSON file so it
survives container restarts. If the file is missing or corrupt, HITL
defaults to ON.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("talim.app.hitl_mode")

_DEFAULT_PATH = Path("state/hitl_mode.json")

_state: dict[str, Any] = {
    "enabled": True,
    "changed_at": None,
    "changed_by": None,
}
_loaded = False


def _load(path: Path | None = None) -> None:
    global _loaded
    if path is None:
        path = _DEFAULT_PATH
    if path.exists():
        try:
            data = json.loads(path.read_text())
            _state["enabled"] = bool(data.get("enabled", True))
            _state["changed_at"] = data.get("changed_at")
            _state["changed_by"] = data.get("changed_by")
        except Exception:
            logger.warning("hitl_mode: failed to read %s; defaulting to enabled", path)
            _state["enabled"] = True
    _loaded = True


def _save(path: Path | None = None) -> None:
    if path is None:
        path = _DEFAULT_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_state, indent=2) + "\n")
    except Exception:
        logger.warning("hitl_mode: failed to persist state to %s", path, exc_info=True)


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        _load()


def is_hitl_enabled() -> bool:
    _ensure_loaded()
    return _state["enabled"]


def set_hitl_enabled(enabled: bool, *, actor: str = "operator") -> dict[str, Any]:
    _ensure_loaded()
    _state["enabled"] = enabled
    _state["changed_at"] = datetime.now(timezone.utc).isoformat()
    _state["changed_by"] = actor
    _save()
    action = "enabled" if enabled else "disabled"
    logger.info("hitl_mode: HITL %s by %s", action, actor)
    return dict(_state)


def get_hitl_mode() -> dict[str, Any]:
    _ensure_loaded()
    return dict(_state)


def load_hitl_mode(path: Path | None = None) -> None:
    """Explicitly load state from disk (called at bootstrap)."""
    _load(path)
