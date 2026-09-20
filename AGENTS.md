# AGENTS.md

## Project intent

ADD is an execution system, not a planning system. Preserve the rule: show one primary action at a time and reduce activation energy.

## Structure

- `backend/`: FastAPI application, domain logic, SQLAlchemy models, tests.
- `frontend/`: Next.js app for the `NU` and Inbox flows.
- `docs/`: product, architecture, integration and deployment contracts.
- `.planning/`: project requirements and staged roadmap.

## Engineering rules

1. Execution App is the source of truth for tasks, actions, sessions and completions.
2. Hermes may suggest, decompose and draft; it does not write directly to the database.
3. Home Assistant supplies context and receives a mirror; it does not own task state.
4. Keep state transitions explicit and test them.
5. Do not add Redis, background workers, gamification or complex planning without a measured MVP need.
6. Never expose more than one primary action in the main UI.

## Verification

Run `pytest` in `backend/` and `npm run build` in `frontend/` before shipping a change.
