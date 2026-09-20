"""Add application display preferences."""
from alembic import op
import sqlalchemy as sa

revision = "0014_app_preferences"
down_revision = "0013_saved_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_preferences",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_badge_mode", sa.String(length=10), nullable=False, server_default="dot"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("app_preferences")
