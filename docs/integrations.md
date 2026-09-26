# Integrations

## Hermes Agent

Hermes is intake, decomposition and drafting. It must use API/MCP tools and never access PostgreSQL directly.

Planned MCP tools:

- `execution_create_task_suggestion`
- `execution_get_current_action`
- `execution_start_action`
- `execution_complete_action`
- `execution_mark_stuck`
- `execution_get_today_status`
- `execution_search_tasks`
- `execution_create_message_draft`

Current HTTP contract: `POST /api/mcp/task-suggestions` accepts `title`, optional description/source/deadline, `suggested_next_action` and confidence. Low-confidence suggestions should later remain pending for approval; the MVP endpoint is deliberately isolated so that policy can be added without changing the domain model.

## Home Assistant

Home Assistant supplies `is_home` and optionally a computer/room context. The selection endpoint accepts `is_home`, `energy`, `computer_available` and `max_minutes`. A future adapter may poll a configured REST entity or receive a webhook.

Todo mirror rule: mirror only task title, current action text, status and due date. Updates originate in ADD; inbound HA todo edits must be treated as commands/suggestions, never as authoritative state.

## Gmail, Calendar and WhatsApp (later)

These belong in phases 2/3 behind Hermes. Gmail and Calendar produce candidate suggestions; calendar events are context, not automatic todos. WhatsApp may expose conversational intake and drafts, but sending always requires explicit user confirmation. Personal WhatsApp Web/Baileys has account-risk implications; an official business API is a separate deployment choice.

## Mail intake and triage

Mail accounts are configured through `/mail` and are stored as encrypted
provider credentials. Supported providers are Gmail, Microsoft Graph/Outlook
and IMAP. SMTP credentials may be kept with the account for a future sender,
but ADD does not send replies in this slice.

`POST /api/mail/sync` runs an idempotent bounded batch. The optional API-process
poller runs every 15 minutes when mail polling is enabled in the ADD settings.
A database lease
prevents concurrent runs. Provider cursors are stored per account and failed
accounts expose only a generic error in the API.

Rules run before the LLM: provider spam, `List-Unsubscribe`, mailing headers and
sender history are preferred. Remaining messages may be classified as
`personal`, `action`, `meeting` or `unknown` through the existing LLM gateway.
Only spam archive and high-confidence newsletter unsubscribe/trash are automatic;
messages needing user judgment become normal pending ADD suggestions. Permanent
delete and automatic sending are not supported.

MCP mail tools are read-only or explicit: `get_mail_summary`,
`get_mail_triage_queue`, `approve_mail_action`, `retry_mail_sync`,
`create_task_from_email` and `draft_reply_from_email`.

The Settings GUI is the runtime configuration surface. It stores provider
credentials encrypted and controls mail cadence, cleanup confidence, API token,
GitHub feedback configuration and cookie behavior. `.env`/Compose values are
only bootstrap fallbacks; PostgreSQL connection and container/deployment
settings remain outside the running application.
