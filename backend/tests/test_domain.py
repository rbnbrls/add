from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.domain import choose_action, finish_accountability, finish_session, resolve_blocked_action, start_accountability, start_action
from app.models import Action, ActionStatus, SessionOutcome, Task, TaskStatus


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s: yield s


def add(db, title, text, **kwargs):
    task = Task(title=title, status=TaskStatus.ACTIVE, deadline=kwargs.pop("deadline", None))
    db.add(task); db.flush(); action = Action(task_id=task.id, text=text, **kwargs); db.add(action); db.commit(); return action


def test_selection_prefers_deadline_and_context(db):
    add(db, "Later", "Long action", estimated_minutes=30)
    chosen = add(db, "Due", "Open document", estimated_minutes=5, deadline=datetime.now(timezone.utc) + timedelta(hours=1), requires_home=True)
    assert choose_action(db, is_home=True).id == chosen.id
    assert choose_action(db, is_home=False).id != chosen.id


def test_selection_can_filter_to_low_energy_short_action(db):
    add(db, "Big", "Do big thing", estimated_minutes=30, energy="high")
    small = add(db, "Small", "Open one mail", estimated_minutes=3, energy="low")
    assert choose_action(db, energy="low", max_minutes=5).id == small.id


def test_state_transitions_and_completion_log(db):
    action = add(db, "Mail", "Open mail")
    session = start_action(db, action)
    assert action.status == ActionStatus.ACTIVE
    finish_session(db, session, SessionOutcome.STUCK, "too_big")
    assert action.status == ActionStatus.BLOCKED
    with pytest.raises(ValueError): finish_session(db, session, SessionOutcome.DONE)


def test_done_closes_action(db):
    action = add(db, "Laundry", "Move basket")
    session = start_action(db, action)
    finish_session(db, session, SessionOutcome.DONE)
    assert action.status == ActionStatus.DONE


def test_finished_session_accumulates_actual_minutes_once(db):
    action = add(db, "Tijd", "Werk aan de taak")
    session = start_action(db, action)
    session.started_at = datetime.now(timezone.utc) - timedelta(seconds=61)
    finish_session(db, session, SessionOutcome.CONTINUE)
    db.refresh(action.task)
    assert action.task.actual_minutes == 2
    with pytest.raises(ValueError): finish_session(db, session, SessionOutcome.DONE)


def test_accountability_session_follows_execution_session(db):
    action = add(db, "Focus", "Open the document")
    session = start_action(db, action)
    accountability = start_accountability(db, session, "Ruben")
    assert accountability.status == "running"
    with pytest.raises(ValueError): start_accountability(db, session, "Ruben")
    finish_accountability(db, accountability, "completed")
    assert accountability.status == "completed"
    with pytest.raises(ValueError): finish_accountability(db, accountability, "stopped")


def test_blocked_action_can_be_retried_or_get_a_prerequisite(db):
    action = add(db, "Stuck", "Figure out the first step")
    session = start_action(db, action)
    finish_session(db, session, SessionOutcome.STUCK, "too_big")
    result = resolve_blocked_action(db, action, "create_prerequisite", "Prepare the task", "Find the relevant document")
    assert result["prerequisite"].title == "Prepare the task"
    assert action.status == ActionStatus.BLOCKED
    resolve_blocked_action(db, action, "retry")
    assert action.status == ActionStatus.READY


def test_daily_limit_allows_one_important_and_two_small_actions(db):
    important = add(db, "Important", "Finish important work", estimated_minutes=30)
    small_one = add(db, "Small 1", "First small thing", estimated_minutes=5)
    small_two = add(db, "Small 2", "Second small thing", estimated_minutes=5)
    small_three = add(db, "Small 3", "Third small thing", estimated_minutes=5)
    for action in (important, small_one, small_two):
        session = start_action(db, action)
        finish_session(db, session, SessionOutcome.DONE)
    assert choose_action(db, energy="low", max_minutes=10) is None
    assert choose_action(db, max_minutes=60) is None
    assert small_three.status == ActionStatus.READY
