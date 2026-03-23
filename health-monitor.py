#!/usr/bin/env python3
"""
health-monitor.py — Service health monitor with auto-fix for Mac Mini fleet.

Checks every 60 seconds:
  1. API Server (port 8000)       — auto-restarts uvicorn
  2. Dev Server (port 3002)       — clears .next cache, restarts next dev
  3. Git Sync (origin/main)       — fetches and resets if diverged
  4. Dashboard (port 3003)        — restarts dashboard
  5. Docker (port 3001)           — logs warning only
  6. Worker Daemon                — restarts if dead

Run in tmux:
  tmux new-session -d -s health-monitor \
    'cd ~/Developer/claude-handler && python3 health-monitor.py'
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Configuration ────────────────────────────────────────────
FLEET_DIR = Path.home() / ".claude-fleet"
LOG_FILE = FLEET_DIR / "logs" / "health-monitor.log"
HANDLER_DIR = Path(__file__).resolve().parent
DPSPICE_DIR = Path.home() / "Developer" / "dynamic-phasors" / "DPSpice-com"

CHECK_INTERVAL = 60  # seconds

PORTS = {
    "api": 8000,
    "dev": 3002,
    "dashboard": 3003,
    "docker": 3001,
}

# Max consecutive fix attempts before backing off
MAX_FIX_ATTEMPTS = 3
BACKOFF_CYCLES = 5  # skip this many cycles after hitting max attempts

# ── Logging ──────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("health-monitor")
logger.setLevel(logging.INFO)

fmt = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(fmt)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(fmt)
logger.addHandler(console_handler)


# ── State tracking ───────────────────────────────────────────
fix_attempts: dict[str, int] = {}
backoff_remaining: dict[str, int] = {}


def log_ok(msg: str) -> None:
    logger.info("[OK] %s", msg)


def log_fix(msg: str) -> None:
    logger.info("[FIX] %s", msg)


def log_warn(msg: str) -> None:
    logger.info("[WARN] %s", msg)


def log_err(msg: str) -> None:
    logger.info("[ERR] %s", msg)


# ── Helpers ──────────────────────────────────────────────────
def curl_check(url: str, timeout: int = 5) -> tuple[int, str]:
    """Return (status_code, body). Returns (0, "") on connection failure."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "-", "-w", "\n%{http_code}", "--connect-timeout", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        parts = result.stdout.rsplit("\n", 1)
        body = parts[0] if len(parts) > 1 else ""
        code = int(parts[-1]) if parts[-1].strip().isdigit() else 0
        return code, body
    except (subprocess.TimeoutExpired, Exception):
        return 0, ""


def kill_port(port: int) -> bool:
    """Kill all processes listening on a port. Returns True if anything was killed."""
    try:
        result = subprocess.run(
            ["lsof", "-t", f"-i:{port}"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split("\n")
        pids = [p.strip() for p in pids if p.strip()]
        if pids:
            subprocess.run(["kill", "-9"] + pids, capture_output=True, timeout=5)
            time.sleep(1)
            return True
    except Exception:
        pass
    return False


def tmux_session_exists(name: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def tmux_kill(name: str) -> None:
    subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True, timeout=5)


def tmux_start(name: str, cmd: str) -> None:
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, cmd],
        capture_output=True, timeout=5,
    )


def process_running(pattern: str) -> bool:
    """Check if a process matching the pattern is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def should_skip(service: str) -> bool:
    """Check if a service is in backoff (too many failed fix attempts)."""
    if backoff_remaining.get(service, 0) > 0:
        backoff_remaining[service] -= 1
        if backoff_remaining[service] == 0:
            fix_attempts[service] = 0
            log_warn(f"{service}: backoff expired, will retry fixes")
        else:
            return True
    return False


def record_fix_attempt(service: str) -> bool:
    """Record a fix attempt. Returns False if we should back off."""
    fix_attempts[service] = fix_attempts.get(service, 0) + 1
    if fix_attempts[service] >= MAX_FIX_ATTEMPTS:
        backoff_remaining[service] = BACKOFF_CYCLES
        log_err(f"{service}: {MAX_FIX_ATTEMPTS} fix attempts failed, backing off for {BACKOFF_CYCLES} cycles")
        return False
    return True


def reset_fix_count(service: str) -> None:
    fix_attempts[service] = 0
    backoff_remaining.pop(service, None)


# ── Check functions ──────────────────────────────────────────

def check_api() -> tuple[bool, str]:
    """Check API server on port 8000."""
    code, body = curl_check(f"http://localhost:{PORTS['api']}/health")
    if code != 200:
        return False, f"health endpoint returned {code}"

    # Verify cases endpoint returns valid JSON with case2000_texas
    code, body = curl_check(f"http://localhost:{PORTS['api']}/api/cases")
    if code != 200:
        return False, f"/api/cases returned {code}"

    try:
        cases = json.loads(body)
        body_str = json.dumps(cases)
        if "case2000_texas" not in body_str:
            return False, "case2000_texas not found in /api/cases"
    except json.JSONDecodeError:
        return False, "/api/cases returned invalid JSON"

    # Verify areas endpoint has area data
    code, body = curl_check(f"http://localhost:{PORTS['api']}/api/areas/case2000_texas")
    if code != 200:
        return False, f"/api/areas/case2000_texas returned {code}"

    try:
        areas_data = json.loads(body)
        if "areas" not in areas_data or not areas_data["areas"]:
            return False, "areas data is empty for case2000_texas"
    except json.JSONDecodeError:
        return False, "/api/areas returned invalid JSON"

    return True, ""


def check_dev_server() -> tuple[bool, str]:
    """Check dev server on port 3002."""
    code, body = curl_check(f"http://localhost:{PORTS['dev']}/app")
    if code != 200:
        return False, f"/app returned {code}"
    if "DPSpice" not in body:
        return False, "/app response does not contain 'DPSpice'"
    return True, ""


def check_git_sync() -> tuple[bool, str]:
    """Check if local main matches origin/main."""
    if not DPSPICE_DIR.is_dir():
        return True, ""  # Skip if project doesn't exist

    try:
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=DPSPICE_DIR, capture_output=True, timeout=30,
        )
        local = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=DPSPICE_DIR, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        remote = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            cwd=DPSPICE_DIR, capture_output=True, text=True, timeout=5,
        ).stdout.strip()

        if local != remote:
            # Check if local is ahead (has unpushed commits) — that's OK
            merge_base = subprocess.run(
                ["git", "merge-base", local, remote],
                cwd=DPSPICE_DIR, capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if merge_base == remote:
                # Local is ahead of remote — not a divergence issue
                return True, ""
            return False, f"local HEAD {local[:8]} != origin/main {remote[:8]}"
    except Exception as e:
        return False, f"git check failed: {e}"

    return True, ""


def check_dashboard() -> tuple[bool, str]:
    """Check dashboard on port 3003."""
    code, _ = curl_check(f"http://localhost:{PORTS['dashboard']}/")
    if code != 200:
        return False, f"dashboard returned {code}"
    return True, ""


def check_docker() -> tuple[bool, str]:
    """Check Docker container on port 3001."""
    code, _ = curl_check(f"http://localhost:{PORTS['docker']}/")
    if code != 200:
        return False, f"Docker container returned {code}"
    return True, ""


def check_worker_daemon() -> tuple[bool, str]:
    """Check if worker-daemon.sh is running."""
    if tmux_session_exists("worker-daemon"):
        return True, ""
    if process_running("worker-daemon.sh"):
        return True, ""
    return False, "worker-daemon tmux session not found"


# ── Fix functions ────────────────────────────────────────────

def fix_api() -> None:
    """Kill and restart API server."""
    log_fix("API: killing and restarting uvicorn")
    kill_port(PORTS["api"])
    tmux_kill("dpspice-api")
    time.sleep(1)

    venv_python = DPSPICE_DIR / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = Path("python3")

    cmd = (
        f"cd {DPSPICE_DIR} && "
        f"export PYTHONPATH=src/python && "
        f"{venv_python} -m uvicorn api.main:app --host 0.0.0.0 --port {PORTS['api']} "
        f"2>&1 | tee /tmp/dpspice-api.log"
    )
    tmux_start("dpspice-api", cmd)
    time.sleep(5)

    code, _ = curl_check(f"http://localhost:{PORTS['api']}/health")
    if code == 200:
        log_fix("API: restarted successfully")
        reset_fix_count("api")
    else:
        log_err("API: failed to restart")


def fix_dev_server() -> None:
    """Kill, clear .next cache, restart dev server."""
    log_fix("Dev server: killing, clearing cache, restarting")
    kill_port(PORTS["dev"])
    tmux_kill("dpspice-dev")
    time.sleep(1)

    next_cache = DPSPICE_DIR / "web" / ".next"
    if next_cache.exists():
        shutil.rmtree(next_cache, ignore_errors=True)
        log_fix("Dev server: cleared .next cache")

    cmd = (
        f"cd {DPSPICE_DIR}/web && "
        f"export PATH=/opt/homebrew/bin:$HOME/.local/bin:$HOME/.nvm/versions/node/$(ls $HOME/.nvm/versions/node/ 2>/dev/null | sort -V | tail -1)/bin:$PATH && "
        f"npm run dev -- -H 0.0.0.0 -p {PORTS['dev']} "
        f"2>&1 | tee /tmp/dpspice-dev.log"
    )
    tmux_start("dpspice-dev", cmd)
    time.sleep(15)  # Next.js takes time to compile

    code, _ = curl_check(f"http://localhost:{PORTS['dev']}/app")
    if code == 200:
        log_fix("Dev server: restarted successfully")
        reset_fix_count("dev")
    else:
        log_err("Dev server: failed to restart after cache clear")


def fix_git_sync() -> None:
    """Reset local to match origin/main."""
    log_fix("Git: resetting to origin/main")
    try:
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=DPSPICE_DIR, capture_output=True, timeout=30,
        )
        result = subprocess.run(
            ["git", "reset", "--hard", "origin/main"],
            cwd=DPSPICE_DIR, capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            log_fix("Git: reset to origin/main successful")
            reset_fix_count("git")
        else:
            log_err(f"Git: reset failed: {result.stderr.strip()}")
    except Exception as e:
        log_err(f"Git: reset failed: {e}")


def fix_dashboard() -> None:
    """Restart the fleet dashboard."""
    log_fix("Dashboard: restarting")
    kill_port(PORTS["dashboard"])
    tmux_kill("fleet-dashboard-web")
    time.sleep(1)

    api_py = HANDLER_DIR / "dashboard" / "api.py"
    if not api_py.exists():
        log_err("Dashboard: api.py not found, cannot restart")
        return

    cmd = (
        f"cd {HANDLER_DIR}/dashboard && "
        f"python3 -m uvicorn api:app --host 0.0.0.0 --port {PORTS['dashboard']}"
    )
    tmux_start("fleet-dashboard-web", cmd)
    time.sleep(3)

    code, _ = curl_check(f"http://localhost:{PORTS['dashboard']}/")
    if code == 200:
        log_fix("Dashboard: restarted successfully")
        reset_fix_count("dashboard")
    else:
        log_err("Dashboard: failed to restart")


def fix_worker_daemon() -> None:
    """Restart the worker daemon."""
    log_fix("Worker daemon: restarting")
    tmux_kill("worker-daemon")
    time.sleep(1)

    daemon_script = HANDLER_DIR / "worker-daemon.sh"
    if not daemon_script.exists():
        log_err("Worker daemon: worker-daemon.sh not found")
        return

    log_dir = FLEET_DIR / "logs"
    cmd = f"cd {HANDLER_DIR} && ./worker-daemon.sh 2>&1 | tee {log_dir}/daemon.log"
    tmux_start("worker-daemon", cmd)
    time.sleep(3)

    if tmux_session_exists("worker-daemon"):
        log_fix("Worker daemon: restarted successfully")
        reset_fix_count("worker")
    else:
        log_err("Worker daemon: failed to restart")


# ── Main cycle ───────────────────────────────────────────────

def run_cycle() -> list[tuple[str, str]]:
    """Run one health check cycle. Returns list of (service, issue) tuples."""
    issues: list[tuple[str, str]] = []

    # 1. API Server
    if not should_skip("api"):
        ok, issue = check_api()
        if not ok:
            log_warn(f"API: {issue}")
            if record_fix_attempt("api"):
                fix_api()
            issues.append(("api", issue))
        else:
            reset_fix_count("api")

    # 2. Dev Server
    if not should_skip("dev"):
        ok, issue = check_dev_server()
        if not ok:
            log_warn(f"Dev server: {issue}")
            if record_fix_attempt("dev"):
                fix_dev_server()
            issues.append(("dev", issue))
        else:
            reset_fix_count("dev")

    # 3. Git Sync
    if not should_skip("git"):
        ok, issue = check_git_sync()
        if not ok:
            log_warn(f"Git sync: {issue}")
            if record_fix_attempt("git"):
                fix_git_sync()
                # Restart dev server after code change
                log_fix("Git: triggering dev server restart after sync")
                fix_dev_server()
            issues.append(("git", issue))
        else:
            reset_fix_count("git")

    # 4. Dashboard
    if not should_skip("dashboard"):
        ok, issue = check_dashboard()
        if not ok:
            log_warn(f"Dashboard: {issue}")
            if record_fix_attempt("dashboard"):
                fix_dashboard()
            issues.append(("dashboard", issue))
        else:
            reset_fix_count("dashboard")

    # 5. Docker (warn only — no auto-fix)
    ok, issue = check_docker()
    if not ok:
        log_warn(f"Docker: {issue} (manual fix required)")
        issues.append(("docker", issue))

    # 6. Worker Daemon
    if not should_skip("worker"):
        ok, issue = check_worker_daemon()
        if not ok:
            log_warn(f"Worker daemon: {issue}")
            if record_fix_attempt("worker"):
                fix_worker_daemon()
            issues.append(("worker", issue))
        else:
            reset_fix_count("worker")

    return issues


def main() -> None:
    logger.info("=" * 60)
    logger.info("Health monitor started")
    logger.info("  API:        http://localhost:%d", PORTS["api"])
    logger.info("  Dev server: http://localhost:%d", PORTS["dev"])
    logger.info("  Dashboard:  http://localhost:%d", PORTS["dashboard"])
    logger.info("  Docker:     http://localhost:%d", PORTS["docker"])
    logger.info("  DPSpice:    %s", DPSPICE_DIR)
    logger.info("  Interval:   %ds", CHECK_INTERVAL)
    logger.info("  Log file:   %s", LOG_FILE)
    logger.info("=" * 60)

    # Graceful shutdown
    def handle_signal(sig: int, _: object) -> None:
        logger.info("Received signal %d, shutting down", sig)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    cycle_count = 0
    while True:
        cycle_count += 1
        try:
            issues = run_cycle()
            if not issues:
                # Log "all healthy" every 10 minutes (every 10 cycles at 60s)
                if cycle_count % 10 == 1:
                    log_ok("All services healthy")
            else:
                service_names = ", ".join(s for s, _ in issues)
                log_warn(f"Issues detected: {service_names}")
        except Exception as e:
            log_err(f"Cycle {cycle_count} failed: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
