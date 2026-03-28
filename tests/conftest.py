"""Fixtures for task-db tests."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Load task-db.py (hyphenated name) via importlib
_TASK_DB_PATH = Path(__file__).resolve().parent.parent / "task-db.py"
_spec = importlib.util.spec_from_file_location("task_db", _TASK_DB_PATH)
_task_db_module = importlib.util.module_from_spec(_spec)
sys.modules["task_db"] = _task_db_module
_spec.loader.exec_module(_task_db_module)


@pytest.fixture
def task_db(tmp_path):
    """
    Provide a task_db module wired to a temporary SQLite database.
    Each test gets a fresh, empty database with the schema initialized.
    """
    db_path = tmp_path / "tasks.db"
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    with patch.object(_task_db_module, "DB_PATH", db_path), \
         patch.object(_task_db_module, "TASKS_DIR", tasks_dir), \
         patch.object(_task_db_module, "FLEET_DIR", tmp_path):
        _task_db_module.init_db()
        # Expose tmp_path and tasks_dir on the module for convenience
        _task_db_module._test_tmp = tmp_path
        _task_db_module._test_tasks_dir = tasks_dir
        yield _task_db_module
