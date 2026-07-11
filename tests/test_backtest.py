"""Tests for the backtest engine (WP-12)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from talim.app.nodes.backtest_run import backtest_run
from talim.backtest.engine import run_backtest
from talim.backtest.metrics import Trade, compute_metrics
from talim.backtest.data_loader import load_ohlcv
from talim.backtest.sizing import BacktestSizingConfig, size_trade
from talim.models.backtest import BacktestRequest, BacktestResult


# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------

def _sine_df(n: int = 400, freq: str = "5min") -> pd.DataFrame:
    close = 5000.0 + 60.0 * np.sin(np.arange(n) * 0.12)
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01 09:30", periods=n, freq=freq),
        "open": close,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(n, 10000.0),
    })


# ---------------------------------------------------------------------------
# Metrics unit tests
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_empty_trades(self):
        m = compute_metrics([])
        assert m["total_trades"] == 0
        assert m["net_pnl"] == 0.0
        assert m["sharpe_ratio"] == 0.0
        assert m["max_drawdown"] == 0.0
        assert m["win_rate"] == 0.0

    def test_known_sequence(self):
        # 3 wins of +10, 2 losses of -5: net=20, win_rate=0.6
        trades = [
            Trade("long", 100, 110),
            Trade("long", 100, 110),
            Trade("long", 100, 110),
            Trade("long", 100, 95),
            Trade("long", 100, 95),
        ]
        m = compute_metrics(trades)
        assert m["total_trades"] == 5
        assert m["net_pnl"] == pytest.approx(20.0)
        assert m["win_rate"] == pytest.approx(0.6)
        assert m["sharpe_ratio"] != 0.0

    def test_short_pnl(self):
        # Short entry 100, exit 90 → +10 PnL
        m = compute_metrics([Trade("short", 100, 90)])
        assert m["net_pnl"] == pytest.approx(10.0)

    def test_max_drawdown(self):
        # +10, -20, +5 → equity 10, -10, -5; peak 10; trough -10; dd = -20
        trades = [Trade("long", 100, 110), Trade("long", 100, 80), Trade("long", 100, 105)]
        m = compute_metrics(trades)
        assert m["max_drawdown"] == pytest.approx(-20.0)


class TestSizing:
    def test_risk_pct_sizes_from_entry_to_stop_risk(self):
        cfg = BacktestSizingConfig(
            initial_capital=10_000.0,
            mode="risk_pct",
            risk_per_trade_pct=0.02,
        )
        qty = size_trade(
            entry_price=100.0,
            stop_price=95.0,
            available_capital=10_000.0,
            config=cfg,
        )
        assert qty == pytest.approx(40.0)  # $200 risk budget / $5 unit risk

    def test_sizing_respects_position_and_exposure_caps(self):
        cfg = BacktestSizingConfig(
            initial_capital=10_000.0,
            mode="risk_pct",
            risk_per_trade_pct=0.10,
            max_position_qty=25.0,
            max_total_exposure=1_000.0,
        )
        qty = size_trade(
            entry_price=100.0,
            stop_price=90.0,
            available_capital=10_000.0,
            config=cfg,
        )
        assert qty == pytest.approx(10.0)  # exposure cap wins: $1,000 / $100


# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------

class TestEngine:
    def test_runs_with_default_params(self):
        df = _sine_df()
        results = run_backtest("momentum-US500", param_variants=[{}], df=df)
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, BacktestResult)
        assert r.strategy_name == "momentum-US500"
        assert r.total_trades >= 1

    def test_two_variants_both_returned(self):
        df = _sine_df()
        variants = [
            {"ema_fast_period": 5, "ema_slow_period": 13},
            {"ema_fast_period": 8, "ema_slow_period": 21},
        ]
        results = run_backtest("momentum-US500", param_variants=variants, df=df)
        assert len(results) == 2
        # Each variant tag is preserved.
        sent = {tuple(sorted(v.items())) for v in variants}
        got = {tuple(sorted(r.param_variant.items())) for r in results}
        assert sent == got

    def test_results_sorted_by_sharpe_desc(self):
        df = _sine_df()
        variants = [
            {"ema_fast_period": 5, "ema_slow_period": 13},
            {"ema_fast_period": 8, "ema_slow_period": 21},
            {"ema_fast_period": 12, "ema_slow_period": 34},
        ]
        results = run_backtest("momentum-US500", param_variants=variants, df=df)
        sharpes = [r.sharpe_ratio for r in results]
        assert sharpes == sorted(sharpes, reverse=True)

    def test_no_signals_yields_zero_metrics(self):
        # Truly flat data → no crossovers → no trades.
        n = 200
        flat = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="5min"),
            "open": np.full(n, 5000.0),
            "high": np.full(n, 5000.5),
            "low": np.full(n, 4999.5),
            "close": np.full(n, 5000.0),
            "volume": np.full(n, 10000.0),
        })
        results = run_backtest("momentum-US500", df=flat)
        assert results[0].total_trades == 0
        assert results[0].net_pnl == 0.0

    def test_runs_au200_strategy_from_timeframe_file(self, tmp_path):
        df = _sine_df()
        inst_dir = tmp_path / "AU200.cash"
        inst_dir.mkdir()
        df.to_parquet(inst_dir / "1h.parquet")
        results = run_backtest(
            "momentum-AU200",
            param_variants=[{}],
            data_dir=tmp_path,
            instrument="AU200.cash",
            timeframe="1h",
        )
        assert len(results) == 1
        assert results[0].strategy_name == "momentum-AU200"

    def test_risk_pct_sizing_changes_backtest_scale_and_return_basis(self):
        df = _sine_df()
        fixed = run_backtest("momentum-US500", param_variants=[{}], df=df)[0]
        sized = run_backtest(
            "momentum-US500",
            param_variants=[{}],
            df=df,
            sizing=BacktestSizingConfig(
                initial_capital=10_000.0,
                mode="risk_pct",
                risk_per_trade_pct=0.01,
                max_position_qty=10.0,
            ),
        )[0]
        assert sized.total_trades == fixed.total_trades
        assert sized.net_pnl != pytest.approx(fixed.net_pnl)
        assert sized.return_pct == pytest.approx(sized.net_pnl / 10_000.0)


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

class TestDataLoader:
    def test_load_single_file(self, tmp_path):
        df = _sine_df(50)
        path = tmp_path / "ES.parquet"
        df.to_parquet(path)
        loaded = load_ohlcv(tmp_path, "ES")
        assert len(loaded) == 50

    def test_load_per_day_directory(self, tmp_path):
        df = _sine_df(48, freq="30min")  # 24 hours
        sub = tmp_path / "ES"
        sub.mkdir()
        for d, group in df.groupby(df["timestamp"].dt.date):
            group.to_parquet(sub / f"{d.isoformat()}.parquet")
        loaded = load_ohlcv(tmp_path, "ES")
        assert len(loaded) == 48

    def test_load_timeframe_specific_file(self, tmp_path):
        df = _sine_df(100, freq="1h")
        sub = tmp_path / "AU200.cash"
        sub.mkdir()
        df.to_parquet(sub / "1h.parquet")
        loaded = load_ohlcv(tmp_path, "AU200.cash", timeframe="1h")
        assert len(loaded) == 100

    def test_missing_data_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_ohlcv(tmp_path, "NOPE")

    def test_missing_timeframe_file_raises_without_fallback(self, tmp_path):
        # Directory exists with a generic parquet but no <timeframe>.parquet.
        sub = tmp_path / "US500.cash"
        sub.mkdir()
        _sine_df(20).to_parquet(sub / "some-other-day.parquet")
        with pytest.raises(FileNotFoundError, match="No 1h parquet"):
            load_ohlcv(tmp_path, "US500.cash", timeframe="1h")

    def test_empty_parquet_raises(self, tmp_path):
        sub = tmp_path / "US500.cash"
        sub.mkdir()
        empty = pd.DataFrame(
            {"timestamp": pd.to_datetime([]), "open": [], "high": [], "low": [], "close": [], "volume": []}
        )
        empty.to_parquet(sub / "5m.parquet")
        with pytest.raises(ValueError, match="empty"):
            load_ohlcv(tmp_path, "US500.cash", timeframe="5m")

    def test_multi_price_type_file_defaults_to_mid_rows(self, tmp_path):
        base = _sine_df(10, freq="1h")
        frames = []
        for price_type, offset in [("BID", -1.0), ("MID", 0.0), ("ASK", 1.0)]:
            frame = base.copy()
            frame["price_type"] = price_type
            frame["close"] = frame["close"] + offset
            frames.append(frame)
        sub = tmp_path / "AU200.proxy"
        sub.mkdir()
        pd.concat(frames, ignore_index=True).to_parquet(sub / "1h.parquet")

        loaded = load_ohlcv(tmp_path, "AU200.proxy", timeframe="1h")

        assert len(loaded) == len(base)
        assert set(loaded["price_type"]) == {"MID"}
        assert loaded["timestamp"].is_unique

    def test_duplicate_timestamps_raise_after_price_type_filtering(self, tmp_path):
        df = pd.concat([_sine_df(5, freq="1h"), _sine_df(5, freq="1h")], ignore_index=True)
        sub = tmp_path / "US500.cash"
        sub.mkdir()
        df.to_parquet(sub / "1h.parquet")

        with pytest.raises(ValueError, match="duplicate timestamp"):
            load_ohlcv(tmp_path, "US500.cash", timeframe="1h")


# ---------------------------------------------------------------------------
# Node + graph integration
# ---------------------------------------------------------------------------

class TestBacktestNode:
    def test_node_no_request(self):
        assert backtest_run({}) == {}

    def test_node_writes_result(self, tmp_path):
        df = _sine_df()
        (tmp_path / "ES.parquet").write_bytes(b"")  # placeholder, replaced below
        df.to_parquet(tmp_path / "ES.parquet")
        req = BacktestRequest(
            strategy_name="momentum-US500",
            param_variants=[{}],
            data_dir=str(tmp_path),
        )
        update = backtest_run({"pending_backtest": req})
        assert update["pending_backtest"] is None
        assert isinstance(update["backtest_result"], list)
        assert update["backtest_result"][0].strategy_name == "momentum-US500"

    def test_node_supports_au200_instrument_and_timeframe(self, tmp_path):
        df = _sine_df(300, freq="1h")
        inst_dir = tmp_path / "AU200.cash"
        inst_dir.mkdir()
        df.to_parquet(inst_dir / "1h.parquet")
        req = BacktestRequest(
            strategy_name="momentum-AU200",
            instrument="AU200.cash",
            timeframe="1h",
            param_variants=[{}],
            data_dir=str(tmp_path),
        )
        update = backtest_run({"pending_backtest": req})
        assert update["pending_backtest"] is None
        assert update["backtest_result"] is not None
        assert update["backtest_result"][0].strategy_name == "momentum-AU200"

    def test_graph_cron_with_pending_backtest(self, tmp_path):
        from talim.app.entrypoints import cron_trigger

        df = _sine_df()
        df.to_parquet(tmp_path / "ES.parquet")
        req = BacktestRequest(
            strategy_name="momentum-US500",
            param_variants=[{}],
            data_dir=str(tmp_path),
        )
        # Use a thread that bypasses signal_scanner: include last_scan_time so
        # cron_trigger doesn't think it's empty. Pending_backtest routes to
        # backtest_run via the router.
        final = cron_trigger(
            initial_state={"pending_backtest": req},  # type: ignore[arg-type]
            thread_id="bt-int-1",
        )
        assert final.get("pending_backtest") is None
        assert final.get("backtest_result") is not None
        assert len(final["backtest_result"]) == 1
