"""Shared fixtures for dashboard API tests.

Creates an isolated temp directory that mimics ~/.claude-fleet/ so tests
never touch the real fleet state.  Patches db.py and api.py to use it.
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture()
def fleet_dir(tmp_path):
    """Create a temporary fleet directory with standard subdirectories."""
    for subdir in ("tasks", "review-queue", "logs", "secrets", "reply-actions"):
        (tmp_path / subdir).mkdir()
    return tmp_path


@pytest.fixture()
def test_db(fleet_dir):
    """Create a fresh SQLite database in the temp fleet dir."""
    db_path = fleet_dir / "fleet.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            slug TEXT,
            branch TEXT,
            project_name TEXT,
            project_path TEXT,
            subdir TEXT,
            dispatched_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            merged_at TEXT,
            status TEXT DEFAULT 'queued',
            base_branch TEXT DEFAULT 'main',
            prompt TEXT,
            prompt_file TEXT,
            budget_usd REAL,
            permission_mode TEXT,
            tmux_session TEXT,
            pr_url TEXT,
            merged_into TEXT,
            error_message TEXT,
            loc_added INTEGER DEFAULT 0,
            loc_removed INTEGER DEFAULT 0,
            raw_json TEXT,
            route TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS review_items (
            filename TEXT PRIMARY KEY,
            task_id TEXT,
            project TEXT,
            type TEXT,
            priority TEXT DEFAULT 'normal',
            created_at TEXT,
            review_category TEXT,
            body TEXT,
            summary TEXT,
            branch TEXT,
            pr_status TEXT DEFAULT 'unknown',
            archived INTEGER DEFAULT 0,
            archived_at TEXT,
            raw_yaml TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT NOT NULL,
            freeze_projects TEXT,
            freeze_from TEXT,
            freeze_until TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS backlog (
            id TEXT PRIMARY KEY,
            slug TEXT,
            priority INTEGER DEFAULT 0,
            project_name TEXT,
            project_path TEXT,
            prompt TEXT,
            budget_usd REAL,
            estimated_minutes INTEGER,
            category TEXT,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS auto_heal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now')),
            bug_id TEXT,
            project TEXT,
            action TEXT,
            result TEXT,
            details TEXT
        );
    """)
    conn.commit()
    return conn


def insert_task(conn, task_id, *, status="completed", project="test-project",
                started_at=None, finished_at=None, branch="worker/test",
                pr_url="", error_message="", prompt="do something",
                budget_usd=5.0):
    """Helper to insert a task into the test database."""
    now = datetime.now().isoformat()
    started_at = started_at or now
    finished_at = finished_at or (now if status not in ("queued", "running") else "")
    raw = {
        "id": task_id,
        "slug": task_id,
        "status": status,
        "project_name": project,
        "project_path": f"/tmp/{project}",
        "branch": branch,
        "dispatched_at": now,
        "started_at": started_at,
        "finished_at": finished_at,
        "pr_url": pr_url,
        "error_message": error_message,
        "prompt": prompt,
        "budget_usd": budget_usd,
    }
    conn.execute("""
        INSERT INTO tasks (id, slug, branch, project_name, project_path,
            dispatched_at, started_at, finished_at, status, prompt,
            budget_usd, pr_url, error_message, raw_json, route)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
    """, (
        task_id, task_id, branch, project, f"/tmp/{project}",
        now, started_at, finished_at, status, prompt,
        budget_usd, pr_url, error_message, json.dumps(raw),
    ))
    conn.commit()
    return raw


@pytest.fixture()
def seed_tasks(test_db):
    """Insert a small set of tasks for testing."""
    insert_task(test_db, "20260328-100000-alpha", status="completed")
    insert_task(test_db, "20260328-110000-beta", status="failed",
                error_message="build failed")
    insert_task(test_db, "20260328-120000-gamma", status="queued",
                started_at="", finished_at="")
    insert_task(test_db, "20260328-130000-delta", status="running",
                finished_at="")
    return test_db


@pytest.fixture()
def client(fleet_dir, test_db, monkeypatch):
    """Return a Starlette TestClient wired to the temp fleet dir + DB."""
    # Ensure dashboard/ is on sys.path so `import db` works
    dashboard_dir = str(Path(__file__).resolve().parent.parent)
    if dashboard_dir not in sys.path:
        sys.path.insert(0, dashboard_dir)

    # Patch db module's connection and paths BEFORE importing api
    import db as db_mod
    monkeypatch.setattr(db_mod, "_conn", test_db)
    monkeypatch.setattr(db_mod, "DB_PATH", fleet_dir / "fleet.db")
    monkeypatch.setattr(db_mod, "FLEET_DIR", fleet_dir)

    import api as api_mod
    monkeypatch.setattr(api_mod, "FLEET_DIR", fleet_dir)
    monkeypatch.setattr(api_mod, "TASKS_DIR", fleet_dir / "tasks")
    monkeypatch.setattr(api_mod, "REVIEW_DIR", fleet_dir / "review-queue")
    monkeypatch.setattr(api_mod, "LOGS_DIR", fleet_dir / "logs")
    monkeypatch.setattr(api_mod, "PROJECTS_FILE", fleet_dir / "projects.json")
    monkeypatch.setattr(api_mod, "WORKERS_FILE", fleet_dir / "workers.json")
    monkeypatch.setattr(api_mod, "EVENTS_FILE", fleet_dir / "events.json")
    monkeypatch.setattr(api_mod, "REPLY_ACTIONS_DIR", fleet_dir / "reply-actions")
    monkeypatch.setattr(api_mod, "SECRETS_DIR", fleet_dir / "secrets")
    monkeypatch.setattr(api_mod, "_machine_identity_cache", None)

    from starlette.testclient import TestClient
    with TestClient(api_mod.app, raise_server_exceptions=False) as tc:
        yield tc
