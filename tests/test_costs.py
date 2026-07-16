"""Tests for standardised backtest cost assumptions (BR-05 / WP-86)."""

import json

import numpy as np
import pandas as pd
import pytest

from talim.backtest.costs import (
    DEFAULT_COSTS_PATH,
    ZERO_COSTS,
    BacktestCostConfig,
    load_cost_config,
)
from talim.backtest.engine import run_backtest
from talim.backtest.metrics import Trade


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


class TestCostConfig:
    def test_rejects_negative_values(self):
        with pytest.raises(ValueError):
            BacktestCostConfig(spread_points=-0.1)
        with pytest.raises(ValueError):
            BacktestCostConfig(slippage_points=-0.1)
        with pytest.raises(ValueError):
            BacktestCostConfig(commission_per_side=-1.0)

    def test_long_fills_are_adverse_on_both_sides(self):
        costs = BacktestCostConfig(spread_points=1.0, slippage_points=0.5)
        # half-spread 0.5 + slippage 0.5 = 1.0 point per fill
        assert costs.entry_fill(100.0, "long") == pytest.approx(101.0)
        assert costs.exit_fill(100.0, "long") == pytest.approx(99.0)

    def test_short_fills_are_adverse_on_both_sides(self):
        costs = BacktestCostConfig(spread_points=1.0, slippage_points=0.5)
        assert costs.entry_fill(100.0, "short") == pytest.approx(99.0)
        assert costs.exit_fill(100.0, "short") == pytest.approx(101.0)

    def test_zero_costs_change_nothing(self):
        assert ZERO_COSTS.entry_fill(100.0, "long") == 100.0
        assert ZERO_COSTS.exit_fill(100.0, "short") == 100.0
        assert ZERO_COSTS.round_trip_commission(3.0) == 0.0

    def test_commission_is_per_side_times_qty(self):
        costs = BacktestCostConfig(commission_per_side=2.5)
        assert costs.round_trip_commission(4.0) == pytest.approx(20.0)


class TestTradeFees:
    def test_fees_subtract_from_pnl(self):
        assert Trade("long", 100.0, 110.0, qty=2.0, fees=3.0).pnl == pytest.approx(17.0)
        assert Trade("short", 100.0, 90.0, qty=1.0, fees=1.0).pnl == pytest.approx(9.0)


class TestLoader:
    def test_loads_known_venue_instrument(self, tmp_path):
        path = tmp_path / "costs.json"
        path.write_text(json.dumps({
            "venues": {
                "demo": {
                    "instruments": {
                        "X.cash": {
                            "spread_points": 1.5,
                            "slippage_points": 0.2,
                            "commission_per_side": 0.0,
                        }
                    }
                }
            }
        }))
        costs = load_cost_config("demo", "X.cash", path=path)
        assert costs.spread_points == 1.5
        assert costs.slippage_points == 0.2
        assert "demo/X.cash" in costs.source

    def test_unknown_venue_fails_loudly(self, tmp_path):
        path = tmp_path / "costs.json"
        path.write_text(json.dumps({"venues": {}}))
        with pytest.raises(ValueError, match="no cost assumptions for venue"):
            load_cost_config("nope", "X.cash", path=path)

    def test_unknown_instrument_fails_loudly(self, tmp_path):
        path = tmp_path / "costs.json"
        path.write_text(json.dumps({"venues": {"demo": {"instruments": {}}}}))
        with pytest.raises(ValueError, match="no cost assumptions for instrument"):
            load_cost_config("demo", "X.cash", path=path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_cost_config("demo", "X.cash", path=tmp_path / "absent.json")

    @pytest.mark.parametrize(
        ("venue", "instrument"),
        [
            ("forexcom", "US500.cash"),
            ("forexcom", "AU200.cash"),
            ("ig", "US500.cash"),
            ("ig", "AU200.cash"),
            ("dukascopy-proxy", "US500.proxy"),
            ("dukascopy-proxy", "AU200.proxy"),
        ],
    )
    def test_shipped_config_covers_traded_instruments(self, venue, instrument):
        costs = load_cost_config(venue, instrument, path=DEFAULT_COSTS_PATH)
        assert costs.spread_points > 0


class TestEngineIntegration:
    def test_costs_reduce_net_pnl(self):
        df = _sine_df()
        frictionless = run_backtest("momentum-US500", param_variants=[{}], df=df)
        costed = run_backtest(
            "momentum-US500",
            param_variants=[{}],
            df=df,
            costs=BacktestCostConfig(spread_points=1.0, slippage_points=0.5),
        )
        assert frictionless[0].total_trades == costed[0].total_trades
        # 1.0 point round-trip haircut per unit per trade (2 fills x 1.0 adverse
        # points x qty 1) plus symmetric exit adjustments: strictly worse.
        assert costed[0].net_pnl < frictionless[0].net_pnl
        expected_haircut = 2.0 * (1.0 / 2 + 0.5) * frictionless[0].total_trades
        assert frictionless[0].net_pnl - costed[0].net_pnl == pytest.approx(
            expected_haircut
        )

    def test_commission_reduces_pnl_by_flat_amount(self):
        df = _sine_df()
        frictionless = run_backtest("momentum-US500", param_variants=[{}], df=df)
        costed = run_backtest(
            "momentum-US500",
            param_variants=[{}],
            df=df,
            costs=BacktestCostConfig(commission_per_side=2.0),
        )
        expected = 2.0 * 2.0 * frictionless[0].total_trades  # 2 sides x $2 x qty 1
        assert frictionless[0].net_pnl - costed[0].net_pnl == pytest.approx(expected)
