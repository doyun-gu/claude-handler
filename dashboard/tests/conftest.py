"""Fixtures for dashboard database tests.

Each test gets a fresh temporary directory and SQLite database,
completely isolated from the production fleet.db.
"""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Provide each test with a fresh, isolated database.

    Patches db module globals so no test ever touches ~/.claude-fleet/.
    Yields the tmp_path for tests that need to write JSON/MD fixture files.
    """
    fleet_dir = tmp_path / ".claude-fleet"
    fleet_dir.mkdir()
    db_path = fleet_dir / "fleet.db"

    # Reset module state
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "FLEET_DIR", fleet_dir)
    monkeypatch.setattr(db, "DB_PATH", db_path)

    yield tmp_path

    # Close connection so temp files can be cleaned up
    if db._conn is not None:
        db._conn.close()
        monkeypatch.setattr(db, "_conn", None)


def insert_task_row(
    task_id: str,
    *,
    status: str = "queued",
    project_name: str = "test-project",
    slug: str = "",
    branch: str = "",
    dispatched_at: str = "",
    started_at: str = "",
    finished_at: str = "",
    pr_url: str = "",
    error_message: str = "",
    budget_usd: float = None,
    loc_added: int = 0,
    loc_removed: int = 0,
    route: str = "",
    extra: dict = None,
) -> dict:
    """Insert a task directly into the database. Returns the raw_json dict."""
    conn = db.get_conn()
    data = {
        "id": task_id,
        "slug": slug or task_id,
        "branch": branch,
        "project_name": project_name,
        "project_path": f"/tmp/{project_name}",
        "status": status,
        "dispatched_at": dispatched_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "pr_url": pr_url,
        "error_message": error_message,
        "budget_usd": budget_usd,
        "loc_added": loc_added,
        "loc_removed": loc_removed,
        "route": route,
    }
    if extra:
        data.update(extra)

    conn.execute(
        """
        INSERT INTO tasks (
            id, slug, branch, project_name, project_path,
            dispatched_at, started_at, finished_at,
            status, prompt, budget_usd, loc_added, loc_removed,
            pr_url, error_message, raw_json, route
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            data["slug"],
            branch,
            project_name,
            data["project_path"],
            dispatched_at,
            started_at,
            finished_at,
            status,
            f"Do something for {task_id}",
            budget_usd,
            loc_added,
            loc_removed,
            pr_url,
            error_message,
            json.dumps(data),
            route,
        ),
    )
    conn.commit()
    return data
