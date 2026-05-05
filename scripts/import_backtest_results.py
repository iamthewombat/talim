#!/usr/bin/env python3
"""Import existing JSON backtest result artifacts into SQL summary history.

This keeps JSON files as detail artifacts and writes one searchable summary row
per result/variant into `backtest_runs`.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from talim.backtest.history import BacktestHistory, default_history_path
from talim.models.backtest import BacktestRequest, BacktestResult

METRIC_KEYS = {
    "strategy_name",
    "strategy",
    "instrument",
    "timeframe",
    "rank",
    "label",
    "net_pnl",
    "raw_yearly_pnl",
    "net_after_avg_spread",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "win_rate",
    "profit_factor",
    "total_trades",
    "trades",
    "param_variant",
    "params",
    "matched_dates",
    "period_start",
    "period_end",
    "status",
    "artifact_path",
    "notes",
}
TIMEFRAME_RE = re.compile(r"(?:^|-)(5m|30m|1h|1d)(?:-|$)")


def _infer_strategy(path: Path, row: dict[str, Any] | None = None) -> str:
    if row:
        value = row.get("strategy_name") or row.get("strategy")
        if value:
            return str(value)
    name = path.name
    for prefix in [
        "mean-reversion-AU200",
        "mean-reversion-US500",
        "momentum-AU200",
        "momentum-US500",
    ]:
        if name.startswith(prefix):
            return prefix
    return "unknown"


def _infer_instrument(path: Path, row: dict[str, Any] | None = None) -> str:
    if row and row.get("instrument"):
        return str(row["instrument"])
    text = path.name
    if "AU200" in text:
        return "AU200.cash"
    if "US500" in text:
        return "US500.cash"
    return ""


def _infer_timeframe(path: Path, row: dict[str, Any] | None = None) -> str:
    if row and row.get("timeframe"):
        return str(row["timeframe"])
    match = TIMEFRAME_RE.search(path.name)
    return match.group(1) if match else ""


def _infer_period_start(path: Path, row: dict[str, Any] | None = None) -> str:
    if row and row.get("period_start"):
        return str(row["period_start"])
    match = re.search(r"from-(\d{4}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else ""


def _created_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _params_from_row(row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("param_variant"), dict):
        return dict(row["param_variant"])
    if isinstance(row.get("params"), dict):
        return dict(row["params"])
    return {k: v for k, v in row.items() if k not in METRIC_KEYS}


def _result_from_row(path: Path, row: dict[str, Any], *, strategy: str | None = None, timeframe: str | None = None) -> tuple[BacktestRequest, BacktestResult]:
    strategy_name = strategy or _infer_strategy(path, row)
    instrument = _infer_instrument(path, row)
    tf = timeframe or _infer_timeframe(path, row)
    total_trades = row.get("total_trades", row.get("trades", 0))
    net_pnl = row.get("net_pnl", row.get("net_after_avg_spread", row.get("raw_yearly_pnl", 0.0)))
    params = _params_from_row(row)
    request = BacktestRequest(
        strategy_name=strategy_name,
        instrument=instrument,
        timeframe=tf,
        param_variants=[params],
        data_dir="data/backtest",
        engine="imported-json",
    )
    result = BacktestResult(
        strategy_name=strategy_name,
        net_pnl=float(net_pnl or 0.0),
        sharpe_ratio=float(row.get("sharpe_ratio", 0.0) or 0.0),
        max_drawdown=float(row.get("max_drawdown", 0.0) or 0.0),
        win_rate=float(row.get("win_rate", 0.0) or 0.0),
        total_trades=int(total_trades or 0),
        param_variant=params,
        matched_dates=list(row.get("matched_dates") or []),
        return_pct=float(row.get("return_pct", 0.0) or 0.0),
        sortino_ratio=float(row.get("sortino_ratio", 0.0) or 0.0),
        profit_factor=float(row.get("profit_factor", 0.0) or 0.0),
        period_start=_infer_period_start(path, row),
        period_end=str(row.get("period_end", "") or ""),
        status=str(row.get("status", "completed") or "completed"),
        artifact_path=str(path),
    )
    return request, result


def _rows_from_summary(path: Path, data: dict[str, Any]) -> Iterable[tuple[BacktestRequest, BacktestResult]]:
    strategy = str(data.get("strategy") or _infer_strategy(path))
    instrument = str(data.get("instrument") or _infer_instrument(path))
    for tf, metrics in (data.get("baseline") or {}).items():
        if isinstance(metrics, dict):
            row = {**metrics, "timeframe": tf, "instrument": instrument, "param_variant": {}, "status": "completed"}
            yield _result_from_row(path, row, strategy=strategy, timeframe=str(tf))
    for tf, rows in (data.get("sweep_top10") or {}).items():
        for row in rows or []:
            if isinstance(row, dict):
                row = {**row, "timeframe": tf, "instrument": instrument, "status": "completed"}
                yield _result_from_row(path, row, strategy=strategy, timeframe=str(tf))


def _iter_results(path: Path) -> Iterable[tuple[BacktestRequest, BacktestResult]]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        for row in data["results"]:
            if isinstance(row, dict):
                yield _result_from_row(path, row)
        return
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict):
                yield _result_from_row(path, row)
        return
    if isinstance(data, dict) and ("baseline" in data or "sweep_top10" in data):
        yield from _rows_from_summary(path, data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["data/backtest/results"], help="JSON file or directory paths to import")
    parser.add_argument("--history-db", default=None, help="SQLite history DB path")
    parser.add_argument("--dry-run", action="store_true", help="Count importable rows without writing")
    args = parser.parse_args()

    files: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        else:
            files.append(path)

    history = None if args.dry_run else BacktestHistory(args.history_db or default_history_path())
    imported = 0
    skipped = 0
    for path in files:
        try:
            rows = list(_iter_results(path))
        except Exception as exc:
            print(f"skip {path}: {exc}")
            skipped += 1
            continue
        if not rows:
            skipped += 1
            continue
        for request, result in rows:
            imported += 1
            if history is not None:
                history.record_run(
                    result=result,
                    request=request,
                    triggered_by="import",
                    notes=f"imported from {path.name}",
                    created_at=_created_at(path),
                    status=result.status,
                    artifact_path=str(path),
                )
    print(json.dumps({"imported": imported, "skipped_files": skipped, "dry_run": args.dry_run}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
