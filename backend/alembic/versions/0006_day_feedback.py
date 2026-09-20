"""Add rollover provenance and deferral signals."""
from alembic import op
import sqlalchemy as sa

revision = "0006_day_feedback"
down_revision = "0005_inbox_funnel"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("defer_count", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("last_deferred_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("task_rollover_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("rollover_date", sa.Date(), nullable=False),
        sa.Column("from_planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("to_planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("task_id", "rollover_date", name="uq_task_rollover_date"))

def downgrade() -> None:
    op.drop_table("task_rollover_events")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("last_deferred_at")
        batch.drop_column("defer_count")
