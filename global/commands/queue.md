# /queue — Mac Mini Server Dashboard

Commander-only. If not commander, say so and stop.

## Step 1: Read fleet config

```bash
source ~/.claude-fleet/machine-role.conf 2>/dev/null
```

Use `$SSH_TARGET` for all SSH calls.

## Step 2: Gather data in one SSH call

```bash
ssh $SSH_TARGET "
export PATH=/opt/homebrew/bin:\$HOME/.local/bin:\$PATH
echo '===SYSTEM==='
hostname; sysctl -n hw.ncpu
sysctl -n hw.memsize | awk '{printf \"%.0f\", \$1/1024/1024/1024}'
uptime | sed 's/.*up //;s/,.*//'
vm_stat | awk '/Pages free/{f=\$3}/Pages active/{a=\$3}/speculative/{s=\$3}END{gsub(/\./,\"\",f);gsub(/\./,\"\",a);gsub(/\./,\"\",s);t=f+a+s;printf \"%d %d\n\",a*16/1024,t*16/1024}'
echo '===CPU==='
top -l 1 -n 0 2>/dev/null | grep 'CPU usage' | head -1
echo '===TMUX==='
tmux list-sessions 2>/dev/null || echo 'none'
echo '===CLAUDE==='
ps aux | grep claude | grep -v grep | awk '{printf \"%s|%s|%s|%s\n\",\$2,\$3,\$4,substr(\$0,index(\$0,\$11),80)}'
echo '===TASKS==='
for f in ~/.claude-fleet/tasks/*.json; do
  [ -f \"\$f\" ] && python3 -c \"
import json; d=json.load(open('\$f'))
print('|'.join([d.get('slug','?'),d['status'],d.get('project_name','?'),d.get('branch',''),d.get('started_at',''),d.get('finished_at','')]))
\" 2>/dev/null; done
echo '===REVIEW==='
ls ~/.claude-fleet/review-queue/*.md 2>/dev/null | while read f; do
  head -7 \"\$f\" | grep -E 'type:|priority:' | tr '\n' '|'; echo \"\$(basename \$f)\"; done
echo '===SERVICES==='
curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://localhost:8000/health 2>/dev/null; echo ' api:8000'
curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 http://localhost:3001 2>/dev/null; echo ' web:3001'
echo '===DISK==='
df -h / | tail -1 | awk '{print \$4,\$5}'
echo '===DEBUG==='
grep -c 'status: 🔴 NEW' ~/Developer/dynamic-phasors/DPSpice-com/DEBUG_DETECTOR.md 2>/dev/null || echo 0
"
```

Also get worker IP: `ssh $SSH_TARGET "ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print \$1}'"``

## Step 3: Present the dashboard

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⚡ MAC MINI SERVER              {date} {time}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SYSTEM
  Host: {hostname}   Uptime: {uptime}
  CPU:  {ncpu} cores   Usage: {cpu_idle}% idle
  RAM:  {ram_used}GB / {ram_total}GB   Disk: {free} free ({pct} used)

  SERVICES
  API   http://{worker_ip}:8000   {✅ 200 | ❌ DOWN}
  Web   http://{worker_ip}:3001   {✅ 200 | ❌ DOWN}
  Health checker / Worker daemon   {✅ running | ❌ stopped}

  TASKS  (🔄 running · 📋 queued · ✅ done · ❌ failed · ⏸ blocked)
  {icon} {slug}   {project}   {elapsed/duration/position}

  CLAUDE PROCESSES
  PID {pid}  CPU: {cpu}%  RAM: {mem}MB  {cmd}

  REVIEW QUEUE ({count} items)
  {icon} {filename}  ({type}, {priority})

  AUTO-DETECTED BUGS: {count} new  (DEBUG_DETECTOR.md)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Actions: /worker-review  /worker-status {slug}  /dispatch
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

For task timing: compute elapsed (now − started_at), duration (finished_at − started_at), queue position from JSON order. Show inline (e.g. "running 23m", "done in 15m", "queued 2nd").

## Step 4: Contextual actions

- Review items → "Run `/worker-review` to review {n} tasks"
- Running task → "Run `/worker-status {slug}` for live output"
- Idle → "Mac Mini is idle. Run `/dispatch` to send work."
- Bugs → "{n} auto-detected bugs in DEBUG_DETECTOR.md"
- Service down → "⚠️ {service} DOWN — health checker should auto-restart in ~60s"

## Variants

- `/queue` — full dashboard
- `/queue tasks` — task list only
- `/queue services` — service health only
- `/queue bugs` — DEBUG_DETECTOR.md contents
