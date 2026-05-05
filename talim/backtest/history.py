"""Backtest run history store (WP-68).

Every backtest run — engine, CLI, or graph node — should call `record_run` so
operators can query what was tested, when, and with what params. Stored in a
dedicated SQLite file so checkpoint/episodic DBs stay focused.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from talim.models.backtest import BacktestRequest, BacktestResult


_SCHEMA = Path(__file__).parent / "schema.sql"

_MIGRATIONS: dict[str, str] = {
    "period_start": "ALTER TABLE backtest_runs ADD COLUMN period_start TEXT NOT NULL DEFAULT ''",
    "period_end": "ALTER TABLE backtest_runs ADD COLUMN period_end TEXT NOT NULL DEFAULT ''",
    "return_pct": "ALTER TABLE backtest_runs ADD COLUMN return_pct REAL NOT NULL DEFAULT 0.0",
    "sortino_ratio": "ALTER TABLE backtest_runs ADD COLUMN sortino_ratio REAL NOT NULL DEFAULT 0.0",
    "profit_factor": "ALTER TABLE backtest_runs ADD COLUMN profit_factor REAL NOT NULL DEFAULT 0.0",
    "status": "ALTER TABLE backtest_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'",
    "artifact_path": "ALTER TABLE backtest_runs ADD COLUMN artifact_path TEXT NOT NULL DEFAULT ''",
}


def default_history_path() -> Path:
    raw = os.environ.get("TALIM_BACKTEST_HISTORY_DB", "state/backtest_history.db")
    return Path(raw)


class BacktestHistory:
    """SQLite-backed history of backtest runs."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = default_history_path()
        path = Path(db_path)
        if path.parent != Path("") and str(path.parent) not in (".", ""):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA.read_text())
        self._migrate_schema()
        self._conn.commit()

    def _migrate_schema(self) -> None:
        """Add summary columns to older history DBs without rewriting rows."""
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(backtest_runs)").fetchall()
        }
        for name, statement in _MIGRATIONS.items():
            if name not in columns:
                self._conn.execute(statement)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_backtest_runs_status ON backtest_runs(status)"
        )

    def record_run(
        self,
        *,
        result: BacktestResult,
        request: BacktestRequest | None = None,
        engine: str = "on_bar",
        triggered_by: str = "",
        notes: str = "",
        created_at: datetime | None = None,
        status: str | None = None,
        artifact_path: str | None = None,
    ) -> int:
        """Insert one summary row for a single variant result. Returns the new id."""
        instrument = getattr(request, "instrument", "") or ""
        timeframe = getattr(request, "timeframe", None) or ""
        if request is not None:
            engine = getattr(request, "engine", engine) or engine
        ts = (created_at or datetime.now(tz=timezone.utc)).isoformat()
        matched = [
            d.isoformat() if isinstance(d, date) else str(d)
            for d in (result.matched_dates or [])
        ]
        cur = self._conn.execute(
            """
            INSERT INTO backtest_runs
                (created_at, strategy, instrument, timeframe, engine,
                 period_start, period_end, param_variant, matched_dates,
                 net_pnl, return_pct, sharpe_ratio, sortino_ratio,
                 max_drawdown, win_rate, profit_factor, total_trades,
                 triggered_by, status, artifact_path, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                result.strategy_name,
                instrument,
                timeframe,
                engine,
                str(getattr(result, "period_start", "") or ""),
                str(getattr(result, "period_end", "") or ""),
                json.dumps(result.param_variant, sort_keys=True, default=str),
                json.dumps(matched),
                float(result.net_pnl),
                float(getattr(result, "return_pct", 0.0) or 0.0),
                float(result.sharpe_ratio),
                float(getattr(result, "sortino_ratio", 0.0) or 0.0),
                float(result.max_drawdown),
                float(result.win_rate),
                float(getattr(result, "profit_factor", 0.0) or 0.0),
                int(result.total_trades),
                triggered_by,
                status or getattr(result, "status", "completed") or "completed",
                artifact_path or getattr(result, "artifact_path", "") or "",
                notes,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def list_runs(
        self,
        *,
        strategy: str | None = None,
        instrument: str | None = None,
        triggered_by: str | None = None,
        status: str | None = None,
        timeframe: str | None = None,
        since: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return runs newest-first, filtered and paginated."""
        clauses: list[str] = []
        params: list[Any] = []
        if strategy is not None:
            clauses.append("strategy = ?")
            params.append(strategy)
        if instrument is not None:
            clauses.append("instrument = ?")
            params.append(instrument)
        if triggered_by is not None:
            clauses.append("triggered_by = ?")
            params.append(triggered_by)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if timeframe is not None:
            clauses.append("timeframe = ?")
            params.append(timeframe)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        where = " AND ".join(clauses) if clauses else "1=1"
        rows = self._conn.execute(
            f"""
            SELECT * FROM backtest_runs
            WHERE {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, int(limit), int(offset)),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]


    def list_outcomes(
        self,
        *,
        strategy: str | None = None,
        instrument: str | None = None,
        status: str | None = None,
        timeframe: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return grouped strategy outcomes built from summary rows."""
        rows = self.list_runs(
            strategy=strategy,
            instrument=instrument,
            status=status,
            timeframe=timeframe,
            since=since,
            limit=100_000,
            offset=0,
        )
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            params = _outcome_params(row.get("param_variant") or {})
            key_payload = {
                "strategy": row.get("strategy") or "",
                "instrument": row.get("instrument") or "",
                "timeframe": row.get("timeframe") or "",
                "params": params,
            }
            key = json.dumps(key_payload, sort_keys=True, separators=(",", ":"))
            group = groups.setdefault(
                key,
                {
                    "key": key,
                    "strategy": key_payload["strategy"],
                    "instrument": key_payload["instrument"],
                    "timeframe": key_payload["timeframe"],
                    "params": params,
                    "run_count": 0,
                    "net_pnl": 0.0,
                    "avg_net_pnl": 0.0,
                    "best_net_pnl": None,
                    "return_pct": 0.0,
                    "sharpe_ratio": 0.0,
                    "best_sharpe": None,
                    "sortino_ratio": 0.0,
                    "profit_factor": 0.0,
                    "max_drawdown": 0.0,
                    "win_rate": 0.0,
                    "total_trades": 0,
                    "latest_created_at": "",
                    "period_start": "",
                    "period_end": "",
                    "status": row.get("status") or "completed",
                    "artifact_paths": [],
                    "run_ids": [],
                },
            )
            trades = int(row.get("total_trades") or 0)
            net = float(row.get("net_pnl") or 0.0)
            return_pct = float(row.get("return_pct") or 0.0)
            sharpe = float(row.get("sharpe_ratio") or 0.0)
            sortino = float(row.get("sortino_ratio") or 0.0)
            profit_factor = float(row.get("profit_factor") or 0.0)
            win_rate = float(row.get("win_rate") or 0.0)
            group["run_count"] += 1
            group["net_pnl"] += net
            group["total_trades"] += trades
            group["return_pct"] += return_pct
            group["sharpe_ratio"] += sharpe
            group["sortino_ratio"] += sortino
            group["profit_factor"] += profit_factor
            group["win_rate"] += win_rate * trades
            if group["best_net_pnl"] is None or net > group["best_net_pnl"]:
                group["best_net_pnl"] = net
                group["best_run_id"] = row.get("id")
            if group["best_sharpe"] is None or sharpe > group["best_sharpe"]:
                group["best_sharpe"] = sharpe
            group["max_drawdown"] = min(float(group["max_drawdown"]), float(row.get("max_drawdown") or 0.0))
            created = str(row.get("created_at") or "")
            if created > group["latest_created_at"]:
                group["latest_created_at"] = created
            start = str(row.get("period_start") or "")
            end = str(row.get("period_end") or "")
            if start and (not group["period_start"] or start < group["period_start"]):
                group["period_start"] = start
            if end and end > group["period_end"]:
                group["period_end"] = end
            artifact = row.get("artifact_path")
            if artifact and artifact not in group["artifact_paths"]:
                group["artifact_paths"].append(artifact)
            group["run_ids"].append(row.get("id"))
        outcomes = []
        for group in groups.values():
            count = group["run_count"] or 1
            trades = group["total_trades"] or 0
            group["avg_net_pnl"] = group["net_pnl"] / count
            group["return_pct"] = group["return_pct"] / count
            group["sharpe_ratio"] = group["sharpe_ratio"] / count
            group["sortino_ratio"] = group["sortino_ratio"] / count
            group["profit_factor"] = group["profit_factor"] / count
            group["win_rate"] = group["win_rate"] / trades if trades else 0.0
            group["artifact_paths"] = group["artifact_paths"][:5]
            group["run_ids"] = group["run_ids"][:20]
            outcomes.append(group)
        outcomes.sort(key=lambda g: (g["sharpe_ratio"], g["net_pnl"]), reverse=True)
        return outcomes[: int(limit)]

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM backtest_runs WHERE id = ?", (int(run_id),)
        ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def record_results(
        self,
        results: list[BacktestResult],
        *,
        request: BacktestRequest | None = None,
        engine: str = "on_bar",
        triggered_by: str = "",
        notes: str = "",
        status: str | None = None,
        artifact_path: str | None = None,
    ) -> list[int]:
        """Insert one row per result; return ids in the same order."""
        return [
            self.record_run(
                result=r,
                request=request,
                engine=engine,
                triggered_by=triggered_by,
                notes=notes,
                status=status,
                artifact_path=artifact_path,
            )
            for r in results
        ]

    def close(self) -> None:
        self._conn.close()



def _outcome_params(params: dict[str, Any]) -> dict[str, Any]:
    """Params that define a strategy variant, excluding validation/run labels."""
    excluded = {"year", "rank", "label"}
    return {k: v for k, v in sorted(params.items()) if k not in excluded}

def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    out["param_variant"] = _safe_loads(out.get("param_variant"), default={})
    out["matched_dates"] = _safe_loads(out.get("matched_dates"), default=[])
    return out


def _safe_loads(value: Any, *, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
