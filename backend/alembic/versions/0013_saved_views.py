"""Add bounded local smart views for read-only task filters."""
from alembic import op
import sqlalchemy as sa

revision = "0013_saved_views"
down_revision = "0012_schedule_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_views",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("saved_views")
