"""Create the current ADD schema.

Revision ID: 0001_initial
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


task_status = postgresql.ENUM("INBOX", "ACTIVE", "DONE", "ARCHIVED", name="taskstatus", create_type=False)
action_status = postgresql.ENUM("READY", "ACTIVE", "DONE", "BLOCKED", "SNOOZED", name="actionstatus", create_type=False)
session_outcome = postgresql.ENUM("RUNNING", "DONE", "CONTINUE", "STUCK", "STOP_FOR_TODAY", name="sessionoutcome", create_type=False)
suggestion_status = postgresql.ENUM("PENDING", "ACCEPTED", "REJECTED", name="suggestionstatus", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        task_status.create(bind, checkfirst=True)
        action_status.create(bind, checkfirst=True)
        session_outcome.create(bind, checkfirst=True)
        suggestion_status.create(bind, checkfirst=True)

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", task_status, nullable=False),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_ref", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("status", action_status, nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("energy", sa.String(length=20), nullable=False),
        sa.Column("requires_home", sa.Boolean(), nullable=False),
        sa.Column("requires_computer", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "execution_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", session_outcome, nullable=False),
        sa.Column("stuck_reason", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "accountability_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("execution_session_id", sa.String(length=36), nullable=False),
        sa.Column("participant_label", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["execution_session_id"], ["execution_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "completion_log",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "task_suggestions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_ref", sa.String(length=240), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suggested_next_action", sa.String(length=300), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", suggestion_status, nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "integration_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider"),
    )
    op.create_table(
        "local_account",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("password_hash", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("local_account")
    op.drop_table("integration_credentials")
    op.drop_table("outbox_events")
    op.drop_table("task_suggestions")
    op.drop_table("completion_log")
    op.drop_table("accountability_sessions")
    op.drop_table("execution_sessions")
    op.drop_table("actions")
    op.drop_table("tasks")

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        suggestion_status.drop(bind, checkfirst=True)
        session_outcome.drop(bind, checkfirst=True)
        action_status.drop(bind, checkfirst=True)
        task_status.drop(bind, checkfirst=True)
