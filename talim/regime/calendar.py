"""Macro event calendar (WP-22).

Hand-curated set of dates the regime matcher should exclude when looking for
historically similar sessions. Architecture §7.2 calls this out as a domain
filter — high-impact macro releases warp the tape in ways that make
fingerprint similarity misleading.

The PoC keeps the list in a JSON file so it can be edited without redeploying.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent / "macro_events.json"


class MacroCalendar:
    def __init__(self, events: set[date] | None = None) -> None:
        self._events: set[date] = set(events or set())

    @classmethod
    def from_file(cls, path: Path | str | None = None) -> "MacroCalendar":
        p = Path(path) if path is not None else _DEFAULT_PATH
        if not p.exists():
            return cls(set())
        raw = json.loads(p.read_text())
        events = {date.fromisoformat(d) for d in raw.get("dates", [])}
        return cls(events)

    def is_macro_event(self, d: date) -> bool:
        return d in self._events

    def add(self, d: date) -> None:
        self._events.add(d)

    def __len__(self) -> int:
        return len(self._events)
