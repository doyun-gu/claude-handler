"""Tests for task-db.py — the fleet daemon's SQLite task database."""

import json
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch


# ── Helpers ──────────────────────────────────────────────────

def make_manifest(task_id, **overrides):
    """Build a minimal task JSON manifest dict."""
    base = {
        "id": task_id,
        "slug": overrides.pop("slug", task_id),
        "branch": overrides.pop("branch", f"worker/{task_id}"),
        "project_name": overrides.pop("project_name", "test-project"),
        "project_path": overrides.pop("project_path", "/tmp/test-project"),
        "status": overrides.pop("status", "queued"),
        "prompt": overrides.pop("prompt", f"Do {task_id}"),
        "priority": overrides.pop("priority", 0),
        "depends_on": overrides.pop("depends_on", []),
    }
    base.update(overrides)
    return base


def write_manifest(tasks_dir, manifest):
    """Write a manifest dict as a JSON file and return the path."""
    path = tasks_dir / f"{manifest['id']}.json"
    path.write_text(json.dumps(manifest))
    return str(path)


# ── Task Registration ────────────────────────────────────────

class TestTaskRegistration:
    def test_add_task_stores_all_fields(self, task_db):
        m = make_manifest("reg-1", priority=5, budget_usd=10.0)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

        task = task_db.get_task("reg-1")
        assert task is not None
        assert task["id"] == "reg-1"
        assert task["slug"] == "reg-1"
        assert task["branch"] == "worker/reg-1"
        assert task["project_name"] == "test-project"
        assert task["project_path"] == "/tmp/test-project"
        assert task["status"] == "queued"
        assert task["prompt"] == "Do reg-1"
        assert task["priority"] == 5
        assert task["budget_usd"] == 10.0

    def test_add_task_defaults(self, task_db):
        m = {"id": "reg-2", "slug": "reg-2", "branch": "b", "project_name": "p", "project_path": "/p"}
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

        task = task_db.get_task("reg-2")
        assert task["budget_usd"] == 5.0
        assert task["max_turns"] == 200
        assert task["max_retries"] == 3
        assert task["priority"] == 0

    def test_add_task_reads_prompt_file(self, task_db):
        prompt_file = task_db._test_tasks_dir / "my-prompt.prompt"
        prompt_file.write_text("Build the feature\nWith details")

        m = {"id": "reg-3", "slug": "reg-3", "branch": "b", "project_name": "p",
             "project_path": "/p", "prompt_file": "my-prompt.prompt"}
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

        task = task_db.get_task("reg-3")
        assert task["prompt"] == "Build the feature\nWith details"

    def test_add_task_with_depends_on(self, task_db):
        m = make_manifest("reg-4", depends_on=["dep-a", "dep-b"])
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

        task = task_db.get_task("reg-4")
        assert json.loads(task["depends_on"]) == ["dep-a", "dep-b"]

    def test_add_task_replace_existing(self, task_db):
        """INSERT OR REPLACE should update an existing task."""
        m = make_manifest("reg-5", prompt="version 1")
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

        m2 = make_manifest("reg-5", prompt="version 2")
        path2 = write_manifest(task_db._test_tasks_dir, m2)
        task_db.add_from_json(path2)

        task = task_db.get_task("reg-5")
        assert task["prompt"] == "version 2"


# ── Atomic Claiming ──────────────────────────────────────────

class TestAtomicClaiming:
    def _insert_task(self, task_db, task_id, **kw):
        m = make_manifest(task_id, **kw)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

    def test_claim_returns_highest_priority(self, task_db):
        self._insert_task(task_db, "c-low", priority=1)
        self._insert_task(task_db, "c-high", priority=10)
        self._insert_task(task_db, "c-mid", priority=5)

        claimed = task_db.claim_next_for_daemon()
        assert claimed["id"] == "c-high"

    def test_claim_sets_running(self, task_db):
        self._insert_task(task_db, "c-1")
        claimed = task_db.claim_next_for_daemon()
        assert claimed is not None

        task = task_db.get_task("c-1")
        assert task["status"] == "running"
        assert task["started_at"] is not None

    def test_claim_empty_queue_returns_none(self, task_db):
        assert task_db.claim_next_for_daemon() is None

    def test_claim_skips_same_project_running(self, task_db):
        """Only one task per project should run at a time."""
        self._insert_task(task_db, "c-2a", project_name="proj-A")
        self._insert_task(task_db, "c-2b", project_name="proj-A")
        self._insert_task(task_db, "c-2c", project_name="proj-B")

        first = task_db.claim_next_for_daemon()
        assert first["project_name"] == "proj-A"

        second = task_db.claim_next_for_daemon()
        assert second["project_name"] == "proj-B"

        # No more claimable — proj-A is running, proj-B is running
        third = task_db.claim_next_for_daemon()
        assert third is None

    def test_claim_respects_blocked_projects(self, task_db):
        self._insert_task(task_db, "c-3a", project_name="blocked-proj")
        self._insert_task(task_db, "c-3b", project_name="ok-proj")

        claimed = task_db.claim_next_for_daemon(blocked_projects={"blocked-proj"})
        assert claimed["id"] == "c-3b"

    def test_claim_respects_max_parallel(self, task_db):
        for i in range(5):
            self._insert_task(task_db, f"par-{i}", project_name=f"proj-{i}")

        # Claim up to max_parallel=2
        task_db.claim_next_for_daemon(max_parallel=2)
        task_db.claim_next_for_daemon(max_parallel=2)
        third = task_db.claim_next_for_daemon(max_parallel=2)
        assert third is None

    def test_concurrent_claim_only_one_wins(self, task_db):
        """Simulate two threads racing to claim the same task."""
        self._insert_task(task_db, "race-1", project_name="race-proj")

        results = []
        errors = []

        def claim_worker():
            try:
                result = task_db.claim_next_for_daemon()
                results.append(result)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=claim_worker)
        t2 = threading.Thread(target=claim_worker)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Exactly one should have claimed, the other gets None
        claimed = [r for r in results if r is not None]
        nones = [r for r in results if r is None]
        assert len(claimed) == 1, f"Expected exactly 1 claim, got {len(claimed)}"
        assert len(nones) + len(errors) >= 1

    def test_claim_task_basic(self, task_db):
        """Test the simpler claim_task function."""
        self._insert_task(task_db, "ct-1")
        claimed = task_db.claim_task()
        assert claimed is not None
        assert claimed["id"] == "ct-1"
        assert task_db.get_task("ct-1")["status"] == "running"


# ── Status Updates ───────────────────────────────────────────

class TestStatusUpdates:
    def _add_and_claim(self, task_db, task_id, **kw):
        m = make_manifest(task_id, **kw)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)
        task_db.claim_next_for_daemon()
        return task_db.get_task(task_id)

    def test_queued_to_running(self, task_db):
        task = self._add_and_claim(task_db, "st-1")
        assert task["status"] == "running"

    def test_running_to_completed(self, task_db):
        self._add_and_claim(task_db, "st-2")
        task_db.update_status("st-2", "completed", pr_url="https://github.com/pr/1")

        task = task_db.get_task("st-2")
        assert task["status"] == "completed"
        assert task["finished_at"] is not None
        assert task["pr_url"] == "https://github.com/pr/1"

    def test_running_to_failed(self, task_db):
        self._add_and_claim(task_db, "st-3")
        task_db.update_status("st-3", "failed", error_message="segfault")

        task = task_db.get_task("st-3")
        assert task["status"] == "failed"
        assert task["finished_at"] is not None
        assert task["error_message"] == "segfault"

    def test_update_cost_and_eval_fields(self, task_db):
        self._add_and_claim(task_db, "st-4")
        task_db.update_status("st-4", "completed",
                              cost_usd=2.50,
                              eval_result="pass",
                              eval_rounds=3,
                              eval_score=95,
                              eval_cost_usd=0.50,
                              route="fast",
                              loc_added=100,
                              loc_removed=20)

        task = task_db.get_task("st-4")
        assert task["cost_usd"] == 2.50
        assert task["eval_result"] == "pass"
        assert task["eval_rounds"] == 3
        assert task["eval_score"] == 95
        assert task["eval_cost_usd"] == 0.50
        assert task["route"] == "fast"
        assert task["loc_added"] == 100
        assert task["loc_removed"] == 20

    def test_update_pid_and_pgid(self, task_db):
        self._add_and_claim(task_db, "st-5")
        task_db.update_status("st-5", "running", pid=12345, pgid=12340)

        task = task_db.get_task("st-5")
        assert task["pid"] == 12345
        assert task["pgid"] == 12340

    def test_update_ignores_unknown_kwargs(self, task_db):
        self._add_and_claim(task_db, "st-6")
        # Should not raise — unknown keys are silently ignored
        task_db.update_status("st-6", "completed", unknown_field="ignored")
        assert task_db.get_task("st-6")["status"] == "completed"


# ── Heartbeat ────────────────────────────────────────────────

class TestHeartbeat:
    def _add_running(self, task_db, task_id, **kw):
        m = make_manifest(task_id, **kw)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)
        task_db.claim_next_for_daemon()

    def test_heartbeat_updates_task(self, task_db):
        self._add_running(task_db, "hb-1")
        task_db.record_heartbeat("hb-1", log_size=1024, pid_alive=True)

        task = task_db.get_task("hb-1")
        assert task["last_heartbeat"] is not None
        assert task["last_log_size"] == 1024

    def test_heartbeat_creates_history(self, task_db):
        self._add_running(task_db, "hb-2")
        task_db.record_heartbeat("hb-2", log_size=100)
        task_db.record_heartbeat("hb-2", log_size=200)
        task_db.record_heartbeat("hb-2", log_size=300)

        db = task_db.get_db(readonly=True)
        beats = db.execute(
            "SELECT log_size FROM heartbeats WHERE task_id = 'hb-2' ORDER BY checked_at"
        ).fetchall()
        db.close()
        assert [b["log_size"] for b in beats] == [100, 200, 300]

    def test_stale_task_detection(self, task_db):
        """A running task with old heartbeat and dead PID should be stuck."""
        self._add_running(task_db, "hb-3")

        # Set heartbeat to 30 minutes ago
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        db = task_db.get_db()
        db.execute(
            "UPDATE tasks SET last_heartbeat = ? WHERE id = 'hb-3'", (old_time,)
        )
        db.commit()
        db.close()

        # Mock _is_project_process_alive to return False
        with patch.object(task_db, "_is_project_process_alive", return_value=False):
            stuck = task_db.find_stuck(minutes=10)
        assert len(stuck) == 1
        assert stuck[0]["id"] == "hb-3"
        assert "no heartbeat" in stuck[0]["reason"]

    def test_alive_process_not_stuck(self, task_db):
        """A task with a live PID should never be flagged as stuck."""
        self._add_running(task_db, "hb-4")

        # Set heartbeat to 30 minutes ago (would normally be stuck)
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        db = task_db.get_db()
        db.execute(
            "UPDATE tasks SET last_heartbeat = ? WHERE id = 'hb-4'", (old_time,)
        )
        db.commit()
        db.close()

        with patch.object(task_db, "_is_project_process_alive", return_value=True):
            stuck = task_db.find_stuck(minutes=10)
        assert len(stuck) == 0

    def test_frozen_log_detected_as_stuck(self, task_db):
        """Two heartbeats with same log size = frozen log = stuck."""
        self._add_running(task_db, "hb-5")

        # Record two heartbeats with identical log sizes
        task_db.record_heartbeat("hb-5", log_size=5000)
        task_db.record_heartbeat("hb-5", log_size=5000)

        with patch.object(task_db, "_is_project_process_alive", return_value=False):
            stuck = task_db.find_stuck(minutes=10)
        # Task has a recent heartbeat so it might not be flagged via time check.
        # But frozen log should catch it.
        frozen = [s for s in stuck if "frozen" in s.get("reason", "")]
        assert len(frozen) == 1


# ── Dependencies ─────────────────────────────────────────────

class TestDependencies:
    def _insert(self, task_db, task_id, **kw):
        m = make_manifest(task_id, **kw)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

    def test_task_with_unmet_deps_not_claimed(self, task_db):
        self._insert(task_db, "dep-parent", priority=1)
        self._insert(task_db, "dep-child", priority=10, depends_on=["dep-parent"])

        # Child has higher priority but depends on parent
        claimed = task_db.claim_next_for_daemon()
        assert claimed["id"] == "dep-parent"

    def test_task_claimed_after_deps_completed(self, task_db):
        self._insert(task_db, "dep-a")
        self._insert(task_db, "dep-b", depends_on=["dep-a"])

        # Claim and complete dep-a
        task_db.claim_next_for_daemon()
        task_db.update_status("dep-a", "completed")

        # Now dep-b should be claimable
        claimed = task_db.claim_next_for_daemon()
        assert claimed is not None
        assert claimed["id"] == "dep-b"

    def test_merged_status_satisfies_deps(self, task_db):
        """A 'merged' task should satisfy dependencies too."""
        self._insert(task_db, "dep-m")
        self._insert(task_db, "dep-after-m", depends_on=["dep-m"])

        task_db.claim_next_for_daemon()
        task_db.update_status("dep-m", "merged")

        claimed = task_db.claim_next_for_daemon()
        assert claimed["id"] == "dep-after-m"

    def test_deps_by_id_and_slug(self, task_db):
        """Dependencies can reference either task id or slug."""
        self._insert(task_db, "dep-by-slug", slug="my-slug")
        self._insert(task_db, "dep-waiter", depends_on=["my-slug"])

        task_db.claim_next_for_daemon()
        task_db.update_status("dep-by-slug", "completed")

        claimed = task_db.claim_next_for_daemon()
        assert claimed["id"] == "dep-waiter"

    def test_multiple_deps_all_must_complete(self, task_db):
        self._insert(task_db, "multi-a", project_name="p1")
        self._insert(task_db, "multi-b", project_name="p2")
        self._insert(task_db, "multi-c", depends_on=["multi-a", "multi-b"], project_name="p3")

        # Claim and complete only one dep
        task_db.claim_next_for_daemon()
        task_db.update_status("multi-a", "completed")
        task_db.claim_next_for_daemon()  # claims multi-b

        # multi-c can't be claimed yet (multi-b is running, not completed)
        third = task_db.claim_next_for_daemon()
        assert third is None

        # Complete multi-b
        task_db.update_status("multi-b", "completed")
        claimed = task_db.claim_next_for_daemon()
        assert claimed["id"] == "multi-c"

    def test_claim_task_basic_deps(self, task_db):
        """The simpler claim_task also checks dependencies."""
        self._insert(task_db, "ct-dep-parent")
        self._insert(task_db, "ct-dep-child", depends_on=["ct-dep-parent"])

        claimed = task_db.claim_task()
        assert claimed["id"] == "ct-dep-parent"


# ── Listing & Querying ───────────────────────────────────────

class TestListing:
    def _insert(self, task_db, task_id, **kw):
        m = make_manifest(task_id, **kw)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

    def test_list_all_tasks(self, task_db):
        for i in range(3):
            self._insert(task_db, f"list-{i}")
        tasks = task_db.list_tasks()
        assert len(tasks) == 3

    def test_list_by_status(self, task_db):
        self._insert(task_db, "ls-q1")
        self._insert(task_db, "ls-q2")
        self._insert(task_db, "ls-r1")
        task_db.claim_next_for_daemon()  # claims ls-q1 or ls-q2

        queued = task_db.list_tasks(status="queued")
        running = task_db.list_tasks(status="running")
        assert len(queued) + len(running) == 3
        assert len(running) == 1

    def test_list_by_project(self, task_db):
        """count_by_status filters correctly."""
        self._insert(task_db, "cnt-1")
        self._insert(task_db, "cnt-2")
        self._insert(task_db, "cnt-3")
        task_db.claim_next_for_daemon()

        assert task_db.count_by_status("queued") == 2
        assert task_db.count_by_status("running") == 1
        assert task_db.count_by_status("completed") == 0

    def test_get_task_not_found(self, task_db):
        assert task_db.get_task("nonexistent") is None

    def test_list_empty(self, task_db):
        assert task_db.list_tasks() == []
        assert task_db.list_tasks(status="queued") == []


# ── Cost Tracking ────────────────────────────────────────────

class TestCostTracking:
    def _insert_and_run(self, task_db, task_id, **kw):
        m = make_manifest(task_id, **kw)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)
        task_db.claim_next_for_daemon()

    def test_cost_today(self, task_db):
        self._insert_and_run(task_db, "cost-1")
        task_db.update_status("cost-1", "completed", cost_usd=3.50)

        cost = task_db.get_cost_today()
        assert cost == 3.50

    def test_cost_today_empty(self, task_db):
        assert task_db.get_cost_today() == 0.0


# ── Stats ────────────────────────────────────────────────────

class TestStats:
    def _insert(self, task_db, task_id, **kw):
        m = make_manifest(task_id, **kw)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

    def test_stats_summary(self, task_db):
        self._insert(task_db, "stat-1", project_name="p1")
        self._insert(task_db, "stat-2", project_name="p2")
        self._insert(task_db, "stat-3", project_name="p3")
        task_db.claim_next_for_daemon()
        task_db.update_status("stat-1", "completed", cost_usd=1.0)

        with patch.object(task_db, "_is_project_process_alive", return_value=False):
            stats = task_db.get_stats()
        assert stats["total"] == 3
        assert stats["counts"].get("completed", 0) == 1
        assert stats["counts"].get("queued", 0) == 2


# ── Recover Stuck ────────────────────────────────────────────

class TestRecoverStuck:
    def _insert_and_run(self, task_db, task_id, **kw):
        m = make_manifest(task_id, **kw)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)
        task_db.claim_next_for_daemon()

    def test_recover_marks_failed(self, task_db):
        self._insert_and_run(task_db, "rec-1")

        # Set old heartbeat
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        db = task_db.get_db()
        db.execute("UPDATE tasks SET last_heartbeat = ? WHERE id = 'rec-1'", (old_time,))
        db.commit()
        db.close()

        with patch.object(task_db, "_is_project_process_alive", return_value=False):
            count = task_db.recover_stuck(minutes=10)
        assert count == 1

        task = task_db.get_task("rec-1")
        assert task["status"] == "failed"
        assert "Auto-recovered" in task["error_message"]

    def test_recover_nothing_stuck(self, task_db):
        with patch.object(task_db, "_is_project_process_alive", return_value=False):
            count = task_db.recover_stuck()
        assert count == 0


# ── Edge Cases ───────────────────────────────────────────────

class TestEdgeCases:
    def _insert(self, task_db, task_id, **kw):
        m = make_manifest(task_id, **kw)
        path = write_manifest(task_db._test_tasks_dir, m)
        task_db.add_from_json(path)

    def test_init_db_idempotent(self, task_db):
        """Calling init_db multiple times should not fail or lose data."""
        self._insert(task_db, "idem-1")
        task_db.init_db()
        task_db.init_db()
        assert task_db.get_task("idem-1") is not None

    def test_empty_depends_on(self, task_db):
        """Tasks with empty depends_on should be claimable."""
        self._insert(task_db, "empty-dep", depends_on=[])
        claimed = task_db.claim_next_for_daemon()
        assert claimed["id"] == "empty-dep"

    def test_claim_only_queued(self, task_db):
        """Completed or failed tasks should never be claimed."""
        self._insert(task_db, "done-task")
        task_db.claim_next_for_daemon()
        task_db.update_status("done-task", "completed")

        # Nothing left to claim
        assert task_db.claim_next_for_daemon() is None

    def test_dispatched_at_ordering(self, task_db):
        """Same priority tasks should be claimed in dispatched_at order."""
        for i in range(3):
            m = make_manifest(f"ord-{i}", priority=0,
                              dispatched_at=f"2026-01-0{i+1}T00:00:00Z")
            path = write_manifest(task_db._test_tasks_dir, m)
            task_db.add_from_json(path)

        claimed = task_db.claim_next_for_daemon()
        assert claimed["id"] == "ord-0"  # earliest dispatched_at

    def test_count_nonexistent_status(self, task_db):
        assert task_db.count_by_status("nonexistent") == 0
