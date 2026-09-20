# ADD product specification

## Purpose

ADD closes the gap between intention and action. It presents one physically executable next action, starts a forgiving short session, and makes stopping or being stuck valid outcomes.

## Core concepts

- **Task:** desired outcome, possibly vague or large.
- **Action:** one concrete step that can be performed now. A task has one current action in the MVP.
- **Inbox:** low-friction capture; no deadline, category or estimate required.
- **Now:** one selected action. At most three alternatives may be exposed outside the primary card.
- **Session:** a bounded attempt to execute an action.
- **Completion log:** append-only record of session outcomes.

## States

Task: `inbox → active → done` (or `archived`). Action: `ready → active → done`, with `blocked` after stuck and `ready` again after continue/stop-for-today. Sessions end with `done`, `continue`, `stuck` or `stop_for_today`.

## MVP acceptance criteria

1. A user can capture a task in one short form.
2. A task can receive a concrete next action.
3. `GET /api/now` returns no more than one action.
4. Start creates a session and marks the action active.
5. Every terminal session outcome is recorded; double-finish is rejected.
6. Selection respects home, computer, energy and duration constraints and favors imminent deadlines.
7. Hermes suggestions enter through an API boundary; Home Assistant context can be passed to selection.
