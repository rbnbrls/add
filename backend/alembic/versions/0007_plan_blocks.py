"""Add explicit planning time blocks."""
from alembic import op
import sqlalchemy as sa

revision = "0007_plan_blocks"
down_revision = "0006_day_feedback"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("plan_blocks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))

def downgrade() -> None:
    op.drop_table("plan_blocks")
