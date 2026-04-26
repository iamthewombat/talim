"""Tests for WP-68 backtest run history + query API."""

from __future__ import annotations

import json
import os
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from talim.api.bridge import create_app
from talim.app.nodes.backtest_run import backtest_run
from talim.backtest.engine import run_backtest
from talim.backtest.history import BacktestHistory
from talim.models.backtest import BacktestRequest, BacktestResult


SECRET = "history-test-secret"


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------


def _sine_df(n: int = 400) -> pd.DataFrame:
    close = 5000.0 + 60.0 * np.sin(np.arange(n) * 0.12)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01 09:30", periods=n, freq="5min"),
        "open": close,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(n, 10000.0),
    })


def _sample_result(strategy: str = "momentum-US500", *, variant=None, sharpe=1.0) -> BacktestResult:
    return BacktestResult(
        strategy_name=strategy,
        net_pnl=123.45,
        sharpe_ratio=sharpe,
        max_drawdown=-10.0,
        win_rate=0.55,
        total_trades=9,
        param_variant=variant or {"ema_fast_period": 8},
        matched_dates=[date(2025, 6, 1)],
    )


# ---------------------------------------------------------------------------
# Store unit tests
# ---------------------------------------------------------------------------


class TestBacktestHistoryStore:
    def test_record_and_get_round_trip(self, tmp_path):
        h = BacktestHistory(tmp_path / "h.db")
        req = BacktestRequest(
            strategy_name="momentum-US500",
            instrument="US500.cash",
            timeframe="5m",
            param_variants=[{"ema_fast_period": 8}],
            data_dir="data/ig",
        )
        run_id = h.record_run(
            result=_sample_result(),
            request=req,
            triggered_by="cli",
            notes="unit-test",
        )
        assert run_id >= 1
        row = h.get_run(run_id)
        assert row is not None
        assert row["strategy"] == "momentum-US500"
        assert row["instrument"] == "US500.cash"
        assert row["timeframe"] == "5m"
        assert row["triggered_by"] == "cli"
        assert row["notes"] == "unit-test"
        assert row["net_pnl"] == pytest.approx(123.45)
        assert row["param_variant"] == {"ema_fast_period": 8}
        assert row["matched_dates"] == ["2025-06-01"]

    def test_list_runs_newest_first(self, tmp_path):
        h = BacktestHistory(tmp_path / "h.db")
        ids = [
            h.record_run(result=_sample_result(sharpe=0.1)),
            h.record_run(result=_sample_result(sharpe=0.2)),
            h.record_run(result=_sample_result(sharpe=0.3)),
        ]
        rows = h.list_runs(limit=10)
        assert [r["id"] for r in rows] == list(reversed(ids))

    def test_list_runs_filters(self, tmp_path):
        h = BacktestHistory(tmp_path / "h.db")
        req_a = BacktestRequest(strategy_name="momentum-US500", instrument="US500.cash")
        req_b = BacktestRequest(strategy_name="momentum-AU200", instrument="AU200.cash")
        h.record_run(result=_sample_result("momentum-US500"), request=req_a, triggered_by="cli")
        h.record_run(result=_sample_result("momentum-AU200"), request=req_b, triggered_by="node")
        h.record_run(result=_sample_result("momentum-US500"), request=req_a, triggered_by="cli")

        assert len(h.list_runs(strategy="momentum-US500")) == 2
        assert len(h.list_runs(strategy="momentum-AU200")) == 1
        assert len(h.list_runs(instrument="AU200.cash")) == 1
        assert len(h.list_runs(triggered_by="cli")) == 2
        # Unknown id → None
        assert h.get_run(9999) is None

    def test_list_runs_pagination(self, tmp_path):
        h = BacktestHistory(tmp_path / "h.db")
        for i in range(5):
            h.record_run(result=_sample_result(sharpe=float(i)))
        page1 = h.list_runs(limit=2, offset=0)
        page2 = h.list_runs(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})

    def test_record_results_preserves_order(self, tmp_path):
        h = BacktestHistory(tmp_path / "h.db")
        results = [_sample_result(variant={"n": i}, sharpe=float(i)) for i in range(3)]
        ids = h.record_results(results, triggered_by="cli")
        assert ids == sorted(ids)  # insert order → ascending ids
        rows = h.list_runs(limit=10)
        # newest-first means inserted-last id is first
        assert rows[0]["id"] == ids[-1]


# ---------------------------------------------------------------------------
# Node integration
# ---------------------------------------------------------------------------


class TestBacktestNodePersistsHistory:
    def test_node_writes_history_row(self, tmp_path, monkeypatch):
        df = _sine_df()
        df.to_parquet(tmp_path / "ES.parquet")
        history_db = tmp_path / "node_history.db"
        monkeypatch.setenv("TALIM_BACKTEST_HISTORY_DB", str(history_db))

        req = BacktestRequest(
            strategy_name="momentum-US500",
            instrument="ES",
            param_variants=[{}],
            data_dir=str(tmp_path),
        )
        update = backtest_run({"pending_backtest": req})
        assert update["backtest_result"] is not None

        h = BacktestHistory(history_db)
        rows = h.list_runs(strategy="momentum-US500")
        assert len(rows) == 1
        assert rows[0]["triggered_by"] == "node"
        assert rows[0]["instrument"] == "ES"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestBacktestCliPersistsHistory:
    def test_cli_prints_run_ids_and_persists(self, tmp_path):
        import subprocess
        import sys

        df = _sine_df()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        df.to_parquet(data_dir / "ES.parquet")
        history_db = tmp_path / "cli_history.db"

        env = os.environ.copy()
        env["TALIM_BACKTEST_HISTORY_DB"] = str(history_db)
        result = subprocess.run(
            [
                sys.executable,
                "scripts/run_backtest.py",
                "--strategy",
                "momentum-US500",
                "--instrument",
                "ES",
                "--data-dir",
                str(data_dir),
                "--params",
                '{"ema_fast_period": 5, "ema_slow_period": 13}',
                "--notes",
                "integration-run",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["run_ids"]
        h = BacktestHistory(history_db)
        rows = h.list_runs(strategy="momentum-US500")
        assert len(rows) == 1
        assert rows[0]["id"] == payload["run_ids"][0]
        assert rows[0]["triggered_by"] == "cli"
        assert rows[0]["notes"] == "integration-run"

    def test_cli_no_history_flag(self, tmp_path):
        import subprocess
        import sys

        df = _sine_df()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        df.to_parquet(data_dir / "ES.parquet")
        history_db = tmp_path / "cli_history.db"

        env = os.environ.copy()
        env["TALIM_BACKTEST_HISTORY_DB"] = str(history_db)
        result = subprocess.run(
            [
                sys.executable,
                "scripts/run_backtest.py",
                "--strategy",
                "momentum-US500",
                "--instrument",
                "ES",
                "--data-dir",
                str(data_dir),
                "--no-history",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert not history_db.exists()


# ---------------------------------------------------------------------------
# Operator API
# ---------------------------------------------------------------------------


class TestBacktestOperatorEndpoints:
    def _make_client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TALIM_BRIDGE_SECRET", SECRET)
        db = tmp_path / "api_history.db"
        history = BacktestHistory(db)

        class _FakeRuntime:
            backtest_history = history

            def operator_backtests(self, **kwargs):
                return history.list_runs(**kwargs)

            def operator_backtest(self, run_id):
                row = history.get_run(run_id)
                if row is None:
                    raise KeyError(run_id)
                return row

        app = create_app(
            bridge_message_fn=lambda **_: {},
            resume_fn=lambda **_: {},
            cron_trigger_fn=lambda **_: {},
        )
        app.state.talim_runtime = _FakeRuntime()
        return TestClient(app), history

    def test_list_endpoint_returns_rows(self, tmp_path, monkeypatch):
        client, history = self._make_client(tmp_path, monkeypatch)
        for i in range(3):
            history.record_run(
                result=_sample_result(sharpe=float(i)),
                triggered_by="cli",
            )
        r = client.get(
            "/talim/operator/backtests",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert len(body["runs"]) == 3
        assert body["runs"][0]["sharpe_ratio"] == pytest.approx(2.0)

    def test_list_endpoint_filters(self, tmp_path, monkeypatch):
        client, history = self._make_client(tmp_path, monkeypatch)
        history.record_run(result=_sample_result("momentum-US500"), triggered_by="cli")
        history.record_run(result=_sample_result("momentum-AU200"), triggered_by="node")
        r = client.get(
            "/talim/operator/backtests?strategy=momentum-US500",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["runs"]) == 1
        assert body["runs"][0]["strategy"] == "momentum-US500"

    def test_get_endpoint_returns_row(self, tmp_path, monkeypatch):
        client, history = self._make_client(tmp_path, monkeypatch)
        run_id = history.record_run(result=_sample_result(), triggered_by="cli")
        r = client.get(
            f"/talim/operator/backtests/{run_id}",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["run"]["id"] == run_id
        assert body["run"]["strategy"] == "momentum-US500"

    def test_get_endpoint_404(self, tmp_path, monkeypatch):
        client, _ = self._make_client(tmp_path, monkeypatch)
        r = client.get(
            "/talim/operator/backtests/999",
            headers={"X-Talim-Secret": SECRET},
        )
        assert r.status_code == 404

    def test_list_endpoint_auth_required(self, tmp_path, monkeypatch):
        client, _ = self._make_client(tmp_path, monkeypatch)
        r = client.get("/talim/operator/backtests")
        assert r.status_code in (401, 403)
