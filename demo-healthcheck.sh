#!/bin/bash
# demo-healthcheck.sh — Smart demo agent for Mac Mini
# 1. Keeps DPSpice demo alive (auto-restart if down)
# 2. Scans logs for errors/crashes → writes to DEBUG_DETECTOR.md
# 3. Auto-creates worker tasks for recurring bugs
#
# Run in tmux: tmux new-session -d -s demo-health './demo-healthcheck.sh'

set -uo pipefail
export PATH=/opt/homebrew/bin:$HOME/.local/bin:$PATH

DPSPICE_DIR="$HOME/Developer/dynamic-phasors/DPSpice-com"
FLEET_DIR="$HOME/.claude-fleet"
DEBUG_FILE="$DPSPICE_DIR/DEBUG_DETECTOR.md"
API_PORT=8000
WEB_PORT=3001
CHECK_INTERVAL=60       # seconds between health checks
LOG_SCAN_INTERVAL=300   # seconds between deep log scans (5 min)
LOG_ROTATE_INTERVAL=86400  # seconds between log rotations (24h)
LAST_LOG_SCAN=0
LAST_LOG_ROTATE=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "[health $(date +%H:%M:%S)] $1"; }

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

This file is maintained by `demo-healthcheck.sh`. It logs errors detected in
the running DPSpice demo. The Worker daemon reads this to know what to fix next.

**Status key:** 🔴 NEW | 🟡 KNOWN | ✅ FIXED | 🔄 WORKER_ASSIGNED

---

HEADER
    fi
}

# Log a bug to DEBUG_DETECTOR.md
# Usage: log_bug <slug> <severity> <description> <raw_error>
log_bug() {
    local slug="$1"
    local severity="$2"
    local description="$3"
    local raw_error="${4:-no error output}"
    local timestamp
    timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    init_debug_file

    # Check if this bug is already logged (avoid duplicates)
    if grep -q "slug: $slug" "$DEBUG_FILE" 2>/dev/null; then
        # Update the "last seen" timestamp
        local temp_file="${DEBUG_FILE}.tmp"
        python3 -c "
import re, sys
content = open('$DEBUG_FILE').read()
# Find this bug's section and update last_seen
pattern = r'(slug: $slug.*?last_seen: )\S+'
replacement = r'\g<1>$timestamp'
updated = re.sub(pattern, replacement, content, flags=re.DOTALL)
# Increment occurrence count
pattern2 = r'(slug: $slug.*?occurrences: )(\d+)'
def inc(m): return m.group(1) + str(int(m.group(2)) + 1)
updated = re.sub(pattern2, inc, updated, flags=re.DOTALL)
open('$DEBUG_FILE', 'w').write(updated)
" 2>/dev/null
        log "${YELLOW}Bug '$slug' seen again — updated count${NC}"
        return
    fi

    # New bug — append to file
    cat >> "$DEBUG_FILE" << BUG_ENTRY

### 🔴 NEW: $description

- **slug:** $slug
- **severity:** $severity
- **first_seen:** $timestamp
- **last_seen:** $timestamp
- **occurrences:** 1
- **status:** 🔴 NEW

\`\`\`
$(echo "$raw_error" | head -30)
\`\`\`

BUG_ENTRY

    log "${RED}NEW BUG logged: $slug — $description${NC}"

    # Email notification for new bugs
    # DISABLED "$HOME/Developer/claude-handler/fleet-notify.sh" --bug-detected "$slug" 2>/dev/null &

    # Also write to review queue so Commander sees it on startup
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
    [[ ! -f "$DEBUG_FILE" ]] && return

    local critical_count
    critical_count=$(grep -c "severity: critical" "$DEBUG_FILE" 2>/dev/null)
    critical_count=${critical_count:-0}
    critical_count=${critical_count// /}

    local new_count
    new_count=$(grep -c "status: 🔴 NEW" "$DEBUG_FILE" 2>/dev/null)
    new_count=${new_count:-0}
    new_count=${new_count// /}

    if (( new_count >= 3 )) || (( critical_count >= 1 )); then
        local task_id="auto-$(date +%Y%m%d-%H%M%S)-bugfix"
        local task_file="$FLEET_DIR/tasks/${task_id}.json"

        # Only create if no existing auto-bugfix task is queued/running
        if ls "$FLEET_DIR/tasks"/auto-*-bugfix.json 2>/dev/null | xargs grep -l '"queued"\|"running"' 2>/dev/null | head -1 | grep -q .; then
            return  # Already have an active auto-bugfix task
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
  "prompt": "Read $DEBUG_FILE for auto-detected bugs. Fix all bugs marked 🔴 NEW. For each bug: investigate the error, fix the root cause, add a defensive check to prevent it recurring, update the bug status in DEBUG_DETECTOR.md to ✅ FIXED. Run npm run build and npm test after each fix. Commit after each bug fix. Open PR when done.",
  "budget_usd": 10,
  "permission_mode": "dangerously-skip-permissions",
  "tmux_session": "claude-auto-bugfix",
  "priority": -1
}
TASK
        log "${BLUE}Auto-created worker task: $task_id ($new_count new bugs, $critical_count critical)${NC}"
    fi
}

# ─── Preview server for completed worker branches ──
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

- **Preview (new):** http://192.168.1.114:$PREVIEW_PORT/app
- **Stable demo:** http://192.168.1.114:3001/app

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

        "$HOME/Developer/claude-handler/fleet-notify.sh" \
            "Fleet Digest — ${current_count} items to review" \
            "<table style='width:100%;font-size:13px;border-collapse:collapse;'>$rows</table><div style='margin-top:16px;text-align:center;'><a href='mailto:${GMAIL_USER:-}?subject=Re:%20Fleet%20Digest&body=merge%20all' style='display:inline-block;padding:8px 24px;background:#166534;color:#FFFFFF;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600;'>✓ Merge All</a></div>" \
            2>/dev/null &

        log "${BLUE}Digest email sent (${current_count} items)${NC}"
    fi
}

# ─── Main loop ────────────────────────────────────

init_debug_file
log "${GREEN}Demo health checker + error detector started${NC}"
log "  API:        http://0.0.0.0:$API_PORT"
log "  Frontend:   http://0.0.0.0:$WEB_PORT"
log "  Health:     every ${CHECK_INTERVAL}s"
log "  Log scan:   every ${LOG_SCAN_INTERVAL}s"
log "  Debug file: $DEBUG_FILE"
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
        "$HOME/Developer/claude-handler/fleet-notify.sh" --check-replies 2>/dev/null

        # Send digest if new completed items since last digest
        send_digest_if_needed
    fi

    # ── Daily log rotation (every LOG_ROTATE_INTERVAL) ──
    if (( now - LAST_LOG_ROTATE >= LOG_ROTATE_INTERVAL )); then
        LAST_LOG_ROTATE=$now
        FLEET_BRAIN="$HOME/Developer/claude-handler/fleet-brain.py"
        if [[ -f "$FLEET_BRAIN" ]]; then
            log "${BLUE}Running daily log rotation...${NC}"
            python3 "$FLEET_BRAIN" log-rotate 2>&1 | while IFS= read -r line; do
                log "  $line"
            done
        fi
    fi

    sleep "$CHECK_INTERVAL"
done
