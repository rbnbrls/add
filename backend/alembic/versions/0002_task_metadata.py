"""Add task metadata and hierarchy."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_task_metadata"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


task_priority = postgresql.ENUM("LOW", "MEDIUM", "HIGH", name="taskpriority", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        task_priority.create(bind, checkfirst=True)
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("actual_minutes", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("parent_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("priority", task_priority, nullable=False, server_default="MEDIUM"))
        if bind.dialect.name != "sqlite":
            batch.create_foreign_key("fk_tasks_parent_id", "tasks", ["parent_id"], ["id"])
    if bind.dialect.name == "sqlite":
        # SQLite cannot add a self-referencing FK through ALTER TABLE. The
        # ORM still enforces the relationship and PostgreSQL gets the FK.
        pass
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("actual_minutes", server_default=None)
        batch.alter_column("tags", server_default=None)
        batch.alter_column("priority", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("tasks") as batch:
        if bind.dialect.name != "sqlite":
            batch.drop_constraint("fk_tasks_parent_id", type_="foreignkey")
        batch.drop_column("priority")
        batch.drop_column("tags")
        batch.drop_column("parent_id")
        batch.drop_column("actual_minutes")
        batch.drop_column("planned_at")
    if bind.dialect.name != "sqlite":
        task_priority.drop(bind, checkfirst=True)
