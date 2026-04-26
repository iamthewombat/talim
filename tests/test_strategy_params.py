"""Tests for WP-72 strategy parameter schema + validated loading."""

from __future__ import annotations

import pytest

from talim.strategy.loader import load_strategy
from talim.strategy.params import (
    ParamSpec,
    StrategyParamError,
    validate_param_dict,
)


# ---------------------------------------------------------------------------
# ParamSpec coercion / validation
# ---------------------------------------------------------------------------


class TestParamSpec:
    def test_int_coerces_whole_float(self):
        spec = ParamSpec("n", int, 10, min=1, max=100)
        assert spec.coerce_and_validate(5.0, strategy="s") == 5

    def test_int_rejects_fractional_float(self):
        spec = ParamSpec("n", int, 10)
        with pytest.raises(StrategyParamError) as exc:
            spec.coerce_and_validate(5.5, strategy="s")
        assert exc.value.param == "n"

    def test_int_rejects_bool(self):
        spec = ParamSpec("n", int, 10)
        with pytest.raises(StrategyParamError):
            spec.coerce_and_validate(True, strategy="s")

    def test_float_coerces_int(self):
        spec = ParamSpec("x", float, 1.0, min=0.0, max=5.0)
        assert spec.coerce_and_validate(3, strategy="s") == 3.0

    def test_float_rejects_string(self):
        spec = ParamSpec("x", float, 1.0)
        with pytest.raises(StrategyParamError):
            spec.coerce_and_validate("3.0", strategy="s")

    def test_min_max_inclusive(self):
        spec = ParamSpec("n", int, 5, min=1, max=10)
        assert spec.coerce_and_validate(1, strategy="s") == 1
        assert spec.coerce_and_validate(10, strategy="s") == 10
        with pytest.raises(StrategyParamError):
            spec.coerce_and_validate(0, strategy="s")
        with pytest.raises(StrategyParamError):
            spec.coerce_and_validate(11, strategy="s")

    def test_choices_allowlist(self):
        spec = ParamSpec("side", str, "long", choices=("long", "short"))
        assert spec.coerce_and_validate("short", strategy="s") == "short"
        with pytest.raises(StrategyParamError):
            spec.coerce_and_validate("sideways", strategy="s")

    def test_bool_handling(self):
        spec = ParamSpec("flag", bool, False)
        assert spec.coerce_and_validate(True, strategy="s") is True
        assert spec.coerce_and_validate(0, strategy="s") is False
        with pytest.raises(StrategyParamError):
            spec.coerce_and_validate("yes", strategy="s")

    def test_to_dict_is_json_safe(self):
        spec = ParamSpec("n", int, 5, min=1, max=10, description="count")
        d = spec.to_dict()
        assert d == {
            "name": "n",
            "type": "int",
            "default": 5,
            "min": 1,
            "max": 10,
            "choices": None,
            "description": "count",
        }


class TestValidateParamDict:
    def test_unknown_key_rejected(self):
        schema = [ParamSpec("a", int, 1)]
        with pytest.raises(StrategyParamError) as exc:
            validate_param_dict({"b": 2}, schema, strategy="s")
        assert exc.value.reason == "unknown parameter"

    def test_partial_update_allowed(self):
        schema = [ParamSpec("a", int, 1), ParamSpec("b", int, 2)]
        assert validate_param_dict({"a": 3}, schema, strategy="s") == {"a": 3}

    def test_all_valid_coerces(self):
        schema = [ParamSpec("a", int, 1, min=0, max=10), ParamSpec("b", float, 2.0)]
        assert validate_param_dict({"a": 5, "b": 3}, schema, strategy="s") == {"a": 5, "b": 3.0}


# ---------------------------------------------------------------------------
# BaseStrategy wiring via real strategies
# ---------------------------------------------------------------------------


class TestStrategySchemaWiring:
    def test_momentum_es_schema_shape(self):
        s = load_strategy("momentum-US500")
        schema = s.params_schema()
        names = {spec["name"] for spec in schema}
        assert names == {
            "ema_fast_period",
            "ema_slow_period",
            "atr_multiplier_stop",
            "atr_multiplier_target",
        }

    def test_current_params_returns_defaults(self):
        s = load_strategy("momentum-US500")
        assert s.current_params() == {
            "ema_fast_period": 8,
            "ema_slow_period": 21,
            "atr_multiplier_stop": 1.5,
            "atr_multiplier_target": 3.0,
        }

    def test_valid_params_load_and_coerce(self):
        s = load_strategy("momentum-US500")
        s.load_params({"ema_fast_period": 10, "atr_multiplier_stop": 2})  # int → float
        assert s.ema_fast_period == 10
        assert s.atr_multiplier_stop == 2.0

    def test_out_of_range_rejected(self):
        s = load_strategy("momentum-US500")
        with pytest.raises(StrategyParamError):
            s.load_params({"ema_fast_period": 0})

    def test_unknown_param_rejected(self):
        s = load_strategy("momentum-US500")
        with pytest.raises(StrategyParamError):
            s.load_params({"ema_fastt_period": 10})  # typo

    def test_wrong_type_rejected(self):
        s = load_strategy("mean-reversion-US500")
        with pytest.raises(StrategyParamError):
            s.load_params({"bb_period": 5.5})

    def test_momentum_au200_schema_covers_all_params(self):
        s = load_strategy("momentum-AU200")
        names = {spec["name"] for spec in s.params_schema()}
        assert names == {
            "ema_fast_period",
            "ema_slow_period",
            "atr_period",
            "atr_multiplier_stop",
            "atr_multiplier_target",
            "min_ema_gap_atr",
        }


# ---------------------------------------------------------------------------
# Backtest CLI surface (non-zero exit on invalid params)
# ---------------------------------------------------------------------------


class TestBacktestCliValidation:
    def test_run_backtest_engine_rejects_bad_variant(self):
        from talim.backtest.engine import run_backtest

        with pytest.raises(StrategyParamError):
            run_backtest(
                strategy_name="momentum-US500",
                param_variants=[{"ema_fast_period": 0}],
                data_dir="data",
                instrument="ES",
            )

    def test_cli_exits_non_zero_on_bad_params(self, tmp_path, monkeypatch):
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "scripts/run_backtest.py",
                "--strategy",
                "momentum-AU200",
                "--instrument",
                "AU200.cash",
                "--data-dir",
                "data/ig",
                "--timeframe",
                "1h",
                "--params",
                '{"ema_fast_period": 999999}',
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "ema_fast_period" in result.stderr


# ---------------------------------------------------------------------------
# strategy_update node validation
# ---------------------------------------------------------------------------


class TestStrategyUpdateValidation:
    def _patch_llm(self, monkeypatch, response_text: str):
        from talim.app import llm_context
        from talim.llm.mock import MockLLMClient

        llm_context.reset_llm_client()
        llm_context.configure_llm_client(MockLLMClient(responses=[response_text]))

    def test_invalid_proposal_is_rejected_not_applied(self, monkeypatch):
        from talim.app.nodes.strategy_update import strategy_update

        self._patch_llm(
            monkeypatch,
            '{"ema_fast_period": 0, "rationale": "tighter"}',
        )
        state = {
            "regime": "momentum",
            "active_strategies": ["momentum-US500"],
            "strategy_params": {"momentum-US500": {"ema_fast_period": 8}},
        }
        update = strategy_update(state)
        # Rejected → no strategy_params mutation, notification explains why
        assert "strategy_params" not in update
        assert "rejected" in update["pending_notification"]
        assert "ema_fast_period" in update["pending_notification"]

    def test_valid_proposal_is_applied(self, monkeypatch):
        from talim.app.nodes.strategy_update import strategy_update

        self._patch_llm(
            monkeypatch,
            '{"ema_fast_period": 10, "rationale": "ok"}',
        )
        state = {
            "regime": "momentum",
            "active_strategies": ["momentum-US500"],
            "strategy_params": {"momentum-US500": {"ema_fast_period": 8, "ema_slow_period": 21}},
        }
        update = strategy_update(state)
        assert update["strategy_params"]["momentum-US500"]["ema_fast_period"] == 10
        # Untouched params persist
        assert update["strategy_params"]["momentum-US500"]["ema_slow_period"] == 21


# ---------------------------------------------------------------------------
# Operator endpoint
# ---------------------------------------------------------------------------


class TestOperatorStrategyParamsEndpoint:
    def test_returns_schema_and_current(self):
        from fastapi.testclient import TestClient

        from talim.api.bridge import create_app

        class _FakeRuntime:
            config = type("C", (), {"strategies": ("momentum-US500",)})()

            def operator_strategy_params(self, name: str):
                from talim.strategy.loader import load_strategy

                if name != "momentum-US500":
                    raise KeyError(name)
                inst = load_strategy(name)
                return {
                    "strategy": name,
                    "schema": inst.params_schema(),
                    "current": inst.current_params(),
                }

        app = create_app(
            bridge_message_fn=lambda **_: {},
            resume_fn=lambda **_: {},
            cron_trigger_fn=lambda **_: {},
        )
        app.state.talim_runtime = _FakeRuntime()

        import os
        os.environ["TALIM_BRIDGE_SECRET"] = "testsecret"
        headers = {"X-Talim-Secret": "testsecret"}
        client = TestClient(app)
        r = client.get("/talim/operator/strategies/momentum-US500/params", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["strategy"] == "momentum-US500"
        assert body["current"]["ema_fast_period"] == 8
        assert any(spec["name"] == "ema_fast_period" for spec in body["schema"])

    def test_unknown_strategy_returns_404(self):
        from fastapi.testclient import TestClient

        from talim.api.bridge import create_app

        class _FakeRuntime:
            def operator_strategy_params(self, name: str):
                raise KeyError(name)

        app = create_app(
            bridge_message_fn=lambda **_: {},
            resume_fn=lambda **_: {},
            cron_trigger_fn=lambda **_: {},
        )
        app.state.talim_runtime = _FakeRuntime()

        import os
        os.environ["TALIM_BRIDGE_SECRET"] = "testsecret"
        headers = {"X-Talim-Secret": "testsecret"}
        client = TestClient(app)
        r = client.get("/talim/operator/strategies/nope/params", headers=headers)
        assert r.status_code == 404
