# Architecture

```text
Next.js UI ──HTTP──> FastAPI domain API ──SQLAlchemy──> PostgreSQL
                         ↑       ↓              ↓
                 Hermes MCP   mail loop      provider APIs
                              (15 min)   Gmail · Graph · IMAP
```

The API is the only writer of domain state. The app is the source of truth. External systems provide suggestions/context or receive a deliberately limited mirror. Alembic is the schema authority for deployed and local databases; `Base.metadata.create_all()` is reserved for isolated test databases.

Application runtime preferences are stored in `app_preferences` and encrypted
credentials in `integration_credentials`; the Settings GUI is the source of
truth for API-token, cookie, mail, GitHub, LLM and integration configuration.
Environment values remain bootstrap fallbacks only. Database URLs, PostgreSQL
credentials, container images, ports, volumes and healthchecks remain Docker
deployment configuration because changing them requires a process/container
restart and cannot safely be applied by the running application.

The first MVP uses no Redis and no worker: selection and state transitions are short, synchronous transactions. A worker becomes justified only for retries, scheduled intake, or outbound notification volume.

## Boundaries

- `domain.py`: deterministic selection and state transitions.
- `main.py`: transport/API layer.
- `models.py`: persistence model.
- frontend: presentation only; it must not implement selection rules.
- `mail.py`: provider-neutral mailbox adapters and rules-first classification.
  Persisted mail data is metadata, a short snippet and an action audit only.

Mailbox processing runs in the API process for the single-replica deployment.
A database lease prevents duplicate runs. The loop is dormant until the user
enables mail polling in ADD preferences; a separate queue/worker remains a
later scale decision.

## Production hardening after MVP

Add structured logging and rate limiting on integration endpoints before multi-user or internet exposure. Authentication/session management, request idempotency, backups and encrypted secret storage are already present in the current MVP, but still require operational hardening.
