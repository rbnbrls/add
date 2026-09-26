"""Store mailbox polling enablement in the ADD application preferences."""
from alembic import op
import sqlalchemy as sa

revision = "0019_mail_poll_preference"
down_revision = "0018_mail_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_preferences", sa.Column("mail_poll_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("app_preferences", sa.Column("api_cors_origins", sa.String(length=500), nullable=False, server_default="http://localhost:3000,http://127.0.0.1:3000"))
    op.add_column("app_preferences", sa.Column("secure_cookies", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("app_preferences", sa.Column("mail_poll_interval_seconds", sa.Integer(), nullable=False, server_default="900"))
    op.add_column("app_preferences", sa.Column("mail_sync_batch_size", sa.Integer(), nullable=False, server_default="25"))
    op.add_column("app_preferences", sa.Column("mail_auto_cleanup_confidence", sa.Float(), nullable=False, server_default="0.99"))
    op.add_column("app_preferences", sa.Column("github_repo", sa.String(length=240), nullable=False, server_default="rbnbrls/add"))


def downgrade() -> None:
    op.drop_column("app_preferences", "github_repo")
    op.drop_column("app_preferences", "mail_auto_cleanup_confidence")
    op.drop_column("app_preferences", "mail_sync_batch_size")
    op.drop_column("app_preferences", "mail_poll_interval_seconds")
    op.drop_column("app_preferences", "secure_cookies")
    op.drop_column("app_preferences", "api_cors_origins")
    op.drop_column("app_preferences", "mail_poll_enabled")
