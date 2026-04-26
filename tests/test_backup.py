"""Tests for the backup script and restore workflow (WP-43)."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from talim.memory.episodic import EpisodicMemory


class TestBackupScript:
    def test_script_is_executable(self):
        p = Path("scripts/backup.sh")
        assert p.exists()
        assert p.stat().st_mode & 0o111  # executable bit

    def test_backup_produces_restorable_file(self, tmp_path):
        """Create a DB, back it up via sqlite3 .backup, verify the copy."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        # Create an episodic DB with a record
        db_path = state_dir / "episodic.db"
        mem = EpisodicMemory(str(db_path))
        mem.record_decision(
            timestamp="2025-06-15T10:00:00",
            instrument="ES",
            strategy="momentum-US500",
            side="long",
            entry_price=5000.0,
            stop=4980.0,
            target=5030.0,
        )
        mem.close()

        # Run sqlite3 .backup (same mechanism as backup.sh)
        backup_path = backup_dir / "episodic-test.db"
        subprocess.run(
            ["sqlite3", str(db_path), f".backup '{backup_path}'"],
            check=True,
        )
        assert backup_path.exists()
        assert backup_path.stat().st_size > 0

        # Verify the backup is a valid, queryable DB
        conn = sqlite3.connect(str(backup_path))
        count = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        conn.close()
        assert count == 1

    def test_backup_restore_round_trip(self, tmp_path):
        """Write records → backup → delete original → restore → query."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        db_path = state_dir / "episodic.db"
        mem = EpisodicMemory(str(db_path))
        for i in range(5):
            mem.record_decision(
                timestamp=f"2025-06-15T10:0{i}:00",
                instrument="ES",
                strategy="momentum-US500",
                side="long",
                entry_price=5000.0 + i,
                stop=4980.0,
                target=5030.0,
            )
        mem.close()

        # Backup
        backup_path = tmp_path / "episodic-backup.db"
        subprocess.run(
            ["sqlite3", str(db_path), f".backup '{backup_path}'"],
            check=True,
        )

        # Destroy original
        db_path.unlink()
        assert not db_path.exists()

        # Restore
        import shutil
        shutil.copy(str(backup_path), str(db_path))

        # Verify restored data
        restored = EpisodicMemory(str(db_path))
        decisions = restored.query_decisions()
        restored.close()
        assert len(decisions) == 5


class TestDockerComposeAOF:
    def test_redis_aof_enabled_in_compose(self):
        """Verify docker-compose.yml enables Redis AOF persistence and binds
        the data dir to a host path that survives container recreation."""
        compose = Path("docker-compose.yml").read_text()
        assert "--appendonly" in compose
        assert "yes" in compose
        # WP-47: redis state lives in ./redis (bind mount), not in the
        # `redis-data` named volume that earlier WPs used.
        assert "./redis:/data" in compose
