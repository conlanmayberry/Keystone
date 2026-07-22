from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from megachud.db import ensure_task_execution_mode_column


def test_ensure_task_execution_mode_column_patches_a_pre_existing_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    # A "tasks" table as it existed before execution_mode was added — no
    # migration framework exists in this project, so simulate the
    # pre-migration schema directly rather than going through init_db()
    # (which would create the column from day one via the current model).
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)"))

    assert "execution_mode" not in {c["name"] for c in inspect(engine).get_columns("tasks")}

    ensure_task_execution_mode_column(engine)
    assert "execution_mode" in {c["name"] for c in inspect(engine).get_columns("tasks")}

    ensure_task_execution_mode_column(engine)  # idempotent — must not raise
    assert "execution_mode" in {c["name"] for c in inspect(engine).get_columns("tasks")}


def test_ensure_task_execution_mode_column_is_a_noop_without_a_tasks_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    ensure_task_execution_mode_column(engine)  # must not raise
