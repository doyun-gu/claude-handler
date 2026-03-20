# /queue — Worker Server Dashboard

You are the Commander. This command shows a real-time dashboard of everything running on the Worker machine.

## Steps

### Step 1: Read fleet config

```bash
source ~/.claude-fleet/machine-role.conf 2>/dev/null
```

Use `$SSH_TARGET` for the worker hostname and `$MACHINE_ROLE` to verify this is a commander.
If not commander, say: "This command is for Commander machines only."

Get the worker IP for display:
```bash
ssh $SSH_TARGET "ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print \$1}'"
```

### Step 2: Gather all data from Worker (single SSH call for speed)

Run this as one SSH command to avoid multiple round-trips:

```bash
ssh $SSH_TARGET "
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
curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://localhost:3003/health 2>/dev/null; echo ' dashboard:3003'

echo '===DISK==='
df -h / | tail -1 | awk '{print \$4, \$5}'
"
```

### Step 3: Parse and present the dashboard

Format the output as a polished dashboard. Use box-drawing characters and alignment:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WORKER SERVER                           {date} {time}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SYSTEM
  ─────
  Host:     {hostname}          Uptime: {uptime}
  CPU:      {ncpu} cores        Usage:  {cpu_idle}% idle
  RAM:      {ram_used}GB / {ram_total}GB ({pct}%)
  Disk:     {disk_free} free ({disk_pct} used)

  SERVICES
  ────────
  Dashboard  http://{worker_ip}:3003  {ok/down}
  Worker daemon                        {ok/down}

  TASKS
  ─────
  {status_icon} {slug:30s}  {project:15s}  {duration/ETA}
  ...

  Status icons:
    running   show elapsed time: "running 23m"
    queued    show position: "next" / "2nd in queue"
    done      show duration: "done in 15m"
    failed    show "FAILED — check log"
    blocked   show reason

  CLAUDE PROCESSES
  ────────────────
  PID {pid}  CPU: {cpu}%  RAM: {mem}MB  {task_description}

  REVIEW QUEUE ({count} items)
  ────────────────────────────
  {icon} {filename}  ({type}, {priority})
  ...

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
- If review queue has items: "Run `/worker-review` to review {count} completed tasks"
- If running task exists: "Run `/worker-status {slug}` for live output"
- If queue is empty and no running task: "Worker is idle. Run `/dispatch` to send work."
- If a service is down: "Warning: {service} is DOWN — supervisor should auto-restart within 30s"

## Quick Variants

- `/queue` — Full dashboard (default)
- `/queue tasks` — Just the task list (no system info)
- `/queue services` — Just service health
