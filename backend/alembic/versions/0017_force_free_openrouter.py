"""Force the LLM configuration to the OpenRouter free router."""
from alembic import op
import sqlalchemy as sa

revision = "0017_force_free_openrouter"
down_revision = "0016_llm_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE app_preferences SET llm_provider = 'openrouter', llm_base_url = 'https://openrouter.ai/api/v1', llm_model = 'openrouter/free'"))


def downgrade() -> None:
    pass
