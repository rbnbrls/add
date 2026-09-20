"""Store natural-language capture audit data and parsed metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0003_natural_language_capture"
down_revision = "0002_task_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_suggestions") as batch:
        batch.add_column(sa.Column("original_input", sa.Text(), nullable=True))
        batch.add_column(sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
        batch.alter_column("tags", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("task_suggestions") as batch:
        batch.drop_column("tags")
        batch.drop_column("planned_at")
        batch.drop_column("original_input")
