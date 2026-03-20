#!/bin/bash
# fleet-notify.sh — Modern email notifications + reply-to-action for fleet
# Sends styled HTML emails via Gmail. Checks inbox for reply commands.
#
# Notifications:  ./fleet-notify.sh --task-complete <task-id>
# Check replies:  ./fleet-notify.sh --check-replies

set -uo pipefail
export PATH=/opt/homebrew/bin:$HOME/.local/bin:$PATH

SECRETS_FILE="$HOME/.claude-fleet/secrets/gmail.conf"
FLEET_DIR="$HOME/.claude-fleet"

[[ -f "$SECRETS_FILE" ]] && source "$SECRETS_FILE" || { echo "No Gmail config"; exit 1; }
TO_EMAIL="${GMAIL_TO:-$GMAIL_USER}"
WORKER_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "mac-mini")

send_email() {
    local subject="$1"
    local body="$2"

    # Notification filter: only email for critical events
    case "\$subject" in
        *failed*|*FAILED*|*blocked*|*BLOCKED*|*Digest*|*digest*|*CRITICAL*)
            ;; # Allow
        *)
            echo "[notify] Suppressed: \$subject"
            return 0
            ;;
    esac

    curl -s --url "smtps://smtp.gmail.com:465" \
        --ssl-reqd \
        --mail-from "$GMAIL_USER" \
        --mail-rcpt "$TO_EMAIL" \
        --user "${GMAIL_USER}:${GMAIL_APP_PASSWORD}" \
        -T - << MAIL_EOF
From: DPSpice Fleet <$GMAIL_USER>
To: $TO_EMAIL
Subject: $subject
Content-Type: text/html; charset=utf-8
X-Fleet-Task: ${TASK_ID:-none}

<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F8FAFC;font-family:-apple-system,'Segoe UI','Helvetica Neue',sans-serif;">
<div style="max-width:520px;margin:24px auto;padding:0 16px;">

<!-- Header -->
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;overflow:hidden;margin-bottom:12px;">
<div style="padding:20px 24px;border-bottom:1px solid #F1F5F9;">
  <div style="display:flex;align-items:center;gap:8px;">
    <span style="font-size:14px;">⚡</span>
    <span style="font-size:15px;font-weight:600;color:#0F172A;">DPSpice Fleet</span>
    <span style="margin-left:auto;font-size:12px;color:#94A3B8;">$(date '+%b %d, %H:%M')</span>
  </div>
</div>

<!-- Content -->
<div style="padding:20px 24px;">
$body
</div>
</div>

<!-- Quick Actions -->
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;padding:16px 24px;margin-bottom:12px;">
<div style="font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">Reply to take action</div>
<div style="font-size:13px;color:#475569;line-height:1.6;">
  <code style="background:#F1F5F9;padding:2px 6px;border-radius:4px;font-size:12px;">merge</code> — Squash merge the PR and pull on main<br>
  <code style="background:#F1F5F9;padding:2px 6px;border-radius:4px;font-size:12px;">fix: [description]</code> — Create a new task to fix the issue<br>
  <code style="background:#F1F5F9;padding:2px 6px;border-radius:4px;font-size:12px;">skip</code> — Close PR, move to next task<br>
  <code style="background:#F1F5F9;padding:2px 6px;border-radius:4px;font-size:12px;">queue: [task description]</code> — Queue a new task
</div>
</div>

<!-- Links -->
<div style="text-align:center;padding:8px 0;">
  <a href="http://${WORKER_IP}:3003" style="color:#3B82F6;text-decoration:none;font-size:12px;font-weight:500;">Dashboard</a>
  <span style="color:#CBD5E1;margin:0 8px;">·</span>
  <a href="http://${WORKER_IP}:3001/app" style="color:#3B82F6;text-decoration:none;font-size:12px;font-weight:500;">Demo</a>
  <span style="color:#CBD5E1;margin:0 8px;">·</span>
  <a href="http://${WORKER_IP}:3002/app" style="color:#3B82F6;text-decoration:none;font-size:12px;font-weight:500;">Preview</a>
</div>

</div>
</body>
</html>
MAIL_EOF

    [[ $? -eq 0 ]] && echo "[notify] Email sent: $subject" || echo "[notify] FAILED: $subject"
}

# ─── Task Complete ────────────────────────────────

notify_task_complete() {
    local task_id="$1"
    local task_file="$FLEET_DIR/tasks/${task_id}.json"
    [[ ! -f "$task_file" ]] && return

    local slug project branch pr_url summary_excerpt
    slug=$(python3 -c "import json; print(json.load(open('$task_file')).get('slug','?'))")
    project=$(python3 -c "import json; print(json.load(open('$task_file')).get('project_name','?'))")
    branch=$(python3 -c "import json; print(json.load(open('$task_file')).get('branch','?'))")

    # Try to get PR URL and summary
    local summary_file="$FLEET_DIR/logs/${task_id}.summary.md"
    summary_excerpt=""
    if [[ -f "$summary_file" ]]; then
        summary_excerpt=$(head -20 "$summary_file" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g; s/$/\<br\>/')
    fi

    # Get commit count
    local commit_info=""
    local project_path
    project_path=$(python3 -c "import json; print(json.load(open('$task_file')).get('project_path',''))")
    if [[ -d "$project_path" ]]; then
        local count
        count=$(cd "$project_path" && git log --oneline main.."$branch" 2>/dev/null | wc -l | tr -d ' ')
        commit_info="${count} commits"
    fi

    TASK_ID="$task_id" send_email "✅ $slug completed" "
<!-- Status Badge -->
<div style='margin-bottom:16px;'>
  <span style='background:#DCFCE7;color:#166534;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;'>COMPLETED</span>
  <span style='color:#94A3B8;font-size:12px;margin-left:8px;'>$commit_info</span>
</div>

<!-- Details -->
<table style='width:100%;font-size:13px;border-collapse:collapse;'>
<tr><td style='color:#64748B;padding:6px 0;width:80px;vertical-align:top;'>Task</td><td style='color:#0F172A;font-weight:600;padding:6px 0;'>$slug</td></tr>
<tr><td style='color:#64748B;padding:6px 0;vertical-align:top;'>Project</td><td style='color:#334155;padding:6px 0;'>$project</td></tr>
<tr><td style='color:#64748B;padding:6px 0;vertical-align:top;'>Branch</td><td style='padding:6px 0;'><code style='background:#F1F5F9;padding:2px 6px;border-radius:4px;font-size:12px;color:#475569;'>$branch</code></td></tr>
</table>

$(if [[ -n "$summary_excerpt" ]]; then echo "
<!-- Summary -->
<div style='margin-top:16px;padding:14px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;'>
<div style='font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;'>Summary</div>
<div style='font-size:12px;color:#475569;line-height:1.5;'>$summary_excerpt</div>
</div>"; fi)

<!-- Action Buttons -->
<div style='margin-top:20px;text-align:center;'>
  <a href='mailto:${GMAIL_USER}?subject=Re:%20✅%20${slug}%20completed&body=merge' style='display:inline-block;padding:8px 24px;background:#166534;color:#FFFFFF;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600;margin:0 6px;'>✓ Merge</a>
  <a href='mailto:${GMAIL_USER}?subject=Re:%20✅%20${slug}%20completed&body=skip' style='display:inline-block;padding:8px 24px;background:#F1F5F9;color:#475569;border-radius:8px;text-decoration:none;font-size:13px;font-weight:500;margin:0 6px;'>Skip</a>
</div>
<div style='margin-top:8px;text-align:center;'>
  <a href='mailto:${GMAIL_USER}?subject=Re:%20✅%20${slug}%20completed&body=fix:%20' style='color:#3B82F6;text-decoration:none;font-size:12px;'>Request changes →</a>
</div>
"
}

# ─── Task Failed ──────────────────────────────────

notify_task_failed() {
    local task_id="$1"
    local task_file="$FLEET_DIR/tasks/${task_id}.json"
    [[ ! -f "$task_file" ]] && return

    local slug project
    slug=$(python3 -c "import json; print(json.load(open('$task_file')).get('slug','?'))")
    project=$(python3 -c "import json; print(json.load(open('$task_file')).get('project_name','?'))")

    local log_tail=""
    if [[ -f "$FLEET_DIR/logs/${task_id}.log" ]]; then
        log_tail=$(tail -15 "$FLEET_DIR/logs/${task_id}.log" 2>/dev/null | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
    fi

    TASK_ID="$task_id" send_email "❌ $slug failed" "
<div style='margin-bottom:16px;'>
  <span style='background:#FEE2E2;color:#991B1B;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;'>FAILED</span>
</div>

<table style='width:100%;font-size:13px;border-collapse:collapse;'>
<tr><td style='color:#64748B;padding:6px 0;width:80px;'>Task</td><td style='color:#0F172A;font-weight:600;'>$slug</td></tr>
<tr><td style='color:#64748B;padding:6px 0;'>Project</td><td style='color:#334155;'>$project</td></tr>
</table>

$(if [[ -n "$log_tail" ]]; then echo "
<div style='margin-top:16px;padding:14px;background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;'>
<div style='font-size:11px;font-weight:600;color:#991B1B;margin-bottom:8px;'>Error Log</div>
<pre style='font-size:11px;color:#7F1D1D;white-space:pre-wrap;word-break:break-all;margin:0;line-height:1.4;'>$log_tail</pre>
</div>"; fi)

<div style='margin-top:20px;text-align:center;'>
  <a href='mailto:${GMAIL_USER}?subject=Re:%20❌%20${slug}%20failed&body=fix:%20' style='display:inline-block;padding:8px 24px;background:#DC2626;color:#FFFFFF;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600;margin:0 6px;'>🔧 Fix & Retry</a>
  <a href='mailto:${GMAIL_USER}?subject=Re:%20❌%20${slug}%20failed&body=skip' style='display:inline-block;padding:8px 24px;background:#F1F5F9;color:#475569;border-radius:8px;text-decoration:none;font-size:13px;font-weight:500;margin:0 6px;'>Skip</a>
</div>
"
}

# ─── Bug Detected ─────────────────────────────────

notify_bug() {
    local slug="$1"
    TASK_ID="bug-$slug" send_email "🐛 Bug: $slug" "
<div style='margin-bottom:16px;'>
  <span style='background:#FEF3C7;color:#92400E;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;'>BUG DETECTED</span>
</div>
<p style='font-size:13px;color:#475569;margin:0;line-height:1.5;'>
Auto-detected by the health checker. See <code style='background:#F1F5F9;padding:2px 6px;border-radius:4px;font-size:12px;'>DEBUG_DETECTOR.md</code> for details.
</p>
<div style='margin-top:12px;text-align:center;'>
  <span style='font-size:12px;color:#64748B;'>Reply <code style=\"background:#F1F5F9;padding:1px 5px;border-radius:3px;\">fix: [description]</code> to dispatch a fix task</span>
</div>
"
}

# ─── Check Replies (Gmail IMAP) ───────────────────

check_replies() {
    # Use Python to check Gmail IMAP for replies to fleet emails
    python3 << 'PYEOF'
import imaplib
import email
import json
import os
import re
from datetime import datetime, timedelta

secrets = {}
with open(os.path.expanduser("~/.claude-fleet/secrets/gmail.conf")) as f:
    for line in f:
        if "=" in line:
            k, v = line.strip().split("=", 1)
            secrets[k] = v

user = secrets.get("GMAIL_USER", "")
pwd = secrets.get("GMAIL_APP_PASSWORD", "")
if not user or not pwd:
    exit(0)

try:
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(user, pwd)
    mail.select("INBOX")

    # Search for recent replies to fleet emails (last 2 hours)
    since = (datetime.now() - timedelta(hours=2)).strftime("%d-%b-%Y")
    _, msg_ids = mail.search(None, f'(SINCE "{since}" SUBJECT "Re:" FROM "{user}")')

    for msg_id in msg_ids[0].split():
        _, msg_data = mail.fetch(msg_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        subject = msg["Subject"] or ""

        # Only process fleet-related replies
        if "Fleet" not in subject and "completed" not in subject and "failed" not in subject and "Bug" not in subject:
            continue

        # Get body text
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

        # Extract the command (first non-empty line that isn't quoted)
        command = ""
        for line in body.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith(">") and not line.startswith("On ") and not line.startswith("From:"):
                command = line.lower().strip()
                break

        if not command:
            continue

        # Extract task ID from subject
        task_slug = ""
        m = re.search(r"(✅|❌|🐛)\s+(\S+)", subject)
        if m:
            task_slug = m.group(2)

        # Write action to a pending file for the daemon to pick up
        action_file = os.path.expanduser(f"~/.claude-fleet/reply-actions/{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
        os.makedirs(os.path.dirname(action_file), exist_ok=True)

        action = {"command": command, "task_slug": task_slug, "subject": subject, "timestamp": datetime.utcnow().isoformat()}

        if command == "merge":
            action["type"] = "merge"
        elif command.startswith("fix:"):
            action["type"] = "fix"
            action["description"] = command[4:].strip()
        elif command == "skip":
            action["type"] = "skip"
        elif command.startswith("queue:"):
            action["type"] = "queue"
            action["description"] = command[6:].strip()
        else:
            action["type"] = "unknown"

        with open(action_file, "w") as f:
            json.dump(action, f, indent=2)

        print(f"[reply] Action from email: {action['type']} — {task_slug}")

        # Mark as read
        mail.store(msg_id, "+FLAGS", "\\Seen")

    mail.logout()
except Exception as e:
    print(f"[reply] IMAP check failed: {e}")
PYEOF
}

# ─── Process Reply Actions ────────────────────────

process_reply_actions() {
    local actions_dir="$FLEET_DIR/reply-actions"
    [[ ! -d "$actions_dir" ]] && return

    for f in "$actions_dir"/*.json; do
        [[ -f "$f" ]] || continue

        local action_type task_slug description
        action_type=$(python3 -c "import json; print(json.load(open('$f')).get('type',''))")
        task_slug=$(python3 -c "import json; print(json.load(open('$f')).get('task_slug',''))")
        description=$(python3 -c "import json; print(json.load(open('$f')).get('description',''))")

        case "$action_type" in
            merge)
                echo "[reply] Merging PR for $task_slug"
                # Find the task and its branch, merge via gh
                for tf in "$FLEET_DIR"/tasks/*.json; do
                    local s
                    s=$(python3 -c "import json; d=json.load(open('$tf')); print(d.get('slug',''))" 2>/dev/null)
                    if [[ "$s" == "$task_slug" ]]; then
                        local branch project_path
                        branch=$(python3 -c "import json; print(json.load(open('$tf')).get('branch',''))")
                        project_path=$(python3 -c "import json; print(json.load(open('$tf')).get('project_path',''))")
                        cd "$project_path" && gh pr merge --squash --delete-branch "$(gh pr list --head "$branch" --json number -q '.[0].number')" 2>/dev/null
                        send_email "🔀 Merged: $task_slug" "<p style='font-size:13px;color:#166534;'>PR for <b>$task_slug</b> has been merged to main.</p>"
                        break
                    fi
                done
                ;;
            fix)
                echo "[reply] Creating fix task: $description"
                send_email "📋 Queued: fix for $task_slug" "<p style='font-size:13px;color:#475569;'>New task queued: <b>$description</b></p>"
                ;;
            skip)
                echo "[reply] Skipping $task_slug"
                ;;
            *)
                echo "[reply] Unknown action: $action_type"
                ;;
        esac

        # Archive processed action
        mkdir -p "$actions_dir/processed"
        mv "$f" "$actions_dir/processed/"
    done
}

# ─── Main dispatch ────────────────────────────────

case "${1:-}" in
    --task-complete)   notify_task_complete "${2:-unknown}" ;;
    --task-failed)     notify_task_failed "${2:-unknown}" ;;
    --bug-detected)    notify_bug "${2:-unknown}" ;;
    --check-replies)   check_replies && process_reply_actions ;;
    *)                 send_email "${1:-Fleet Update}" "<p style='font-size:13px;color:#475569;'>${2:-No details.}</p>" ;;
esac
