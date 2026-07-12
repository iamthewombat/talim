#!/usr/bin/env python3
"""Re-record all strategy baselines with standardised costs (WP-86/WP-87).

Runs every entry in config/backtest_baselines.json through the on_bar engine
with the standard venue cost assumptions, records each variant to the backtest
history DB (triggered_by="baseline"), and writes one dated JSON snapshot to
docs/backtest-baselines/.

Requires the ingested parquet datasets referenced by each entry's data_dir
(deploy-host task; see docs/backtest-us500-runbook.md for ingestion).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from talim.backtest.costs import DEFAULT_COSTS_PATH, load_cost_config
from talim.backtest.engine import run_backtest
from talim.backtest.history import BacktestHistory, default_history_path
from talim.backtest.sizing import BacktestSizingConfig
from talim.models.backtest import BacktestRequest

DEFAULT_MANIFEST = Path("config/backtest_baselines.json")
DEFAULT_OUTPUT_DIR = Path("docs/backtest-baselines")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Baseline set JSON (default: config/backtest_baselines.json)",
    )
    parser.add_argument(
        "--costs-config",
        default=str(DEFAULT_COSTS_PATH),
        help="Cost assumptions JSON (default: config/backtest_costs.json)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output snapshot path (default: "
            "docs/backtest-baselines/baselines-<YYYY-MM-DD>.json)"
        ),
    )
    parser.add_argument(
        "--history-db",
        default=None,
        help="Backtest history SQLite DB (default: $TALIM_BACKTEST_HISTORY_DB or state/backtest_history.db)",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Skip recording runs to the backtest history store",
    )
    parser.add_argument(
        "--frictionless",
        action="store_true",
        help="Skip cost assumptions (debugging only; snapshot is marked frictionless)",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Write the snapshot even if some entries fail (e.g. one venue's "
            "data is not ingested yet); failures are recorded in the snapshot"
        ),
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Free-text note stored in the snapshot and history rows",
    )
    return parser


def _run_entry(entry: dict, *, costs_config: str, frictionless: bool, sizing: BacktestSizingConfig) -> dict:
    strategy = entry["strategy"]
    instrument = entry["instrument"]
    timeframe = entry.get("timeframe")
    data_dir = entry["data_dir"]
    variants = entry.get("param_variants") or [{}]

    costs = None
    if not frictionless:
        costs = load_cost_config(entry["costs_venue"], instrument, path=costs_config)

    results = run_backtest(
        strategy_name=strategy,
        instrument=instrument,
        timeframe=timeframe,
        data_dir=data_dir,
        param_variants=variants,
        sizing=sizing,
        costs=costs,
    )
    # run_backtest sorts by sharpe; keep manifest variant order for stable diffs.
    by_params = {json.dumps(r.param_variant, sort_keys=True): r for r in results}
    ordered = [by_params[json.dumps(v, sort_keys=True)] for v in variants]
    return {
        "strategy": strategy,
        "instrument": instrument,
        "timeframe": timeframe,
        "data_dir": data_dir,
        "costs": costs.to_dict() if costs is not None else None,
        "results": [
            {
                "params": r.param_variant,
                "net_pnl": round(r.net_pnl, 4),
                "sharpe_ratio": round(r.sharpe_ratio, 4),
                "sortino_ratio": round(r.sortino_ratio, 4),
                "max_drawdown": round(r.max_drawdown, 4),
                "win_rate": round(r.win_rate, 4),
                "profit_factor": round(r.profit_factor, 4),
                "total_trades": r.total_trades,
                "return_pct": round(r.return_pct, 6),
                "period_start": r.period_start,
                "period_end": r.period_end,
            }
            for r in ordered
        ],
        "_result_objects": ordered,  # stripped before writing; used for history
    }


def main() -> int:
    args = _build_parser().parse_args()
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"error: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text())
    entries = manifest.get("baselines", [])
    if not entries:
        print(f"error: no baselines defined in {manifest_path}", file=sys.stderr)
        return 2

    # Same sizing the historical baseline snapshots used: fixed 1 unit.
    sizing = BacktestSizingConfig()

    completed: list[dict] = []
    failures: list[dict] = []
    for entry in entries:
        label = f"{entry.get('strategy')}/{entry.get('instrument')}/{entry.get('timeframe')}"
        try:
            completed.append(
                _run_entry(
                    entry,
                    costs_config=args.costs_config,
                    frictionless=args.frictionless,
                    sizing=sizing,
                )
            )
            print(f"ok: {label}", file=sys.stderr)
        except (FileNotFoundError, ValueError) as exc:
            failures.append({"entry": label, "error": str(exc)})
            print(f"fail: {label}: {exc}", file=sys.stderr)

    if failures and not args.allow_partial:
        print(
            f"error: {len(failures)} of {len(entries)} baseline entries failed; "
            "nothing written. Ingest the missing data or rerun with --allow-partial.",
            file=sys.stderr,
        )
        return 2
    if not completed:
        print("error: every baseline entry failed; nothing written.", file=sys.stderr)
        return 2

    history_ids: dict[str, list[int]] = {}
    if not args.no_history:
        history = BacktestHistory(args.history_db or str(default_history_path()))
        for item in completed:
            request = BacktestRequest(
                strategy_name=item["strategy"],
                instrument=item["instrument"],
                timeframe=item["timeframe"],
                param_variants=[r["params"] for r in item["results"]],
                data_dir=item["data_dir"],
                engine="on_bar",
            )
            ids = history.record_results(
                item["_result_objects"],
                request=request,
                triggered_by="baseline",
                notes=args.notes,
            )
            history_ids[f"{item['strategy']}/{item['timeframe']}"] = ids
            for r, run_id in zip(item["results"], ids):
                r["history_run_id"] = run_id

    for item in completed:
        item.pop("_result_objects", None)

    today = datetime.now(tz=UTC).date().isoformat()
    output = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"baselines-{today}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "recorded_at": today,
        "engine": "on_bar",
        "cost_model": "frictionless" if args.frictionless else f"WP-86 standard ({args.costs_config})",
        "sizing": {
            "mode": sizing.mode,
            "fixed_qty": sizing.fixed_qty,
            "initial_capital": sizing.initial_capital,
        },
        "manifest": str(manifest_path),
        "notes": args.notes,
        "baselines": completed,
        "failures": failures,
    }
    output.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(json.dumps({"output": str(output), "entries": len(completed), "failures": len(failures), "history_ids": history_ids}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
