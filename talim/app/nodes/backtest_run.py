"""backtest_run node — runs the engine on a pending request (WP-12)."""

from __future__ import annotations

import logging

from talim.app.state import TalimState
from talim.backtest.engine import run_backtest
from talim.backtest.history import BacktestHistory, default_history_path
from talim.backtest.vectorbt_engine import (
    VectorbtUnsupported,
    run_vectorbt_backtest,
    vectorbt_available,
)

logger = logging.getLogger("talim.nodes.backtest_run")


def backtest_run(state: TalimState) -> TalimState:
    req = state.get("pending_backtest")
    if req is None:
        logger.info("backtest_run: no pending_backtest, skipping")
        return {}

    engine_choice = getattr(req, "engine", "on_bar")
    try:
        if engine_choice == "vectorbt" and vectorbt_available():
            # WP-29 fast path — requires an in-memory df, so this is mostly
            # used by the tools/MCP layer rather than the disk-loaded path.
            logger.info("backtest_run: using vectorbt engine")
            results = run_vectorbt_backtest(
                strategy_name=req.strategy_name,
                param_variants=req.param_variants or [{}],
                df=getattr(req, "df", None),
            )
        else:
            results = run_backtest(
                strategy_name=req.strategy_name,
                param_variants=req.param_variants or [{}],
                matched_dates=req.matched_dates,
                data_dir=req.data_dir,
                instrument=getattr(req, "instrument", "ES"),
                timeframe=getattr(req, "timeframe", None),
            )
    except VectorbtUnsupported as e:
        logger.warning("backtest_run: vectorbt unsupported (%s); falling back", e)
        results = run_backtest(
            strategy_name=req.strategy_name,
            param_variants=req.param_variants or [{}],
            matched_dates=req.matched_dates,
            data_dir=req.data_dir,
            instrument=getattr(req, "instrument", "ES"),
            timeframe=getattr(req, "timeframe", None),
        )
    except Exception as e:
        logger.exception("backtest_run: engine failed: %s", e)
        return {"pending_backtest": None, "backtest_result": None}

    logger.info(
        "backtest_run: %d variants, best sharpe=%.3f",
        len(results),
        results[0].sharpe_ratio if results else 0.0,
    )

    try:
        history = BacktestHistory(default_history_path())
        history.record_results(
            results,
            request=req,
            engine=engine_choice if engine_choice in {"on_bar", "vectorbt"} else "on_bar",
            triggered_by="node",
        )
    except Exception:  # noqa: BLE001
        logger.warning("backtest_run: history recording failed", exc_info=True)

    return {"pending_backtest": None, "backtest_result": results}
