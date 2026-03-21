#!/bin/bash
# memory-sync.sh — Bidirectional sync of Claude memory between machines
# Usage: ./memory-sync.sh [push|pull|sync]
#   push  — MacBook → Mac Mini
#   pull  — Mac Mini → MacBook
#   sync  — bidirectional (default)
#
# Designed to be called from fleet workflows, hooks, or manually.
# Uses rsync --update so newer files always win. Lightweight: only diffs transfer.

set -euo pipefail

REMOTE="${WORKER_HOST:-worker}"
MEMORY_ROOT="$HOME/.claude/projects"
MODE="${1:-sync}"

# Find all memory directories on this machine
find_memory_dirs() {
  find "$MEMORY_ROOT" -type d -name memory 2>/dev/null
}

do_push() {
  while IFS= read -r dir; do
    rel="${dir#$HOME/}"
    rsync -au --delete-after "$dir/" "$REMOTE:~/$rel/" 2>/dev/null
  done < <(find_memory_dirs)
}

do_pull() {
  # Pull known remote memory dirs (list them first to avoid pulling empty paths)
  remote_dirs=$(ssh "$REMOTE" "find ~/.claude/projects -type d -name memory 2>/dev/null" 2>/dev/null) || return 0
  while IFS= read -r rdir; do
    [[ -z "$rdir" ]] && continue
    rel="${rdir#\~/}"
    rel="${rel#$HOME/}"
    # Normalise to home-relative
    rel="${rel#.claude/}"
    local_dir="$HOME/.claude/$rel"
    mkdir -p "$local_dir"
    rsync -au "$REMOTE:~/.claude/$rel/" "$local_dir/" 2>/dev/null
  done <<< "$remote_dirs"
}

case "$MODE" in
  push) do_push ;;
  pull) do_pull ;;
  sync) do_push; do_pull ;;
  *)    echo "Usage: $0 [push|pull|sync]"; exit 1 ;;
esac
