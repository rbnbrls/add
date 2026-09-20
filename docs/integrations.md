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
