#!/usr/bin/env bash
# Talim database backup script (WP-43).
#
# Usage:
#   ./scripts/backup.sh [--s3 BUCKET]
#
# Creates timestamped SQLite .backup copies in $BACKUP_DIR, then optionally
# uploads them to S3.
set -euo pipefail

BACKUP_DIR="${TALIM_BACKUP_DIR:-/app/backups}"
STATE_DIR="${TALIM_STATE_DIR:-/app/state}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
S3_BUCKET=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --s3) S3_BUCKET="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$BACKUP_DIR"

backup_db() {
    local name="$1"
    local src="${STATE_DIR}/${name}"
    local dst="${BACKUP_DIR}/${name%.db}-${TIMESTAMP}.db"

    if [[ ! -f "$src" ]]; then
        echo "SKIP: $src not found"
        return
    fi

    sqlite3 "$src" ".backup '$dst'"
    echo "OK:   $src → $dst ($(du -h "$dst" | cut -f1))"

    if [[ -n "$S3_BUCKET" ]]; then
        aws s3 cp "$dst" "s3://${S3_BUCKET}/talim/${name%.db}-${TIMESTAMP}.db" --quiet
        echo "  → uploaded to s3://${S3_BUCKET}/talim/"
    fi
}

backup_db "episodic.db"
backup_db "pattern.db"
backup_db "working_memory.db"

# Prune local backups older than 7 days
find "$BACKUP_DIR" -name "*.db" -mtime +7 -delete 2>/dev/null || true

echo "Backup complete: $TIMESTAMP"
