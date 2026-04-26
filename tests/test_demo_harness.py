"""Tests for the WP-63 demo execution harness."""

from __future__ import annotations

from talim.app.demo_harness import run_mock_demo_execution


def test_mock_demo_execution_completes_full_order_path(tmp_path):
    result = run_mock_demo_execution(state_dir=tmp_path)

    assert result.thread_id == "demo-exec-1"
    assert result.instrument == "ES"
    assert result.strategy == "momentum-US500"
    assert result.side in {"long", "short"}
    assert result.order_count == 1
    assert result.position_count == 1
    assert result.decision_count == 1
    assert result.reconcile_divergences == 0
    assert "executed enter" in result.last_action
    assert result.account_balance != 100_000.0
