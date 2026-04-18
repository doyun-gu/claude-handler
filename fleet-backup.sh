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

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
    shift
fi

FLEET_DIR="$HOME/.claude-fleet"
BACKUP_TARGET="${1:-macbook}"  # SSH hostname for MacBook
BACKUP_DIR="$FLEET_DIR/backups"
REMOTE_BACKUP_DIR=".claude-fleet/mac-mini-backup"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRUNE_LOG="$FLEET_DIR/logs/transcript-prune.log"
TRANSCRIPT_ROOT="$HOME/.claude/projects"
TRANSCRIPT_MAX_AGE_DAYS="${TRANSCRIPT_MAX_AGE_DAYS:-14}"

prune_claude_transcripts() {
    [[ -d "$TRANSCRIPT_ROOT" ]] || return 0

    # Skip if any task is currently running (transcript may be open).
    # Count lines that look like a task row (alphanumeric leader) rather than
    # `grep -c "^"` which would include blank lines and a header row.
    if [[ -f "$SCRIPT_DIR/task-db.py" ]]; then
        local running_count
        running_count=$(python3 "$SCRIPT_DIR/task-db.py" list running 2>/dev/null | grep -cE '^[[:space:]]*[a-z0-9]' || true)
        running_count=${running_count:-0}
        if (( running_count > 0 )); then
            return 0
        fi
    fi

    mkdir -p "$(dirname "$PRUNE_LOG")"
    local ts
    ts=$(date '+%Y-%m-%dT%H:%M:%S')
    local deleted=0 bytes_freed=0 skipped_open=0

    # Build candidate list: *.jsonl older than N days under ~/.claude/projects
    while IFS= read -r -d '' f; do
        # Skip if file is currently open (held by any process)
        if lsof -t -- "$f" >/dev/null 2>&1; then
            skipped_open=$((skipped_open + 1))
            continue
        fi
        local size
        size=$(stat -f%z "$f" 2>/dev/null || echo 0)
        if (( DRY_RUN )); then
            echo "[$ts] DRY-RUN would delete $f ($size bytes)" >> "$PRUNE_LOG"
        else
            if rm -f -- "$f"; then
                bytes_freed=$((bytes_freed + size))
                deleted=$((deleted + 1))
            fi
        fi
    done < <(find "$TRANSCRIPT_ROOT" -type f -name '*.jsonl' -mtime "+${TRANSCRIPT_MAX_AGE_DAYS}" -print0 2>/dev/null)

    local mb=$((bytes_freed / 1024 / 1024))
    if (( DRY_RUN )); then
        local cand
        cand=$(find "$TRANSCRIPT_ROOT" -type f -name '*.jsonl' -mtime "+${TRANSCRIPT_MAX_AGE_DAYS}" 2>/dev/null | wc -l | tr -d ' ')
        echo "[$ts] dry-run: ${cand} candidates older than ${TRANSCRIPT_MAX_AGE_DAYS}d" >> "$PRUNE_LOG"
    else
        echo "[$ts] pruned ${deleted} files (${mb} MB freed, ${skipped_open} skipped as open)" >> "$PRUNE_LOG"
    fi
}

# Local rolling backup (always runs — unless dry-run)
if (( ! DRY_RUN )); then
    mkdir -p "$BACKUP_DIR"
    cp "$FLEET_DIR/tasks.db" "$BACKUP_DIR/tasks.db.$(date +%Y%m%d)" 2>/dev/null
    # Keep only last 7 days of local backups
    find "$BACKUP_DIR" -name "tasks.db.*" -mtime +7 -delete 2>/dev/null
fi

# Prune stale Claude transcripts (runs every time backup runs)
prune_claude_transcripts

# Dry-run stops here — no remote side effects
if (( DRY_RUN )); then
    echo "[backup] dry-run complete — see $PRUNE_LOG"
    exit 0
fi

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
