#!/bin/bash
# fleet-status-server.sh — Tiny web dashboard for fleet status
# Serves a live status page at http://0.0.0.0:3003
# Also sends macOS notifications when tasks complete.
#
# Run: tmux new-session -d -s fleet-status './fleet-status-server.sh'

set -uo pipefail
export PATH=/opt/homebrew/bin:$HOME/.local/bin:$PATH

FLEET_DIR="$HOME/.claude-fleet"
PORT=3003
NOTIFIED_FILE="/tmp/fleet-notified-tasks"
touch "$NOTIFIED_FILE"

# Generate the HTML status page
generate_html() {
    local tasks_html=""
    local review_html=""
    local services_html=""

    # Tasks
    for f in "$FLEET_DIR"/tasks/*.json; do
        [[ -f "$f" ]] || continue
        local info
        info=$(python3 -c "
import json
d = json.load(open('$f'))
slug = d.get('slug','?')
status = d['status']
project = d.get('project_name','?')
started = d.get('started_at','—')
finished = d.get('finished_at','—')
icon = {'queued':'📋','running':'🔄','completed':'✅','failed':'❌','blocked':'⏸️','merged':'🔀'}.get(status,'❓')
print(f'<tr><td>{icon} {status}</td><td><b>{slug}</b></td><td>{project}</td><td>{started[11:19] if started != \"—\" else \"—\"}</td><td>{finished[11:19] if finished != \"—\" else \"—\"}</td></tr>')
" 2>/dev/null)
        tasks_html+="$info"
    done

    # Review queue
    for f in "$FLEET_DIR"/review-queue/*.md; do
        [[ -f "$f" ]] || continue
        local fname
        fname=$(basename "$f")
        local type priority
        type=$(grep 'type:' "$f" | head -1 | awk '{print $2}')
        priority=$(grep 'priority:' "$f" | head -1 | awk '{print $2}')
        local icon="💬"
        [[ "$type" == "completed" ]] && icon="✅"
        [[ "$type" == "blocked" ]] && icon="🔴"
        [[ "$type" == "failed" ]] && icon="❌"
        review_html+="<tr><td>$icon $type</td><td>$fname</td><td>$priority</td></tr>"
    done

    # Services
    local api_status web_status preview_status
    api_status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 http://localhost:8000/health 2>/dev/null)
    web_status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 http://localhost:3001/app 2>/dev/null)
    preview_status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 http://localhost:3002/app 2>/dev/null)

    local api_icon="✅" web_icon="✅" preview_icon="✅"
    [[ "$api_status" != "200" ]] && api_icon="❌"
    [[ "$web_status" != "200" ]] && web_icon="❌"
    [[ "$preview_status" != "200" ]] && preview_icon="❌"

    # System info
    local cpu_cores mem_gb uptime_str
    cpu_cores=$(sysctl -n hw.ncpu 2>/dev/null || echo "?")
    mem_gb=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1024/1024/1024}')
    uptime_str=$(uptime | sed 's/.*up //' | sed 's/,.*//')

    cat << HTMLEOF
HTTP/1.1 200 OK
Content-Type: text/html; charset=utf-8
Connection: close
Access-Control-Allow-Origin: *

<!DOCTYPE html>
<html>
<head>
<title>Fleet Status — Mac Mini</title>
<meta http-equiv="refresh" content="30">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, 'Segoe UI', sans-serif; background: #0F172A; color: #E2E8F0; padding: 24px; }
  h1 { font-size: 20px; color: #F8FAFC; margin-bottom: 4px; }
  .subtitle { color: #94A3B8; font-size: 13px; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 24px; }
  .card { background: #1E293B; border-radius: 8px; padding: 16px; }
  .card h3 { font-size: 12px; color: #94A3B8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
  .card .value { font-size: 24px; font-weight: 600; }
  .green { color: #4ADE80; }
  .red { color: #F87171; }
  .amber { color: #FBBF24; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
  th { text-align: left; padding: 8px 12px; color: #94A3B8; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid #334155; }
  td { padding: 8px 12px; border-bottom: 1px solid #1E293B; font-size: 13px; }
  .section { margin-bottom: 24px; }
  .section h2 { font-size: 14px; color: #CBD5E1; margin-bottom: 12px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; }
  .badge-green { background: #166534; color: #4ADE80; }
  .badge-red { background: #7F1D1D; color: #F87171; }
  a { color: #60A5FA; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>

<h1>⚡ Fleet Status — Mac Mini Worker</h1>
<p class="subtitle">Auto-refreshes every 30s · $(date '+%Y-%m-%d %H:%M:%S')</p>

<div class="grid">
  <div class="card">
    <h3>System</h3>
    <div class="value">${cpu_cores} cores</div>
    <div style="color:#94A3B8;font-size:12px">${mem_gb}GB RAM · up ${uptime_str}</div>
  </div>
  <div class="card">
    <h3>Demo</h3>
    <div class="value">${web_icon} Live</div>
    <div style="font-size:12px"><a href="http://$(ipconfig getifaddr en0 2>/dev/null):3001/app" target="_blank">:3001/app</a></div>
  </div>
  <div class="card">
    <h3>Preview</h3>
    <div class="value">${preview_icon} $(cat /tmp/dpspice-preview-branch 2>/dev/null || echo 'none')</div>
    <div style="font-size:12px"><a href="http://$(ipconfig getifaddr en0 2>/dev/null):3002/app" target="_blank">:3002/app</a></div>
  </div>
</div>

<div class="section">
  <h2>Services</h2>
  <table>
    <tr><th>Service</th><th>Port</th><th>Status</th></tr>
    <tr><td>API (FastAPI)</td><td>8000</td><td>${api_icon} ${api_status}</td></tr>
    <tr><td>Demo (Next.js)</td><td>3001</td><td>${web_icon} ${web_status}</td></tr>
    <tr><td>Preview</td><td>3002</td><td>${preview_icon} ${preview_status}</td></tr>
    <tr><td>Status page</td><td>3003</td><td>✅ 200</td></tr>
  </table>
</div>

<div class="section">
  <h2>Tasks</h2>
  <table>
    <tr><th>Status</th><th>Task</th><th>Project</th><th>Started</th><th>Finished</th></tr>
    ${tasks_html:-<tr><td colspan="5" style="color:#64748B">No tasks</td></tr>}
  </table>
</div>

<div class="section">
  <h2>Review Queue</h2>
  <table>
    <tr><th>Type</th><th>Item</th><th>Priority</th></tr>
    ${review_html:-<tr><td colspan="3" style="color:#64748B">Empty — nothing to review</td></tr>}
  </table>
</div>

<div style="color:#475569;font-size:11px;margin-top:24px">
  Worker daemon · Health checker · Fleet status server
</div>

</body>
</html>
HTMLEOF
}

# Send macOS notification for newly completed tasks
check_notifications() {
    for f in "$FLEET_DIR"/tasks/*.json; do
        [[ -f "$f" ]] || continue
        local task_id status
        task_id=$(python3 -c "import json; print(json.load(open('$f'))['id'])" 2>/dev/null)
        status=$(python3 -c "import json; print(json.load(open('$f'))['status'])" 2>/dev/null)

        if [[ "$status" == "completed" || "$status" == "failed" ]]; then
            if ! grep -q "$task_id" "$NOTIFIED_FILE" 2>/dev/null; then
                local slug
                slug=$(python3 -c "import json; print(json.load(open('$f')).get('slug','task'))" 2>/dev/null)
                local icon="✅"
                [[ "$status" == "failed" ]] && icon="❌"

                # macOS notification
                osascript -e "display notification \"$icon $slug — $status\" with title \"Fleet Worker\" subtitle \"Task $status\" sound name \"Glass\"" 2>/dev/null

                echo "$task_id" >> "$NOTIFIED_FILE"
            fi
        fi
    done
}

# Main: serve HTTP and check notifications
echo "[status $(date +%H:%M:%S)] Fleet status server on port $PORT"
echo "[status $(date +%H:%M:%S)] Dashboard: http://0.0.0.0:$PORT"

while true; do
    check_notifications
    # Serve one request (nc closes after each)
    generate_html | nc -l "$PORT" -w 2 >/dev/null 2>&1
done
