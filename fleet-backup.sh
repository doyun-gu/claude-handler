#!/bin/bash
# fleet-backup.sh — Sync critical fleet data to Commander (MacBook) for disaster recovery
#
# Runs on Mac Mini after task completions. Backs up:
# - tasks.db (SQLite — source of truth for all task state)
# - dispatch-log/ (immutable copies of every dispatched task)
# - review-queue/ (current review items)
# - workers.json, projects.json, machine-role.conf
# - daemon logs (last 7 days)
#
# Usage: ./fleet-backup.sh [--target macbook-hostname]
#
# The Commander (MacBook) should be reachable via SSH.
# If not reachable, backup silently skips (no error, no block).

set -uo pipefail

FLEET_DIR="$HOME/.claude-fleet"
BACKUP_TARGET="${1:-macbook}"  # SSH hostname for MacBook
BACKUP_DIR="$FLEET_DIR/backups"
REMOTE_BACKUP_DIR=".claude-fleet/mac-mini-backup"

# Local rolling backup (always runs)
mkdir -p "$BACKUP_DIR"
cp "$FLEET_DIR/tasks.db" "$BACKUP_DIR/tasks.db.$(date +%Y%m%d)" 2>/dev/null
# Keep only last 7 days of local backups
find "$BACKUP_DIR" -name "tasks.db.*" -mtime +7 -delete 2>/dev/null

# Remote backup to MacBook (best-effort, non-blocking)
if ssh -o ConnectTimeout=3 -o BatchMode=yes "$BACKUP_TARGET" "mkdir -p ~/$REMOTE_BACKUP_DIR" 2>/dev/null; then
    # Sync critical files
    rsync -az --timeout=10 \
        "$FLEET_DIR/tasks.db" \
        "$FLEET_DIR/workers.json" \
        "$FLEET_DIR/projects.json" \
        "$FLEET_DIR/machine-role.conf" \
        "$BACKUP_TARGET:~/$REMOTE_BACKUP_DIR/" 2>/dev/null

    # Sync dispatch log (immutable task history)
    rsync -az --timeout=10 \
        "$FLEET_DIR/dispatch-log/" \
        "$BACKUP_TARGET:~/$REMOTE_BACKUP_DIR/dispatch-log/" 2>/dev/null

    # Sync review queue
    rsync -az --timeout=10 \
        "$FLEET_DIR/review-queue/" \
        "$BACKUP_TARGET:~/$REMOTE_BACKUP_DIR/review-queue/" 2>/dev/null

    # Sync recent logs (last 7 days only)
    find "$FLEET_DIR/logs" -name "*.log" -mtime -7 -print0 2>/dev/null | \
        rsync -az --timeout=10 --files-from=- --from0 / \
        "$BACKUP_TARGET:~/$REMOTE_BACKUP_DIR/logs/" 2>/dev/null

    echo "[backup] Synced to $BACKUP_TARGET:~/$REMOTE_BACKUP_DIR"
else
    # MacBook not reachable — skip silently (don't block daemon)
    true
fi
