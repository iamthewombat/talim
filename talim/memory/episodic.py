"""Episodic memory — records and queries trading decisions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from pathlib import Path


_SCHEMA = Path(__file__).parent / "schema.sql"


class EpisodicMemory:
    """SQLite-backed store for trading decisions."""

    def __init__(self, db_path: str = "talim_memory.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        schema = _SCHEMA.read_text()
        self._conn.executescript(schema)
        self._migrate_decisions()
        self._migrate_signals()

    def _migrate_decisions(self) -> None:
        """Idempotently add WP-21 columns to pre-existing decisions tables."""
        existing = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(decisions)").fetchall()
        }
        adds = [
            ("signal_type", "TEXT NOT NULL DEFAULT 'entry'"),
            ("atr_ratio", "REAL DEFAULT NULL"),
            ("action", "TEXT NOT NULL DEFAULT ''"),
            ("notes", "TEXT NOT NULL DEFAULT ''"),
        ]
        for name, ddl in adds:
            if name not in existing:
                self._conn.execute(f"ALTER TABLE decisions ADD COLUMN {name} {ddl}")
        self._conn.commit()


    def _migrate_signals(self) -> None:
        """Idempotently add durable signal lifecycle storage (WP-76)."""
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL UNIQUE,
                thread_id TEXT NOT NULL DEFAULT 'cron-main',
                status TEXT NOT NULL DEFAULT 'pending',
                instrument TEXT NOT NULL,
                strategy TEXT NOT NULL,
                side TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'enter',
                entry_price REAL NOT NULL,
                stop REAL NOT NULL,
                target REAL NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                regime TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                source_bar_timestamp TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                approved_at TEXT DEFAULT NULL,
                rejected_at TEXT DEFAULT NULL,
                executed_at TEXT DEFAULT NULL,
                decision_actor TEXT DEFAULT NULL,
                latest_validation_status TEXT DEFAULT NULL,
                latest_validation_reason TEXT DEFAULT NULL,
                dashboard_url TEXT DEFAULT NULL,
                context_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        existing = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(signals)").fetchall()
        }
        adds = [
            ("thread_id", "TEXT NOT NULL DEFAULT 'cron-main'"),
            ("status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("action", "TEXT NOT NULL DEFAULT 'enter'"),
            ("confidence", "REAL NOT NULL DEFAULT 0.0"),
            ("source_bar_timestamp", "TEXT DEFAULT NULL"),
            ("approved_at", "TEXT DEFAULT NULL"),
            ("rejected_at", "TEXT DEFAULT NULL"),
            ("executed_at", "TEXT DEFAULT NULL"),
            ("decision_actor", "TEXT DEFAULT NULL"),
            ("latest_validation_status", "TEXT DEFAULT NULL"),
            ("latest_validation_reason", "TEXT DEFAULT NULL"),
            ("dashboard_url", "TEXT DEFAULT NULL"),
            ("context_json", "TEXT NOT NULL DEFAULT '{}'"),
        ]
        for name, ddl in adds:
            if name not in existing:
                self._conn.execute(f"ALTER TABLE signals ADD COLUMN {name} {ddl}")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_instrument ON signals(instrument)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at)")
        self._conn.commit()

    def record_decision(
        self,
        *,
        timestamp: str,
        instrument: str,
        strategy: str,
        side: str,
        entry_price: float,
        stop: float,
        target: float,
        regime: str = "",
        rationale: str = "",
        outcome: str = "pending",
        pnl: float = 0.0,
        approved: bool = True,
        signal_type: str = "entry",
        atr_ratio: float | None = None,
        action: str = "",
        notes: str = "",
    ) -> int:
        """Record a trading decision. Returns the row id."""
        cur = self._conn.execute(
            """
            INSERT INTO decisions
                (timestamp, instrument, strategy, side, entry_price, stop, target,
                 regime, rationale, outcome, pnl, approved,
                 signal_type, atr_ratio, action, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp, instrument, strategy, side, entry_price, stop, target,
                regime, rationale, outcome, pnl, 1 if approved else 0,
                signal_type, atr_ratio, action, notes,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def query_decisions(
        self,
        instrument: str | None = None,
        strategy: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Query decisions with optional filters."""
        clauses = []
        params: list = []

        if instrument is not None:
            clauses.append("instrument = ?")
            params.append(instrument)
        if strategy is not None:
            clauses.append("strategy = ?")
            params.append(strategy)
        if date_from is not None:
            clauses.append("timestamp >= ?")
            params.append(date_from)
        if date_to is not None:
            clauses.append("timestamp <= ?")
            params.append(date_to)

        where = " AND ".join(clauses) if clauses else "1=1"
        rows = self._conn.execute(
            f"SELECT * FROM decisions WHERE {where} ORDER BY timestamp", params
        ).fetchall()
        return [dict(row) for row in rows]

    def get_stats(self, strategy: str) -> dict:
        """Get aggregate stats for a strategy."""
        rows = self._conn.execute(
            """
            SELECT
                COUNT(*) as total_decisions,
                SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl
            FROM decisions
            WHERE strategy = ?
            """,
            (strategy,),
        ).fetchone()
        return dict(rows) if rows else {}

    def record_activation(
        self,
        *,
        strategy: str,
        action: str,
        actor: str = "operator",
        notes: str = "",
        timestamp: str | None = None,
    ) -> int:
        """Record a strategy enable/disable event (WP-70). Returns the row id."""
        ts = timestamp or datetime.now(tz=timezone.utc).isoformat()
        cur = self._conn.execute(
            """
            INSERT INTO strategy_activations
                (timestamp, strategy, action, actor, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ts, strategy, action, actor, notes),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def query_activations(
        self,
        *,
        strategy: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if strategy is not None:
            clauses.append("strategy = ?")
            params.append(strategy)
        where = " AND ".join(clauses) if clauses else "1=1"
        rows = self._conn.execute(
            f"""
            SELECT * FROM strategy_activations
            WHERE {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]


    @staticmethod
    def signal_id_for(signal: dict[str, Any]) -> str:
        """Return a stable public id for a signal snapshot."""
        parts = [
            signal.get("strategy"),
            signal.get("instrument"),
            signal.get("side"),
            signal.get("action", "enter"),
            signal.get("entry_price"),
            signal.get("timestamp"),
        ]
        raw = "|".join("" if part is None else str(part) for part in parts)
        return "SIG-" + hashlib.sha256(raw.encode()).hexdigest()[:12].upper()

    def record_signal(
        self,
        *,
        signal: dict[str, Any],
        thread_id: str = "cron-main",
        status: str = "pending",
        context: dict[str, Any] | None = None,
        dashboard_url: str | None = None,
        signal_id: str | None = None,
    ) -> str:
        """Upsert a durable signal lifecycle row and return its signal_id."""
        sid = signal_id or self.signal_id_for(signal)
        now = datetime.now(tz=timezone.utc).isoformat()
        source_ts = signal.get("timestamp")
        created_at = source_ts or now
        context_json = json.dumps(context or {}, sort_keys=True, default=str)
        self._conn.execute(
            """
            INSERT INTO signals
                (signal_id, thread_id, status, instrument, strategy, side, action,
                 entry_price, stop, target, rationale, regime, confidence,
                 source_bar_timestamp, created_at, updated_at, dashboard_url, context_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signal_id) DO UPDATE SET
                thread_id=excluded.thread_id,
                status=CASE
                    WHEN signals.status IN ('approved', 'rejected', 'executed', 'invalid', 'expired', 'superseded')
                    THEN signals.status
                    ELSE excluded.status
                END,
                updated_at=excluded.updated_at,
                dashboard_url=excluded.dashboard_url,
                context_json=excluded.context_json
            """,
            (
                sid, thread_id, status, signal.get("instrument", ""),
                signal.get("strategy", ""), signal.get("side", ""),
                signal.get("action", "enter"), float(signal.get("entry_price", 0.0)),
                float(signal.get("stop", 0.0)), float(signal.get("target", 0.0)),
                signal.get("rationale", ""), signal.get("regime_context") or signal.get("regime") or "",
                float(signal.get("confidence", 0.0) or 0.0), source_ts, created_at, now,
                dashboard_url, context_json,
            ),
        )
        self._conn.commit()
        return sid

    def get_signal(self, signal_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM signals WHERE signal_id = ?", (signal_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        try:
            data["context"] = json.loads(data.get("context_json") or "{}")
        except json.JSONDecodeError:
            data["context"] = {}
        return data

    def update_signal_status(
        self,
        signal_id: str,
        *,
        status: str,
        actor: str | None = None,
        validation_status: str | None = None,
        validation_reason: str | None = None,
    ) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        fields = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, now]
        if actor is not None:
            fields.append("decision_actor = ?")
            params.append(actor)
        if validation_status is not None:
            fields.append("latest_validation_status = ?")
            params.append(validation_status)
        if validation_reason is not None:
            fields.append("latest_validation_reason = ?")
            params.append(validation_reason)
        if status == "approved":
            fields.append("approved_at = ?")
            params.append(now)
        elif status == "rejected":
            fields.append("rejected_at = ?")
            params.append(now)
        elif status == "executed":
            fields.append("executed_at = ?")
            params.append(now)
        params.append(signal_id)
        self._conn.execute(
            f"UPDATE signals SET {', '.join(fields)} WHERE signal_id = ?", params
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
