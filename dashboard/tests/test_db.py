"""Tests for dashboard/db.py — the fleet database layer.

Covers: schema init, migrations, CRUD, status transitions, queries,
edge cases, and concurrent writes.
"""

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import db

# insert_task_row is defined in conftest.py; pytest loads it automatically.
# We access it via a module-level import from the tests package.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from conftest import insert_task_row


# ── Schema & Connection ──────────────────────────────────


class TestConnection:
    """get_conn() and schema initialization."""

    def test_get_conn_creates_db(self, isolated_db):
        conn = db.get_conn()
        assert conn is not None
        assert db.DB_PATH.exists()

    def test_get_conn_returns_same_connection(self, isolated_db):
        c1 = db.get_conn()
        c2 = db.get_conn()
        assert c1 is c2

    def test_wal_mode_enabled(self, isolated_db):
        conn = db.get_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self, isolated_db):
        conn = db.get_conn()
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_tables_created(self, isolated_db):
        conn = db.get_conn()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "tasks" in tables
        assert "review_items" in tables
        assert "events" in tables
        assert "backlog" in tables
        assert "auto_heal_log" in tables

    def test_indexes_created(self, isolated_db):
        conn = db.get_conn()
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_tasks_status" in indexes
        assert "idx_tasks_project" in indexes
        assert "idx_tasks_finished" in indexes


# ── Schema Migration ─────────────────────────────────────


class TestMigration:
    """_migrate_schema adds columns without losing data."""

    def test_migrate_adds_missing_columns(self, isolated_db):
        """Simulate an old database missing loc_added, loc_removed, route."""
        conn = sqlite3.connect(str(db.DB_PATH))
        conn.execute("""
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
                raw_json TEXT
            )
        """)
        # Insert a row before migration
        conn.execute(
            "INSERT INTO tasks (id, status, raw_json) VALUES (?, ?, ?)",
            ("old-task", "completed", '{"id": "old-task"}'),
        )
        conn.commit()
        conn.close()

        # Now let db.py connect — it will run _init_schema + _migrate_schema
        # Reset _conn so get_conn() creates a new connection to this DB
        db._conn = None
        new_conn = db.get_conn()

        # Verify columns were added
        cols = {
            row[1]
            for row in new_conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        assert "loc_added" in cols
        assert "loc_removed" in cols
        assert "route" in cols

        # Verify existing data survived
        row = new_conn.execute(
            "SELECT id, status FROM tasks WHERE id = 'old-task'"
        ).fetchone()
        assert row is not None
        assert row["status"] == "completed"

    def test_migrate_idempotent(self, isolated_db):
        """Running migration twice doesn't fail or duplicate columns."""
        conn = db.get_conn()
        # Manually call _migrate_schema again
        db._migrate_schema(conn)
        cols = [
            row[1]
            for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        ]
        # No duplicate column names
        assert len(cols) == len(set(cols))


# ── CRUD Operations ──────────────────────────────────────


class TestCRUD:
    """insert (via helper), get_task, update_task, get_all_tasks."""

    def test_insert_and_get_task(self, isolated_db):
        insert_task_row("task-001", status="queued", project_name="alpha")
        task = db.get_task("task-001")
        assert task is not None
        assert task["id"] == "task-001"
        assert task["project_name"] == "alpha"
        assert task["status"] == "queued"

    def test_get_task_not_found(self, isolated_db):
        db.get_conn()  # ensure schema
        assert db.get_task("nonexistent") is None

    def test_get_task_partial_match(self, isolated_db):
        insert_task_row("20260328-120000-build-api")
        task = db.get_task("build-api")
        assert task is not None
        assert task["id"] == "20260328-120000-build-api"

    def test_update_task_status(self, isolated_db):
        insert_task_row("task-002", status="queued")
        result = db.update_task("task-002", {"status": "running", "started_at": "2026-03-28T12:00:00Z"})
        assert result is True
        task = db.get_task("task-002")
        assert task["status"] == "running"
        assert task["started_at"] == "2026-03-28T12:00:00Z"

    def test_update_task_not_found(self, isolated_db):
        db.get_conn()
        result = db.update_task("ghost", {"status": "running"})
        assert result is False

    def test_update_task_preserves_other_fields(self, isolated_db):
        insert_task_row("task-003", status="running", project_name="beta", branch="worker/test")
        db.update_task("task-003", {"status": "completed", "finished_at": "2026-03-28T13:00:00Z"})
        task = db.get_task("task-003")
        assert task["status"] == "completed"
        assert task["project_name"] == "beta"
        assert task["branch"] == "worker/test"

    def test_update_task_writes_raw_json(self, isolated_db):
        insert_task_row("task-004", status="queued")
        db.update_task("task-004", {"status": "completed", "pr_url": "https://github.com/pr/1"})
        conn = db.get_conn()
        row = conn.execute("SELECT raw_json FROM tasks WHERE id = ?", ("task-004",)).fetchone()
        data = json.loads(row["raw_json"])
        assert data["status"] == "completed"
        assert data["pr_url"] == "https://github.com/pr/1"

    def test_get_all_tasks_empty(self, isolated_db):
        db.get_conn()
        assert db.get_all_tasks() == []

    def test_get_all_tasks_returns_newest_first(self, isolated_db):
        insert_task_row("aaa-001")
        insert_task_row("zzz-002")
        tasks = db.get_all_tasks()
        assert len(tasks) == 2
        # Sorted by id DESC: zzz before aaa
        assert tasks[0]["id"] == "zzz-002"
        assert tasks[1]["id"] == "aaa-001"

    def test_get_tasks_by_status(self, isolated_db):
        insert_task_row("t1", status="queued")
        insert_task_row("t2", status="running")
        insert_task_row("t3", status="completed")
        insert_task_row("t4", status="queued")

        queued = db.get_tasks_by_status("queued")
        assert len(queued) == 2
        assert all(t["status"] == "queued" for t in queued)

        running = db.get_tasks_by_status("running")
        assert len(running) == 1
        assert running[0]["id"] == "t2"


# ── Status Transitions ───────────────────────────────────


class TestStatusTransitions:
    """Realistic lifecycle: queued -> running -> completed/failed."""

    def test_queued_to_running_to_completed(self, isolated_db):
        insert_task_row("lifecycle-1", status="queued", dispatched_at="2026-03-28T10:00:00Z")

        db.update_task("lifecycle-1", {
            "status": "running",
            "started_at": "2026-03-28T10:05:00Z",
        })
        task = db.get_task("lifecycle-1")
        assert task["status"] == "running"

        db.update_task("lifecycle-1", {
            "status": "completed",
            "finished_at": "2026-03-28T10:30:00Z",
            "pr_url": "https://github.com/org/repo/pull/42",
        })
        task = db.get_task("lifecycle-1")
        assert task["status"] == "completed"
        assert task["pr_url"] == "https://github.com/org/repo/pull/42"

    def test_queued_to_running_to_failed(self, isolated_db):
        insert_task_row("lifecycle-2", status="queued")

        db.update_task("lifecycle-2", {
            "status": "running",
            "started_at": "2026-03-28T11:00:00Z",
        })

        db.update_task("lifecycle-2", {
            "status": "failed",
            "finished_at": "2026-03-28T11:15:00Z",
            "error_message": "pytest failed with 3 errors",
        })
        task = db.get_task("lifecycle-2")
        assert task["status"] == "failed"
        assert task["error_message"] == "pytest failed with 3 errors"

    def test_completed_to_merged(self, isolated_db):
        insert_task_row("lifecycle-3", status="completed", finished_at="2026-03-28T12:00:00Z")
        db.update_task("lifecycle-3", {
            "status": "merged",
        })
        task = db.get_task("lifecycle-3")
        assert task["status"] == "merged"


# ── Query Functions ──────────────────────────────────────


class TestQueries:
    """get_queue_by_project, get_daily_completions, get_task_stats, get_analytics."""

    def test_get_queue_by_project(self, isolated_db):
        insert_task_row("q1", status="running", project_name="alpha", started_at="2026-03-28T10:00:00Z")
        insert_task_row("q2", status="queued", project_name="alpha", dispatched_at="2026-03-28T09:00:00Z")
        insert_task_row("q3", status="queued", project_name="beta", dispatched_at="2026-03-28T09:30:00Z")
        insert_task_row("q4", status="completed", project_name="alpha")  # should not appear

        result = db.get_queue_by_project()
        ids = [r["id"] for r in result]
        assert "q1" in ids
        assert "q2" in ids
        assert "q3" in ids
        assert "q4" not in ids
        # Running tasks come first
        assert result[0]["status"] == "running"

    def test_get_daily_completions(self, isolated_db):
        today = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        insert_task_row("dc1", status="completed", finished_at=today)
        insert_task_row("dc2", status="merged", finished_at=today)
        insert_task_row("dc3", status="failed", finished_at=today)
        insert_task_row("dc4", status="queued")  # no finished_at

        completions = db.get_daily_completions(days=7)
        assert len(completions) == 1
        day = completions[0]
        assert day["count"] == 3  # completed + merged + failed all have finished_at
        assert day["completed"] == 1
        assert day["merged"] == 1
        assert day["failed"] == 1

    def test_get_daily_completions_empty(self, isolated_db):
        db.get_conn()
        assert db.get_daily_completions() == []

    def test_get_task_stats(self, isolated_db):
        today = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        insert_task_row("ts1", status="completed", project_name="alpha", finished_at=today)
        insert_task_row("ts2", status="merged", project_name="alpha", finished_at=today)
        insert_task_row("ts3", status="completed", project_name="beta", finished_at=today)
        insert_task_row("ts4", status="failed", project_name="alpha", finished_at=today)  # not counted

        stats = db.get_task_stats()
        assert stats["today"] == 3  # ts1, ts2, ts3 (completed/merged)
        assert stats["today_by_project"]["alpha"] == 2
        assert stats["today_by_project"]["beta"] == 1
        assert stats["week"] >= 3
        assert stats["month"] >= 3

    def test_get_analytics_empty(self, isolated_db):
        db.get_conn()
        analytics = db.get_analytics()
        assert analytics["avg_duration_min"] == 0
        assert analytics["success_rate"] == 100.0
        assert analytics["queue_depth"] == 0
        assert analytics["running"] == 0

    def test_get_analytics_with_data(self, isolated_db):
        now = datetime.utcnow()
        start = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        insert_task_row("a1", status="completed", started_at=start, finished_at=end)
        insert_task_row("a2", status="failed", started_at=start, finished_at=end)
        insert_task_row("a3", status="queued")
        insert_task_row("a4", status="running", started_at=start)

        analytics = db.get_analytics()
        assert analytics["avg_duration_min"] > 0
        assert 0 < analytics["success_rate"] < 100
        assert analytics["total_finished"] == 2
        assert analytics["total_success"] == 1
        assert analytics["queue_depth"] == 1
        assert analytics["running"] == 1

    def test_get_project_breakdown(self, isolated_db):
        insert_task_row("pb1", status="completed", project_name="alpha")
        insert_task_row("pb2", status="failed", project_name="alpha")
        insert_task_row("pb3", status="running", project_name="beta")

        breakdown = db.get_project_breakdown()
        projects = {r["project_name"]: r for r in breakdown}
        assert "alpha" in projects
        assert projects["alpha"]["done"] == 1
        assert projects["alpha"]["failed"] == 1
        assert "beta" in projects
        assert projects["beta"]["active"] == 1

    def test_get_daily_throughput(self, isolated_db):
        today = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        insert_task_row("dt1", status="completed", finished_at=today)
        insert_task_row("dt2", status="merged", finished_at=today)

        throughput = db.get_daily_throughput(days=7)
        assert len(throughput) == 1
        assert throughput[0]["count"] == 2


# ── Events ───────────────────────────────────────────────


class TestEvents:
    def test_add_and_get_events(self, isolated_db):
        db.get_conn()
        event_id = db.add_event({
            "title": "Release freeze",
            "start": "2026-03-30",
            "end": "2026-04-01",
            "freeze_projects": ["alpha", "beta"],
            "notes": "Mobile release cut",
        })
        assert event_id is not None

        events = db.get_all_events()
        assert len(events) == 1
        assert events[0]["title"] == "Release freeze"
        assert events[0]["freeze_projects"] == ["alpha", "beta"]

    def test_get_events_empty(self, isolated_db):
        db.get_conn()
        assert db.get_all_events() == []


# ── Review Items ─────────────────────────────────────────


class TestReviewItems:
    def test_get_active_review_items_empty(self, isolated_db):
        db.get_conn()
        assert db.get_active_review_items() == []

    def test_archive_review_item(self, isolated_db):
        # archive_review_item also moves the file on disk for backward compat
        review_dir = db.FLEET_DIR / "review-queue"
        review_dir.mkdir(exist_ok=True)

        conn = db.get_conn()
        conn.execute(
            """INSERT INTO review_items (filename, task_id, project, type, archived)
               VALUES (?, ?, ?, ?, ?)""",
            ("task-1-completed.md", "task-1", "alpha", "completed", 0),
        )
        conn.commit()

        items = db.get_active_review_items()
        assert len(items) == 1

        filename = db.archive_review_item("task-1")
        assert filename == "task-1-completed.md"

        items = db.get_active_review_items()
        assert len(items) == 0

    def test_archive_review_item_not_found(self, isolated_db):
        db.get_conn()
        assert db.archive_review_item("nonexistent") is None


# ── Backlog ──────────────────────────────────────────────


class TestBacklog:
    def test_get_all_backlog_empty(self, isolated_db):
        db.get_conn()
        assert db.get_all_backlog() == []

    def test_get_all_backlog_sorted_by_priority(self, isolated_db):
        conn = db.get_conn()
        for i, (task_id, priority) in enumerate([("b3", 3), ("b1", 1), ("b2", 2)]):
            data = {"id": task_id, "priority": priority, "slug": task_id}
            conn.execute(
                """INSERT INTO backlog (id, slug, priority, raw_json)
                   VALUES (?, ?, ?, ?)""",
                (task_id, task_id, priority, json.dumps(data)),
            )
        conn.commit()

        backlog = db.get_all_backlog()
        assert len(backlog) == 3
        assert backlog[0]["id"] == "b1"  # priority 1 first
        assert backlog[2]["id"] == "b3"  # priority 3 last


# ── Auto Heal Log ────────────────────────────────────────


class TestAutoHealLog:
    def test_log_and_get(self, isolated_db):
        db.get_conn()
        db.log_auto_heal("BUG-001", "alpha", "restart", "success", "Restarted service")

        log = db.get_auto_heal_log(limit=10)
        assert len(log) == 1
        assert log[0]["bug_id"] == "BUG-001"
        assert log[0]["result"] == "success"

    def test_log_respects_limit(self, isolated_db):
        db.get_conn()
        for i in range(5):
            db.log_auto_heal(f"BUG-{i}", "alpha", "fix", "success")

        log = db.get_auto_heal_log(limit=3)
        assert len(log) == 3


# ── LOC Queries ──────────────────────────────────────────


class TestLOC:
    def test_get_loc_history(self, isolated_db):
        today = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        insert_task_row("loc1", status="completed", project_name="alpha",
                        finished_at=today, loc_added=100, loc_removed=20)
        insert_task_row("loc2", status="merged", project_name="beta",
                        finished_at=today, loc_added=50, loc_removed=10)

        hist = db.get_loc_history()
        assert hist["today"]["added"] == 150
        assert hist["today"]["removed"] == 30
        assert hist["today"]["net"] == 120
        assert "alpha" in hist["today"]["by_project"]
        assert hist["today"]["by_project"]["alpha"]["added"] == 100

    def test_get_project_loc_from_tasks(self, isolated_db):
        today = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        insert_task_row("ploc1", status="completed", project_name="gamma",
                        finished_at=today, loc_added=200, loc_removed=50)
        insert_task_row("ploc2", status="completed", project_name="gamma",
                        finished_at=today, loc_added=100, loc_removed=25)

        result = db.get_project_loc_from_tasks()
        assert len(result) == 1
        assert result[0]["project_name"] == "gamma"
        assert result[0]["total_added"] == 300
        assert result[0]["total_removed"] == 75
        assert result[0]["task_count"] == 2


# ── JSON Migration ───────────────────────────────────────


class TestJSONMigration:
    """migrate_tasks() reads JSON files from tasks/ directory."""

    def test_migrate_tasks_from_json(self, isolated_db):
        tasks_dir = db.FLEET_DIR / "tasks"
        tasks_dir.mkdir()

        data = {
            "id": "json-task-1",
            "slug": "json-task-1",
            "branch": "worker/json-task",
            "project_name": "delta",
            "project_path": "/tmp/delta",
            "status": "completed",
            "dispatched_at": "2026-03-28T08:00:00Z",
            "started_at": "2026-03-28T08:05:00Z",
            "finished_at": "2026-03-28T08:30:00Z",
            "base_branch": "main",
            "prompt": "Build the thing",
            "pr_url": "https://github.com/org/delta/pull/5",
        }
        (tasks_dir / "json-task-1.json").write_text(json.dumps(data))

        count = db.migrate_tasks()
        assert count == 1

        task = db.get_task("json-task-1")
        assert task is not None
        assert task["project_name"] == "delta"
        assert task["status"] == "completed"

    def test_migrate_tasks_skips_invalid_json(self, isolated_db):
        tasks_dir = db.FLEET_DIR / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "bad.json").write_text("not valid json{{{")

        count = db.migrate_tasks()
        assert count == 0

    def test_migrate_tasks_no_directory(self, isolated_db):
        db.get_conn()
        count = db.migrate_tasks()
        assert count == 0

    def test_migrate_does_not_downgrade_status(self, isolated_db):
        """If DB has 'completed' but JSON has 'queued', don't overwrite."""
        insert_task_row("conflict-task", status="completed")

        tasks_dir = db.FLEET_DIR / "tasks"
        tasks_dir.mkdir()
        stale = {"id": "conflict-task", "status": "queued", "slug": "conflict-task"}
        (tasks_dir / "conflict-task.json").write_text(json.dumps(stale))

        db.migrate_tasks()
        task = db.get_task("conflict-task")
        assert task["status"] == "completed"  # not overwritten


# ── Edge Cases ───────────────────────────────────────────


class TestEdgeCases:
    def test_duplicate_task_id(self, isolated_db):
        """Inserting the same ID twice via migrate should upsert, not crash."""
        tasks_dir = db.FLEET_DIR / "tasks"
        tasks_dir.mkdir()

        data = {"id": "dup-1", "slug": "dup-1", "status": "running", "project_name": "x"}
        (tasks_dir / "dup-1.json").write_text(json.dumps(data))
        db.migrate_tasks()

        # Update to a more advanced status
        data["status"] = "completed"
        data["finished_at"] = "2026-03-28T12:00:00Z"
        (tasks_dir / "dup-1.json").write_text(json.dumps(data))
        db.migrate_tasks()

        task = db.get_task("dup-1")
        assert task["status"] == "completed"

    def test_empty_database_queries(self, isolated_db):
        """All query functions should return gracefully on empty DB."""
        db.get_conn()
        assert db.get_all_tasks() == []
        assert db.get_tasks_by_status("queued") == []
        assert db.get_task("anything") is None
        assert db.get_active_review_items() == []
        assert db.get_all_events() == []
        assert db.get_all_backlog() == []
        assert db.get_daily_completions() == []
        assert db.get_queue_by_project() == []
        assert db.get_auto_heal_log() == []

        stats = db.get_task_stats()
        assert stats["today"] == 0
        assert stats["week"] == 0
        assert stats["month"] == 0

        analytics = db.get_analytics()
        assert analytics["avg_duration_min"] == 0
        assert analytics["success_rate"] == 100.0

    def test_unicode_in_task_names(self, isolated_db):
        insert_task_row("unicode-1", slug="빌드-테스트-🚀", project_name="프로젝트-알파")

        task = db.get_task("unicode-1")
        assert task is not None
        assert task["slug"] == "빌드-테스트-🚀"
        assert task["project_name"] == "프로젝트-알파"

    def test_very_long_prompt(self, isolated_db):
        """Tasks with very long prompts should store and retrieve correctly."""
        long_prompt = "x" * 50000
        conn = db.get_conn()
        data = {"id": "long-1", "slug": "long-1", "prompt": long_prompt, "status": "queued"}
        conn.execute(
            "INSERT INTO tasks (id, slug, status, prompt, raw_json) VALUES (?, ?, ?, ?, ?)",
            ("long-1", "long-1", "queued", long_prompt, json.dumps(data)),
        )
        conn.commit()

        task = db.get_task("long-1")
        assert task is not None
        assert task["prompt"] == long_prompt

    def test_missing_fields_in_raw_json(self, isolated_db):
        """get_task should handle raw_json with minimal fields."""
        conn = db.get_conn()
        minimal = {"id": "minimal-1"}
        conn.execute(
            "INSERT INTO tasks (id, status, raw_json) VALUES (?, ?, ?)",
            ("minimal-1", "queued", json.dumps(minimal)),
        )
        conn.commit()

        task = db.get_task("minimal-1")
        assert task is not None
        assert task["id"] == "minimal-1"

    def test_null_budget(self, isolated_db):
        insert_task_row("null-budget", budget_usd=None)
        task = db.get_task("null-budget")
        assert task is not None
        assert task.get("budget_usd") is None

    def test_update_task_with_unknown_column(self, isolated_db):
        """update_task should store unknown keys in raw_json but not crash."""
        insert_task_row("extra-1", status="queued")
        result = db.update_task("extra-1", {"status": "running", "custom_field": "value"})
        assert result is True

        task = db.get_task("extra-1")
        assert task["custom_field"] == "value"  # stored in raw_json
        assert task["status"] == "running"

    def test_get_all_tasks_with_corrupted_raw_json(self, isolated_db):
        """Tasks with invalid raw_json should be silently skipped."""
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO tasks (id, status, raw_json, route) VALUES (?, ?, ?, ?)",
            ("bad-json", "queued", "NOT-JSON{{{", ""),
        )
        insert_task_row("good-task")
        conn.commit()

        tasks = db.get_all_tasks()
        # bad-json skipped, good-task returned
        assert len(tasks) == 1
        assert tasks[0]["id"] == "good-task"


# ── Concurrent Writes ────────────────────────────────────


class TestConcurrency:
    """WAL mode allows concurrent reads/writes without locking."""

    def test_concurrent_updates(self, isolated_db):
        """Two threads updating different tasks should not conflict."""
        insert_task_row("conc-1", status="queued")
        insert_task_row("conc-2", status="queued")

        errors = []

        def update_task(task_id, new_status):
            try:
                # Each thread needs its own connection in WAL mode
                conn = sqlite3.connect(str(db.DB_PATH), check_same_thread=False)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.row_factory = sqlite3.Row

                row = conn.execute(
                    "SELECT raw_json FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                data = json.loads(row["raw_json"])
                data["status"] = new_status

                conn.execute(
                    "UPDATE tasks SET status = ?, raw_json = ? WHERE id = ?",
                    (new_status, json.dumps(data), task_id),
                )
                conn.commit()
                conn.close()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=update_task, args=("conc-1", "running"))
        t2 = threading.Thread(target=update_task, args=("conc-2", "running"))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert errors == [], f"Concurrent updates failed: {errors}"

        task1 = db.get_task("conc-1")
        task2 = db.get_task("conc-2")
        assert task1["status"] == "running"
        assert task2["status"] == "running"

    def test_concurrent_same_task(self, isolated_db):
        """Two threads updating the SAME task — last writer wins, no crash."""
        insert_task_row("conc-same", status="queued")
        errors = []

        def update_to(status, delay=0):
            try:
                time.sleep(delay)
                conn = sqlite3.connect(str(db.DB_PATH), check_same_thread=False)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                row = conn.execute(
                    "SELECT raw_json FROM tasks WHERE id = 'conc-same'"
                ).fetchone()
                data = json.loads(row[0])
                data["status"] = status
                conn.execute(
                    "UPDATE tasks SET status = ?, raw_json = ? WHERE id = 'conc-same'",
                    (status, json.dumps(data)),
                )
                conn.commit()
                conn.close()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=update_to, args=("running", 0))
        t2 = threading.Thread(target=update_to, args=("completed", 0.01))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert errors == [], f"Concurrent same-task updates failed: {errors}"

        task = db.get_task("conc-same")
        # We don't assert which status won — just that it didn't crash
        # and the task is in a valid state
        assert task["status"] in ("running", "completed")


# ── Timeline & Costs ─────────────────────────────────────


class TestTimelineAndCosts:
    def test_get_task_timeline(self, isolated_db):
        now = datetime.utcnow()
        start = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        insert_task_row("tl1", status="completed", project_name="alpha",
                        started_at=start, finished_at=end, dispatched_at=start)

        timeline = db.get_task_timeline(hours=24)
        assert len(timeline) >= 1
        found = [t for t in timeline if t["id"] == "tl1"]
        assert len(found) == 1
        assert found[0]["duration_minutes"] > 0

    def test_get_daily_costs(self, isolated_db):
        today = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        insert_task_row("cost1", status="completed", project_name="alpha",
                        finished_at=today, budget_usd=1.50)
        insert_task_row("cost2", status="completed", project_name="alpha",
                        finished_at=today, budget_usd=2.00)

        costs = db.get_daily_costs(days=7)
        assert len(costs) >= 1
        alpha = [c for c in costs if c["project_name"] == "alpha"]
        assert alpha[0]["total_budget"] == 3.50
        assert alpha[0]["task_count"] == 2

    def test_get_recent_completions(self, isolated_db):
        now = datetime.utcnow()
        start = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        insert_task_row("rc1", status="completed", started_at=start, finished_at=end)

        recent = db.get_recent_completions(limit=5)
        assert len(recent) == 1
        assert recent[0]["id"] == "rc1"
        assert recent[0]["duration_minutes"] > 0
        assert "ago" in recent[0]["time_ago"]

    def test_get_cumulative_completions(self, isolated_db):
        today = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        insert_task_row("cc1", status="completed", project_name="alpha", finished_at=today)
        insert_task_row("cc2", status="merged", project_name="beta", finished_at=today)

        result = db.get_cumulative_completions(days=14)
        assert len(result) == 2
        projects = {r["project_name"] for r in result}
        assert "alpha" in projects
        assert "beta" in projects


# ── Run Migration (all) ──────────────────────────────────


class TestRunMigration:
    def test_run_migration_returns_counts(self, isolated_db):
        # Create a JSON task file to be migrated
        tasks_dir = db.FLEET_DIR / "tasks"
        tasks_dir.mkdir()
        data = {"id": "rm-1", "status": "queued", "slug": "rm-1"}
        (tasks_dir / "rm-1.json").write_text(json.dumps(data))

        results = db.run_migration()
        assert isinstance(results, dict)
        assert results["tasks"] == 1
        assert "review_items" in results
        assert "events" in results
        assert "backlog" in results

    def test_run_migration_idempotent(self, isolated_db):
        db.get_conn()
        r1 = db.run_migration()
        r2 = db.run_migration()
        # Running twice should not crash or duplicate
        assert isinstance(r2, dict)
