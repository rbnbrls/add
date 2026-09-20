"""Add inbox batches and advisory estimates."""

from alembic import op
import sqlalchemy as sa


revision = "0005_inbox_funnel"
down_revision = "0004_task_decomposition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_suggestions") as batch:
        batch.add_column(sa.Column("batch_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("suggested_estimated_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("task_suggestions") as batch:
        batch.drop_column("suggested_estimated_minutes")
        batch.drop_column("batch_id")
