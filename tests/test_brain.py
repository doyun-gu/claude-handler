"""Tests for fleet-brain.py scheduler logic."""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path so we can import fleet-brain as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# fleet-brain.py has a hyphen, so we need importlib
import importlib
brain = importlib.import_module("fleet-brain")

Task = brain.Task
classify_topics = brain.classify_topics
topic_affinity = brain.topic_affinity
score_task = brain.score_task
pick_next = brain.pick_next
pick_all_next = brain.pick_all_next
deps_satisfied = brain.deps_satisfied
get_queued = brain.get_queued
get_completed = brain.get_completed
get_running = brain.get_running
get_failed = brain.get_failed
build_execution_plan = brain.build_execution_plan
infer_group = brain.infer_group
should_retry = brain.should_retry
format_eta = brain.format_eta
TOPIC_KEYWORDS = brain.TOPIC_KEYWORDS


# ── Helpers ──────────────────────────────────────────────────

def make_task(slug="task-1", status="queued", project="proj",
              priority=0, depends_on=None, retry_count=0,
              dispatched_at="", prompt="", group="",
              topics=None, id_=None):
    """Create a Task for testing without touching the filesystem."""
    t = Task(
        id=id_ or f"20260328-{slug}",
        slug=slug,
        status=status,
        project=project,
        project_path=f"/tmp/{project}",
        prompt=prompt,
        group=group,
        depends_on=depends_on or [],
        priority=priority,
        retry_count=retry_count,
        dispatched_at=dispatched_at,
        file_path=f"/tmp/tasks/{slug}.json",
    )
    # Set topics explicitly or auto-classify
    if topics is not None:
        t.topics = topics
    else:
        t.topics = classify_topics(slug, prompt)
    if not t.group:
        t.group = infer_group(t)
    return t


# ── Topic Classification ────────────────────────────────────

class TestClassifyTopics:
    def test_engine_keywords(self):
        topics = classify_topics("powerflow-solver", "implement newton-raphson")
        assert "engine" in topics

    def test_ui_keywords(self):
        topics = classify_topics("update-button-style", "fix css layout")
        assert "ui" in topics

    def test_api_keywords(self):
        topics = classify_topics("add-endpoint", "create rest api route")
        assert "api" in topics

    def test_test_keywords(self):
        topics = classify_topics("add-pytest-coverage", "write test spec")
        assert "test" in topics

    def test_docs_keywords(self):
        topics = classify_topics("update-readme", "add architecture doc")
        assert "docs" in topics

    def test_infra_keywords(self):
        topics = classify_topics("docker-setup", "configure ci deploy")
        assert "infra" in topics

    def test_fix_keywords(self):
        topics = classify_topics("fix-crash", "debug error in parser")
        assert "fix" in topics

    def test_feature_keywords(self):
        topics = classify_topics("add-export", "implement new feature")
        assert "feature" in topics

    def test_refactor_keywords(self):
        topics = classify_topics("refactor-parser", "simplify and clean code")
        assert "refactor" in topics

    def test_no_match_returns_general(self):
        topics = classify_topics("zzz-unknown", "nothing recognizable here xyz")
        assert topics == ["general"]

    def test_multiple_topics(self):
        topics = classify_topics("fix-api-test", "fix the broken api test endpoint")
        assert "fix" in topics
        assert "api" in topics
        assert "test" in topics

    def test_slug_and_prompt_both_checked(self):
        # keyword in slug only
        t1 = classify_topics("engine-work", "do something")
        assert "engine" in t1
        # keyword in prompt only
        t2 = classify_topics("some-task", "fix the solver engine")
        assert "engine" in t2


# ── Topic Affinity ──────────────────────────────────────────

class TestTopicAffinity:
    def test_identical_topics(self):
        assert topic_affinity(["engine"], ["engine"]) == 1.0

    def test_no_overlap(self):
        assert topic_affinity(["engine"], ["ui"]) == 0.0

    def test_partial_overlap(self):
        score = topic_affinity(["engine", "test"], ["engine", "api"])
        # overlap=1 (engine), union=3 (engine, test, api) → 1/3
        assert abs(score - 1 / 3) < 0.01

    def test_empty_lists(self):
        assert topic_affinity([], ["engine"]) == 0.0
        assert topic_affinity(["engine"], []) == 0.0
        assert topic_affinity([], []) == 0.0


# ── Scoring Function ────────────────────────────────────────

class TestScoreTask:
    def test_higher_priority_scores_higher(self):
        high = make_task(slug="high", priority=100)
        low = make_task(slug="low", priority=0)
        all_tasks = [high, low]

        s_high = score_task(high, None, all_tasks)
        s_low = score_task(low, None, all_tasks)
        assert s_high > s_low

    def test_priority_is_dominant_factor(self):
        """Priority * 10 should dominate over affinity and age bonuses."""
        high = make_task(slug="high-prio", priority=50)
        low = make_task(slug="low-prio", priority=0, topics=["engine"])
        # Even with affinity boost from just_completed, priority should win
        completed = make_task(slug="engine-done", status="completed", topics=["engine"])
        all_tasks = [high, low, completed]

        s_high = score_task(high, completed, all_tasks)
        s_low = score_task(low, completed, all_tasks)
        assert s_high > s_low

    def test_age_bonus_increases_over_time(self):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        new_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

        old_task = make_task(slug="old", dispatched_at=old_time)
        new_task = make_task(slug="new", dispatched_at=new_time)
        all_tasks = [old_task, new_task]

        s_old = score_task(old_task, None, all_tasks)
        s_new = score_task(new_task, None, all_tasks)
        assert s_old > s_new

    def test_age_bonus_capped_at_10(self):
        """Age bonus maxes out at 10 points."""
        very_old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        task = make_task(slug="ancient", dispatched_at=very_old, priority=0)
        score = score_task(task, None, [task])
        # priority=0, no affinity, no deps. Score should be exactly age bonus ≤ 10
        assert score <= 10.0

    def test_retry_penalty_decreases_score(self):
        fresh = make_task(slug="fresh", retry_count=0)
        retried = make_task(slug="retried", retry_count=3)
        all_tasks = [fresh, retried]

        s_fresh = score_task(fresh, None, all_tasks)
        s_retried = score_task(retried, None, all_tasks)
        assert s_fresh > s_retried

    def test_affinity_bonus_same_project(self):
        """Same project + topic overlap gives higher score than different project."""
        completed = make_task(slug="done", status="completed",
                              project="projA", topics=["engine"])
        same_proj = make_task(slug="next-same", project="projA", topics=["engine"])
        diff_proj = make_task(slug="next-diff", project="projB", topics=["engine"])
        all_tasks = [completed, same_proj, diff_proj]

        s_same = score_task(same_proj, completed, all_tasks)
        s_diff = score_task(diff_proj, completed, all_tasks)
        assert s_same > s_diff

    def test_affinity_bonus_same_group(self):
        completed = make_task(slug="done", status="completed", group="projA:engine")
        same_group = make_task(slug="next", group="projA:engine")
        diff_group = make_task(slug="other", group="projB:ui")
        all_tasks = [completed, same_group, diff_group]

        s_same = score_task(same_group, completed, all_tasks)
        s_diff = score_task(diff_group, completed, all_tasks)
        assert s_same > s_diff

    def test_dependency_chain_bonus(self):
        """Tasks that unlock other tasks should score higher."""
        blocker = make_task(slug="blocker", id_="20260328-blocker")
        dependent1 = make_task(slug="dep1", depends_on=["blocker"])
        dependent2 = make_task(slug="dep2", depends_on=["blocker"])
        unrelated = make_task(slug="unrelated")
        all_tasks = [blocker, dependent1, dependent2, unrelated]

        s_blocker = score_task(blocker, None, all_tasks)
        s_unrelated = score_task(unrelated, None, all_tasks)
        # blocker unlocks 2 tasks → +30 bonus
        assert s_blocker > s_unrelated

    def test_no_just_completed_no_affinity(self):
        task = make_task(slug="lonely", topics=["engine"])
        score = score_task(task, None, [task])
        # Only base priority (0) contributes, no affinity, no deps, no age
        assert score == 0.0


# ── Dependency Ordering ─────────────────────────────────────

class TestDependencies:
    def test_no_deps_always_satisfied(self):
        task = make_task(slug="free")
        assert deps_satisfied(task, []) is True

    def test_dep_on_completed_satisfied(self):
        dep = make_task(slug="prereq", status="completed")
        task = make_task(slug="waiter", depends_on=["prereq"])
        assert deps_satisfied(task, [dep]) is True

    def test_dep_on_merged_satisfied(self):
        dep = make_task(slug="prereq", status="merged")
        task = make_task(slug="waiter", depends_on=["prereq"])
        assert deps_satisfied(task, [dep]) is True

    def test_dep_on_queued_not_satisfied(self):
        dep = make_task(slug="prereq", status="queued")
        task = make_task(slug="waiter", depends_on=["prereq"])
        assert deps_satisfied(task, [dep]) is False

    def test_dep_on_running_not_satisfied(self):
        dep = make_task(slug="prereq", status="running")
        task = make_task(slug="waiter", depends_on=["prereq"])
        assert deps_satisfied(task, [dep]) is False

    def test_multiple_deps_all_must_be_satisfied(self):
        dep1 = make_task(slug="dep1", status="completed")
        dep2 = make_task(slug="dep2", status="queued")
        task = make_task(slug="waiter", depends_on=["dep1", "dep2"])
        assert deps_satisfied(task, [dep1, dep2]) is False

    def test_multiple_deps_all_completed(self):
        dep1 = make_task(slug="dep1", status="completed")
        dep2 = make_task(slug="dep2", status="merged")
        task = make_task(slug="waiter", depends_on=["dep1", "dep2"])
        assert deps_satisfied(task, [dep1, dep2]) is True

    def test_dep_by_id(self):
        dep = make_task(slug="prereq", status="completed", id_="abc-123")
        task = make_task(slug="waiter", depends_on=["abc-123"])
        assert deps_satisfied(task, [dep]) is True

    def test_dep_not_found_not_satisfied(self):
        """If the dependency slug doesn't match anything, it's not satisfied."""
        task = make_task(slug="waiter", depends_on=["nonexistent"])
        assert deps_satisfied(task, []) is False


# ── Priority Ordering (pick_next) ───────────────────────────

class TestPickNext:
    def test_higher_priority_picked_first(self):
        high = make_task(slug="high", priority=100)
        low = make_task(slug="low", priority=0)
        tasks = [low, high]

        result = pick_next(tasks, blocked_projects=set())
        assert result.slug == "high"

    def test_empty_queue_returns_none(self):
        result = pick_next([], blocked_projects=set())
        assert result is None

    def test_all_completed_returns_none(self):
        tasks = [make_task(slug="done", status="completed")]
        result = pick_next(tasks, blocked_projects=set())
        assert result is None

    def test_blocked_project_skipped(self):
        t1 = make_task(slug="t1", project="projA", priority=100)
        t2 = make_task(slug="t2", project="projB", priority=0)
        tasks = [t1, t2]

        result = pick_next(tasks, blocked_projects={"projA"})
        assert result.slug == "t2"

    def test_unsatisfied_dep_skipped(self):
        dep = make_task(slug="prereq", status="queued")
        waiter = make_task(slug="waiter", depends_on=["prereq"], priority=100)
        free = make_task(slug="free", priority=0)
        tasks = [dep, waiter, free]

        result = pick_next(tasks, blocked_projects=set())
        # waiter has higher priority but deps not met, so prereq or free
        assert result.slug in ("prereq", "free")
        assert result.slug != "waiter"

    def test_just_completed_affinity(self):
        """After completing an engine task, prefer another engine task."""
        engine_done = make_task(slug="engine-done", status="completed",
                                project="proj", topics=["engine"])
        engine_next = make_task(slug="engine-next", project="proj",
                                topics=["engine"], priority=0)
        ui_task = make_task(slug="ui-task", project="proj",
                            topics=["ui"], priority=0)
        tasks = [engine_done, engine_next, ui_task]

        result = pick_next(tasks, just_completed_slug="engine-done",
                           blocked_projects=set())
        assert result.slug == "engine-next"

    def test_deps_must_complete_before_dependent_runs(self):
        """Dependency task should be picked before the dependent task."""
        dep = make_task(slug="step1", priority=0)
        dependent = make_task(slug="step2", depends_on=["step1"], priority=100)
        tasks = [dep, dependent]

        result = pick_next(tasks, blocked_projects=set())
        assert result.slug == "step1"


# ── Parallel Picking (pick_all_next) ────────────────────────

class TestPickAllNext:
    def test_one_per_project(self):
        t1 = make_task(slug="t1", project="projA")
        t2 = make_task(slug="t2", project="projA")
        t3 = make_task(slug="t3", project="projB")
        tasks = [t1, t2, t3]

        result = pick_all_next(tasks)
        projects = [t.project for t in result]
        # Each project should appear at most once
        assert len(projects) == len(set(projects))
        assert len(result) == 2  # one from A, one from B

    def test_running_project_blocked(self):
        running = make_task(slug="running", project="projA", status="running")
        queued = make_task(slug="queued", project="projA")
        other = make_task(slug="other", project="projB")
        tasks = [running, queued, other]

        result = pick_all_next(tasks)
        picked_projects = {t.project for t in result}
        assert "projA" not in picked_projects
        assert "projB" in picked_projects

    def test_empty_queue(self):
        result = pick_all_next([])
        assert result == []


# ── Execution Plan ──────────────────────────────────────────

class TestBuildExecutionPlan:
    def test_independent_tasks_in_one_round(self):
        t1 = make_task(slug="a", project="p1")
        t2 = make_task(slug="b", project="p2")
        tasks = [t1, t2]

        plan = build_execution_plan(tasks)
        assert len(plan) == 1
        assert len(plan[0]) == 2

    def test_dependent_tasks_in_separate_rounds(self):
        dep = make_task(slug="first", project="proj")
        waiter = make_task(slug="second", depends_on=["first"], project="proj")
        tasks = [dep, waiter]

        plan = build_execution_plan(tasks)
        assert len(plan) == 2
        assert plan[0][0].slug == "first"
        assert plan[1][0].slug == "second"

    def test_all_deps_unresolvable_empty_plan(self):
        """Circular or unresolvable dependencies produce no rounds."""
        t1 = make_task(slug="a", depends_on=["b"])
        t2 = make_task(slug="b", depends_on=["a"])
        tasks = [t1, t2]

        plan = build_execution_plan(tasks)
        assert len(plan) == 0

    def test_complex_dependency_chain(self):
        """A → B → C should produce 3 rounds."""
        a = make_task(slug="a", project="p1")
        b = make_task(slug="b", depends_on=["a"], project="p1")
        c = make_task(slug="c", depends_on=["b"], project="p1")
        tasks = [a, b, c]

        plan = build_execution_plan(tasks)
        assert len(plan) == 3
        assert plan[0][0].slug == "a"
        assert plan[1][0].slug == "b"
        assert plan[2][0].slug == "c"


# ── Edge Cases ──────────────────────────────────────────────

class TestEdgeCases:
    def test_single_task_queue(self):
        task = make_task(slug="only-one")
        result = pick_next([task], blocked_projects=set())
        assert result.slug == "only-one"

    def test_all_tasks_have_unmet_deps(self):
        t1 = make_task(slug="a", depends_on=["missing1"])
        t2 = make_task(slug="b", depends_on=["missing2"])
        result = pick_next([t1, t2], blocked_projects=set())
        assert result is None

    def test_all_projects_blocked(self):
        t1 = make_task(slug="t1", project="projA")
        t2 = make_task(slug="t2", project="projB")
        result = pick_next([t1, t2], blocked_projects={"projA", "projB"})
        assert result is None

    def test_mixed_statuses_only_queued_picked(self):
        completed = make_task(slug="done", status="completed")
        running = make_task(slug="going", status="running")
        failed = make_task(slug="broken", status="failed")
        queued = make_task(slug="ready", status="queued")
        tasks = [completed, running, failed, queued]

        result = pick_next(tasks, blocked_projects=set())
        assert result.slug == "ready"


# ── Filter Helpers ──────────────────────────────────────────

class TestFilterHelpers:
    def test_get_queued(self):
        tasks = [make_task(status="queued"), make_task(slug="b", status="completed")]
        assert len(get_queued(tasks)) == 1

    def test_get_completed_includes_merged(self):
        tasks = [
            make_task(slug="a", status="completed"),
            make_task(slug="b", status="merged"),
            make_task(slug="c", status="queued"),
        ]
        assert len(get_completed(tasks)) == 2

    def test_get_running(self):
        tasks = [make_task(status="running"), make_task(slug="b", status="queued")]
        assert len(get_running(tasks)) == 1

    def test_get_failed(self):
        tasks = [make_task(status="failed"), make_task(slug="b", status="queued")]
        assert len(get_failed(tasks)) == 1


# ── Retry Logic ─────────────────────────────────────────────

class TestRetry:
    def test_should_retry_within_limit(self):
        task = make_task(status="failed", retry_count=1)
        assert should_retry(task) is True

    def test_should_not_retry_at_max(self):
        task = make_task(status="failed", retry_count=3)
        assert should_retry(task) is False

    def test_should_not_retry_non_failed(self):
        task = make_task(status="queued", retry_count=0)
        assert should_retry(task) is False


# ── Infer Group ─────────────────────────────────────────────

class TestInferGroup:
    def test_infers_from_project_and_topic(self):
        task = make_task(slug="fix-bug", project="myapp", topics=["fix"])
        assert infer_group(task) == "myapp:fix"

    def test_general_when_no_topics(self):
        task = make_task(slug="xyz", project="proj", topics=["general"])
        assert infer_group(task) == "proj:general"


# ── Format ETA ──────────────────────────────────────────────

class TestFormatEta:
    def test_under_one_minute(self):
        assert format_eta(0.5) == "<1m"

    def test_minutes(self):
        assert format_eta(25) == "~25m"

    def test_hours_and_minutes(self):
        assert format_eta(90) == "~1h 30m"

    def test_exact_hours(self):
        assert format_eta(120) == "~2h"
