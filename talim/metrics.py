"""Prometheus-style metrics for the /metrics endpoint (WP-41).

Lightweight counters/gauges — no dependency on prometheus_client.
Rendered as Prometheus text exposition format.
"""

from __future__ import annotations

import threading
from typing import Any


class _Metrics:
    """Thread-safe in-process metric store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + n

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def get(self, name: str) -> int | float:
        with self._lock:
            if name in self._counters:
                return self._counters[name]
            return self._gauges.get(name, 0)

    def render(self) -> str:
        """Render all metrics in Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            for name, val in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {val}")
            for name, val in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {val}")
        lines.append("")  # trailing newline
        return "\n".join(lines)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()


# Module-level singleton
METRICS = _Metrics()
