"""Add reproducible focus duration and pause state."""
from alembic import op
import sqlalchemy as sa
revision = "0010_focus_state"
down_revision = "0009_backup_snapshots"
branch_labels = None
depends_on = None
def upgrade() -> None:
    with op.batch_alter_table("execution_sessions") as batch:
        batch.add_column(sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="600"))
        batch.add_column(sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("paused_seconds", sa.Integer(), nullable=False, server_default="0"))
def downgrade() -> None:
    with op.batch_alter_table("execution_sessions") as batch:
        batch.drop_column("paused_seconds"); batch.drop_column("paused_at"); batch.drop_column("duration_seconds")
