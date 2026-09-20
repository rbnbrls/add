# API contracts

All IDs are opaque UUID strings. Timestamps are ISO-8601. The HTTP API is the stable boundary for the future Hermes MCP adapter.

## Create a task

`POST /api/tasks`

```json
{
  "title": "Belastingaangifte 2025",
  "source_type": "manual",
  "next_action": {
    "text": "Open Mijn Belastingdienst en log in",
    "estimated_minutes": 5,
    "energy": "low",
    "requires_home": false,
    "requires_computer": true
  }
}
```

Tasks also support `description`, `category`, `deadline`, `planned_at`,
`actual_minutes`, `parent_id`, `tags` and `priority`. `planned_at` is the
intended start/planning moment; `deadline` remains the latest acceptable
moment. `priority` is `low`, `medium` or `high`, and tags are a normalized
JSON list of unique non-empty strings.

`PATCH /api/tasks/{id}` applies only supplied fields. Sending `null` clears a
nullable field such as `description`, `deadline`, `planned_at` or `parent_id`.
Parent changes that point to the task itself or one of its descendants return
`409`. `DELETE /api/tasks/{id}` returns `409` when the task has children or an
active execution session; otherwise it removes the leaf task and its linked
execution records transactionally.

Example metadata payload:

```json
{
  "planned_at": "2026-09-19T10:00:00+02:00",
  "deadline": "2026-09-20T17:00:00+02:00",
  "actual_minutes": 25,
  "tags": ["werk", "administratie"],
  "priority": "high"
}
```

## Hermes suggestion

`POST /api/mcp/task-suggestions` (requires `X-ADD-Token` when configured)

```json
{
  "title": "Reageren op verzekeraar",
  "description": "Documenten zijn vóór vrijdag nodig.",
  "source_type": "email",
  "source_ref": "gmail:message-id",
  "deadline": "2026-09-18T17:00:00+02:00",
  "suggested_next_action": "Open de e-mail en lees welke documenten gevraagd worden.",
  "confidence": 0.91
}
```

Suggestions are created with `pending` status. Accept explicitly with
`POST /api/mcp/task-suggestions/{id}/approve` or reject with
`POST /api/mcp/task-suggestions/{id}/reject`.

`POST /api/mcp` (alias `/api/mcp/rpc`) exposes a token-protected JSON-RPC bridge
with `initialize`, `ping`, `resources/list`, `prompts/list`, `tools/list` and `tools/call` for the `execution_*`
Hermes tools, including the complete start/complete/stuck lifecycle. Suggestions
created through this bridge remain pending. Send `X-ADD-Token` when
`ADD_API_TOKEN` is not `change-me`.

`prompts/list` exposes the `decompose_task`, `draft_message` and `resolve_stuck`
templates. `prompts/get` returns the selected template with placeholders; it does
not call an AI provider.

## Current action

## Task decomposition

`POST /api/tasks/{id}/decompositions` accepts `{ "child_count": 3 }`, where
`child_count` is between 2 and 8. The endpoint calls the internal structured
LLM gateway and stores the result as a pending decomposition proposal; the LLM
never writes tasks or actions.

`GET /api/tasks/{id}/decompositions` returns the proposal history, including
the ordered child-task preview. Approve or reject the complete batch explicitly
with `POST /api/decompositions/{proposal_id}/approve` or
`POST /api/decompositions/{proposal_id}/reject`.

Approval creates each child as an `inbox` task with `parent_id` set to the
original task and creates no action or execution session. Only pending
proposals can be decided. Duplicate child titles in provider output are
invalid; titles already present under the parent are not proposed again, and a
second approval/rejection returns `409`. Decomposition proposals and items are
included in backups when present, while older backups remain valid.

`POST /api/mcp/create-message-draft` returns a draft with `send_required: true`; it does not send anything. `POST /api/mcp/send-message` requires `{confirmed: true}` and otherwise returns `409`; the MVP returns a confirmed `sent` result without connecting an external provider.

`GET /api/mcp/current-action` returns one action or `404` when none is eligible. `GET /api/now` accepts `is_home`, `energy`, `computer_available` and `max_minutes` for Home Assistant/context-aware selection.

`GET /api/reminders/preview` applies the same context selection and returns a quiet or ready preview without sending a notification.

`GET /api/daily-review?timezone=Europe/Amsterdam` is a read-only aggregation of
pending proposals, unplanned inbox tasks, overdue tasks and tasks planned for
today. It returns exactly one `next_decision` (`review`, `plan`, `overdue`,
`today` or `quiet`) with a safe navigation target; it never starts, completes,
plans or rejects anything. A disabled reminder provider and quiet-hours window
remain explicit preview states. Routine materialization continues through
`POST /api/routines/{routine_id}/materialize`; the occurrence key is
`routine_id + occurrence_date`, the resulting task carries `source_type:
"routine"` and a stable `source_ref`, and a retry returns
`already_materialized` without creating a duplicate.

`POST /api/offline/complete` is accepted only for an action that is still
`ready`. A stale, missing or otherwise changed action returns `409` with an
`offline conflict` detail. The client stores that conflict locally until the
user explicitly dismisses it; it never silently retries against a different
action or overwrites server state.

`GET /api/widget` is a compact read-only cross-device read model. It returns
the context-selected `next_action` when one is available, the number of open
proposals and canonical `capture_url`, `review_url` and `execute_url` targets.
It does not create, start or complete anything. The PWA manifest exposes
shortcuts to the quick capture route (`/intake?quick=1`) and NU; the global
command menu uses the same canonical routes and is opened with Ctrl/Cmd+K.

`GET /api/backup/export` returns a JSON backup of domain collections without mutating state.
`POST /api/backup/validate` validates that backup shape without mutating state; it is used by the `/backup` UI before any future restore workflow.
`POST /api/backup/preview` returns the same validation plus an explicit non-mutating restore preview.

## Session lifecycle

- `POST /api/actions/{action_id}/start` → `{session_id, action}`
- `GET /api/sessions/active` returns the current running session and its `started_at`, or `null`; the focus UI uses this to restore a session after reload.
- `POST /api/sessions/{session_id}/finish` with `{outcome, stuck_reason?}`
- `outcome`: `done | continue | stuck | stop_for_today`
- `GET /api/actions?status=blocked` lists actions needing a resolution.
- `POST /api/actions/{action_id}/resolve` with `resolution: retry` or `resolution: create_prerequisite` (the latter also requires `prerequisite_title` and `prerequisite_action`).
- `GET /api/completions` returns the latest 100 append-only session outcomes for audit and UI history, enriched with task title and action text when available.
- `GET /api/today-summary` returns a read-only daily summary of outcomes, ready/blocked work, daily-limit progress, a short headline and the next open deadline when available.

Future MCP tools map one-to-one to these commands and must preserve the same transition rules.

## Internal LLM gateway

The backend exposes an internal synchronous `LLMGateway` service for structured
JSON generation. It supports OpenAI-compatible `POST {base_url}/chat/completions`
providers, including Ollama and LM Studio. The base URL, model and timeout are
configured through environment settings; the API key is read from the encrypted
credential vault under provider `llm` by default.

The gateway adds the requested Pydantic model's JSON Schema to the system prompt,
requires one plain JSON object, validates the response and returns a typed model.
It is not exposed as an HTTP endpoint, does not write tasks/actions/sessions, and
does not call an AI provider through the MCP adapter. F3, F4 and F5 are the first
planned consumers.

## Text assistance tools

`POST /api/text/rewrite` accepts `text` (1–4000 characters) and `tone` (`formal`
or `informal`). It returns a temporary rewritten `text` in Dutch. The endpoint
preserves meaning, does not add facts and does not store or send the result.

`POST /api/text/analyze` accepts `text` (1–4000 characters) and returns the Dutch
fields `tone`, `emotion`, `directness` and `attention_point`. The result is
temporary and is not persisted. Both endpoints require the normal API auth
boundary and map expected LLM configuration, provider, timeout and response
errors to a safe HTTP 503 without exposing provider details or secrets.

## Natural-language inbox capture

`POST /api/inbox/capture` accepts a trimmed `text` value of 1–4000 characters
and creates a pending proposal through the internal LLM gateway. Optional
`source_type` values are `natural_language`, `shortcut`, `web_link` and
`voice_transcript`; a
`web_link` requires a valid `http`/`https` `source_ref`, while a `shortcut`
derives a stable source reference from the text unless `idempotency_key` is
provided. A voice transcript may provide a provider-owned `source_ref`; ADD
stores the transcript as text and does not store audio. The optional `timezone`
defaults to `Europe/Amsterdam` and is validated before scheduling. Repeating a shortcut with the same source reference or a web link
with the same URL returns the original pending proposal without another
provider call. The response
contains `mode: "parsed"` or `mode: "plain_text"` and a suggestion with the
original input, title, description, planned time, tags, suggested next action and
confidence. When scheduling language is detected, the suggestion additionally
contains `deadline`, `parsed_duration_minutes`, `recurrence`,
`schedule_timezone`, `schedule_status` (`none`, `parsed` or `ambiguous`) and
`schedule_notes`. These fields are advisory metadata until the user explicitly
approves or plans the proposal; ambiguous values never auto-approve. The
original input is stored separately for auditability.

Provider, timeout or structured-output failures never discard the capture. They
create a pending `plain_text` proposal with safe defaults and still require
explicit approval through the existing task-suggestion review endpoints.

Approval copies the parsed metadata into a Task and creates its first Action;
rejection creates neither. The existing `POST /api/tasks` contract is unchanged.

## Generic inbox review funnel

`POST /api/inbox/brain-dump` accepts the same trimmed `text` shape as natural
language capture and returns a list of pending `SuggestionOut` records. The
records share a `batch_id` and `source_ref`, retain the original input, and
can be approved or rejected independently through the existing generic
suggestion decision endpoints. Provider failures create one safe plain-text
proposal for review instead of mutating task state.

`GET /api/inbox/review` returns the oldest pending proposal from all supported
sources, or `404` when the queue is empty. Email, chat, calendar, Home
Assistant and brain-dump intake all use this same queue. Calendar intake
creates an action proposal with the event start as its deadline; it does not
create a calendar block automatically.

## Smart views

`GET /api/smart-views/query` is a read-only task query accepting the bounded
filters `period=today|week`, `overdue`, `source`, `priority`, `blocked`,
`unplanned` and `timezone`. Completed and archived tasks are excluded from
these operational views. Date boundaries are calculated in the requested IANA
timezone and returned as ordinary `TaskOut` records; the endpoint never starts,
plans, completes or mutates a task.

`POST /api/smart-views` stores a local named view with the same explicit filter
shape. At most three views exist at once; duplicate names and invalid timezones
are rejected. `GET /api/smart-views/{id}/tasks` evaluates a saved view using the
same read-only query path, so Review and Plan can use one consistent source of
filtered task context. `DELETE /api/smart-views/{id}` removes only the saved
view. The backup export includes `smart_views`, and restore treats the field as
optional for backwards-compatible backups.

`POST /api/inbox/review/{suggestion_id}/estimate` asks the internal LLM gateway
for an optional advisory estimate and stores it as
`suggested_estimated_minutes` on the pending proposal. It does not create or
update a task or action. Approval accepts an optional
`{"estimated_minutes": 15}` body; that value takes precedence over the
advisory estimate, which otherwise takes precedence over the action default.
Only approval writes `Action.estimated_minutes`.

## Inbox planning and replan

`POST /api/inbox/review/{suggestion_id}/plan` makes one explicit planning
decision for a pending proposal. `destination` is `today`, `at` or `inbox`;
the first two require `start_at` and `duration_minutes`. The endpoint creates
the task/action only after the planning decision is valid, stores `planned_at`
and a `plan_blocks` read model when scheduled, and never starts execution.
Past starts return `422` and overlapping blocks return `409`.

`POST /api/tasks/{task_id}/replan` accepts `inbox`, `next_free` or `at`. It
requires one explicit destination, is idempotent when the requested schedule
already matches, and records the inverse transition. `POST /api/planning/undo`
undoes only the latest not-yet-undone planning decision. Planning decisions are
append-only apart from their `undone_at` marker and are included in backups.

## Home Assistant adapter

- `GET /api/ha/now` accepts `is_home`, `energy`, `computer_available` and `max_minutes` as query parameters and requires `X-ADD-Token` when configured.
- `GET /api/ha/todo-mirror` returns only task title, status, due date and current action.
- `POST /api/ha/sync` sends the mirror to `HA_WEBHOOK_URL` when configured. The payload is marked with `origin: "add"`; without a URL it returns `disabled` and performs no network call.
- `GET /api/ha/outbox` returns the latest mirror events and their `pending`, `delivered` or `failed` status.
- `POST /api/ha/poll` reads context from `HA_CONTEXT_URL` when configured and returns the selected action; without a URL it returns `disabled`. Polling is explicit and synchronous in the MVP.
- `GET /api/ha/config` exposes only non-secret runtime flags for the GUI, including whether live context and webhook delivery are configured.
- `POST /api/ha/outbox/{event_id}/retry` retries a pending or failed mirror event against `HA_WEBHOOK_URL`; delivered events cannot be sent twice.
- `POST /api/ha/events` turns an inbound HA event into a pending suggestion; it never changes task state directly. Events with `origin: "add"` are rejected to prevent mirror loops.
