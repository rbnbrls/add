"""Add configurable LLM provider settings."""
from alembic import op
import sqlalchemy as sa

revision = "0016_llm_preferences"
down_revision = "0015_task_assistant_prompt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_preferences", sa.Column("llm_provider", sa.String(length=40), nullable=False, server_default="openrouter"))
    op.add_column("app_preferences", sa.Column("llm_base_url", sa.String(length=240), nullable=False, server_default="https://openrouter.ai/api/v1"))
    op.add_column("app_preferences", sa.Column("llm_model", sa.String(length=160), nullable=False, server_default="openrouter/free"))
    op.add_column("app_preferences", sa.Column("llm_credential_provider", sa.String(length=80), nullable=False, server_default="llm"))


def downgrade() -> None:
    op.drop_column("app_preferences", "llm_credential_provider")
    op.drop_column("app_preferences", "llm_model")
    op.drop_column("app_preferences", "llm_base_url")
    op.drop_column("app_preferences", "llm_provider")
