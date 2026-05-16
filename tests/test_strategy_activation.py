"""Tests for WP-70 hot strategy activation controls."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from talim.api.bridge import create_app
from talim.app.execute_context import get_execute_context
from talim.app.nodes.risk_check import configure_risk_rules
from talim.app.nodes.signal_scanner import _context as scanner_context
from talim.app.runtime import bootstrap_runtime
from talim.risk.rules import RiskRules


SECRET = "activation-test-secret"


@pytest.fixture(autouse=True)
def _reset_contexts(monkeypatch):
    monkeypatch.setenv("TALIM_BRIDGE_SECRET", SECRET)
    yield
    scanner_context.reset()
    get_execute_context().reset()
    configure_risk_rules(RiskRules())


def _runtime(monkeypatch, tmp_path, strategies: str = "momentum-US500"):
    monkeypatch.setenv("TALIM_EXCHANGE_MODE", "mock")
    monkeypatch.setenv("TALIM_PRICEFEED", "mock")
    monkeypatch.setenv("TALIM_INSTRUMENTS", "ES")
    monkeypatch.setenv("TALIM_STRATEGIES", strategies)
    monkeypatch.setenv("TALIM_CHECKPOINT_DB", str(tmp_path / "checkpoints.db"))
    monkeypatch.setenv("TALIM_EPISODIC_DB", str(tmp_path / "episodic.db"))
    monkeypatch.setenv("TALIM_BACKTEST_HISTORY_DB", str(tmp_path / "history.db"))
    monkeypatch.setenv("TALIM_RISK_CONFIG", "")
    return bootstrap_runtime()


class TestRuntimeActivation:
    def test_enable_adds_and_is_audited(self, monkeypatch, tmp_path):
        rt = _runtime(monkeypatch, tmp_path)
        assert "mean-reversion-US500" not in rt._active_strategies
        payload = rt.enable_strategy("mean-reversion-US500", actor="unit-test")
        assert "mean-reversion-US500" in payload["active"]
        assert "mean-reversion-US500" in rt._active_strategies
        # Scanner also sees it
        assert "mean-reversion-US500" in scanner_context.strategies
        rows = rt.episodic.query_activations(strategy="mean-reversion-US500")
        assert len(rows) == 1
        assert rows[0]["action"] == "enable"
        assert rows[0]["actor"] == "unit-test"
        assert rows[0]["notes"] == ""

    def test_disable_removes_and_preserves_pending_hitl(self, monkeypatch, tmp_path):
        rt = _runtime(monkeypatch, tmp_path, strategies="momentum-US500")
        # Simulate a pending HITL signal by writing state via the checkpointer.
        from talim.app.graph import build_graph
        from talim.models.signal import Signal

        graph = build_graph(checkpointer=rt.checkpointer)
        cfg = {"configurable": {"thread_id": "activation-hitl"}}
        pending = Signal(
            strategy="momentum-US500",
            instrument="ES",
            side="long",
            entry_price=5000.0,
            stop=4950.0,
            target=5100.0,
            rationale="test",
            regime_context="momentum",
        )
        graph.update_state(cfg, {"pending_signal": pending})
        # Now disable the strategy that produced it.
        payload = rt.disable_strategy("momentum-US500")
        assert "momentum-US500" not in payload["active"]
        # Pending signal survives.
        snapshot = graph.get_state(cfg)
        assert snapshot.values["pending_signal"] is not None
        rows = rt.episodic.query_activations(strategy="momentum-US500")
        assert rows[0]["action"] == "disable"

    def test_enable_unknown_raises_file_not_found(self, monkeypatch, tmp_path):
        rt = _runtime(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            rt.enable_strategy("does-not-exist")
        # No audit row when validation fails before mutation.
        rows = rt.episodic.query_activations(strategy="does-not-exist")
        assert rows == []

    def test_enable_idempotent_noop(self, monkeypatch, tmp_path):
        rt = _runtime(monkeypatch, tmp_path)
        rt.enable_strategy("momentum-US500")  # already active
        rows = rt.episodic.query_activations(strategy="momentum-US500")
        assert rows[0]["notes"] == "noop"

    def test_operator_strategies_lists_available(self, monkeypatch, tmp_path):
        rt = _runtime(monkeypatch, tmp_path)
        payload = rt.operator_strategies()
        assert payload["active"] == ["momentum-US500"]
        # Available should include every strategy/*/strategy.py on disk
        assert "momentum-US500" in payload["available"]
        assert "mean-reversion-US500" in payload["available"]
        assert "momentum-AU200" in payload["available"]

    def test_seed_state_reflects_toggle(self, monkeypatch, tmp_path):
        rt = _runtime(monkeypatch, tmp_path)
        rt.disable_strategy("momentum-US500")
        state = rt.seed_state()
        assert state["active_strategies"] == []
        rt.enable_strategy("momentum-US500")
        state = rt.seed_state()
        assert state["active_strategies"] == ["momentum-US500"]


class TestScannerSkipsDisabledStrategies:
    def test_signal_scanner_respects_state_active_list(self, monkeypatch, tmp_path):
        import pandas as pd
        import numpy as np
        from talim.app.nodes.signal_scanner import configure_scanner, signal_scanner
        from talim.connectors.pricefeed.mock import MockPriceFeed
        from talim.strategy.loader import load_strategy

        n = 120
        close = 5000.0 + 50.0 * np.sin(np.arange(n) * 0.15)
        df = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="5min"),
            "open": close,
            "high": close + 5,
            "low": close - 5,
            "close": close,
            "volume": np.full(n, 10000.0),
        })
        feed = MockPriceFeed()
        feed.load(df)
        feed.subscribe("ES")
        feed.connect()
        configure_scanner(feed, strategies=[load_strategy("momentum-US500")])
        feed.replay()

        # With strategy active, scanner processes it; with empty list, it doesn't
        active = signal_scanner({"active_strategies": ["momentum-US500"]})
        disabled = signal_scanner({"active_strategies": []})

        # "active_strategies": [] means the scanner skips all strategies and
        # yields no pending signal, regardless of whether one would have fired.
        assert disabled.get("pending_signal") is None
        # Sanity — scanner still computed ATR / regime fingerprint in both cases
        assert "atr_current" in active
        assert "atr_current" in disabled


class TestOperatorActivationEndpoints:
    def _client(self, monkeypatch, tmp_path):
        rt = _runtime(monkeypatch, tmp_path)
        app = create_app(
            bridge_message_fn=lambda **_: {},
            resume_fn=lambda **_: {},
            cron_trigger_fn=lambda **_: {},
        )
        app.state.talim_runtime = rt
        return TestClient(app), rt

    def test_list_endpoint(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        r = client.get(
            "/talim/operator/strategies",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["active"] == ["momentum-US500"]
        assert "mean-reversion-US500" in body["available"]

    def test_enable_endpoint(self, monkeypatch, tmp_path):
        client, rt = self._client(monkeypatch, tmp_path)
        r = client.post(
            "/talim/operator/strategies/mean-reversion-US500/enable",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["strategy"] == "mean-reversion-US500"
        assert body["action"] == "enable"
        assert "mean-reversion-US500" in body["active"]
        assert "mean-reversion-US500" in rt._active_strategies

    def test_enable_unknown_returns_404(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        r = client.post(
            "/talim/operator/strategies/does-not-exist/enable",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 404

    def test_disable_endpoint(self, monkeypatch, tmp_path):
        client, rt = self._client(monkeypatch, tmp_path)
        r = client.post(
            "/talim/operator/strategies/momentum-US500/disable",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["action"] == "disable"
        assert "momentum-US500" not in body["active"]
        assert "momentum-US500" not in rt._active_strategies

    def test_endpoints_require_auth(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        assert client.get("/talim/operator/strategies").status_code in (401, 403)
        assert client.post(
            "/talim/operator/strategies/momentum-US500/enable"
        ).status_code in (401, 403)
        assert client.post(
            "/talim/operator/strategies/momentum-US500/disable"
        ).status_code in (401, 403)


class TestOperatorSignalLifecycle:
    def test_pending_records_durable_signal_and_detail_endpoint(self, monkeypatch, tmp_path):
        from talim.app.graph import build_graph
        from talim.models.signal import Signal

        monkeypatch.setenv("TALIM_PUBLIC_BASE_URL", "http://operator.test/talim")
        client, rt = TestOperatorActivationEndpoints()._client(monkeypatch, tmp_path)
        graph = build_graph(checkpointer=rt.checkpointer)
        cfg = {"configurable": {"thread_id": "cron-main"}}
        pending = Signal(
            strategy="momentum-US500",
            instrument="ES",
            side="long",
            entry_price=5000.0,
            stop=4950.0,
            target=5100.0,
            rationale="unit-test signal",
            regime_context="ranging",
        )
        graph.update_state(cfg, {
            "pending_signal": pending,
            "pending_notification": "pending test",
            "atr_current": 12.5,
            "regime": "ranging",
        })

        r = client.get(
            "/talim/operator/pending?thread_id=cron-main",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        signal_id = body["signal_id"]
        assert signal_id.startswith("SIG-")
        assert body["pending_signal"]["signal_id"] == signal_id
        assert body["dashboard_url"].endswith(f"/dashboard/signal.html?signal={signal_id}")

        detail = client.get(
            f"/talim/operator/signals/{signal_id}",
            headers={"X-Talim-Secret": SECRET},
        )
        assert detail.status_code == 200
        signal = detail.json()["signal"]
        assert signal["signal_id"] == signal_id
        assert signal["status"] == "pending"
        assert signal["strategy"] == "momentum-US500"
        assert signal["context"]["atr_current"] == 12.5

    def test_signal_detail_404(self, monkeypatch, tmp_path):
        client, _ = TestOperatorActivationEndpoints()._client(monkeypatch, tmp_path)
        r = client.get(
            "/talim/operator/signals/SIG-NOPE",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 404


class TestSignalValidation:
    def test_momentum_validation_blocks_wrong_ema_side(self):
        from datetime import datetime, timezone, timedelta
        from talim.models.bar import OHLCVBar
        from talim.models.signal import Signal
        from talim.strategy.loader import load_strategy

        strat = load_strategy("momentum-US500")
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        closes = [100 + i for i in range(30)] + [130 - i for i in range(20)]
        bars = [OHLCVBar(
            instrument="US500.cash",
            timestamp=start + timedelta(minutes=5 * i),
            open=c, high=c + 1, low=c - 1, close=c, volume=1000, timeframe="5m",
        ) for i, c in enumerate(closes)]
        sig = Signal(
            instrument="US500.cash", strategy="momentum-US500", side="long",
            entry_price=112, stop=100, target=136, rationale="test",
            regime_context="", timestamp=bars[-2].timestamp,
        )
        result = strat.validate_signal(sig, bars, atr=2.0)
        assert result.status == "condition_invalidated"
        assert result.approval_allowed is False

    def test_pending_endpoint_includes_validation(self, monkeypatch, tmp_path):
        from datetime import datetime, timezone, timedelta
        from talim.app.graph import build_graph
        from talim.app.nodes.signal_scanner import _context as scanner_context
        from talim.models.bar import OHLCVBar
        from talim.models.signal import Signal

        client, rt = TestOperatorActivationEndpoints()._client(monkeypatch, tmp_path)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(50):
            c = 5000 + i
            scanner_context.record_bar(OHLCVBar(
                instrument="ES", timestamp=start + timedelta(minutes=5 * i),
                open=c, high=c + 1, low=c - 1, close=c, volume=1000, timeframe="5m",
            ))
        graph = build_graph(checkpointer=rt.checkpointer)
        cfg = {"configurable": {"thread_id": "cron-main"}}
        pending = Signal(
            strategy="momentum-US500", instrument="ES", side="long",
            entry_price=5048, stop=5040, target=5064, rationale="test",
            regime_context="ranging", timestamp=start + timedelta(minutes=5 * 48),
        )
        graph.update_state(cfg, {"pending_signal": pending, "atr_current": 2.0})
        r = client.get("/talim/operator/pending?thread_id=cron-main", headers={"X-Talim-Secret": SECRET})
        assert r.status_code == 200
        body = r.json()
        assert body["validation"]["status"] in {"valid", "price_moved_too_far", "condition_invalidated"}
        assert body["pending_signal"]["validation"] == body["validation"]


class TestApprovalValidationEnforcement:
    def test_operator_approve_blocks_stale_signal(self, monkeypatch, tmp_path):
        from datetime import datetime, timezone, timedelta
        from talim.app.graph import build_graph
        from talim.app.nodes.signal_scanner import _context as scanner_context
        from talim.models.bar import OHLCVBar
        from talim.models.signal import Signal

        client, rt = TestOperatorActivationEndpoints()._client(monkeypatch, tmp_path)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(50):
            c = 5000 + i
            scanner_context.record_bar(OHLCVBar(
                instrument="ES", timestamp=start + timedelta(minutes=5 * i),
                open=c, high=c + 1, low=c - 1, close=c, volume=1000, timeframe="5m",
            ))
        graph = build_graph(checkpointer=rt.checkpointer)
        cfg = {"configurable": {"thread_id": "cron-main"}}
        pending = Signal(
            strategy="momentum-US500", instrument="ES", side="long",
            entry_price=5020, stop=5010, target=5040, rationale="test",
            regime_context="ranging", timestamp=start + timedelta(minutes=5 * 20),
        )
        graph.update_state(cfg, {"pending_signal": pending, "atr_current": 2.0})
        pending_resp = client.get("/talim/operator/pending?thread_id=cron-main", headers={"X-Talim-Secret": SECRET})
        signal_id = pending_resp.json()["signal_id"]

        r = client.post(
            "/talim/operator/decision",
            json={"thread_id": "cron-main", "approved": True},
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["pending_signal_cleared"] is True
        assert "Approval blocked" in body["last_action"]

        row = rt.episodic.get_signal(signal_id)
        assert row is not None
        assert row["status"] == "expired"
        assert row["latest_validation_status"] == "stale"


class TestSignalIdDecisionPath:
    def test_signal_id_mismatch_blocks_without_clearing(self, monkeypatch, tmp_path):
        from datetime import datetime, timezone
        from talim.app.graph import build_graph
        from talim.models.signal import Signal

        client, rt = TestOperatorActivationEndpoints()._client(monkeypatch, tmp_path)
        graph = build_graph(checkpointer=rt.checkpointer)
        cfg = {"configurable": {"thread_id": "cron-main"}}
        pending = Signal(
            strategy="momentum-US500", instrument="ES", side="long",
            entry_price=5000, stop=4990, target=5020, rationale="test",
            regime_context="ranging", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        graph.update_state(cfg, {"pending_signal": pending})
        r = client.post(
            "/talim/operator/decision",
            json={"thread_id": "cron-main", "approved": False, "signal_id": "SIG-WRONG"},
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["pending_signal_cleared"] is False
        assert "Decision blocked" in body["last_action"]
        snap = graph.get_state(cfg)
        assert snap.values["pending_signal"] is not None
