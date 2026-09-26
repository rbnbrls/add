import os
import subprocess
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings


BACKEND = Path(__file__).parents[1]


def migration_config(database_url: str) -> Config:
    settings.database_url = database_url
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_fresh_database_is_created_by_migration(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    config = migration_config(database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    assert set(inspect(engine).get_table_names()) == {
        "accountability_sessions",
        "actions",
        "completion_log",
        "execution_sessions",
        "integration_credentials",
        "local_account",
        "outbox_events",
        "task_suggestions",
        "task_decomposition_items",
        "task_decomposition_proposals",
            "tasks",
            "task_rollover_events",
        "plan_blocks",
        "planning_decisions",
            "routines",
            "routine_occurrences",
            "reminder_preferences",
        "backup_snapshots",
        "saved_views",
        "app_preferences",
        "alembic_version",
    }
    columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    assert {"actual_minutes", "parent_id", "tags", "planned_at", "priority"} <= columns
    suggestion_columns = {column["name"] for column in inspect(engine).get_columns("task_suggestions")}
    assert {"original_input", "planned_at", "tags", "batch_id", "suggested_estimated_minutes"} <= suggestion_columns
    assert {"id", "name", "filters", "created_at"} <= {column["name"] for column in inspect(engine).get_columns("saved_views")}


def test_existing_schema_can_be_stamped_without_losing_rows(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'existing.db'}"
    engine = create_engine(database_url)
    config = migration_config(database_url)
    command.upgrade(config, "0001_initial")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tasks "
                "(id, title, status, source_type, created_at) "
                "VALUES ('task-1', 'Bestaande taak', 'INBOX', 'manual', '2026-01-01 00:00:00')"
            )
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT title FROM tasks WHERE id = 'task-1'")).scalar_one() == "Bestaande taak"


def test_baseline_can_be_downgraded(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'downgrade.db'}"
    config = migration_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(database_url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one() == 0


def test_importing_app_does_not_create_database(tmp_path):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(BACKEND)
    environment["DATABASE_URL"] = f"sqlite:///{tmp_path / 'import.db'}"
    subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env=environment,
        check=True,
    )
    assert not (tmp_path / "import.db").exists()
