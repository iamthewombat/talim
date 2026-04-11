"""Pattern memory — stores and queries regime fingerprint library."""

from __future__ import annotations

import sqlite3
import struct
from datetime import date
from pathlib import Path

import numpy as np

from talim.regime.fingerprint import compute_fingerprint
from talim.regime.library import build_library


_SCHEMA = Path(__file__).parent / "schema.sql"

# 6 float64 values = 48 bytes
_FP_FORMAT = "6d"


def _pack_fingerprint(fp: np.ndarray) -> bytes:
    return struct.pack(_FP_FORMAT, *fp.tolist())


def _unpack_fingerprint(data: bytes) -> np.ndarray:
    return np.array(struct.unpack(_FP_FORMAT, data), dtype=np.float64)


class PatternMemory:
    """SQLite-backed store for regime fingerprint library."""

    def __init__(self, db_path: str = "talim_memory.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        schema = _SCHEMA.read_text()
        self._conn.executescript(schema)

    def get_library(self) -> tuple[np.ndarray, list[date]]:
        """Load the full fingerprint library.

        Returns:
            (features, dates) where features is shape (n, 6).
        """
        rows = self._conn.execute(
            "SELECT session_date, fingerprint FROM regime_library ORDER BY session_date"
        ).fetchall()

        if not rows:
            return np.empty((0, 6), dtype=np.float64), []

        features = []
        dates = []
        for row in rows:
            features.append(_unpack_fingerprint(row["fingerprint"]))
            dates.append(date.fromisoformat(row["session_date"]))

        return np.array(features, dtype=np.float64), dates

    def update_library(
        self, fingerprints: np.ndarray, dates: list[date], labels: list[str] | None = None
    ) -> int:
        """Insert or update fingerprints in the library.

        Returns the number of rows upserted.
        """
        if labels is None:
            labels = [""] * len(dates)

        count = 0
        for i, (fp, d) in enumerate(zip(fingerprints, dates)):
            packed = _pack_fingerprint(fp)
            label = labels[i] if i < len(labels) else ""
            self._conn.execute(
                """
                INSERT INTO regime_library (session_date, fingerprint, regime_label)
                VALUES (?, ?, ?)
                ON CONFLICT(session_date) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    regime_label = excluded.regime_label
                """,
                (d.isoformat(), packed, label),
            )
            count += 1
        self._conn.commit()
        return count

    def rebuild_from_dataframe(
        self, df: "pd.DataFrame", session_size: int = 50
    ) -> int:
        """Rebuild the library from an OHLCV DataFrame.

        Clears existing entries and rebuilds from scratch.
        """
        import pandas as pd

        features, dates = build_library(df, session_size=session_size)
        if features.shape[0] == 0:
            return 0

        self._conn.execute("DELETE FROM regime_library")
        return self.update_library(features, dates)

    def close(self) -> None:
        self._conn.close()
