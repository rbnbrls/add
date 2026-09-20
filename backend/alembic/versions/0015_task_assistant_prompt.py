"""Add configurable task assistant prompt."""
from alembic import op
import sqlalchemy as sa

revision = "0015_task_assistant_prompt"
down_revision = "0014_app_preferences"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("app_preferences", sa.Column("task_assistant_prompt", sa.Text(), nullable=False, server_default="Help me decompose this task into concrete, small next steps and improve its description."))

def downgrade() -> None:
    op.drop_column("app_preferences", "task_assistant_prompt")
