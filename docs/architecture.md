# Architecture

```text
Next.js UI ──HTTP──> FastAPI domain API ──SQLAlchemy──> PostgreSQL
                         ↑                 ↓
                 Hermes MCP adapter   Home Assistant adapter
```

The API is the only writer of domain state. The app is the source of truth. External systems provide suggestions/context or receive a deliberately limited mirror. Alembic is the schema authority for deployed and local databases; `Base.metadata.create_all()` is reserved for isolated test databases.

The first MVP uses no Redis and no worker: selection and state transitions are short, synchronous transactions. A worker becomes justified only for retries, scheduled intake, or outbound notification volume.

## Boundaries

- `domain.py`: deterministic selection and state transitions.
- `main.py`: transport/API layer.
- `models.py`: persistence model.
- frontend: presentation only; it must not implement selection rules.

## Production hardening after MVP

Add structured logging and rate limiting on integration endpoints before multi-user or internet exposure. Authentication/session management, request idempotency, backups and encrypted secret storage are already present in the current MVP, but still require operational hardening.
