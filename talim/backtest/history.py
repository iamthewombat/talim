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
        self._conn.commit()

    def record_run(
        self,
        *,
        result: BacktestResult,
        request: BacktestRequest | None = None,
        engine: str = "on_bar",
        triggered_by: str = "",
        notes: str = "",
        created_at: datetime | None = None,
    ) -> int:
        """Insert one row for a single variant result. Returns the new id."""
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
                 param_variant, matched_dates, net_pnl, sharpe_ratio,
                 max_drawdown, win_rate, total_trades, triggered_by, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                result.strategy_name,
                instrument,
                timeframe,
                engine,
                json.dumps(result.param_variant, sort_keys=True, default=str),
                json.dumps(matched),
                float(result.net_pnl),
                float(result.sharpe_ratio),
                float(result.max_drawdown),
                float(result.win_rate),
                int(result.total_trades),
                triggered_by,
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
    ) -> list[int]:
        """Insert one row per result; return ids in the same order."""
        return [
            self.record_run(
                result=r,
                request=request,
                engine=engine,
                triggered_by=triggered_by,
                notes=notes,
            )
            for r in results
        ]

    def close(self) -> None:
        self._conn.close()


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
