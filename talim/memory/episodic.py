"""Episodic memory — records and queries trading decisions."""

from __future__ import annotations

import sqlite3
from datetime import datetime
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

    def close(self) -> None:
        self._conn.close()
