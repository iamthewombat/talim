"""Tests for memory stores — episodic, pattern, and working memory."""

import tempfile
import threading
from datetime import date

import numpy as np
import pandas as pd
import pytest

from talim.memory.episodic import EpisodicMemory
from talim.memory.pattern import PatternMemory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episodic(tmp_path: str) -> EpisodicMemory:
    return EpisodicMemory(db_path=f"{tmp_path}/test.db")


def _make_pattern(tmp_path: str) -> PatternMemory:
    return PatternMemory(db_path=f"{tmp_path}/test.db")


def _insert_decisions(mem: EpisodicMemory, n: int = 50) -> None:
    for i in range(n):
        mem.record_decision(
            timestamp=f"2025-06-{(i % 28) + 1:02d}T09:30:00",
            instrument="ES" if i % 2 == 0 else "NQ",
            strategy="momentum-US500" if i % 3 != 0 else "mean-reversion-US500",
            side="long" if i % 2 == 0 else "short",
            entry_price=5000.0 + i,
            stop=4980.0 + i,
            target=5040.0 + i,
            regime="momentum",
            rationale=f"test decision {i}",
            outcome="win" if i % 3 == 0 else ("loss" if i % 3 == 1 else "pending"),
            pnl=100.0 if i % 3 == 0 else (-50.0 if i % 3 == 1 else 0.0),
        )


def _make_synthetic_ohlcv(n: int = 200) -> pd.DataFrame:
    rng = np.random.RandomState(42)
    close = 5000.0 + np.cumsum(rng.randn(n))
    # Use 1-hour freq so sessions land on different dates
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="1h"),
        "open": close - rng.uniform(0, 2, n),
        "high": close + rng.uniform(0, 5, n),
        "low": close - rng.uniform(0, 5, n),
        "close": close,
        "volume": rng.uniform(5000, 15000, n),
    })


# ---------------------------------------------------------------------------
# EpisodicMemory tests
# ---------------------------------------------------------------------------

class TestEpisodicMemory:
    def test_records_wp21_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_episodic(tmp)
            mem.record_decision(
                timestamp="2025-06-15T09:30:00",
                instrument="ES",
                strategy="momentum-US500",
                side="long",
                entry_price=5000.0,
                stop=4980.0,
                target=5040.0,
                signal_type="entry",
                atr_ratio=1.4,
                action="approve",
                notes="trader override",
            )
            row = mem.query_decisions(instrument="ES")[0]
            assert row["signal_type"] == "entry"
            assert row["atr_ratio"] == 1.4
            assert row["action"] == "approve"
            assert row["notes"] == "trader override"
            mem.close()

    def test_migrates_old_decisions_table(self):
        # Build an old-shape table without WP-21 columns, then open it.
        with tempfile.TemporaryDirectory() as tmp:
            import sqlite3
            db = f"{tmp}/legacy.db"
            conn = sqlite3.connect(db)
            conn.executescript(
                """
                CREATE TABLE decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop REAL NOT NULL,
                    target REAL NOT NULL,
                    regime TEXT NOT NULL DEFAULT '',
                    rationale TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL DEFAULT 'pending',
                    pnl REAL DEFAULT 0.0,
                    approved INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            conn.execute(
                "INSERT INTO decisions (timestamp, instrument, strategy, side, "
                "entry_price, stop, target) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2025-06-15T09:30:00", "ES", "momentum-US500", "long", 5000.0, 4980.0, 5040.0),
            )
            conn.commit()
            conn.close()

            mem = EpisodicMemory(db_path=db)
            cols = {
                row[1]
                for row in mem._conn.execute("PRAGMA table_info(decisions)").fetchall()
            }
            assert {
                "signal_type", "atr_ratio", "action", "notes",
                "qty", "entry_decision_id",
            } <= cols
            row = mem.query_decisions(instrument="ES")[0]
            assert row["signal_type"] == "entry"  # default applied
            assert row["qty"] is None
            assert row["entry_decision_id"] is None
            mem.close()

    def test_records_trade_link_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_episodic(tmp)
            entry_id = mem.record_decision(
                timestamp="2025-06-15T09:30:00",
                instrument="ES",
                strategy="momentum-US500",
                side="long",
                entry_price=5000.0,
                stop=4980.0,
                target=5040.0,
                signal_type="enter",
                qty=2.0,
            )
            mem.record_decision(
                timestamp="2025-06-15T10:30:00",
                instrument="ES",
                strategy="momentum-US500",
                side="long",
                entry_price=5010.0,
                stop=4980.0,
                target=5040.0,
                signal_type="exit",
                qty=2.0,
                entry_decision_id=entry_id,
            )
            rows = mem.query_decisions(instrument="ES")
            by_type = {r["signal_type"]: r for r in rows}
            assert by_type["enter"]["qty"] == 2.0
            assert by_type["exit"]["qty"] == 2.0
            assert by_type["exit"]["entry_decision_id"] == entry_id
            mem.close()

    def test_close_pending_entries_returns_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_episodic(tmp)
            ids = [
                mem.record_decision(
                    timestamp=f"2025-06-15T09:3{i}:00",
                    instrument="ES",
                    strategy="momentum-US500",
                    side="long",
                    entry_price=5000.0 + i,
                    stop=4980.0,
                    target=5040.0,
                    signal_type="enter",
                    outcome="pending",
                )
                for i in range(2)
            ]
            closed = mem.close_pending_entries(
                instrument="ES", side="long", strategy="momentum-US500"
            )
            assert closed == ids
            assert all(
                r["outcome"] == "closed"
                for r in mem.query_decisions(instrument="ES")
            )
            # Nothing pending remains, so a second call returns no ids.
            assert mem.close_pending_entries(instrument="ES", side="long") == []
            mem.close()

    def test_migration_backfills_trade_links_from_notes(self):
        # Legacy rows carry qty only in notes and no entry link; opening the
        # DB after the WP-85 migration should backfill both.
        with tempfile.TemporaryDirectory() as tmp:
            import sqlite3
            db = f"{tmp}/legacy.db"
            mem = EpisodicMemory(db_path=db)
            mem.close()
            conn = sqlite3.connect(db)
            conn.execute("ALTER TABLE decisions DROP COLUMN qty")
            conn.execute("ALTER TABLE decisions DROP COLUMN entry_decision_id")
            base = (
                "INSERT INTO decisions (timestamp, instrument, strategy, side, "
                "entry_price, stop, target, signal_type, outcome, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            conn.execute(base, (
                "2025-06-15T09:30:00", "ES", "momentum-US500", "long",
                5000.0, 4980.0, 5040.0, "enter", "closed", "order_id=1 qty=2.0",
            ))
            conn.execute(base, (
                "2025-06-15T09:35:00", "NQ", "momentum-US500", "long",
                20_000.0, 19_900.0, 20_200.0, "enter", "pending", "order_id=2 qty=1.0",
            ))
            conn.execute(base, (
                "2025-06-15T10:30:00", "ES", "momentum-US500", "long",
                5010.0, 4980.0, 5040.0, "exit", "closed", "order_id=3 qty=2.0",
            ))
            conn.commit()
            conn.close()

            mem = EpisodicMemory(db_path=db)
            rows = mem.query_decisions()
            by_key = {(r["instrument"], r["signal_type"]): r for r in rows}
            assert by_key[("ES", "enter")]["qty"] == 2.0
            assert by_key[("ES", "exit")]["qty"] == 2.0
            assert (
                by_key[("ES", "exit")]["entry_decision_id"]
                == by_key[("ES", "enter")]["id"]
            )
            # Unrelated pending entry is not claimed by the ES exit.
            assert by_key[("NQ", "enter")]["entry_decision_id"] is None
            assert by_key[("NQ", "enter")]["qty"] == 1.0

            # Backfill only runs when the column is first added: relink to a
            # bogus value and reopen — it must survive.
            mem._conn.execute(
                "UPDATE decisions SET entry_decision_id = NULL WHERE signal_type = 'exit'"
            )
            mem._conn.commit()
            mem.close()
            mem = EpisodicMemory(db_path=db)
            rows = mem.query_decisions(instrument="ES")
            exit_row = next(r for r in rows if r["signal_type"] == "exit")
            assert exit_row["entry_decision_id"] is None
            mem.close()

    def test_record_and_query_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_episodic(tmp)
            _insert_decisions(mem, 50)
            results = mem.query_decisions()
            assert len(results) == 50
            mem.close()

    def test_query_by_instrument(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_episodic(tmp)
            _insert_decisions(mem, 50)
            es_results = mem.query_decisions(instrument="ES")
            nq_results = mem.query_decisions(instrument="NQ")
            assert len(es_results) + len(nq_results) == 50
            assert all(r["instrument"] == "ES" for r in es_results)
            assert all(r["instrument"] == "NQ" for r in nq_results)
            mem.close()

    def test_query_by_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_episodic(tmp)
            _insert_decisions(mem, 50)
            results = mem.query_decisions(strategy="momentum-US500")
            assert len(results) > 0
            assert all(r["strategy"] == "momentum-US500" for r in results)
            mem.close()

    def test_query_by_date_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_episodic(tmp)
            _insert_decisions(mem, 50)
            results = mem.query_decisions(
                date_from="2025-06-10T00:00:00",
                date_to="2025-06-15T23:59:59",
            )
            assert len(results) > 0
            for r in results:
                assert "2025-06-10" <= r["timestamp"] <= "2025-06-15T23:59:59"
            mem.close()

    def test_get_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_episodic(tmp)
            _insert_decisions(mem, 50)
            stats = mem.get_stats("momentum-US500")
            assert stats["total_decisions"] > 0
            assert "wins" in stats
            assert "losses" in stats
            assert "total_pnl" in stats
            assert "avg_pnl" in stats
            mem.close()

    def test_record_returns_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_episodic(tmp)
            row_id = mem.record_decision(
                timestamp="2025-06-15T09:30:00",
                instrument="ES",
                strategy="momentum-US500",
                side="long",
                entry_price=5000.0,
                stop=4980.0,
                target=5040.0,
            )
            assert isinstance(row_id, int)
            assert row_id > 0
            mem.close()

    def test_concurrent_writers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = f"{tmp}/test.db"
            # Initialize schema once
            mem_init = EpisodicMemory(db_path=db_path)
            mem_init.close()

            errors: list[Exception] = []

            def writer(thread_id: int):
                try:
                    # Each thread gets its own connection
                    mem = EpisodicMemory(db_path=db_path)
                    for i in range(25):
                        mem.record_decision(
                            timestamp=f"2025-06-15T09:{thread_id:02d}:{i:02d}",
                            instrument="ES",
                            strategy="momentum-US500",
                            side="long",
                            entry_price=5000.0 + i,
                            stop=4980.0,
                            target=5040.0,
                        )
                    mem.close()
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(t,)) for t in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Concurrent write errors: {errors}"
            mem = EpisodicMemory(db_path=db_path)
            results = mem.query_decisions()
            assert len(results) == 50
            mem.close()


# ---------------------------------------------------------------------------
# PatternMemory tests
# ---------------------------------------------------------------------------

class TestPatternMemory:
    def test_update_and_get_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_pattern(tmp)
            rng = np.random.RandomState(42)
            fps = rng.randn(10, 6)
            dates = [date(2025, 1, i + 1) for i in range(10)]
            count = mem.update_library(fps, dates)
            assert count == 10

            features, lib_dates = mem.get_library()
            assert features.shape == (10, 6)
            assert len(lib_dates) == 10
            np.testing.assert_array_almost_equal(features, fps)
            mem.close()

    def test_rebuild_from_dataframe(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_pattern(tmp)
            df = _make_synthetic_ohlcv(200)
            count = mem.rebuild_from_dataframe(df, session_size=50)
            assert count == 4  # 200 / 50

            features, dates = mem.get_library()
            assert features.shape == (4, 6)
            assert len(dates) == 4
            mem.close()

    def test_get_empty_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_pattern(tmp)
            features, dates = mem.get_library()
            assert features.shape == (0, 6)
            assert dates == []
            mem.close()

    def test_upsert_on_duplicate_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_pattern(tmp)
            fp1 = np.ones((1, 6))
            fp2 = np.ones((1, 6)) * 2.0
            d = [date(2025, 1, 1)]

            mem.update_library(fp1, d)
            mem.update_library(fp2, d)

            features, dates = mem.get_library()
            assert features.shape == (1, 6)
            np.testing.assert_array_almost_equal(features[0], fp2[0])
            mem.close()

    def test_fingerprint_roundtrip_precision(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_pattern(tmp)
            fp = np.array([[1.23456789012345, -0.000001, 99999.99, 0.0, 1e-15, -1e10]])
            d = [date(2025, 3, 15)]
            mem.update_library(fp, d)

            features, _ = mem.get_library()
            np.testing.assert_array_almost_equal(features[0], fp[0], decimal=10)
            mem.close()


# ---------------------------------------------------------------------------
# WorkingMemory (SqliteSaver) tests
# ---------------------------------------------------------------------------

class TestWorkingMemory:
    def test_create_checkpointer(self):
        from talim.memory.working import create_checkpointer
        saver = create_checkpointer(":memory:")
        assert saver is not None
