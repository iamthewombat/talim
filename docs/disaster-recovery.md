# Disaster Recovery Runbook

## What's at risk

| Database | Contents | Impact of loss |
|----------|----------|----------------|
| `working_memory.db` | LangGraph checkpointer state | In-flight HITL interrupts lost; graph resumes from scratch |
| `episodic.db` | Decision journal (entries, exits, outcomes) | Historical trade record gone; LLM context for strategy updates lost |
| `pattern.db` | Regime fingerprint library | Session matcher returns no candidates until library rebuilt |
| Redis AOF | Event bus streams + consumer group offsets | Missed events during recovery; self-heals on next publish |

## Backup schedule

Configured in `scripts/cron.txt`:

- **Hourly**: `scripts/backup.sh` runs `sqlite3 .backup` on all three DBs into `/app/backups/` with timestamps.
- **Daily 03:00 UTC**: same script, plus optional `--s3 BUCKET` upload.
- **Pruning**: local backups older than 7 days are automatically deleted.

Redis AOF is enabled via `--appendonly yes` in docker-compose.yml and persisted to a named volume.

## Restore procedure

### 1. Stop the stack

```bash
docker compose down
```

### 2. Identify the backup to restore

```bash
ls -lt /app/backups/ | head
# or from S3:
aws s3 ls s3://YOUR_BUCKET/talim/ --recursive | sort -k1,2 | tail
```

### 3. Replace the database files

```bash
# Working memory (most critical — holds HITL state)
cp /app/backups/working_memory-20260408T030000Z.db /app/state/working_memory.db

# Episodic memory
cp /app/backups/episodic-20260408T030000Z.db /app/state/episodic.db

# Pattern memory
cp /app/backups/pattern-20260408T030000Z.db /app/state/pattern.db
```

### 4. Restart

```bash
docker compose up -d
./scripts/healthcheck.sh
```

### 5. Verify

- Check `/talim/health` returns `{"status": "ok"}`
- Check episodic memory count: `sqlite3 /app/state/episodic.db "SELECT COUNT(*) FROM decisions"`
- If HITL was in-flight, the graph will resume from the last checkpoint

## If backups are lost

- **pattern.db**: rebuild from historical data by running the regime library builder
- **episodic.db**: reconstruct from exchange trade history + git log of strategy changes
- **working_memory.db**: unrecoverable — any pending HITL approvals are lost; new scans will create fresh state

## Testing the backup

```bash
# Create a test backup
docker exec talim-app /app/scripts/backup.sh

# Verify the file is a valid SQLite database
sqlite3 /app/backups/episodic-*.db "SELECT COUNT(*) FROM decisions"
```
