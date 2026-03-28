"""Tests for dashboard/api.py endpoints.

Uses Starlette's TestClient (wraps httpx) with an in-memory SQLite DB.
No real server, no real fleet directory.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure dashboard/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import insert_task


# ── GET /api/tasks ────────────────────────────────────────


class TestGetTasks:
    def test_returns_list(self, client):
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_empty_when_no_tasks(self, client):
        resp = client.get("/api/tasks")
        assert resp.json() == []

    def test_returns_seeded_tasks(self, client, seed_tasks):
        resp = client.get("/api/tasks")
        data = resp.json()
        assert len(data) == 4
        ids = {t["id"] for t in data}
        assert "20260328-100000-alpha" in ids
        assert "20260328-110000-beta" in ids

    def test_task_fields(self, client, seed_tasks):
        resp = client.get("/api/tasks")
        task = resp.json()[0]
        for field in ("id", "slug", "status", "project_name"):
            assert field in task


# ── GET /api/system ───────────────────────────────────────


class TestGetSystem:
    def test_returns_system_info(self, client):
        resp = client.get("/api/system")
        assert resp.status_code == 200
        data = resp.json()
        assert "cpu_percent" in data
        assert "ram_total_gb" in data
        assert "uptime" in data
        assert "timestamp" in data
        assert "machine_name" in data

    def test_cpu_percent_is_number(self, client):
        data = client.get("/api/system").json()
        assert isinstance(data["cpu_percent"], (int, float))

    def test_ram_is_positive(self, client):
        data = client.get("/api/system").json()
        assert data["ram_total_gb"] > 0


# ── GET /api/review ───────────────────────────────────────


class TestGetReview:
    def test_returns_list(self, client):
        resp = client.get("/api/review")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_empty_when_no_review_items(self, client):
        assert client.get("/api/review").json() == []

    def test_parses_review_md_file(self, client, fleet_dir):
        """Write a review .md file and confirm it appears in the response."""
        review_dir = fleet_dir / "review-queue"
        review_file = review_dir / "20260328-task-completed.md"
        review_file.write_text(
            "---\n"
            "task_id: 20260328-task\n"
            "project: test-project\n"
            "type: completed\n"
            "priority: normal\n"
            f"created_at: {datetime.now().isoformat()}\n"
            "---\n"
            "## Summary\nTask completed successfully.\n"
        )
        resp = client.get("/api/review")
        items = resp.json()
        assert len(items) == 1
        assert items[0]["meta"]["task_id"] == "20260328-task"
        assert items[0]["review_category"] in ("auto_mergeable", "action_required")

    def test_filter_by_category(self, client, fleet_dir):
        review_dir = fleet_dir / "review-queue"
        (review_dir / "20260328-blocked-task.md").write_text(
            "---\n"
            "task_id: blocked-task\n"
            "project: proj\n"
            "type: blocked\n"
            "priority: high\n"
            f"created_at: {datetime.now().isoformat()}\n"
            "---\nBlocked.\n"
        )
        # blocked infers action_required
        resp = client.get("/api/review?category=action_required")
        assert len(resp.json()) == 1
        resp2 = client.get("/api/review?category=auto_mergeable")
        assert len(resp2.json()) == 0


# ── POST /api/action (skip) ──────────────────────────────


class TestActionSkip:
    def test_skip_dismisses_task(self, client, seed_tasks, fleet_dir):
        # Write a review file so skip has something to archive
        review_dir = fleet_dir / "review-queue"
        (review_dir / "20260328-100000-alpha-completed.md").write_text(
            "---\ntask_id: 20260328-100000-alpha\ntype: completed\n"
            f"created_at: {datetime.now().isoformat()}\n---\nDone.\n"
        )
        # Also write the JSON task manifest so _find_task_manifest can find it
        tasks_dir = fleet_dir / "tasks"
        task_data = {
            "id": "20260328-100000-alpha",
            "slug": "20260328-100000-alpha",
            "status": "completed",
            "branch": "worker/test",
        }
        (tasks_dir / "20260328-100000-alpha.json").write_text(
            json.dumps(task_data)
        )

        resp = client.post("/api/action", json={
            "type": "skip",
            "task_slug": "20260328-100000-alpha",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "Dismissed" in data["message"]

        # Verify the review file was archived
        archived = review_dir / "archived" / "20260328-100000-alpha-completed.md"
        assert archived.exists()

    def test_skip_updates_task_json(self, client, seed_tasks, fleet_dir):
        tasks_dir = fleet_dir / "tasks"
        task_data = {
            "id": "20260328-100000-alpha",
            "slug": "20260328-100000-alpha",
            "status": "completed",
        }
        (tasks_dir / "20260328-100000-alpha.json").write_text(
            json.dumps(task_data)
        )
        client.post("/api/action", json={
            "type": "skip",
            "task_slug": "20260328-100000-alpha",
        })
        updated = json.loads(
            (tasks_dir / "20260328-100000-alpha.json").read_text()
        )
        assert updated["status"] == "dismissed"


# ── POST /api/action (merge) ─────────────────────────────


class TestActionMerge:
    def test_merge_no_manifest_returns_error(self, client):
        resp = client.post("/api/action", json={
            "type": "merge",
            "task_slug": "nonexistent-task",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()

    def test_merge_no_branch_returns_error(self, client, fleet_dir):
        tasks_dir = fleet_dir / "tasks"
        (tasks_dir / "no-branch.json").write_text(json.dumps({
            "id": "no-branch",
            "slug": "no-branch",
            "status": "completed",
            "branch": "",
            "project_path": "/tmp/proj",
        }))
        resp = client.post("/api/action", json={
            "type": "merge",
            "task_slug": "no-branch",
        })
        data = resp.json()
        assert data["status"] == "error"
        assert "branch" in data["message"].lower() or "repo" in data["message"].lower()


# ── POST /api/action (unknown type) ──────────────────────


class TestActionUnknownType:
    def test_unknown_action_type(self, client):
        resp = client.post("/api/action", json={
            "type": "explode",
            "task_slug": "whatever",
        })
        data = resp.json()
        assert data["status"] == "error"
        assert "unknown" in data["message"].lower()

    def test_missing_type_field(self, client):
        resp = client.post("/api/action", json={"task_slug": "x"})
        # FastAPI validation error → 422
        assert resp.status_code == 422


# ── POST /api/tasks/{id}/redispatch ──────────────────────


class TestRedispatch:
    def test_redispatch_failed_task(self, client, seed_tasks, fleet_dir):
        # Write the JSON manifest for the failed task
        tasks_dir = fleet_dir / "tasks"
        task_data = {
            "id": "20260328-110000-beta",
            "slug": "20260328-110000-beta",
            "status": "failed",
            "project_name": "test-project",
            "project_path": "/tmp/test-project",
            "prompt": "fix the bug",
            "budget_usd": 5.0,
            "error_message": "build failed",
        }
        (tasks_dir / "20260328-110000-beta.json").write_text(
            json.dumps(task_data)
        )

        resp = client.post("/api/tasks/20260328-110000-beta/redispatch")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "new_task_id" in data
        assert "beta" in data["new_task_id"]

        # Verify the new JSON file was created
        new_file = tasks_dir / f"{data['new_task_id']}.json"
        assert new_file.exists()
        new_task = json.loads(new_file.read_text())
        assert new_task["status"] == "queued"
        assert new_task["original_task_id"] == "20260328-110000-beta"

    def test_redispatch_nonexistent_task(self, client):
        resp = client.post("/api/tasks/does-not-exist/redispatch")
        data = resp.json()
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()

    def test_redispatch_completed_task_rejected(self, client, fleet_dir):
        tasks_dir = fleet_dir / "tasks"
        (tasks_dir / "completed-task.json").write_text(json.dumps({
            "id": "completed-task",
            "slug": "completed-task",
            "status": "completed",
        }))
        resp = client.post("/api/tasks/completed-task/redispatch")
        data = resp.json()
        assert data["status"] == "error"
        assert "failed" in data["message"].lower() or "blocked" in data["message"].lower()


# ── GET /api/stats/analytics ─────────────────────────────


class TestAnalytics:
    def test_returns_analytics(self, client, seed_tasks):
        resp = client.get("/api/stats/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert "avg_duration_min" in data
        assert "success_rate" in data
        assert "queue_depth" in data
        assert "running" in data

    def test_analytics_empty_db(self, client):
        data = client.get("/api/stats/analytics").json()
        assert data["success_rate"] == 100.0
        assert data["queue_depth"] == 0


# ── GET /api/queue ────────────────────────────────────────


class TestGetQueue:
    def test_returns_list(self, client):
        resp = client.get("/api/queue")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_groups_by_project(self, client, seed_tasks):
        data = client.get("/api/queue").json()
        # seed_tasks has queued + running tasks for "test-project"
        projects = {item["project"] for item in data}
        assert "test-project" in projects

    def test_queue_structure(self, client, seed_tasks):
        data = client.get("/api/queue").json()
        for group in data:
            assert "project" in group
            assert "running" in group
            assert "queued" in group
            assert isinstance(group["queued"], list)


# ── GET /api/stats/task-history ──────────────────────────


class TestTaskHistory:
    def test_returns_structure(self, client, seed_tasks):
        resp = client.get("/api/stats/task-history")
        assert resp.status_code == 200
        data = resp.json()
        assert "today" in data
        assert "week" in data
        assert "month" in data
        assert isinstance(data["today"], int)


# ── GET /api/projects ────────────────────────────────────


class TestGetProjects:
    def test_empty_when_no_file(self, client):
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_projects(self, client, fleet_dir):
        projects_data = {
            "projects": [
                {"name": "alpha", "path": "/tmp/alpha", "repo": ""},
                {"name": "beta", "path": "/tmp/beta", "repo": "git@github.com:user/beta.git"},
            ]
        }
        (fleet_dir / "projects.json").write_text(json.dumps(projects_data))
        resp = client.get("/api/projects")
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "alpha"
        assert "github_url" in data[1]


# ── GET /api/logs ─────────────────────────────────────────


class TestGetLogs:
    def test_empty_logs(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_lists_summary_files(self, client, fleet_dir):
        logs_dir = fleet_dir / "logs"
        (logs_dir / "task-123.summary.md").write_text("## Summary\nDone.")
        (logs_dir / "task-123.log").write_text("line 1\nline 2\n")
        data = client.get("/api/logs").json()
        # Find the task-123 entry
        entry = next((e for e in data if e["task_id"] == "task-123"), None)
        assert entry is not None
        assert entry["has_log"] is True
        assert entry["has_summary"] is True


# ── GET /api/logs/{task_id} ──────────────────────────────


class TestGetLogDetail:
    def test_missing_log(self, client):
        resp = client.get("/api/logs/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "nonexistent"
        assert "log_tail" not in data

    def test_returns_log_content(self, client, fleet_dir):
        logs_dir = fleet_dir / "logs"
        (logs_dir / "my-task.log").write_text("log line 1\nlog line 2\n")
        (logs_dir / "my-task.summary.md").write_text("All good.")
        data = client.get("/api/logs/my-task").json()
        assert "summary" in data
        assert data["summary"] == "All good."
        assert "log_tail" in data
        assert "log line" in data["log_tail"]


# ── POST /api/action (fix, queue) ────────────────────────


class TestActionFixAndQueue:
    def test_fix_action(self, client, fleet_dir):
        resp = client.post("/api/action", json={
            "type": "fix",
            "task_slug": "broken-task",
            "description": "fix the broken thing",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # Verify action file created
        action_files = list((fleet_dir / "reply-actions").glob("*-fix-*.json"))
        assert len(action_files) == 1

    def test_queue_action(self, client, fleet_dir):
        resp = client.post("/api/action", json={
            "type": "queue",
            "task_slug": "new-task",
            "description": "something new",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        action_files = list((fleet_dir / "reply-actions").glob("*-queue-*.json"))
        assert len(action_files) == 1


# ── GET /api/events ──────────────────────────────────────


class TestGetEvents:
    def test_empty_events(self, client):
        resp = client.get("/api/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_events_with_status(self, client, fleet_dir):
        events = [
            {"title": "Deploy", "start": "2026-03-28T10:00:00Z",
             "end": "2026-03-28T12:00:00Z"},
        ]
        (fleet_dir / "events.json").write_text(json.dumps(events))
        data = client.get("/api/events").json()
        assert len(data) == 1
        assert data[0]["title"] == "Deploy"
        assert "status" in data[0]  # computed by API


# ── GET /api/backlog ─────────────────────────────────────


class TestGetBacklog:
    def test_empty_backlog(self, client):
        resp = client.get("/api/backlog")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── GET /api/stats/daily ─────────────────────────────────


class TestStatsDailyCompletions:
    def test_returns_list(self, client, seed_tasks):
        resp = client.get("/api/stats/daily?days=7")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── GET /api/stats/projects ──────────────────────────────


class TestStatsProjects:
    def test_returns_list(self, client, seed_tasks):
        resp = client.get("/api/stats/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if data:
            assert "project_name" in data[0]
            assert "count" in data[0]


# ── POST /api/db/sync ────────────────────────────────────


class TestDbSync:
    def test_sync_returns_ok(self, client):
        resp = client.post("/api/db/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "synced" in data


# ── POST /api/db/migrate ─────────────────────────────────


class TestDbMigrate:
    def test_migrate_returns_ok(self, client):
        resp = client.post("/api/db/migrate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "migrated" in data
