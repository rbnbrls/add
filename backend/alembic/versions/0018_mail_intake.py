"""Add mailbox accounts, metadata and idempotent action audit."""
from alembic import op
import sqlalchemy as sa

revision = "0018_mail_intake"
down_revision = "0017_force_free_openrouter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("provider", sa.Enum("GMAIL", "OUTLOOK", "IMAP", name="mailprovider"), nullable=False),
        sa.Column("address", sa.String(320), nullable=False),
        sa.Column("status", sa.Enum("ACTIVE", "PAUSED", "ERROR", name="mailaccountstatus"), nullable=False),
        sa.Column("credential_provider", sa.String(120), nullable=False),
        sa.Column("sync_cursor", sa.String(500)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "mail_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("mail_accounts.id"), nullable=False),
        sa.Column("provider_message_id", sa.String(500), nullable=False),
        sa.Column("thread_id", sa.String(500)),
        sa.Column("sender", sa.String(320)),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("snippet", sa.Text),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("headers", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("provider_spam", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("category", sa.String(40)),
        sa.Column("confidence", sa.Float),
        sa.Column("triage_status", sa.String(30), nullable=False, server_default="new"),
        sa.Column("last_error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "provider_message_id", name="uq_mail_account_message"),
    )
    op.create_table(
        "mail_action_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("mail_messages.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("detail", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("message_id", "action", name="uq_mail_message_action"),
    )
    op.create_table(
        "mail_sync_leases",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner", sa.String(120), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mail_sync_leases")
    op.drop_table("mail_action_audit")
    op.drop_table("mail_messages")
    op.drop_table("mail_accounts")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS mailaccountstatus")
        op.execute("DROP TYPE IF EXISTS mailprovider")
