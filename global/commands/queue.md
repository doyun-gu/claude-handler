# /queue — Mac Mini Server Dashboard

You are the Commander (MacBook Pro). This command shows a real-time dashboard of everything running on the Mac Mini.

## Steps

### Step 1: Read fleet config

```bash
cat ~/.claude-fleet/machine-role.conf 2>/dev/null
```

If not commander, say: "This command is for Commander machines only."

### Step 2: Gather all data from Mac Mini (single SSH call for speed)

Run this as one SSH command to avoid multiple round-trips:

```bash
ssh mac-mini "
export PATH=/opt/homebrew/bin:\$HOME/.local/bin:\$PATH

echo '===SYSTEM==='
hostname
sysctl -n hw.ncpu
sysctl -n hw.memsize | awk '{printf \"%.0f\", \$1/1024/1024/1024}'
uptime | sed 's/.*up //' | sed 's/,.*//'
vm_stat | awk '/Pages free/ {free=\$3} /Pages active/ {active=\$3} /speculative/ {spec=\$3} END {gsub(/\./,\"\",free); gsub(/\./,\"\",active); gsub(/\./,\"\",spec); total=free+active+spec; printf \"%d %d\n\", active*16/1024, total*16/1024}'

echo '===CPU==='
top -l 1 -n 0 2>/dev/null | grep 'CPU usage' | head -1

echo '===TMUX==='
tmux list-sessions 2>/dev/null || echo 'none'

echo '===CLAUDE==='
ps aux | grep claude | grep -v grep | awk '{printf \"%s|%s|%s|%s\n\", \$2, \$3, \$4, substr(\$0, index(\$0,\$11), 80)}'

echo '===TASKS==='
for f in ~/.claude-fleet/tasks/*.json; do
  [ -f \"\$f\" ] && python3 -c \"
import json
d = json.load(open('\$f'))
print('|'.join([d.get('slug','?'), d['status'], d.get('project_name','?'), d.get('branch',''), d.get('started_at',''), d.get('finished_at','')]))
\" 2>/dev/null
done

echo '===REVIEW==='
ls ~/.claude-fleet/review-queue/*.md 2>/dev/null | while read f; do
  head -7 \"\$f\" | grep -E 'type:|priority:' | tr '\n' '|'
  echo \"\$(basename \$f)\"
done

echo '===SERVICES==='
curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://localhost:8000/health 2>/dev/null; echo ' api:8000'
curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://localhost:3001 2>/dev/null; echo ' web:3001'

echo '===DISK==='
df -h / | tail -1 | awk '{print \$4, \$5}'

echo '===DEBUG==='
grep -c 'status: 🔴 NEW' ~/Developer/dynamic-phasors/DPSpice-com/DEBUG_DETECTOR.md 2>/dev/null || echo 0
"
```

### Step 3: Parse and present the dashboard

Format the output as a polished dashboard. Use box-drawing characters and alignment:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⚡ MAC MINI SERVER                     {date} {time}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SYSTEM
  ─────
  Host:     {hostname}          Uptime: {uptime}
  CPU:      {ncpu} cores        Usage:  {cpu_idle}% idle
  RAM:      {ram_used}GB / {ram_total}GB ({pct}%)
  Disk:     {disk_free} free ({disk_pct} used)

  SERVICES
  ────────
  API   http://192.168.1.114:8000    {✅ 200 | ❌ DOWN}
  Web   http://192.168.1.114:3001    {✅ 200 | ❌ DOWN}
  Health checker                     {✅ running | ❌ stopped}
  Worker daemon                      {✅ running | ❌ stopped}

  TASKS
  ─────
  {status_icon} {slug:30s}  {project:15s}  {duration/ETA}
  {status_icon} {slug:30s}  {project:15s}  {duration/ETA}
  ...

  Status icons:
    🔄 running  →  show elapsed time: "running 23m"
    📋 queued   →  show position: "next" / "2nd in queue"
    ✅ done     →  show duration: "done in 15m"
    ❌ failed   →  show "FAILED — check log"
    ⏸️  blocked  →  show reason

  CLAUDE PROCESSES
  ────────────────
  PID {pid}  CPU: {cpu}%  RAM: {mem}MB  {task_description}

  REVIEW QUEUE ({count} items)
  ────────────────────────────
  {icon} {filename}  ({type}, {priority})
  ...

  AUTO-DETECTED BUGS: {count} new
  ─────────────────────────────
  (from DEBUG_DETECTOR.md)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Actions: /worker-review  /worker-status {slug}  /dispatch
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 4: Calculate durations and ETAs

For running tasks:
- Calculate elapsed time from `started_at` to now
- Estimate remaining time based on average completion time of similar completed tasks
- Show as: "running 23m (~7m remaining)" or just "running 23m" if no estimate

For queued tasks:
- Count position in queue
- Estimate start time based on running task's expected completion
- Show as: "queued (next, ~7m wait)" or "queued (2nd, ~37m wait)"

For completed tasks:
- Calculate duration from `started_at` to `finished_at`
- Show as: "done in 15m"

### Step 5: Offer actions based on state

Based on what's happening:
- If review queue has items: "→ Run `/worker-review` to review {count} completed tasks"
- If running task exists: "→ Run `/worker-status {slug}` for live output"
- If queue is empty and no running task: "→ Mac Mini is idle. Run `/dispatch` to send work."
- If bugs detected: "→ {count} auto-detected bugs in DEBUG_DETECTOR.md"
- If a service is down: "⚠️ {service} is DOWN — health checker should auto-restart within 60s"

## Quick Variants

- `/queue` — Full dashboard (default)
- `/queue tasks` — Just the task list (no system info)
- `/queue services` — Just service health
- `/queue bugs` — Show DEBUG_DETECTOR.md contents
