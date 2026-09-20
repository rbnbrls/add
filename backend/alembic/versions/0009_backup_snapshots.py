"""Add pre-restore rollback snapshots."""
from alembic import op
import sqlalchemy as sa
revision = "0009_backup_snapshots"
down_revision = "0008_routines"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table("backup_snapshots", sa.Column("id",sa.String(36),primary_key=True),sa.Column("payload",sa.Text(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=True))
def downgrade() -> None:
    op.drop_table("backup_snapshots")
