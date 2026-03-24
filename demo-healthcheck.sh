#!/bin/bash
# demo-healthcheck.sh — Smart demo agent for Mac Mini
# 1. Keeps DPSpice demo alive (auto-restart if down)
# 2. Scans logs for errors/crashes → writes to DEBUG_DETECTOR.md
# 3. Auto-creates worker tasks for recurring bugs
#
# Run in tmux: tmux new-session -d -s demo-health './demo-healthcheck.sh'

set -uo pipefail
export PATH=/opt/homebrew/bin:$HOME/.local/bin:$PATH

FLEET_DIR="$HOME/.claude-fleet"
HANDLER_DIR="$(cd "$(dirname "$0")" && pwd)"
BUG_DB="$FLEET_DIR/bug-db.json"

# Detect LAN IP dynamically (macOS: en0, Linux: hostname -I)
WORKER_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || hostname)

# Project-specific settings — override via environment or projects.json
DPSPICE_DIR="${HEALTHCHECK_PROJECT_DIR:-$HOME/Developer/dynamic-phasors/DPSpice-com}"
DEBUG_FILE="$DPSPICE_DIR/DEBUG_DETECTOR.md"
API_PORT="${HEALTHCHECK_API_PORT:-8000}"
WEB_PORT="${HEALTHCHECK_WEB_PORT:-3001}"
CHECK_INTERVAL=60       # seconds between health checks
LOG_SCAN_INTERVAL=300   # seconds between deep log scans (5 min)
LAST_LOG_SCAN=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "[health $(date +%H:%M:%S)] $1"; }

# ── JSON Bug Database ──────────────────────────────

# Initialize bug-db.json if missing
init_bug_db() {
    if [[ ! -f "$BUG_DB" ]]; then
        echo '{"bugs": {}, "version": 1}' > "$BUG_DB"
    fi
}

# Upsert a bug entry. Returns occurrence count to stdout.
bug_db_upsert() {
    local slug="$1" severity="$2" description="$3" raw_error="${4:-}"
    init_bug_db
    python3 -c "
import json, os, time, tempfile

db_path = '$BUG_DB'
slug = '''$slug'''
severity = '''$severity'''
description = '''$(echo "$description" | sed "s/'/\\\\'/g")'''
raw_error = '''$(echo "$raw_error" | head -30 | sed "s/'/\\\\'/g")'''
now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

try:
    with open(db_path) as f:
        db = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    db = {'bugs': {}, 'version': 1}

if slug in db['bugs']:
    db['bugs'][slug]['occurrences'] += 1
    db['bugs'][slug]['last_seen'] = now
    db['bugs'][slug]['severity'] = severity
    db['bugs'][slug]['description'] = description
    if raw_error:
        db['bugs'][slug]['last_error'] = raw_error
else:
    db['bugs'][slug] = {
        'severity': severity,
        'description': description,
        'first_seen': now,
        'last_seen': now,
        'occurrences': 1,
        'status': 'new',
        'heal_count': 0,
        'heal_timestamps': [],
        'escalated': False,
        'last_error': raw_error
    }

# Atomic write
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(db_path))
with os.fdopen(fd, 'w') as f:
    json.dump(db, f, indent=2)
os.rename(tmp, db_path)

print(db['bugs'][slug]['occurrences'])
" 2>/dev/null
}

# Check if a bug is in cooldown (too many heals recently).
# Returns 0 if cooldown is active (should NOT heal), 1 if OK to heal.
bug_db_check_cooldown() {
    local slug="$1"
    init_bug_db
    python3 -c "
import json, time

db_path = '$BUG_DB'
slug = '''$slug'''
now = time.time()

try:
    with open(db_path) as f:
        db = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    exit(1)  # No DB = no cooldown

bug = db.get('bugs', {}).get(slug)
if not bug:
    exit(1)  # Unknown bug = no cooldown

# Cooldown: >= 3 heals in last 300s
recent = [t for t in bug.get('heal_timestamps', []) if now - t < 300]
if len(recent) >= 3:
    exit(0)  # Cooldown active

# Escalation: >= 10 total heals
if bug.get('heal_count', 0) >= 10:
    exit(0)  # Escalated = cooldown

exit(1)  # OK to heal
" 2>/dev/null
}

# Record a successful heal for a bug.
bug_db_record_heal() {
    local slug="$1"
    init_bug_db
    python3 -c "
import json, os, time, tempfile

db_path = '$BUG_DB'
slug = '''$slug'''
now = time.time()

try:
    with open(db_path) as f:
        db = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    exit(0)

bug = db.get('bugs', {}).get(slug)
if not bug:
    exit(0)

bug['heal_count'] = bug.get('heal_count', 0) + 1
timestamps = bug.get('heal_timestamps', [])
timestamps.append(now)
bug['heal_timestamps'] = timestamps[-10:]  # Keep last 10

# Escalate if too many heals
if bug['heal_count'] >= 10 and not bug.get('escalated', False):
    bug['escalated'] = True
    bug['status'] = 'escalated'

db['bugs'][slug] = bug

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(db_path))
with os.fdopen(fd, 'w') as f:
    json.dump(db, f, indent=2)
os.rename(tmp, db_path)
" 2>/dev/null
}

# Regenerate DEBUG_DETECTOR.md from bug-db.json (capped at 50 bugs)
regenerate_debug_md() {
    init_bug_db

    # Archive if existing file is too large (>100KB)
    if [[ -f "$DEBUG_FILE" ]]; then
        local size
        size=$(wc -c < "$DEBUG_FILE" 2>/dev/null | tr -d ' ')
        if (( ${size:-0} > 102400 )); then
            mv "$DEBUG_FILE" "${DEBUG_FILE%.md}-archived-$(date +%Y%m%d-%H%M%S).md.bak"
        fi
    fi

    python3 -c "
import json

db_path = '$BUG_DB'
out_path = '$DEBUG_FILE'

try:
    with open(db_path) as f:
        db = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    db = {'bugs': {}}

bugs = db.get('bugs', {})
# Sort by last_seen desc, cap at 50
sorted_bugs = sorted(bugs.items(), key=lambda x: x[1].get('last_seen', ''), reverse=True)[:50]

status_icons = {'new': '🔴 NEW', 'escalated': '⚠️ ESCALATED', 'healed': '🟢 HEALED', 'fixed': '✅ FIXED'}

lines = []
lines.append('# DEBUG_DETECTOR — Auto-detected Bugs & Errors')
lines.append('')
lines.append('This file is auto-generated from \`bug-db.json\`. Do not edit manually.')
lines.append('')
lines.append(f'**Total tracked bugs:** {len(bugs)} | **Showing:** {len(sorted_bugs)}')
lines.append('')
lines.append('---')
lines.append('')

for slug, bug in sorted_bugs:
    icon = status_icons.get(bug.get('status', 'new'), '🔴 NEW')
    lines.append(f'### {icon}: {bug.get(\"description\", slug)}')
    lines.append('')
    lines.append(f'- **slug:** {slug}')
    lines.append(f'- **severity:** {bug.get(\"severity\", \"unknown\")}')
    lines.append(f'- **first_seen:** {bug.get(\"first_seen\", \"?\")}')
    lines.append(f'- **last_seen:** {bug.get(\"last_seen\", \"?\")}')
    lines.append(f'- **occurrences:** {bug.get(\"occurrences\", 0)}')
    lines.append(f'- **heal_count:** {bug.get(\"heal_count\", 0)}')
    lines.append(f'- **status:** {icon}')
    error = bug.get('last_error', '')
    if error:
        lines.append('')
        lines.append('\`\`\`')
        for line in str(error).split('\\n')[:10]:
            lines.append(line)
        lines.append('\`\`\`')
    lines.append('')

with open(out_path, 'w') as f:
    f.write('\\n'.join(lines))
" 2>/dev/null
}

# ── Auto-heal: fix known bugs from knowledge base ──────────
auto_heal_from_kb() {
    local slug="$1"
    local description="$2"
    local severity="$3"
    local KB_DIR="$FLEET_DIR/bug-knowledge"
    local HEAL_LOG="$FLEET_DIR/logs/auto-heal.log"

    [[ ! -d "$KB_DIR" ]] && return 1

    # Search knowledge base for matching pattern
    for kb in "$KB_DIR"/*.md; do
        [[ -f "$kb" ]] || continue
        local kb_name=$(basename "$kb" .md | tr '-' ' ')

        # Match by slug keywords or description keywords
        if echo "$slug $description" | grep -qi "$(echo "$kb_name" | cut -d' ' -f1)"; then
            local fix_commands=$(sed -n '/^```bash/,/^```/p' "$kb" | grep -v '```' | head -10)

            if [[ -n "$fix_commands" ]]; then
                log "${GREEN}AUTO-HEAL: Known bug matched → $(basename $kb)${NC}"
                eval "$fix_commands" 2>&1 | head -5

                # Increment counter in KB
                local count=$(grep -o 'Times resolved: [0-9]*' "$kb" | grep -o '[0-9]*')
                count=$((${count:-0} + 1))
                sed -i '' "s/Times resolved: [0-9]*/Times resolved: $count/" "$kb" 2>/dev/null

                # Log
                echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] AUTO-HEALED: $slug (kb: $(basename $kb), count: $count)" >> "$HEAL_LOG"
                return 0
            fi
        fi
    done

    # Check for common patterns even without KB entry
    case "$slug" in
        *webpack*|*cache*|*pack.gz*|*hasStartTime*)
            log "${GREEN}AUTO-HEAL: Clearing webpack cache${NC}"
            rm -rf $DPSPICE_DIR/web/.next/cache/webpack 2>/dev/null
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] AUTO-HEALED: $slug (pattern: webpack-cache)" >> "$HEAL_LOG"
            return 0
            ;;
        *ENOENT*|*no-such-file*|*rename*)
            log "${GREEN}AUTO-HEAL: Cache file issue — clearing .next/cache${NC}"
            rm -rf $DPSPICE_DIR/web/.next/cache 2>/dev/null
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] AUTO-HEALED: $slug (pattern: enoent-cache)" >> "$HEAL_LOG"
            return 0
            ;;
        *EADDRINUSE*|*address-already-in-use*|*port-conflict*)
            local port=$(echo "$description" | grep -o '[0-9]\{4\}' | head -1)
            if [[ -n "$port" ]]; then
                log "${GREEN}AUTO-HEAL: Killing stale process on port $port${NC}"
                lsof -ti:"$port" | xargs kill -9 2>/dev/null
                echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] AUTO-HEALED: $slug (pattern: port-conflict:$port)" >> "$HEAL_LOG"
                return 0
            fi
            ;;
        *crash*|*restart-failed*)
            log "${GREEN}AUTO-HEAL: Crash detected — clearing cache and restarting${NC}"
            rm -rf $DPSPICE_DIR/web/.next/cache 2>/dev/null
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] AUTO-HEALED: $slug (pattern: crash-restart)" >> "$HEAL_LOG"
            return 0
            ;;
    esac

    return 1  # Unknown bug, not healed
}


# ─── Health checks ────────────────────────────────

check_api() {
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 http://localhost:$API_PORT/health 2>/dev/null)
    [[ "$status" == "200" ]]
}

check_web() {
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 http://localhost:$WEB_PORT 2>/dev/null)
    [[ "$status" == "200" ]]
}

restart_api() {
    log "${YELLOW}Restarting API server...${NC}"
    tmux kill-session -t dpspice-api 2>/dev/null
    sleep 1
    tmux new-session -d -s dpspice-api \
        "cd $DPSPICE_DIR && export PYTHONPATH=src/python && .venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port $API_PORT 2>&1 | tee /tmp/dpspice-api.log"
    sleep 5
    if check_api; then
        log "${GREEN}API restarted successfully${NC}"
    else
        log "${RED}API failed to restart!${NC}"
        log_bug "api-restart-failed" "critical" "API server failed to restart after crash" \
            "$(tail -20 /tmp/dpspice-api.log 2>/dev/null)"
    fi
}

restart_web() {
    log "${YELLOW}Restarting frontend...${NC}"
    tmux kill-session -t dpspice-web 2>/dev/null
    sleep 1
    tmux new-session -d -s dpspice-web \
        "cd $DPSPICE_DIR/web && export PATH=/opt/homebrew/bin:\$HOME/.local/bin:\$PATH && npm run dev -- -H 0.0.0.0 2>&1 | tee /tmp/dpspice-web.log"
    sleep 10
    if check_web; then
        log "${GREEN}Frontend restarted successfully${NC}"
    else
        log "${RED}Frontend failed to restart!${NC}"
        log_bug "web-restart-failed" "critical" "Frontend failed to restart after crash" \
            "$(tail -20 /tmp/dpspice-web.log 2>/dev/null)"
    fi
}

# ─── Error detection & logging ─────────────────────

# Initialize DEBUG_DETECTOR.md if it doesn't exist
init_debug_file() {
    if [[ ! -f "$DEBUG_FILE" ]]; then
        cat > "$DEBUG_FILE" << 'HEADER'
# DEBUG_DETECTOR — Auto-detected Bugs & Errors

This file is auto-generated from `bug-db.json`. Do not edit manually.

---

HEADER
    fi
}

# Log a bug to the JSON database and regenerate markdown
# Usage: log_bug <slug> <severity> <description> <raw_error>
log_bug() {
    local slug="$1"
    local severity="$2"
    local description="$3"
    local raw_error="${4:-no error output}"
    local timestamp
    timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    # Upsert into JSON database
    local occurrences
    occurrences=$(bug_db_upsert "$slug" "$severity" "$description" "$raw_error")
    occurrences=${occurrences:-1}

    if (( occurrences == 1 )); then
        log "${RED}NEW BUG logged: $slug — $description${NC}"

        # Write to review queue so Commander sees it on startup
        cat > "$FLEET_DIR/review-queue/bug-$slug.md" << REVIEW
---
task_id: bug-$slug
project: DPSpice-com
type: decision_needed
priority: $( [[ "$severity" == "critical" ]] && echo "high" || echo "normal" )
created_at: $timestamp
---

## Bug Detected by Demo Health Checker

**$description**
**Severity:** $severity
**Occurrences:** 1
**First seen:** $timestamp

\`\`\`
$(echo "$raw_error" | head -20)
\`\`\`

Logged to: $DEBUG_FILE
REVIEW
    else
        log "${YELLOW}Bug '$slug' seen again (${occurrences}x)${NC}"
    fi

    # Try auto-heal (with cooldown protection)
    if bug_db_check_cooldown "$slug"; then
        # Cooldown active — skip auto-heal
        log "${YELLOW}COOLDOWN: '$slug' healed too many times recently — skipping auto-heal${NC}"
    else
        if auto_heal_from_kb "$slug" "$description" "$severity"; then
            bug_db_record_heal "$slug"
            log "${GREEN}AUTO-HEALED: $slug${NC}"
            regenerate_debug_md
            return 0
        fi
    fi

    regenerate_debug_md
}

# Scan API logs for Python tracebacks and errors
scan_api_logs() {
    local log_file="/tmp/dpspice-api.log"
    [[ ! -f "$log_file" ]] && return

    # Check for Python tracebacks
    local tracebacks
    tracebacks=$(grep -c "Traceback\|TypeError\|ValueError\|KeyError\|AttributeError\|ImportError" "$log_file" 2>/dev/null)
    tracebacks=${tracebacks:-0}
    tracebacks=${tracebacks// /}

    if (( tracebacks > 0 )); then
        local latest_error
        latest_error=$(grep -A 5 "Traceback\|TypeError\|ValueError\|KeyError\|AttributeError" "$log_file" 2>/dev/null | tail -15)

        # Extract the error type for the slug
        local error_type
        error_type=$(echo "$latest_error" | grep -oE '(TypeError|ValueError|KeyError|AttributeError|ImportError)[^"]*' | head -1 | tr ' ' '-' | tr -d "'" | cut -c1-50)
        [[ -z "$error_type" ]] && error_type="python-error"

        log_bug "api-${error_type}" "high" "Python error in API: $error_type" "$latest_error"
    fi

    # Check for 500 Internal Server Errors
    local server_errors
    server_errors=$(grep -c '"500"' "$log_file" 2>/dev/null)
    server_errors=${server_errors:-0}
    server_errors=${server_errors// /}
    if (( server_errors > 5 )); then
        local recent_500
        recent_500=$(grep '"500"' "$log_file" 2>/dev/null | tail -5)
        log_bug "api-500-errors" "high" "Multiple 500 errors from API ($server_errors total)" "$recent_500"
    fi
}

# Scan frontend logs for JS errors
scan_web_logs() {
    local log_file="/tmp/dpspice-web.log"
    [[ ! -f "$log_file" ]] && return

    # Check for build errors
    local build_errors
    build_errors=$(grep -c "Error:\|error TS\|Module not found\|SyntaxError" "$log_file" 2>/dev/null)
    build_errors=${build_errors:-0}
    build_errors=${build_errors// /}

    if (( build_errors > 0 )); then
        local latest_error
        latest_error=$(grep -B 2 -A 5 "Error:\|error TS\|Module not found\|SyntaxError" "$log_file" 2>/dev/null | tail -15)

        local error_type
        error_type=$(echo "$latest_error" | grep -oE '(Error|SyntaxError|TypeError)[^"]*' | head -1 | tr ' ' '-' | cut -c1-50)
        [[ -z "$error_type" ]] && error_type="build-error"

        log_bug "web-${error_type}" "high" "Frontend build/runtime error: $error_type" "$latest_error"
    fi
}

# Test key API endpoints for correctness (not just 200 OK)
smoke_test_api() {
    # IEEE 14-bus power flow should converge
    local pf_result
    pf_result=$(curl -s --connect-timeout 5 http://localhost:$API_PORT/api/ieee/14bus/power-flow 2>/dev/null)
    local converged
    converged=$(echo "$pf_result" | python3 -c "import json,sys; print(json.load(sys.stdin).get('converged', False))" 2>/dev/null)

    if [[ "$converged" != "True" ]]; then
        log_bug "api-pf-not-converging" "high" "IEEE 14-bus power flow not converging" \
            "$(echo "$pf_result" | head -5)"
    fi

    # IEEE 9-bus should also work
    local pf9
    pf9=$(curl -s --connect-timeout 5 http://localhost:$API_PORT/api/ieee/9bus/power-flow 2>/dev/null)
    local converged9
    converged9=$(echo "$pf9" | python3 -c "import json,sys; print(json.load(sys.stdin).get('converged', False))" 2>/dev/null)

    if [[ "$converged9" != "True" ]]; then
        log_bug "api-9bus-not-converging" "medium" "IEEE 9-bus power flow not converging" \
            "$(echo "$pf9" | head -5)"
    fi
}

# Auto-create a worker task if there are critical unresolved bugs
maybe_create_worker_task() {
    [[ ! -f "$BUG_DB" ]] && return

    local counts
    counts=$(python3 -c "
import json
try:
    db = json.load(open('$BUG_DB'))
    bugs = db.get('bugs', {})
    critical = sum(1 for b in bugs.values() if b.get('severity') == 'critical' and b.get('status') == 'new')
    new = sum(1 for b in bugs.values() if b.get('status') == 'new')
    print(f'{new} {critical}')
except: print('0 0')
" 2>/dev/null)

    local new_count critical_count
    new_count=$(echo "$counts" | awk '{print $1}')
    critical_count=$(echo "$counts" | awk '{print $2}')
    new_count=${new_count:-0}
    critical_count=${critical_count:-0}

    if (( new_count >= 3 )) || (( critical_count >= 1 )); then
        local task_id="auto-$(date +%Y%m%d-%H%M%S)-bugfix"
        local task_file="$FLEET_DIR/tasks/${task_id}.json"

        # Skip if any auto-bugfix task is queued or running
        if ls "$FLEET_DIR/tasks"/auto-*-bugfix.json 2>/dev/null | xargs grep -l '"queued"\|"running"' 2>/dev/null | head -1 | grep -q .; then
            return
        fi

        # Skip if an auto-bugfix task completed in the last 30 minutes (prevents infinite loop
        # when worker finds no NEW bugs but bug-db.json still has status=new)
        local recent_completed
        recent_completed=$(python3 -c "
import json, glob, time
now = time.time()
for f in sorted(glob.glob('$FLEET_DIR/tasks/auto-*-bugfix.json'), reverse=True)[:10]:
    try:
        d = json.load(open(f))
        if d.get('status') == 'completed' and d.get('finished_at'):
            import datetime
            fin = datetime.datetime.fromisoformat(d['finished_at'].replace('Z','+00:00')).timestamp()
            if now - fin < 1800:
                print('RECENT')
                break
    except: pass
" 2>/dev/null)
        if [[ "$recent_completed" == "RECENT" ]]; then
            # A recent bugfix task found nothing to fix — mark all 'new' bugs as fixed
            python3 -c "
import json
f = '$BUG_DB'
db = json.load(open(f))
changed = False
for name, bug in db.get('bugs', {}).items():
    if bug.get('status') == 'new':
        bug['status'] = 'fixed'
        bug['fixed_by'] = 'auto-cleared: worker found no NEW bugs'
        changed = True
if changed:
    json.dump(db, open(f, 'w'), indent=2)
" 2>/dev/null
            return
        fi

        cat > "$task_file" << TASK
{
  "id": "$task_id",
  "slug": "auto-bugfix",
  "branch": "worker/auto-bugfix-$(date +%Y%m%d)",
  "project_name": "DPSpice-com",
  "project_path": "$DPSPICE_DIR",
  "subdir": "",
  "dispatched_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "status": "queued",
  "base_branch": "main",
  "prompt": "Read $DEBUG_FILE for auto-detected bugs. Fix all bugs marked NEW. For each bug: investigate the error, fix the root cause, add a defensive check to prevent it recurring, update bug-db.json status to fixed. Run npm run build and npm test after each fix. Commit after each bug fix. Open PR when done.",
  "budget_usd": 10,
  "permission_mode": "dangerously-skip-permissions",
  "tmux_session": "claude-auto-bugfix"
}
TASK
        log "${BLUE}Auto-created worker task: $task_id ($new_count new bugs, $critical_count critical)${NC}"
    fi
}

# ── Preview server for completed worker branches ──
PREVIEW_PORT=3002

check_preview_server() {
    local latest_branch=""
    for f in "$FLEET_DIR"/tasks/*.json; do
        [[ -f "$f" ]] || continue
        local info
        info=$(python3 -c "
import json
d = json.load(open('$f'))
if d.get('status') == 'completed' and d.get('project_name') == 'DPSpice-com':
    print(d.get('branch',''))
" 2>/dev/null)
        [[ -n "$info" ]] && latest_branch="$info"
    done
    [[ -z "$latest_branch" ]] && return

    local running_branch=""
    running_branch=$(cat /tmp/dpspice-preview-branch 2>/dev/null)
    if [[ "$running_branch" == "$latest_branch" ]]; then
        local status
        status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 http://localhost:$PREVIEW_PORT 2>/dev/null)
        [[ "$status" == "200" ]] && return
    fi

    log "${BLUE}Starting preview server for $latest_branch on port $PREVIEW_PORT${NC}"
    tmux kill-session -t dpspice-preview 2>/dev/null
    tmux new-session -d -s dpspice-preview \
        "cd $DPSPICE_DIR/web && export PATH=/opt/homebrew/bin:\$HOME/.local/bin:\$PATH && git checkout $latest_branch 2>/dev/null; npm run dev -- -H 0.0.0.0 -p $PREVIEW_PORT 2>&1 | tee /tmp/dpspice-preview.log"
    echo "$latest_branch" > /tmp/dpspice-preview-branch
    sleep 10

    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 http://localhost:$PREVIEW_PORT 2>/dev/null)
    if [[ "$status" == "200" ]]; then
        log "${GREEN}Preview: http://0.0.0.0:$PREVIEW_PORT ($latest_branch)${NC}"
        cat > "$FLEET_DIR/review-queue/preview-ready.md" << PREVEOF
---
task_id: preview-server
project: DPSpice-com
type: decision_needed
priority: normal
created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## Preview Ready

- **Preview (new):** http://$WORKER_IP:$PREVIEW_PORT/app
- **Stable demo:** http://$WORKER_IP:$WEB_PORT/app

Compare side-by-side, then \`/worker-review\` to merge.
PREVEOF
    else
        log "${RED}Preview server failed to start${NC}"
    fi
}

# ─── GitHub CLI auth check ─────────────────────────

check_gh_auth() {
    if ! gh auth status &>/dev/null; then
        local auth_output
        auth_output=$(gh auth status 2>&1)
        log "${RED}GitHub CLI auth expired or invalid${NC}"
        log_bug "gh-auth-expired" "high" \
            "GitHub CLI auth is expired — gh commands (PR create, pr list) will fail with HTTP 401" \
            "$auth_output"

        cat > "$FLEET_DIR/review-queue/gh-auth-expired.md" << AUTHEOF
---
task_id: gh-auth-expired
project: claude-handler
type: blocked
priority: high
created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## GitHub CLI Auth Expired on Mac Mini

\`gh auth status\` failed. Worker tasks that create PRs will fail.

### Fix
Run interactively on the Mac Mini:
\`\`\`bash
gh auth login
\`\`\`
Or if a personal access token is available:
\`\`\`bash
echo "<token>" | gh auth login --with-token
\`\`\`

### Raw output
\`\`\`
$auth_output
\`\`\`
AUTHEOF
    else
        # Auth is healthy — clean up stale review-queue item if present
        rm -f "$FLEET_DIR/review-queue/gh-auth-expired.md" 2>/dev/null
    fi
}

# ─── Smoke test: /app page ─────────────────────────
smoke_test_app_page() {
    local body
    body=$(curl -s --connect-timeout 5 http://localhost:$WEB_PORT/app 2>/dev/null)
    if echo "$body" | grep -q "Something went wrong\|undefined is not an object"; then
        log_bug "app-page-crash" "critical" "The /app page has a runtime error" \
            "$(echo "$body" | grep -oE '(Something went wrong|undefined is not|TypeError)[^<]{0,80}' | head -3)"
    fi
}

# ─── Digest email when new items accumulate ───────
LAST_DIGEST_COUNT=0

send_digest_if_needed() {
    local current_count
    current_count=$(ls "$FLEET_DIR"/review-queue/*.md 2>/dev/null | wc -l | tr -d ' ')
    current_count=${current_count:-0}

    # Only send if new items appeared since last digest
    if (( current_count > LAST_DIGEST_COUNT && current_count > 0 )); then
        LAST_DIGEST_COUNT=$current_count

        # Build the queue table HTML
        local rows=""
        for f in "$FLEET_DIR"/review-queue/*.md; do
            [[ -f "$f" ]] || continue
            local fname type priority icon badge_bg badge_color
            fname=$(basename "$f" .md)
            type=$(grep 'type:' "$f" 2>/dev/null | head -1 | awk '{print $2}')
            priority=$(grep 'priority:' "$f" 2>/dev/null | head -1 | awk '{print $2}')

            case "$type" in
                completed) icon="✅"; badge_bg="#DCFCE7"; badge_color="#166534" ;;
                failed)    icon="❌"; badge_bg="#FEE2E2"; badge_color="#991B1B" ;;
                blocked)   icon="🔴"; badge_bg="#FEE2E2"; badge_color="#991B1B" ;;
                *)         icon="💬"; badge_bg="#F1F5F9"; badge_color="#475569" ;;
            esac

            local pri_badge=""
            [[ "$priority" == "high" ]] && pri_badge="<span style='background:#FEE2E2;color:#991B1B;padding:1px 8px;border-radius:10px;font-size:11px;'>HIGH</span>"

            rows+="<tr style='border-bottom:1px solid #E2E8F0;'><td style='padding:8px 0;'>$icon</td><td style='padding:8px 4px;font-weight:500;'>$fname</td><td style='color:#64748B;font-size:12px;'>$type</td><td>$pri_badge</td></tr>"
        done

        "$HANDLER_DIR/fleet-notify.sh" \
            "Fleet Digest — ${current_count} items to review" \
            "<table style='width:100%;font-size:13px;border-collapse:collapse;'>$rows</table><div style='margin-top:16px;text-align:center;'><a href='mailto:${GMAIL_USER:-}?subject=Re:%20Fleet%20Digest&body=merge%20all' style='display:inline-block;padding:8px 24px;background:#166534;color:#FFFFFF;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600;'>✓ Merge All</a></div>" \
            2>/dev/null &

        log "${BLUE}Digest email sent (${current_count} items)${NC}"
    fi
}

# ─── Main loop ────────────────────────────────────

init_bug_db
init_debug_file
log "${GREEN}Demo health checker + error detector started${NC}"
log "  API:        http://0.0.0.0:$API_PORT"
log "  Frontend:   http://0.0.0.0:$WEB_PORT"
log "  Health:     every ${CHECK_INTERVAL}s"
log "  Log scan:   every ${LOG_SCAN_INTERVAL}s"
log "  Debug file: $DEBUG_FILE"
log "  Bug DB:     $BUG_DB"
echo ""

while true; do
    now=$(date +%s)

    # ── Health checks (every CHECK_INTERVAL) ──
    api_ok=true
    web_ok=true

    if ! check_api; then
        api_ok=false
        log "${RED}API DOWN — attempting restart${NC}"
        log_bug "api-crash" "critical" "API server crashed and was restarted" \
            "$(tail -10 /tmp/dpspice-api.log 2>/dev/null)"
        restart_api
    fi

    if ! check_web; then
        web_ok=false
        log "${RED}Frontend DOWN — attempting restart${NC}"
        log_bug "web-crash" "critical" "Frontend server crashed and was restarted" \
            "$(tail -10 /tmp/dpspice-web.log 2>/dev/null)"
        restart_web
    fi

    if $api_ok && $web_ok; then
        if (( now % 600 < CHECK_INTERVAL )); then
            log "${GREEN}All services healthy ✓${NC}"
        fi
    fi

    # ── Deep log scan (every LOG_SCAN_INTERVAL) ──
    if (( now - LAST_LOG_SCAN >= LOG_SCAN_INTERVAL )); then
        LAST_LOG_SCAN=$now
        scan_api_logs
        scan_web_logs
        smoke_test_api
        smoke_test_app_page
        check_gh_auth
        check_preview_server
        maybe_create_worker_task

        # Check Gmail for reply commands
        "$HANDLER_DIR/fleet-notify.sh" --check-replies 2>/dev/null

        # Send digest if new completed items since last digest
        send_digest_if_needed
    fi

    sleep "$CHECK_INTERVAL"
done
