"""Add auditable task decomposition proposals."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_task_decomposition"
down_revision = "0003_natural_language_capture"
branch_labels = None
depends_on = None


decomposition_status = postgresql.ENUM("PENDING", "ACCEPTED", "REJECTED", name="decompositionstatus", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        decomposition_status.create(bind, checkfirst=True)
    op.create_table(
        "task_decomposition_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("status", decomposition_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "task_decomposition_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["task_decomposition_proposals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("task_decomposition_items")
    op.drop_table("task_decomposition_proposals")
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        decomposition_status.drop(bind, checkfirst=True)
