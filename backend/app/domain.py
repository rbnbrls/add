from datetime import date, datetime, time, timezone
from math import ceil
from random import Random
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from .models import AccountabilitySession, Action, ActionStatus, CompletionLog, ExecutionSession, SessionOutcome, Task, TaskRolloverEvent, TaskStatus


def choose_action(db: Session, *, is_home: bool = True, energy: str = "medium", computer_available: bool = True, max_minutes: int | None = None, strategy: str = "deterministic", seed: int | None = None):
    """Return one ready action. Ranking favors overdue/soon tasks, then short low-friction work."""
    candidates = db.scalars(select(Action).join(Task).where(Action.status == ActionStatus.READY, Task.status != TaskStatus.DONE)).all()
    important_done, small_done = daily_completion_counts(db)
    now = datetime.now(timezone.utc)
    def score(a: Action):
        task = a.task
        if a.requires_home and not is_home: return -10_000
        if a.requires_computer and not computer_available: return -10_000
        if max_minutes is not None and a.estimated_minutes > max_minutes: return -10_000
        if a.estimated_minutes >= 30 and important_done >= 1: return -10_000
        if a.estimated_minutes < 30 and small_done >= 2: return -10_000
        value: float = 0
        value += {"high": 20, "medium": 10, "low": 0}.get(task.priority.value if hasattr(task.priority, "value") else task.priority, 10)
        if task.deadline:
            deadline = task.deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            hours = (deadline - now).total_seconds() / 3600
            value += 100 if hours < 0 else max(0, 48 - hours)
        if a.energy == energy: value += 25
        if a.energy == "low": value += 10
        value += max(0, 15 - a.estimated_minutes)
        return value
    eligible = [candidate for candidate in candidates if score(candidate) > -10_000]
    if not eligible: return None
    if strategy == "weighted_random":
        weights = [max(1, score(candidate) + 1) for candidate in eligible]
        return Random(seed).choices(eligible, weights=weights, k=1)[0]
    return sorted(eligible, key=score, reverse=True)[0]


def daily_completion_counts(db: Session):
    """Return today's done count as (important, small); 30 minutes is the MVP boundary."""
    today = datetime.now(timezone.utc).date()
    important = small = 0
    for log in db.scalars(select(CompletionLog).where(CompletionLog.outcome == SessionOutcome.DONE.value)).all():
        created = log.created_at
        if created and (created.date() if created.tzinfo else created.date()) == today:
            action = db.get(Action, log.action_id)
            if action:
                if action.estimated_minutes >= 30: important += 1
                else: small += 1
    return important, small


def start_action(db: Session, action: Action):
    if action.status != ActionStatus.READY: raise ValueError("action is not ready")
    action.status = ActionStatus.ACTIVE
    session = ExecutionSession(action_id=action.id)
    db.add(session); db.commit(); db.refresh(session)
    return session


def pause_session(db: Session, session: ExecutionSession):
    if session.outcome != SessionOutcome.RUNNING: raise ValueError("session already finished")
    if session.paused_at is not None: raise ValueError("session already paused")
    session.paused_at = datetime.now(timezone.utc); db.commit(); db.refresh(session); return session


def resume_session(db: Session, session: ExecutionSession):
    if session.outcome != SessionOutcome.RUNNING: raise ValueError("session already finished")
    if session.paused_at is None: raise ValueError("session is not paused")
    paused_at = session.paused_at
    if paused_at.tzinfo is None: paused_at = paused_at.replace(tzinfo=timezone.utc)
    session.paused_seconds += max(0, ceil((datetime.now(timezone.utc) - paused_at).total_seconds()))
    session.paused_at = None; db.commit(); db.refresh(session); return session


def finish_session(db: Session, session: ExecutionSession, outcome: SessionOutcome, stuck_reason: str | None = None):
    if session.outcome != SessionOutcome.RUNNING: raise ValueError("session already finished")
    action = db.get(Action, session.action_id)
    if not action:
        raise ValueError("session action no longer exists")
    session.outcome = outcome; session.stuck_reason = stuck_reason; session.ended_at = datetime.now(timezone.utc)
    task = db.get(Task, action.task_id)
    started_at = session.started_at
    ended_at = session.ended_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    elapsed_seconds = max(0, (ended_at - started_at).total_seconds() - session.paused_seconds)
    if task and elapsed_seconds:
        task.actual_minutes += ceil(elapsed_seconds / 60)
    if outcome == SessionOutcome.DONE: action.status = ActionStatus.DONE
    elif outcome == SessionOutcome.STUCK: action.status = ActionStatus.BLOCKED
    elif outcome in (SessionOutcome.CONTINUE, SessionOutcome.STOP_FOR_TODAY): action.status = ActionStatus.READY
    if task and outcome == SessionOutcome.STOP_FOR_TODAY:
        task.defer_count += 1
        task.last_deferred_at = ended_at
    db.add(CompletionLog(action_id=action.id, session_id=session.id, outcome=outcome.value))
    db.commit(); db.refresh(session)
    return session


def day_window(day: date, timezone_name: str):
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid timezone") from exc
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start.replace(hour=23, minute=59, second=59, microsecond=999999), tz


def check_day_rollover(db: Session, day: date, timezone_name: str):
    start, _, tz = day_window(day, timezone_name)
    start_utc = start.astimezone(timezone.utc)
    previous = db.scalars(select(Task).where(Task.planned_at.is_not(None), Task.planned_at < start_utc, Task.status.not_in((TaskStatus.DONE, TaskStatus.ARCHIVED)))).all()
    rolled = []
    skipped = []
    for task in previous:
        active = db.scalar(select(ExecutionSession.id).join(Action).where(Action.task_id == task.id, ExecutionSession.outcome == SessionOutcome.RUNNING).limit(1))
        if active:
            skipped.append(task.id)
            continue
        exists = db.scalar(select(TaskRolloverEvent.id).where(TaskRolloverEvent.task_id == task.id, TaskRolloverEvent.rollover_date == day))
        if exists:
            continue
        old = task.planned_at
        if old is None:
            # The query above selects only tasks with a planned_at, so a null
            # here means the row changed underneath the rollover pass.
            continue
        local_old = old.replace(tzinfo=timezone.utc).astimezone(tz) if old.tzinfo is None else old.astimezone(tz)
        local_new = start.replace(hour=local_old.hour, minute=local_old.minute, second=local_old.second, microsecond=local_old.microsecond)
        task.planned_at = local_new.astimezone(timezone.utc)
        db.add(TaskRolloverEvent(task_id=task.id, rollover_date=day, from_planned_at=old, to_planned_at=task.planned_at))
        rolled.append(task.id)
    db.commit()
    return {"date": day, "timezone": timezone_name, "rolled_over": len(rolled), "rolled_over_task_ids": rolled, "skipped_active": skipped}


def validate_parent(db: Session, task: Task, parent_id: str | None):
    if parent_id is None:
        return
    if parent_id == task.id:
        raise ValueError("a task cannot be its own parent")
    parent = db.get(Task, parent_id)
    if not parent:
        raise ValueError("parent task not found")
    current: Task | None = parent
    visited = set()
    while current:
        if current.id in visited:
            raise ValueError("task hierarchy already contains a cycle")
        visited.add(current.id)
        if current.id == task.id:
            raise ValueError("parent relationship would create a cycle")
        current = current.parent


def delete_task(db: Session, task: Task):
    if task.children:
        raise ValueError("cannot delete a task with children")
    action_ids = [action.id for action in task.actions]
    if action_ids and db.scalar(select(ExecutionSession.id).where(ExecutionSession.action_id.in_(action_ids), ExecutionSession.outcome == SessionOutcome.RUNNING).limit(1)):
        raise ValueError("cannot delete a task with an active session")
    session_ids = [row[0] for row in db.execute(select(ExecutionSession.id).where(ExecutionSession.action_id.in_(action_ids))).all()] if action_ids else []
    if session_ids:
        db.execute(delete(CompletionLog).where(CompletionLog.session_id.in_(session_ids)))
        db.execute(delete(ExecutionSession).where(ExecutionSession.id.in_(session_ids)))
    for action in list(task.actions):
        db.delete(action)
    db.delete(task)
    db.commit()


def start_accountability(db: Session, session: ExecutionSession, participant_label: str):
    if session.outcome != SessionOutcome.RUNNING:
        raise ValueError("execution session is not running")
    existing = db.scalar(select(AccountabilitySession).where(AccountabilitySession.execution_session_id == session.id, AccountabilitySession.status == "running"))
    if existing:
        raise ValueError("accountability session already running")
    accountability = AccountabilitySession(execution_session_id=session.id, participant_label=participant_label)
    db.add(accountability); db.commit(); db.refresh(accountability)
    return accountability


def finish_accountability(db: Session, accountability: AccountabilitySession, status: str):
    if accountability.status != "running":
        raise ValueError("accountability session already finished")
    if status not in ("completed", "stopped"):
        raise ValueError("invalid accountability status")
    accountability.status = status; accountability.ended_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(accountability)
    return accountability


def resolve_blocked_action(db: Session, action: Action, resolution: str, prerequisite_title: str | None = None, prerequisite_action: str | None = None):
    if action.status != ActionStatus.BLOCKED:
        raise ValueError("action is not blocked")
    if resolution == "retry":
        action.status = ActionStatus.READY
        db.commit()
        db.refresh(action)
        return {"action": action, "prerequisite": None}
    if resolution != "create_prerequisite" or not prerequisite_title or not prerequisite_action:
        raise ValueError("prerequisite title and action are required")
    task = Task(title=prerequisite_title, status=TaskStatus.ACTIVE, source_type="stuck_resolver")
    db.add(task)
    db.flush()
    db.add(Action(task_id=task.id, text=prerequisite_action, estimated_minutes=10))
    db.commit()
    db.refresh(task)
    return {"action": action, "prerequisite": task}
