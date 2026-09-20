"""Add recurring routines and reminder preferences."""
from alembic import op
import sqlalchemy as sa
revision = "0008_routines"
down_revision = "0007_plan_blocks"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table("routines", sa.Column("id",sa.String(36),primary_key=True),sa.Column("title",sa.String(240),nullable=False),sa.Column("action_text",sa.String(300),nullable=False),sa.Column("recurrence",sa.String(20),nullable=False),sa.Column("weekday",sa.Integer(),nullable=True),sa.Column("specific_date",sa.Date(),nullable=True),sa.Column("local_time",sa.String(5),nullable=False),sa.Column("timezone",sa.String(80),nullable=False),sa.Column("estimated_minutes",sa.Integer(),nullable=False,server_default="10"),sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.true()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=True))
    op.create_table("routine_occurrences",sa.Column("id",sa.String(36),primary_key=True),sa.Column("routine_id",sa.String(36),sa.ForeignKey("routines.id"),nullable=False),sa.Column("occurrence_date",sa.Date(),nullable=False),sa.Column("task_id",sa.String(36),sa.ForeignKey("tasks.id"),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=True),sa.UniqueConstraint("routine_id","occurrence_date",name="uq_routine_occurrence"))
    op.create_table("reminder_preferences",sa.Column("id",sa.String(36),primary_key=True),sa.Column("provider",sa.String(20),nullable=False),sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("quiet_start",sa.String(5),nullable=False,server_default="22:00"),sa.Column("quiet_end",sa.String(5),nullable=False,server_default="07:00"),sa.Column("timezone",sa.String(80),nullable=False,server_default="UTC"))
def downgrade() -> None:
    op.drop_table("reminder_preferences"); op.drop_table("routine_occurrences"); op.drop_table("routines")
