from datetime import date, datetime, timezone
from enum import Enum
from uuid import uuid4
from sqlalchemy import JSON, Boolean, Date, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def now(): return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    INBOX = "inbox"; ACTIVE = "active"; DONE = "done"; ARCHIVED = "archived"


class TaskPriority(str, Enum):
    LOW = "low"; MEDIUM = "medium"; HIGH = "high"


class ActionStatus(str, Enum):
    READY = "ready"; ACTIVE = "active"; DONE = "done"; BLOCKED = "blocked"; SNOOZED = "snoozed"


class SessionOutcome(str, Enum):
    RUNNING = "running"; DONE = "done"; CONTINUE = "continue"; STUCK = "stuck"; STOP_FOR_TODAY = "stop_for_today"


class SuggestionStatus(str, Enum):
    PENDING = "pending"; ACCEPTED = "accepted"; REJECTED = "rejected"


class DecompositionStatus(str, Enum):
    PENDING = "pending"; ACCEPTED = "accepted"; REJECTED = "rejected"


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus), default=TaskStatus.INBOX)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]", nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(SAEnum(TaskPriority), default=TaskPriority.MEDIUM, server_default="MEDIUM", nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    defer_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_deferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actions: Mapped[list["Action"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    parent: Mapped["Task | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Task"]] = relationship(back_populates="parent", order_by="Task.created_at.asc()")


class SavedView(Base):
    __tablename__ = "saved_views"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TaskRolloverEvent(Base):
    __tablename__ = "task_rollover_events"
    __table_args__ = (UniqueConstraint("task_id", "rollover_date", name="uq_task_rollover_date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    rollover_date: Mapped[date] = mapped_column(Date, nullable=False)
    from_planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    to_planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlanBlock(Base):
    __tablename__ = "plan_blocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    task: Mapped[Task] = relationship()


class PlanningDecision(Base):
    __tablename__ = "planning_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    suggestion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    block_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    from_planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    to_planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    from_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    from_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    to_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    to_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Routine(Base):
    __tablename__ = "routines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    action_text: Mapped[str] = mapped_column(String(300), nullable=False)
    recurrence: Mapped[str] = mapped_column(String(20), nullable=False)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    specific_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    local_time: Mapped[str] = mapped_column(String(5), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="UTC")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RoutineOccurrence(Base):
    __tablename__ = "routine_occurrences"
    __table_args__ = (UniqueConstraint("routine_id", "occurrence_date", name="uq_routine_occurrence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    routine_id: Mapped[str] = mapped_column(ForeignKey("routines.id"), nullable=False)
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    routine: Mapped[Routine] = relationship()
    task: Mapped[Task] = relationship()


class ReminderPreference(Base):
    __tablename__ = "reminder_preferences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quiet_start: Mapped[str] = mapped_column(String(5), default="22:00", nullable=False)
    quiet_end: Mapped[str] = mapped_column(String(5), default="07:00", nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC", nullable=False)


class AppPreference(Base):
    __tablename__ = "app_preferences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_badge_mode: Mapped[str] = mapped_column(String(10), default="dot", server_default="dot", nullable=False)
    task_assistant_prompt: Mapped[str] = mapped_column(Text, default="Help me decompose this task into concrete, small next steps and improve its description.", nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(40), default="openrouter", nullable=False)
    llm_base_url: Mapped[str] = mapped_column(String(240), default="https://openrouter.ai/api/v1", nullable=False)
    llm_model: Mapped[str] = mapped_column(String(160), default="openrouter/free", nullable=False)
    llm_credential_provider: Mapped[str] = mapped_column(String(80), default="llm", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class BackupSnapshot(Base):
    __tablename__ = "backup_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TaskDecompositionProposal(Base):
    __tablename__ = "task_decomposition_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    parent_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DecompositionStatus] = mapped_column(SAEnum(DecompositionStatus), default=DecompositionStatus.PENDING, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    parent: Mapped[Task] = relationship()
    items: Mapped[list["TaskDecompositionItem"]] = relationship(back_populates="proposal", cascade="all, delete-orphan", order_by="TaskDecompositionItem.position")


class TaskDecompositionItem(Base):
    __tablename__ = "task_decomposition_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    proposal_id: Mapped[str] = mapped_column(ForeignKey("task_decomposition_proposals.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal: Mapped[TaskDecompositionProposal] = relationship(back_populates="items")


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    text: Mapped[str] = mapped_column(String(300))
    status: Mapped[ActionStatus] = mapped_column(SAEnum(ActionStatus), default=ActionStatus.READY)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=10)
    energy: Mapped[str] = mapped_column(String(20), default="medium")
    requires_home: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_computer: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    task: Mapped[Task] = relationship(back_populates="actions")


class ExecutionSession(Base):
    __tablename__ = "execution_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[SessionOutcome] = mapped_column(SAEnum(SessionOutcome), default=SessionOutcome.RUNNING)
    stuck_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=600, server_default="600", nullable=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class AccountabilitySession(Base):
    __tablename__ = "accountability_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    execution_session_id: Mapped[str] = mapped_column(ForeignKey("execution_sessions.id"))
    participant_label: Mapped[str] = mapped_column(String(120), default="lokale buddy")
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CompletionLog(Base):
    __tablename__ = "completion_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    action_id: Mapped[str] = mapped_column(String(36))
    session_id: Mapped[str] = mapped_column(String(36))
    outcome: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TaskSuggestionRecord(Base):
    __tablename__ = "task_suggestions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), default="hermes")
    source_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]", nullable=False)
    suggested_next_action: Mapped[str] = mapped_column(String(300))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    suggested_estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recurrence: Mapped[str | None] = mapped_column(String(80), nullable=True)
    schedule_timezone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    schedule_status: Mapped[str] = mapped_column(String(20), default="none", server_default="none", nullable=False)
    schedule_notes: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]", nullable=False)
    status: Mapped[SuggestionStatus] = mapped_column(SAEnum(SuggestionStatus), default=SuggestionStatus.PENDING)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IntegrationCredential(Base):
    __tablename__ = "integration_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(40), unique=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LocalAccount(Base):
    __tablename__ = "local_account"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    password_hash: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
