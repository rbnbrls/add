"""Add parsed schedule metadata to inbox proposals."""
from alembic import op
import sqlalchemy as sa

revision = "0012_schedule_metadata"
down_revision = "0011_planning_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_suggestions", sa.Column("parsed_duration_minutes", sa.Integer(), nullable=True))
    op.add_column("task_suggestions", sa.Column("recurrence", sa.String(length=80), nullable=True))
    op.add_column("task_suggestions", sa.Column("schedule_timezone", sa.String(length=80), nullable=True))
    op.add_column("task_suggestions", sa.Column("schedule_status", sa.String(length=20), nullable=False, server_default="none"))
    op.add_column("task_suggestions", sa.Column("schedule_notes", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("task_suggestions", "schedule_notes")
    op.drop_column("task_suggestions", "schedule_status")
    op.drop_column("task_suggestions", "schedule_timezone")
    op.drop_column("task_suggestions", "recurrence")
    op.drop_column("task_suggestions", "parsed_duration_minutes")
