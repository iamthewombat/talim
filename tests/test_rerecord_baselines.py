"""Tests for scripts/rerecord_baselines.py (WP-86/WP-87 baseline snapshots)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import rerecord_baselines  # noqa: E402

from talim.backtest.history import BacktestHistory  # noqa: E402


def _write_dataset(root: Path, instrument: str, timeframe: str, n: int = 400) -> None:
    close = 5000.0 + 60.0 * np.sin(np.arange(n) * 0.12)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01 09:30", periods=n, freq="5min"),
        "open": close,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(n, 10000.0),
    })
    out = root / instrument
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / f"{timeframe}.parquet", index=False)


def _write_costs(path: Path) -> None:
    path.write_text(json.dumps({
        "venues": {
            "testvenue": {
                "instruments": {
                    "US500.cash": {
                        "spread_points": 1.0,
                        "slippage_points": 0.5,
                        "commission_per_side": 0.0,
                    }
                }
            }
        }
    }))


def _write_manifest(path: Path, data_dir: Path, entries: list[dict] | None = None) -> None:
    baselines = entries or [{
        "strategy": "momentum-US500",
        "instrument": "US500.cash",
        "timeframe": "5m",
        "data_dir": str(data_dir),
        "costs_venue": "testvenue",
        "param_variants": [{}],
    }]
    path.write_text(json.dumps({"baselines": baselines}))


def _run(argv: list[str], monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["rerecord_baselines.py", *argv])
    return rerecord_baselines.main()


class TestRerecordBaselines:
    def test_writes_costed_snapshot_and_history(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        _write_dataset(data_dir, "US500.cash", "5m")
        costs_path = tmp_path / "costs.json"
        _write_costs(costs_path)
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, data_dir)
        output = tmp_path / "snapshot.json"
        history_db = tmp_path / "history.db"

        rc = _run([
            "--manifest", str(manifest),
            "--costs-config", str(costs_path),
            "--output", str(output),
            "--history-db", str(history_db),
        ], monkeypatch)

        assert rc == 0
        snapshot = json.loads(output.read_text())
        assert snapshot["cost_model"].startswith("WP-86 standard")
        assert snapshot["failures"] == []
        [entry] = snapshot["baselines"]
        assert entry["costs"]["spread_points"] == 1.0
        [result] = entry["results"]
        assert result["params"] == {}
        assert result["total_trades"] >= 1
        assert isinstance(result["history_run_id"], int)

        history = BacktestHistory(str(history_db))
        rows = history.list_runs(triggered_by="baseline")
        assert len(rows) == 1

    def test_costed_baseline_is_worse_than_frictionless(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        _write_dataset(data_dir, "US500.cash", "5m")
        costs_path = tmp_path / "costs.json"
        _write_costs(costs_path)
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, data_dir)

        costed_out = tmp_path / "costed.json"
        rc = _run([
            "--manifest", str(manifest),
            "--costs-config", str(costs_path),
            "--output", str(costed_out),
            "--no-history",
        ], monkeypatch)
        assert rc == 0

        free_out = tmp_path / "free.json"
        rc = _run([
            "--manifest", str(manifest),
            "--costs-config", str(costs_path),
            "--output", str(free_out),
            "--no-history",
            "--frictionless",
        ], monkeypatch)
        assert rc == 0

        costed = json.loads(costed_out.read_text())["baselines"][0]["results"][0]
        free = json.loads(free_out.read_text())["baselines"][0]["results"][0]
        assert costed["net_pnl"] < free["net_pnl"]

    def test_missing_data_fails_without_writing(self, tmp_path, monkeypatch):
        costs_path = tmp_path / "costs.json"
        _write_costs(costs_path)
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, tmp_path / "no-data")
        output = tmp_path / "snapshot.json"

        rc = _run([
            "--manifest", str(manifest),
            "--costs-config", str(costs_path),
            "--output", str(output),
            "--no-history",
        ], monkeypatch)

        assert rc == 2
        assert not output.exists()

    def test_allow_partial_records_failures(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        _write_dataset(data_dir, "US500.cash", "5m")
        costs_path = tmp_path / "costs.json"
        _write_costs(costs_path)
        manifest = tmp_path / "manifest.json"
        _write_manifest(manifest, data_dir, entries=[
            {
                "strategy": "momentum-US500",
                "instrument": "US500.cash",
                "timeframe": "5m",
                "data_dir": str(data_dir),
                "costs_venue": "testvenue",
                "param_variants": [{}],
            },
            {
                "strategy": "momentum-US500",
                "instrument": "US500.cash",
                "timeframe": "1h",
                "data_dir": str(tmp_path / "no-data"),
                "costs_venue": "testvenue",
                "param_variants": [{}],
            },
        ])
        output = tmp_path / "snapshot.json"

        rc = _run([
            "--manifest", str(manifest),
            "--costs-config", str(costs_path),
            "--output", str(output),
            "--no-history",
            "--allow-partial",
        ], monkeypatch)

        assert rc == 0
        snapshot = json.loads(output.read_text())
        assert len(snapshot["baselines"]) == 1
        assert len(snapshot["failures"]) == 1
        assert "1h" in snapshot["failures"][0]["entry"]

    def test_shipped_manifest_entries_resolve_against_shipped_costs(self):
        manifest = json.loads(Path("config/backtest_baselines.json").read_text())
        from talim.backtest.costs import load_cost_config
        for entry in manifest["baselines"]:
            costs = load_cost_config(entry["costs_venue"], entry["instrument"])
            assert costs.spread_points > 0
            assert entry["param_variants"][0] == {}, "first variant must be defaults"
