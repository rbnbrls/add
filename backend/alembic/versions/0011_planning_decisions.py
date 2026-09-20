"""Add auditable planning transitions for C2."""
from alembic import op
import sqlalchemy as sa

revision = "0011_planning_decisions"
down_revision = "0010_focus_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planning_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("suggestion_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("block_id", sa.String(length=36), nullable=True),
        sa.Column("from_planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("to_planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("from_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("from_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("to_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("to_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("planning_decisions")
