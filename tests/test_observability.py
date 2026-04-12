"""Tests for structured logging and metrics (WP-41)."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from talim.api.bridge import create_app, set_halted
from talim.logging import JSONFormatter, configure_logging
from talim.metrics import METRICS


# --- JSONFormatter ---


class TestJSONFormatter:
    def test_produces_valid_json(self):
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="talim.test", level=logging.INFO, pathname="",
            lineno=0, msg="hello %s", args=("world",), exc_info=None,
        )
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["msg"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "talim.test"
        assert "ts" in parsed

    def test_includes_extras(self):
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="talim.test", level=logging.INFO, pathname="",
            lineno=0, msg="test", args=(), exc_info=None,
        )
        record.node = "signal_scanner"  # type: ignore[attr-defined]
        record.thread_id = "t-1"  # type: ignore[attr-defined]
        record.latency_ms = 42.5  # type: ignore[attr-defined]
        record.outcome = "signal"  # type: ignore[attr-defined]
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["node"] == "signal_scanner"
        assert parsed["thread_id"] == "t-1"
        assert parsed["latency_ms"] == 42.5
        assert parsed["outcome"] == "signal"

    def test_includes_exception(self):
        fmt = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="talim.test", level=logging.ERROR, pathname="",
                lineno=0, msg="fail", args=(), exc_info=sys.exc_info(),
            )
        line = fmt.format(record)
        parsed = json.loads(line)
        assert "exception" in parsed
        assert "boom" in parsed["exception"]


# --- Metrics ---


class TestMetrics:
    @pytest.fixture(autouse=True)
    def _reset(self):
        METRICS.reset()
        yield
        METRICS.reset()

    def test_counter_inc(self):
        METRICS.inc("test_counter")
        assert METRICS.get("test_counter") == 1
        METRICS.inc("test_counter", 5)
        assert METRICS.get("test_counter") == 6

    def test_gauge_set(self):
        METRICS.set_gauge("test_gauge", 42.5)
        assert METRICS.get("test_gauge") == 42.5

    def test_get_missing_returns_zero(self):
        assert METRICS.get("nonexistent") == 0

    def test_render_prometheus_format(self):
        METRICS.inc("talim_signals_emitted_total", 3)
        METRICS.set_gauge("talim_hitl_pending", 1.0)
        text = METRICS.render()
        assert "# TYPE talim_signals_emitted_total counter" in text
        assert "talim_signals_emitted_total 3" in text
        assert "# TYPE talim_hitl_pending gauge" in text
        assert "talim_hitl_pending 1.0" in text


# --- /metrics endpoint ---


class TestMetricsEndpoint:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        monkeypatch.setenv("TALIM_BRIDGE_SECRET", "s")
        set_halted(False)
        METRICS.reset()
        yield
        METRICS.reset()

    def test_metrics_endpoint(self):
        app = create_app(
            bridge_message_fn=lambda **kw: {},
            resume_fn=lambda **kw: {},
            cron_trigger_fn=lambda **kw: {},
        )
        client = TestClient(app)
        METRICS.inc("talim_orders_placed_total", 7)
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        assert "talim_orders_placed_total 7" in r.text
