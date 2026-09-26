import asyncio
import json
import hashlib
import hmac
import logging
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from typing import Literal, Sequence, cast
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import uuid4
import httpx
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import ValidationError
from fastapi.encoders import jsonable_encoder
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from .config import settings
from .capture import NaturalLanguageCaptureResult, estimate_suggestion, parse_brain_dump, parse_capture, parse_schedule, plain_text_capture
from .decomposition import decompose_task, item_from_child, remove_existing_children
from .db import SessionLocal, get_db
from .domain import check_day_rollover, choose_action, daily_completion_counts, day_window, delete_task, finish_accountability, finish_session, pause_session, resolve_blocked_action, resume_session, start_accountability, start_action, validate_parent
from .llm import LLMError, LLMGateway, fetch_openrouter_free_models
from .models import AccountabilitySession, Action, ActionStatus, AppPreference, BackupSnapshot, CompletionLog, DecompositionStatus, ExecutionSession, IntegrationCredential, LocalAccount, OutboxEvent, PlanBlock, PlanningDecision, ReminderPreference, Routine, RoutineOccurrence, SavedView, SessionOutcome, SuggestionStatus, Task, TaskDecompositionItem, TaskDecompositionProposal, TaskPriority, TaskRolloverEvent, TaskStatus, TaskSuggestionRecord
from .schemas import AccountabilityFinishRequest, AccountabilityOut, AccountabilityStartRequest, ActionCreate, ActionOut, AppPreferenceOut, AppPreferenceUpdate, BlockTaskRequest, BrainDumpProposal, CompletionOut, DailyReviewCompleteOut, DailyReviewCompleteRequest, DayCheckRequest, DecompositionApprovalRequest, DecompositionApprovalOut, DecompositionProposalOut, DecompositionRequest, FreeLLMModelCatalogOut, HAContext, HAEvent, LLMSettingsOut, MessageDraft, NaturalLanguageCaptureRequest, NaturalLanguageCaptureResponse, OfflineCompletion, PlanBlockCreate, PlanBlockOut, PlanSuggestionRequest, PlanningDecisionOut, ReminderSettings, ResolveBlockedActionRequest, ReplanRequest, RoutineCreate, RoutineOut, SendMessageRequest, SessionResult, SmartViewCreate, SmartViewFilters, SmartViewOut, StartOut, SuggestionApproval, SuggestionOut, TaskCreate, TaskOut, TaskUpdate, TaskSuggestion, TodayStatus, TextRewriteRequest, TextRewriteResponse, ToneAnalysisRequest, ToneAnalysisResponse, WorkflowSummaryOut
from .security import credential_box, read_encrypted_credential
from .text_assistance import analyze_tone, rewrite_text
from .github_issue import create_github_issue

@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(mail_poll_loop())
    try:
        yield
    finally:
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass


app = FastAPI(title="ADD API", version="0.1.0", lifespan=lifespan)

request_log = logging.getLogger("add.api")
_rate_buckets: dict[tuple[str, str], list[float]] = {}


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = settings.api_cors_origins.split(",")
        try:
            with SessionLocal() as db:
                preference = db.scalar(select(AppPreference).order_by(AppPreference.id.asc()))
                if preference:
                    allowed = preference.api_cors_origins.split(",")
        except Exception:
            pass
        if request.method == "OPTIONS" and origin and origin.strip() in {item.strip() for item in allowed}:
            response = Response(status_code=204)
        else:
            response = await call_next(request)
        if origin and origin.strip() in {item.strip() for item in allowed}:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = request.headers.get("access-control-request-headers", "*")
            response.headers["Vary"] = "Origin"
        return response


app.add_middleware(DynamicCORSMiddleware)


class OperationalMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        key = (request.client.host if request.client else "unknown", request.url.path)
        now = time.monotonic()
        if request.url.path.startswith(("/api/connectors/", "/api/mcp/", "/api/feedback")):
            recent = [stamp for stamp in _rate_buckets.get(key, []) if stamp > now - 60]
            if len(recent) >= 30:
                response = JSONResponse({"detail": "rate limit exceeded", "request_id": request_id}, status_code=429, headers={"X-Request-ID": request_id, "Retry-After": "60"})
                return response
            recent.append(now); _rate_buckets[key] = recent
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            request_log.exception("request_failed", extra={"request_id": request_id, "path": request.url.path})
            raise
        response.headers["X-Request-ID"] = request_id
        request_log.info("request_complete", extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 2)})
        return response


app.add_middleware(OperationalMiddleware)


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000).hex()
    return f"{salt}${digest}"


def password_matches(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000).hex()
        return hmac.compare_digest(candidate, digest)
    except ValueError: return False


def auth(x_add_token: str | None = Header(default=None), add_session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    account = db.scalar(select(LocalAccount))
    preference = db.scalar(select(AppPreference).order_by(AppPreference.id.asc()))
    configured_api_token = read_encrypted_credential(db, "runtime:add-api-token") or settings.add_api_token
    if account or settings.local_login_password:
        if add_session != settings.session_secret: raise HTTPException(401, "login required")
    elif configured_api_token != "change-me" and x_add_token != configured_api_token: raise HTTPException(401, "invalid token")


@app.post("/api/feedback", dependencies=[Depends(auth)])
async def feedback(payload: dict, db: Session = Depends(get_db)):
    """Turn user feedback into a labelled GitHub issue."""
    kind = str(payload.get("type") or "feature").strip().lower()
    title = str(payload.get("title") or "").strip()
    description = str(payload.get("description") or "").strip()
    if kind not in {"bug", "feature"}:
        raise HTTPException(422, "type must be bug or feature")
    if not title:
        raise HTTPException(422, "title is required")
    if not description:
        raise HTTPException(422, "description is required")
    if len(title) > 160 or len(description) > 4000:
        raise HTTPException(422, "feedback is too long")
    preference = get_app_preference(db)
    github_token = read_encrypted_credential(db, "runtime:github-token") or settings.github_token
    if not github_token:
        raise HTTPException(503, "GitHub feedback is not configured")

    label = "bug" if kind == "bug" else "enhancement"
    result = await create_github_issue(
        token=github_token,
        repository=preference.github_repo or settings.github_repo,
        title=f"[{kind.upper()}] {title}",
        body=f"## Feedback uit ADD\n\n**Type:** {kind}\n\n---\n\n{description}",
        labels=[label, "feedback"],
    )
    if not result.success:
        raise HTTPException(502 if result.status_code else 503, result.error or "feedback kon niet worden verzonden")
    return {"success": True, "issue_url": result.issue_url, "issue_number": result.issue_number}


def ha_connection(db: Session) -> dict:
    item = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == "home-assistant-connection"))
    if item:
        try: return json.loads(credential_box().decrypt(item.encrypted_value.encode()).decode())
        except Exception: pass
    return {"webhook_url": settings.ha_webhook_url, "context_url": settings.ha_context_url, "token": settings.ha_webhook_token}


def valid_endpoint(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def get_llm_gateway(db: Session = Depends(get_db)) -> LLMGateway:
    return LLMGateway(db)


def _mail_adapter(account: MailAccount, db: Session) -> MailAdapter:
    credential = read_json_credential(db, account.credential_provider) or {}
    if account.provider == MailProvider.GMAIL: return GmailAdapter(credential)
    if account.provider == MailProvider.OUTLOOK: return GraphAdapter(credential)
    return ImapAdapter(credential)


def _mail_lease(db: Session, owner: str, seconds: int = 600) -> bool:
    now = datetime.now(timezone.utc)
    lease = db.get(MailSyncLease, "global")
    if lease and lease.expires_at > now and lease.owner != owner:
        return False
    if not lease:
        lease = MailSyncLease(id="global", owner=owner, expires_at=now + timedelta(seconds=seconds)); db.add(lease)
    else:
        lease.owner = owner; lease.expires_at = now + timedelta(seconds=seconds)
    db.commit()
    return True


def _mail_action(adapter: MailAdapter, item: MailItem, action: str):
    if action == "archive": adapter.archive(item)
    elif action == "trash": adapter.move_to_trash(item)
    elif action == "unsubscribe": adapter.unsubscribe(item)
    else: raise ValueError("unsupported mail action")


def sync_mailboxes(db: Session, owner: str = "manual") -> dict:
    if not _mail_lease(db, owner): return {"status": "busy", "processed": 0, "accounts": 0}
    processed = 0; created = 0; automatic = 0; errors = []
    accounts = db.scalars(select(MailAccount).where(MailAccount.status == MailAccountStatus.ACTIVE)).all()
    for account in accounts:
        try:
            adapter = _mail_adapter(account, db)
            preference = get_app_preference(db)
            items, cursor = adapter.fetch(account.sync_cursor, preference.mail_sync_batch_size)
            for item in items:
                message = db.scalar(select(MailMessage).where(MailMessage.account_id == account.id, MailMessage.provider_message_id == item.provider_message_id))
                if message: continue
                message = MailMessage(account_id=account.id, provider_message_id=item.provider_message_id, thread_id=item.thread_id, sender=item.sender, subject=item.subject[:500], snippet=(item.snippet or "")[:2000], received_at=item.received_at, headers={k: v[:1000] for k, v in item.headers.items()}, provider_spam=item.provider_spam)
                result = classify(item, get_llm_gateway(db))
                message.category = result.category; message.confidence = result.confidence; message.triage_status = "classified"
                db.add(message); db.flush(); created += 1; processed += 1
                action = None
                if result.category == "spam": action = "archive"
                elif result.category == "newsletter" and result.confidence >= preference.mail_auto_cleanup_confidence and item.headers.get("list-unsubscribe"):
                    action = "unsubscribe"
                if action:
                    audit = MailActionAudit(message_id=message.id, action=action, status="pending"); db.add(audit); db.flush()
                    try:
                        _mail_action(adapter, item, action)
                        if action == "unsubscribe":
                            _mail_action(adapter, item, "trash")
                        audit.status = "done"; audit.completed_at = datetime.now(timezone.utc); message.triage_status = "auto_cleaned"; automatic += 1
                    except Exception as exc:
                        audit.status = "failed"; audit.detail = str(exc)[:500]; message.triage_status = "action_failed"; message.last_error = "mail action failed"
                elif result.category in {"personal", "action", "meeting", "unknown"}:
                    source_ref = f"{account.id}:{item.provider_message_id}"
                    if not external_suggestion(db, "mail", source_ref):
                        db.add(TaskSuggestionRecord(title=item.subject[:240], description=(item.snippet or "")[:4000], source_type="mail", source_ref=source_ref, original_input=(item.snippet or "")[:4000], suggested_next_action=f"Lees en beoordeel: {item.subject}"[:300], confidence=result.confidence, batch_id=account.id))
            account.sync_cursor = cursor; account.last_synced_at = datetime.now(timezone.utc); account.last_error = None
            db.commit()
        except Exception as exc:
            db.rollback(); account.last_error = "mail sync failed"; account.status = MailAccountStatus.ERROR; db.commit(); errors.append(account.id)
    lease = db.get(MailSyncLease, "global")
    if lease and lease.owner == owner: db.delete(lease); db.commit()
    return {"status": "ok" if not errors else "partial", "processed": processed, "created": created, "automatic_actions": automatic, "accounts": len(accounts), "errors": errors}


async def mail_poll_loop():
    while True:
        try:
            with next(get_db()) as db:
                preference = db.scalar(select(AppPreference).order_by(AppPreference.id.asc()))
                interval = preference.mail_poll_interval_seconds if preference else settings.mail_poll_interval_seconds
        except Exception:
            interval = settings.mail_poll_interval_seconds
        await asyncio.sleep(interval)
        try:
            with next(get_db()) as db:
                preference = db.scalar(select(AppPreference).order_by(AppPreference.id.asc()))
                if preference and preference.mail_poll_enabled:
                    await asyncio.to_thread(sync_mailboxes, db, "poller")
        except Exception:
            request_log.exception("mail_poll_failed")


@app.get("/api/mail/accounts", response_model=list[MailAccountOut], dependencies=[Depends(auth)])
def mail_accounts(db: Session = Depends(get_db)):
    return db.scalars(select(MailAccount).order_by(MailAccount.created_at.asc())).all()


@app.post("/api/mail/accounts", response_model=MailAccountOut, dependencies=[Depends(auth)])
def create_mail_account(payload: MailAccountCreate, db: Session = Depends(get_db)):
    provider = MailProvider(payload.provider)
    credential_provider = f"mail:{uuid4()}"
    item = MailAccount(name=payload.name, provider=provider, address=payload.address, credential_provider=credential_provider)
    db.add(item)
    db.add(IntegrationCredential(provider=credential_provider, encrypted_value=credential_box().encrypt(json.dumps(payload.credential).encode()).decode()))
    db.commit(); db.refresh(item)
    return item


@app.post("/api/mail/accounts/{account_id}/test", dependencies=[Depends(auth)])
def test_mail_account(account_id: str, db: Session = Depends(get_db)):
    account = db.get(MailAccount, account_id)
    if not account: raise HTTPException(404, "mail account not found")
    try:
        adapter = _mail_adapter(account, db); adapter.fetch(account.sync_cursor, 1)
        account.last_error = None; account.status = MailAccountStatus.ACTIVE; db.commit()
        return {"ok": True, "message": "mailbox connection works"}
    except Exception:
        account.last_error = "mailbox connection failed"; db.commit()
        return {"ok": False, "message": "mailbox connection failed"}


@app.post("/api/mail/accounts/{account_id}/pause", response_model=MailAccountOut, dependencies=[Depends(auth)])
def pause_mail_account(account_id: str, db: Session = Depends(get_db)):
    account = db.get(MailAccount, account_id)
    if not account: raise HTTPException(404, "mail account not found")
    account.status = MailAccountStatus.PAUSED if account.status == MailAccountStatus.ACTIVE else MailAccountStatus.ACTIVE
    db.commit(); db.refresh(account); return account


@app.delete("/api/mail/accounts/{account_id}", dependencies=[Depends(auth)])
def delete_mail_account(account_id: str, db: Session = Depends(get_db)):
    account = db.get(MailAccount, account_id)
    if not account: raise HTTPException(404, "mail account not found")
    message_ids = list(db.scalars(select(MailMessage.id).where(MailMessage.account_id == account.id)))
    if message_ids:
        db.execute(delete(MailActionAudit).where(MailActionAudit.message_id.in_(message_ids)))
        db.execute(delete(MailMessage).where(MailMessage.account_id == account.id))
    db.delete(account); credential = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == account.credential_provider))
    if credential: db.delete(credential)
    db.commit(); return {"deleted": True, "id": account_id}


@app.post("/api/mail/sync", dependencies=[Depends(auth)])
def sync_mail(payload: dict | None = None, db: Session = Depends(get_db)):
    return sync_mailboxes(db, f"manual:{uuid4()}")


@app.get("/api/mail/summary", dependencies=[Depends(auth)])
def mail_summary(db: Session = Depends(get_db)):
    return {"accounts": db.scalar(select(func.count(MailAccount.id))) or 0, "messages": db.scalar(select(func.count(MailMessage.id))) or 0, "pending_suggestions": db.scalar(select(func.count(TaskSuggestionRecord.id)).where(TaskSuggestionRecord.status == SuggestionStatus.PENDING, TaskSuggestionRecord.source_type == "mail")) or 0, "last_synced_at": max((item.last_synced_at for item in db.scalars(select(MailAccount)).all() if item.last_synced_at), default=None)}


@app.get("/api/mail/triage-queue", response_model=list[MailMessageOut], dependencies=[Depends(auth)])
def mail_triage_queue(db: Session = Depends(get_db)):
    return db.scalars(select(MailMessage).where(MailMessage.triage_status.in_(("classified", "action_failed"))).order_by(MailMessage.received_at.asc().nulls_last()).limit(25)).all()


@app.post("/api/mail/messages/{message_id}/action", dependencies=[Depends(auth)])
def mail_message_action(message_id: str, payload: MailActionRequest, db: Session = Depends(get_db)):
    message = db.get(MailMessage, message_id)
    if not message: raise HTTPException(404, "mail message not found")
    account = db.get(MailAccount, message.account_id)
    if not account: raise HTTPException(404, "mail account not found")
    audit = db.scalar(select(MailActionAudit).where(MailActionAudit.message_id == message.id, MailActionAudit.action == payload.action))
    if audit and audit.status == "done": return {"status": "already_done", "message_id": message_id, "action": payload.action}
    if not audit: audit = MailActionAudit(message_id=message.id, action=payload.action); db.add(audit); db.flush()
    try:
        item = MailItem(message.provider_message_id, message.subject, message.sender, message.snippet, message.received_at, message.thread_id, message.headers, message.provider_spam)
        _mail_action(_mail_adapter(account, db), item, payload.action)
        audit.status = "done"; audit.completed_at = datetime.now(timezone.utc); message.triage_status = "actioned"; db.commit()
        return {"status": "done", "message_id": message_id, "action": payload.action}
    except Exception as exc:
        audit.status = "failed"; audit.detail = str(exc)[:500]; db.commit(); raise HTTPException(502, "mail action failed") from exc


@app.put("/api/ha/setup", dependencies=[Depends(auth)])
def save_ha_setup(payload: dict, db: Session = Depends(get_db)):
    mode = payload.get("mode", "preview")
    if mode not in {"preview", "webhook", "poll"}: raise HTTPException(400, "invalid HA mode")
    if mode == "webhook" and not payload.get("webhook_url"): raise HTTPException(400, "webhook URL required")
    if mode == "poll" and not payload.get("context_url"): raise HTTPException(400, "context URL required")
    if mode == "webhook" and not valid_endpoint(payload.get("webhook_url")): raise HTTPException(400, "invalid webhook URL")
    if mode == "poll" and not valid_endpoint(payload.get("context_url")): raise HTTPException(400, "invalid context URL")
    if mode == "preview": return {"mode": mode, "saved": False, "message": "Preview wijzigt de opgeslagen configuratie niet."}
    config = {"mode": mode, "webhook_url": str(payload.get("webhook_url") or ""), "context_url": str(payload.get("context_url") or ""), "token": str(payload.get("token") or "")}
    item = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == "home-assistant-connection"))
    if not item: item = IntegrationCredential(provider="home-assistant-connection"); db.add(item)
    item.encrypted_value = credential_box().encrypt(json.dumps(config).encode()).decode(); item.updated_at = datetime.now(timezone.utc); db.commit()
    return {"mode": mode, "saved": True, "webhook_configured": bool(config["webhook_url"]), "context_configured": bool(config["context_url"]), "token_configured": bool(config["token"])}


@app.get("/api/auth/status")
def auth_status(add_session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    enabled = bool(settings.local_login_password or db.scalar(select(LocalAccount)))
    return {"enabled": enabled, "login_configured": enabled, "first_start_required": not enabled, "encryption_configured": bool(settings.credential_encryption_key), "authenticated": not enabled or add_session == settings.session_secret}


@app.post("/api/auth/setup")
def setup_local_account(payload: dict, db: Session = Depends(get_db)):
    if db.scalar(select(LocalAccount)) or settings.local_login_password: raise HTTPException(409, "login already configured")
    password = str(payload.get("password") or "")
    if len(password) < 10: raise HTTPException(400, "password must be at least 10 characters")
    db.add(LocalAccount(password_hash=password_hash(password))); db.commit()
    return {"configured": True}


@app.post("/api/auth/login")
def login(payload: dict, response: Response, db: Session = Depends(get_db)):
    account = db.scalar(select(LocalAccount)); password = str(payload.get("password") or "")
    valid = password_matches(password, account.password_hash) if account else password == settings.local_login_password
    if not account and not settings.local_login_password: return {"authenticated": True, "enabled": False}
    if not valid: raise HTTPException(401, "onjuist wachtwoord")
    preference = db.scalar(select(AppPreference).order_by(AppPreference.id.asc()))
    response.set_cookie("add_session", settings.session_secret, httponly=True, samesite="lax", secure=preference.secure_cookies if preference else settings.secure_cookies, max_age=2592000)
    return {"authenticated": True, "enabled": True}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("add_session")
    return {"authenticated": False}


@app.get("/api/security/credentials", dependencies=[Depends(auth)])
def list_credentials(db: Session = Depends(get_db)):
    return [{"provider": item.provider, "updated_at": item.updated_at} for item in db.scalars(select(IntegrationCredential).order_by(IntegrationCredential.provider)).all()]


@app.get("/api/security/credentials/check", dependencies=[Depends(auth)])
def check_credentials(db: Session = Depends(get_db)):
    items = db.scalars(select(IntegrationCredential)).all()
    readable = 0
    for item in items:
        try:
            credential_box().decrypt(item.encrypted_value.encode())
            readable += 1
        except Exception:
            pass
    return {"ok": readable == len(items), "stored": len(items), "readable": readable}


@app.put("/api/security/credentials/{provider}", dependencies=[Depends(auth)])
def save_credential(provider: str, payload: dict, db: Session = Depends(get_db)):
    value = str(payload.get("value") or "")
    if not value: raise HTTPException(400, "credential value required")
    item = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == provider))
    if not item: item = IntegrationCredential(provider=provider); db.add(item)
    item.encrypted_value = credential_box().encrypt(value.encode()).decode(); item.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"provider": provider, "stored": True, "masked": "••••••••", "updated_at": item.updated_at}


@app.delete("/api/security/credentials/{provider}", dependencies=[Depends(auth)])
def delete_credential(provider: str, db: Session = Depends(get_db)):
    item = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == provider))
    if not item: raise HTTPException(404, "credential not found")
    db.delete(item); db.commit()
    return {"provider": provider, "deleted": True}


@app.get("/health")
def health(): return {"status": "ok", "service": "add-api"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ready", "service": "add-api", "database": "ok"}


@app.get("/api/diagnostics")
def diagnostics(db: Session = Depends(get_db)):
    status = today_status(db)
    try:
        migration_revision = db.execute(text("select version_num from alembic_version limit 1")).scalar()
    except Exception:
        # Lightweight test databases and pre-Alembic installations do not
        # have the version table yet; diagnostics must remain readable.
        migration_revision = None
    return {
        "api": "ok",
        "service": "add-api",
        "version": app.version,
        "today": status,
        "integrations": {
            "ha_sync_configured": bool(settings.ha_webhook_url),
            "ha_context_configured": bool(settings.ha_context_url),
            "api_token_configured": settings.add_api_token != "change-me",
        },
        "deployment": {
            "health": "ok",
            "database": "ok",
            "migration_revision": migration_revision,
            "migration_ok": bool(migration_revision),
        },
    }


@app.get("/api/backup/export")
def backup_export(db: Session = Depends(get_db)):
    payload = {
        "format": "add-backup",
        "version": app.version,
        "tasks": jsonable_encoder(db.scalars(select(Task)).all()),
        "actions": jsonable_encoder(db.scalars(select(Action)).all()),
        "sessions": jsonable_encoder(db.scalars(select(ExecutionSession)).all()),
        "accountability": jsonable_encoder(db.scalars(select(AccountabilitySession)).all()),
        "completions": jsonable_encoder(db.scalars(select(CompletionLog)).all()),
        "suggestions": jsonable_encoder(db.scalars(select(TaskSuggestionRecord)).all()),
        "outbox": jsonable_encoder(db.scalars(select(OutboxEvent)).all()),
        "plan_blocks": jsonable_encoder(db.scalars(select(PlanBlock)).all()),
        "planning_decisions": jsonable_encoder(db.scalars(select(PlanningDecision)).all()),
        "routines": jsonable_encoder(db.scalars(select(Routine)).all()),
        "routine_occurrences": jsonable_encoder(db.scalars(select(RoutineOccurrence)).all()),
        "reminder_preferences": jsonable_encoder(db.scalars(select(ReminderPreference)).all()),
        "app_preferences": jsonable_encoder(db.scalars(select(AppPreference)).all()),
        "smart_views": jsonable_encoder(db.scalars(select(SavedView)).all()),
    }
    proposals = db.scalars(select(TaskDecompositionProposal)).all()
    if proposals:
        payload["decompositions"] = jsonable_encoder(proposals)
        payload["decomposition_items"] = jsonable_encoder(db.scalars(select(TaskDecompositionItem)).all())
    return payload


@app.post("/api/backup/validate")
def backup_validate(payload: dict):
    required = {"format", "version", "tasks", "actions", "sessions", "accountability", "completions", "suggestions", "outbox"}
    missing = sorted(required - payload.keys())
    valid = payload.get("format") == "add-backup" and not missing and all(isinstance(payload[key], list) for key in required - {"format", "version"})
    return {"valid": valid, "format": payload.get("format"), "version": payload.get("version"), "missing": missing, "counts": {key: len(payload[key]) for key in required & payload.keys() if isinstance(payload[key], list)}}


@app.post("/api/backup/preview")
def backup_preview(payload: dict):
    result = backup_validate(payload)
    return {**result, "mode": "preview-only", "will_mutate": False, "message": "Deze backup is gecontroleerd; bestaande data blijft ongewijzigd." if result["valid"] else "Deze backup kan niet worden voorbereid voor restore."}


def backup_datetime(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


@app.post("/api/backup/restore", dependencies=[Depends(auth)])
def backup_restore(payload: dict, confirmed: bool = Query(default=False), db: Session = Depends(get_db)):
    result = backup_validate(payload)
    if not result["valid"]:
        raise HTTPException(400, "invalid backup")
    if not confirmed:
        raise HTTPException(409, "explicit restore confirmation required")
    if db.scalar(select(ExecutionSession).where(ExecutionSession.outcome == SessionOutcome.RUNNING)):
        raise HTTPException(409, "finish the active session before restoring")
    snapshot_payload = backup_export(db)
    snapshot = BackupSnapshot(payload=json.dumps(snapshot_payload))
    db.add(snapshot)
    db.commit()
    for model in (BackupSnapshot, TaskDecompositionItem, TaskDecompositionProposal, RoutineOccurrence, PlanningDecision, PlanBlock, AccountabilitySession, CompletionLog, ExecutionSession, Action, TaskSuggestionRecord, OutboxEvent, Routine, ReminderPreference, AppPreference, SavedView, Task):
        if model is BackupSnapshot:
            continue
        db.execute(delete(model))
    for item in payload["tasks"]:
        db.add(Task(id=item["id"], title=item["title"], description=item.get("description"), status=TaskStatus(item["status"]), category=item.get("category"), deadline=backup_datetime(item.get("deadline")), planned_at=backup_datetime(item.get("planned_at")), actual_minutes=item.get("actual_minutes", 0), parent_id=item.get("parent_id"), tags=item.get("tags", []), priority=TaskPriority(item.get("priority", "medium").lower()), source_type=item.get("source_type", "manual"), source_ref=item.get("source_ref"), created_at=backup_datetime(item.get("created_at"))))
    for item in payload["actions"]:
        db.add(Action(id=item["id"], task_id=item["task_id"], text=item["text"], status=ActionStatus(item["status"]), estimated_minutes=item.get("estimated_minutes", 10), energy=item.get("energy", "medium"), requires_home=item.get("requires_home", False), requires_computer=item.get("requires_computer", False), position=item.get("position", 0), created_at=backup_datetime(item.get("created_at"))))
    db.flush()
    for item in payload["sessions"]:
        db.add(ExecutionSession(id=item["id"], action_id=item["action_id"], started_at=backup_datetime(item.get("started_at")), ended_at=backup_datetime(item.get("ended_at")), outcome=SessionOutcome(item["outcome"]), stuck_reason=item.get("stuck_reason")))
    for item in payload.get("accountability", []):
        db.add(AccountabilitySession(id=item["id"], execution_session_id=item["execution_session_id"], participant_label=item.get("participant_label", "lokale buddy"), status=item.get("status", "stopped"), started_at=backup_datetime(item.get("started_at")), ended_at=backup_datetime(item.get("ended_at"))))
    for item in payload["completions"]:
        db.add(CompletionLog(id=item["id"], action_id=item["action_id"], session_id=item["session_id"], outcome=item["outcome"], created_at=backup_datetime(item.get("created_at"))))
    for item in payload["suggestions"]:
        db.add(TaskSuggestionRecord(id=item["id"], title=item["title"], description=item.get("description"), source_type=item.get("source_type", "hermes"), source_ref=item.get("source_ref"), batch_id=item.get("batch_id"), deadline=backup_datetime(item.get("deadline")), original_input=item.get("original_input"), planned_at=backup_datetime(item.get("planned_at")), tags=item.get("tags", []), suggested_next_action=item["suggested_next_action"], confidence=item.get("confidence", .5), suggested_estimated_minutes=item.get("suggested_estimated_minutes"), parsed_duration_minutes=item.get("parsed_duration_minutes"), recurrence=item.get("recurrence"), schedule_timezone=item.get("schedule_timezone"), schedule_status=item.get("schedule_status", "none"), schedule_notes=item.get("schedule_notes", []), status=SuggestionStatus(item["status"]), task_id=item.get("task_id"), created_at=backup_datetime(item.get("created_at"))))
    for item in payload.get("decompositions", []):
        db.add(TaskDecompositionProposal(id=item["id"], parent_id=item["parent_id"], requested_count=item["requested_count"], status=DecompositionStatus(item["status"]), created_at=backup_datetime(item.get("created_at")), updated_at=backup_datetime(item.get("updated_at") or item.get("created_at"))))
    for item in payload.get("decomposition_items", []):
        db.add(TaskDecompositionItem(id=item["id"], proposal_id=item["proposal_id"], title=item["title"], description=item.get("description"), position=item["position"]))
    for item in payload["outbox"]:
        db.add(OutboxEvent(id=item["id"], event_type=item["event_type"], payload=item["payload"], status=item.get("status", "pending"), created_at=backup_datetime(item.get("created_at")), delivered_at=backup_datetime(item.get("delivered_at")), error=item.get("error")))
    for item in payload.get("routines", []):
        db.add(Routine(id=item["id"], title=item["title"], action_text=item["action_text"], recurrence=item["recurrence"], weekday=item.get("weekday"), specific_date=item.get("specific_date"), local_time=item["local_time"], timezone=item.get("timezone", "UTC"), estimated_minutes=item.get("estimated_minutes", 10), enabled=item.get("enabled", True), created_at=backup_datetime(item.get("created_at"))))
    for item in payload.get("plan_blocks", []):
        db.add(PlanBlock(id=item["id"], task_id=item["task_id"], start_at=backup_datetime(item["start_at"]), end_at=backup_datetime(item["end_at"]), created_at=backup_datetime(item.get("created_at"))))
    for item in payload.get("planning_decisions", []):
        db.add(PlanningDecision(id=item["id"], operation=item["operation"], suggestion_id=item.get("suggestion_id"), task_id=item["task_id"], block_id=item.get("block_id"), from_planned_at=backup_datetime(item.get("from_planned_at")), to_planned_at=backup_datetime(item.get("to_planned_at")), from_start_at=backup_datetime(item.get("from_start_at")), from_end_at=backup_datetime(item.get("from_end_at")), to_start_at=backup_datetime(item.get("to_start_at")), to_end_at=backup_datetime(item.get("to_end_at")), undone_at=backup_datetime(item.get("undone_at")), created_at=backup_datetime(item.get("created_at"))))
    for item in payload.get("routine_occurrences", []):
        db.add(RoutineOccurrence(id=item["id"], routine_id=item["routine_id"], occurrence_date=item["occurrence_date"], task_id=item["task_id"], created_at=backup_datetime(item.get("created_at"))))
    for item in payload.get("reminder_preferences", []):
        db.add(ReminderPreference(id=item["id"], provider=item.get("provider", "none"), enabled=item.get("enabled", False), quiet_start=item.get("quiet_start", "22:00"), quiet_end=item.get("quiet_end", "07:00"), timezone=item.get("timezone", "UTC")))
    for item in payload.get("app_preferences", []):
        db.add(AppPreference(id=item["id"], workflow_badge_mode=item.get("workflow_badge_mode", "dot"), mail_poll_enabled=item.get("mail_poll_enabled", False), api_cors_origins=item.get("api_cors_origins", settings.api_cors_origins), secure_cookies=item.get("secure_cookies", settings.secure_cookies), mail_poll_interval_seconds=item.get("mail_poll_interval_seconds", settings.mail_poll_interval_seconds), mail_sync_batch_size=item.get("mail_sync_batch_size", settings.mail_sync_batch_size), mail_auto_cleanup_confidence=item.get("mail_auto_cleanup_confidence", settings.mail_auto_cleanup_confidence), github_repo=item.get("github_repo", settings.github_repo), task_assistant_prompt=item.get("task_assistant_prompt", "Help me decompose this task into concrete, small next steps and improve its description."), llm_provider="openrouter", llm_base_url="https://openrouter.ai/api/v1", llm_model=item.get("llm_model", "openrouter/free"), llm_credential_provider=item.get("llm_credential_provider", "llm"), created_at=backup_datetime(item.get("created_at")), updated_at=backup_datetime(item.get("updated_at") or item.get("created_at"))))
    for item in payload.get("smart_views", []):
        db.add(SavedView(id=item["id"], name=item["name"], filters=item.get("filters", {}), created_at=backup_datetime(item.get("created_at"))))
    db.commit()
    return {"status": "restored", "counts": result["counts"], "rollback_snapshot_id": snapshot.id}


@app.post("/api/backup/rollback", dependencies=[Depends(auth)])
def backup_rollback(confirmed: bool = Query(default=False), db: Session = Depends(get_db)):
    if not confirmed: raise HTTPException(409, "explicit rollback confirmation required")
    snapshot = db.scalar(select(BackupSnapshot).order_by(BackupSnapshot.created_at.desc()).limit(1))
    if not snapshot: raise HTTPException(404, "no rollback snapshot available")
    return backup_restore(json.loads(snapshot.payload), confirmed=True, db=db)


def get_app_preference(db: Session) -> AppPreference:
    preference = db.scalar(select(AppPreference).order_by(AppPreference.id.asc()))
    if not preference:
        preference = AppPreference(workflow_badge_mode="dot", mail_poll_enabled=False, api_cors_origins=settings.api_cors_origins, secure_cookies=settings.secure_cookies, mail_poll_interval_seconds=settings.mail_poll_interval_seconds, mail_sync_batch_size=settings.mail_sync_batch_size, mail_auto_cleanup_confidence=settings.mail_auto_cleanup_confidence, github_repo=settings.github_repo)
        db.add(preference)
        db.commit()
        db.refresh(preference)
    return preference


def llm_settings_out(db: Session) -> dict:
    preference = get_app_preference(db)
    configured = bool(read_encrypted_credential(db, preference.llm_credential_provider))
    return {"provider": preference.llm_provider, "base_url": preference.llm_base_url, "model": preference.llm_model, "configured": configured}


def openrouter_free_catalog(db: Session, api_key: str | None = None) -> list[dict]:
    preference = get_app_preference(db)
    key = api_key or read_encrypted_credential(db, preference.llm_credential_provider)
    router = {"id": "openrouter/free", "name": "OpenRouter Free Router", "context_length": 200000}
    if not key:
        return [router]
    models = fetch_openrouter_free_models(preference.llm_base_url, key, settings.llm_timeout_seconds)
    return [router] + [item for item in models if item["id"] != router["id"]]


@app.get("/api/preferences", response_model=AppPreferenceOut)
def read_preferences(db: Session = Depends(get_db)):
    return get_app_preference(db)


@app.patch("/api/preferences", response_model=AppPreferenceOut, dependencies=[Depends(auth)])
def update_preferences(payload: AppPreferenceUpdate, db: Session = Depends(get_db)):
    preference = get_app_preference(db)
    preference.workflow_badge_mode = payload.workflow_badge_mode
    if payload.mail_poll_enabled is not None:
        preference.mail_poll_enabled = payload.mail_poll_enabled
    if payload.api_cors_origins is not None:
        origins = ",".join(item.strip() for item in payload.api_cors_origins.split(",") if item.strip())
        if not origins: raise HTTPException(422, "at least one CORS origin is required")
        preference.api_cors_origins = origins
    if payload.secure_cookies is not None:
        preference.secure_cookies = payload.secure_cookies
    if payload.mail_poll_interval_seconds is not None:
        preference.mail_poll_interval_seconds = payload.mail_poll_interval_seconds
    if payload.mail_sync_batch_size is not None:
        preference.mail_sync_batch_size = payload.mail_sync_batch_size
    if payload.mail_auto_cleanup_confidence is not None:
        preference.mail_auto_cleanup_confidence = payload.mail_auto_cleanup_confidence
    if payload.github_repo is not None:
        if "/" not in payload.github_repo or payload.github_repo.count("/") != 1:
            raise HTTPException(422, "GitHub repository must be owner/repository")
        preference.github_repo = payload.github_repo.strip()
    if payload.api_token is not None:
        token = payload.api_token.strip()
        item = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == "runtime:add-api-token"))
        if not item:
            item = IntegrationCredential(provider="runtime:add-api-token"); db.add(item)
        item.encrypted_value = credential_box().encrypt(token.encode()).decode(); item.updated_at = datetime.now(timezone.utc)
    if payload.github_token is not None and payload.github_token.strip():
        item = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == "runtime:github-token"))
        if not item:
            item = IntegrationCredential(provider="runtime:github-token"); db.add(item)
        item.encrypted_value = credential_box().encrypt(payload.github_token.strip().encode()).decode(); item.updated_at = datetime.now(timezone.utc)
    if payload.task_assistant_prompt is not None:
        preference.task_assistant_prompt = payload.task_assistant_prompt.strip()
    if payload.llm_provider is not None:
        preference.llm_provider = payload.llm_provider
    if payload.llm_base_url is not None:
        if payload.llm_base_url.rstrip("/") != "https://openrouter.ai/api/v1":
            raise HTTPException(422, "ADD gebruikt uitsluitend de OpenRouter API")
        preference.llm_base_url = payload.llm_base_url.rstrip("/")
    if payload.llm_model is not None:
        candidate_key = payload.llm_api_key.strip() if payload.llm_api_key and payload.llm_api_key.strip() else read_encrypted_credential(db, preference.llm_credential_provider)
        if payload.llm_model != "openrouter/free":
            if not candidate_key:
                raise HTTPException(422, "sla eerst een OpenRouter API-key op")
            try:
                allowed_ids = {item["id"] for item in openrouter_free_catalog(db, candidate_key)}
            except LLMError as exc:
                raise HTTPException(422, "gratis OpenRouter-modellen konden niet worden opgehaald") from exc
            if payload.llm_model not in allowed_ids:
                raise HTTPException(422, "alleen actuele gratis OpenRouter-modellen zijn toegestaan")
        preference.llm_model = payload.llm_model.strip()
    if payload.llm_api_key is not None and payload.llm_api_key.strip():
        item = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == preference.llm_credential_provider))
        if not item:
            item = IntegrationCredential(provider=preference.llm_credential_provider)
            db.add(item)
        item.encrypted_value = credential_box().encrypt(payload.llm_api_key.strip().encode()).decode()
        item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(preference)
    return preference


@app.get("/api/llm-settings", response_model=LLMSettingsOut)
def read_llm_settings(db: Session = Depends(get_db)):
    return llm_settings_out(db)


@app.get("/api/llm/models", response_model=FreeLLMModelCatalogOut, dependencies=[Depends(auth)])
def read_free_llm_models(db: Session = Depends(get_db)):
    preference = get_app_preference(db)
    configured = bool(read_encrypted_credential(db, preference.llm_credential_provider))
    try:
        models = openrouter_free_catalog(db)
    except LLMError as exc:
        raise HTTPException(503, "gratis OpenRouter-modellen konden niet worden opgehaald") from exc
    return {"configured": configured, "models": models}


@app.get("/api/workflow-summary", response_model=WorkflowSummaryOut, dependencies=[Depends(auth)])
def workflow_summary(timezone_name: str = Query(default="Europe/Amsterdam", alias="timezone"), db: Session = Depends(get_db)):
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(400, "invalid timezone") from error
    now_utc = datetime.now(timezone.utc)
    local_now = now_utc.astimezone(zone)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc, end_utc = start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
    open_tasks = [Task.status != TaskStatus.DONE, Task.status != TaskStatus.ARCHIVED]
    inbox_tasks = db.scalars(select(Task).where(Task.status == TaskStatus.INBOX).order_by(Task.created_at.asc())).all()
    pending_suggestions = db.scalars(select(TaskSuggestionRecord).where(TaskSuggestionRecord.status == SuggestionStatus.PENDING).order_by(TaskSuggestionRecord.created_at.asc())).all()
    later_tasks = db.scalars(select(Task).where(*open_tasks, Task.status == TaskStatus.ACTIVE, Task.planned_at.is_(None))).all()
    today_tasks = db.scalars(select(Task).where(*open_tasks, Task.planned_at >= start_utc, Task.planned_at < end_utc)).all()
    upcoming_tasks = db.scalars(select(Task).where(*open_tasks, Task.planned_at >= end_utc)).all()
    missed_tasks = db.scalars(select(Task).where(*open_tasks, Task.planned_at.is_not(None), Task.planned_at < now_utc)).all()
    overdue_tasks = db.scalars(select(Task).where(*open_tasks, Task.deadline.is_not(None), Task.deadline < now_utc)).all()
    blocked_tasks = db.scalars(select(Task).where(*open_tasks, Task.id.in_(select(Action.task_id).where(Action.status == ActionStatus.BLOCKED)))).all()
    long_open_count = len(db.scalars(select(Task).where(*open_tasks, Task.created_at < start_utc - timedelta(days=30))).all())

    source_counts: dict[str, int] = {}
    for task in inbox_tasks:
        source_counts[task.source_type] = source_counts.get(task.source_type, 0) + 1
    for suggestion in pending_suggestions:
        source_counts[suggestion.source_type] = source_counts.get(suggestion.source_type, 0) + 1
    review_keys = {f"suggestion:{item.id}" for item in pending_suggestions}
    review_keys.update(f"task:{item.id}" for item in overdue_tasks)
    review_keys.update(f"task:{item.id}" for item in missed_tasks)
    review_keys.update(f"task:{item.id}" for item in blocked_tasks)
    review_count = len(review_keys)
    review_breakdown = {"open_proposals": len(pending_suggestions), "overdue": len(overdue_tasks), "missed_commitments": len(missed_tasks), "blocked": len(blocked_tasks)}
    if review_count:
        next_item = {"key": "review", "label": "Start dagreview", "href": "/daily-review"}
    elif later_tasks:
        next_item = {"key": "later", "label": "Bekijk Later", "href": "/views?unplanned=true"}
    elif missed_tasks:
        next_item = {"key": "missed", "label": "Bekijk gemiste planning", "href": "/today"}
    elif today_tasks:
        next_item = {"key": "today", "label": "Bekijk vandaag", "href": "/today"}
    else:
        next_item = {"key": "quiet", "label": "Geen actie nodig", "href": "/"}
    return {
        "inbox": {"count": len(inbox_tasks) + len(pending_suggestions), "sources": [{"source_type": key, "count": value} for key, value in sorted(source_counts.items())], "href": "/review"},
        "later": {"count": len(later_tasks), "long_open_count": long_open_count, "href": "/views?unplanned=true"},
        "planned": {"count": len(today_tasks) + len(upcoming_tasks), "today_count": len(today_tasks), "upcoming_count": len(upcoming_tasks), "missed_count": len(missed_tasks), "href": "/today"},
        "review": {"count": review_count, "breakdown": review_breakdown, "href": "/daily-review"},
        "next": next_item,
    }


@app.get("/api/reminders/preview")
def reminder_preview(is_home: bool = True, energy: str = "medium", computer_available: bool = True, max_minutes: int | None = Query(default=None, ge=1), strategy: str = Query(default="deterministic", pattern="^(deterministic|weighted_random)$"), seed: int | None = None, at: datetime | None = None, db: Session = Depends(get_db)):
    preference = db.scalar(select(ReminderPreference).order_by(ReminderPreference.id.asc()))
    if preference and preference.provider != "none" and not preference.enabled:
        return {"status": "provider_disabled", "message": f"{preference.provider} reminders zijn niet ingeschakeld.", "action": None}
    if preference:
        try: local_now = (at or datetime.now(timezone.utc)).astimezone(ZoneInfo(preference.timezone))
        except ZoneInfoNotFoundError: raise HTTPException(400, "invalid timezone")
        current = local_now.strftime("%H:%M")
        quiet = preference.quiet_start <= preference.quiet_end and preference.quiet_start <= current < preference.quiet_end or preference.quiet_start > preference.quiet_end and (current >= preference.quiet_start or current < preference.quiet_end)
        if quiet: return {"status": "quiet_hours", "message": "Stille uren actief.", "action": None}
    action = choose_action(db, is_home=is_home, energy=energy, computer_available=computer_available, max_minutes=max_minutes, strategy=strategy, seed=seed)
    if not action:
        return {"status": "quiet", "message": "Geen reminder nodig.", "action": None}
    return {"status": "ready", "message": f"Als het past: {action.text}", "action": ActionOut.model_validate(action).model_dump(mode="json")}


@app.get("/api/routines", response_model=list[RoutineOut])
def list_routines(db: Session = Depends(get_db)):
    return db.scalars(select(Routine).order_by(Routine.created_at.desc())).all()


@app.post("/api/routines", response_model=RoutineOut, dependencies=[Depends(auth)])
def create_routine(payload: RoutineCreate, db: Session = Depends(get_db)):
    if payload.recurrence == "weekly" and payload.weekday is None: raise HTTPException(422, "weekday is required for weekly recurrence")
    if payload.recurrence == "specific_day" and payload.specific_date is None: raise HTTPException(422, "specific_date is required")
    try: ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError: raise HTTPException(422, "invalid timezone")
    routine = Routine(**payload.model_dump())
    db.add(routine); db.commit(); db.refresh(routine); return routine


@app.post("/api/routines/{routine_id}/materialize", dependencies=[Depends(auth)])
def materialize_routine(routine_id: str, occurrence_date: date | None = Query(default=None), db: Session = Depends(get_db)):
    routine = db.get(Routine, routine_id)
    if not routine: raise HTTPException(404, "routine not found")
    target = occurrence_date or datetime.now(ZoneInfo(routine.timezone)).date()
    if not routine.enabled: return {"status": "disabled", "task": None}
    if routine.recurrence == "weekly" and target.weekday() != routine.weekday: return {"status": "not_due", "task": None}
    if routine.recurrence == "specific_day" and target != routine.specific_date: return {"status": "not_due", "task": None}
    existing = db.scalar(select(RoutineOccurrence).where(RoutineOccurrence.routine_id == routine.id, RoutineOccurrence.occurrence_date == target))
    if existing: return {"status": "already_materialized", "task_id": existing.task_id}
    local_planned = datetime.fromisoformat(f"{target.isoformat()}T{routine.local_time}").replace(tzinfo=ZoneInfo(routine.timezone))
    task = Task(title=routine.title, status=TaskStatus.ACTIVE, planned_at=local_planned.astimezone(timezone.utc), source_type="routine", source_ref=f"{routine.id}:{target.isoformat()}")
    db.add(task); db.flush(); db.add(Action(task_id=task.id, text=routine.action_text, estimated_minutes=routine.estimated_minutes)); db.add(RoutineOccurrence(routine_id=routine.id, occurrence_date=target, task_id=task.id)); db.commit()
    return {"status": "materialized", "task_id": task.id, "source_ref": task.source_ref}


@app.get("/api/reminder-settings", response_model=ReminderSettings)
def get_reminder_settings(db: Session = Depends(get_db)):
    item = db.scalar(select(ReminderPreference).order_by(ReminderPreference.id.asc()))
    return item or ReminderSettings()


@app.put("/api/reminder-settings", response_model=ReminderSettings, dependencies=[Depends(auth)])
def set_reminder_settings(payload: ReminderSettings, db: Session = Depends(get_db)):
    try: ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError: raise HTTPException(422, "invalid timezone")
    item = db.scalar(select(ReminderPreference).order_by(ReminderPreference.id.asc()))
    if not item: item = ReminderPreference(); db.add(item)
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    db.commit(); db.refresh(item); return item


@app.post("/api/tasks", response_model=TaskOut, dependencies=[Depends(auth)])
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    task = Task(title=payload.title, description=payload.description, category=payload.category, deadline=payload.deadline, planned_at=payload.planned_at, actual_minutes=payload.actual_minutes, tags=payload.tags, priority=payload.priority, source_type=payload.source_type, source_ref=payload.source_ref, status=TaskStatus.ACTIVE if payload.next_action else TaskStatus.INBOX)
    try:
        validate_parent(db, task, payload.parent_id)
    except ValueError as error:
        raise HTTPException(409, str(error))
    task.parent_id = payload.parent_id
    db.add(task); db.flush()
    if payload.next_action: db.add(Action(task_id=task.id, **payload.next_action.model_dump()))
    db.commit(); db.refresh(task); return task


@app.post("/api/inbox/capture", response_model=NaturalLanguageCaptureResponse, dependencies=[Depends(auth)])
def capture_inbox(payload: NaturalLanguageCaptureRequest, gateway: LLMGateway = Depends(get_llm_gateway), db: Session = Depends(get_db)):
    text = payload.text
    source_type = payload.source_type
    source_ref = payload.source_ref
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "invalid timezone")
    if source_type == "web_link":
        candidate = (source_ref or "").strip()
        parsed_url = urlparse(candidate)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise HTTPException(422, "web_link requires a valid http(s) URL")
        source_ref = candidate
    elif source_type == "shortcut":
        source_ref = payload.idempotency_key or hashlib.sha256(text.encode("utf-8")).hexdigest()
    if source_type in {"shortcut", "web_link", "voice_transcript"} and source_ref:
        existing = external_suggestion(db, source_type, source_ref)
        if existing:
            return {"mode": "plain_text", "suggestion": existing}
    mode = "parsed"
    schedule = {"status": "none", "timezone": payload.timezone, "notes": []}
    if source_type == "web_link":
        parsed = plain_text_capture(text)
        parsed = parsed.model_copy(update={"description": f"Weblink: {source_ref}", "suggested_next_action": f"Open de link: {source_ref}", "confidence": 1})
    else:
        schedule = parse_schedule(text, timezone_name=payload.timezone)
        try:
            parsed = parse_capture(gateway, text, timezone_name=payload.timezone)
        except LLMError:
            parsed = plain_text_capture(text)
            mode = "plain_text"
        if schedule["status"] in {"parsed", "ambiguous"}:
            parsed = parsed.model_copy(update={
                "planned_at": schedule.get("planned_at") if schedule["status"] == "parsed" else None,
                "deadline": schedule.get("deadline") if schedule["status"] == "parsed" else None,
                "parsed_duration_minutes": schedule.get("duration_minutes"),
                "recurrence": schedule.get("recurrence"),
                "schedule_timezone": schedule.get("timezone"),
                "schedule_status": schedule["status"],
                "schedule_notes": schedule.get("notes", []),
            })
    record = TaskSuggestionRecord(
        title=parsed.title,
        description=parsed.description,
        source_type=source_type,
        source_ref=source_ref,
        original_input=text,
        planned_at=parsed.planned_at,
        deadline=parsed.deadline,
        tags=parsed.tags,
        suggested_next_action=parsed.suggested_next_action,
        confidence=parsed.confidence,
        parsed_duration_minutes=parsed.parsed_duration_minutes,
        recurrence=parsed.recurrence,
        schedule_timezone=parsed.schedule_timezone or payload.timezone,
        schedule_status=parsed.schedule_status,
        schedule_notes=parsed.schedule_notes,
        status=SuggestionStatus.PENDING,
    )
    db.add(record); db.commit(); db.refresh(record)
    return {"mode": mode, "suggestion": record}


@app.post("/api/inbox/brain-dump", response_model=list[SuggestionOut], dependencies=[Depends(auth)])
def brain_dump_inbox(payload: NaturalLanguageCaptureRequest, gateway: LLMGateway = Depends(get_llm_gateway), db: Session = Depends(get_db)):
    batch_id = str(uuid4())
    try:
        # The fallback produces a single plain-text capture when the provider
        # fails, so the proposal list holds either shape.
        proposals: Sequence[BrainDumpProposal | NaturalLanguageCaptureResult] = parse_brain_dump(gateway, payload.text).proposals
    except LLMError:
        proposals = [plain_text_capture(payload.text)]
    records = []
    for proposal in proposals:
        data = proposal.model_dump()
        record = TaskSuggestionRecord(
            title=data["title"], description=data.get("description"), source_type="brain_dump",
            source_ref=batch_id, batch_id=batch_id, deadline=data.get("deadline"),
            original_input=payload.text, planned_at=data.get("planned_at"), tags=data.get("tags", []),
            suggested_next_action=data["suggested_next_action"], confidence=data.get("confidence", 0),
            suggested_estimated_minutes=data.get("suggested_estimated_minutes"), status=SuggestionStatus.PENDING,
        )
        db.add(record); records.append(record)
    db.commit()
    for record in records:
        db.refresh(record)
    return records


def decomposition_error(exc: LLMError) -> HTTPException:
    return HTTPException(503, "Taak opsplitsen is tijdelijk niet beschikbaar.")


@app.post("/api/tasks/{task_id}/decompositions", response_model=DecompositionProposalOut, dependencies=[Depends(auth)])
def create_decomposition(task_id: str, payload: DecompositionRequest, gateway: LLMGateway = Depends(get_llm_gateway), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    try:
        result = decompose_task(gateway, task, payload.child_count, get_app_preference(db).task_assistant_prompt)
        children = remove_existing_children(db, task, result)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except LLMError as exc:
        raise decomposition_error(exc) from exc
    proposal = TaskDecompositionProposal(parent_id=task.id, requested_count=payload.child_count)
    proposal.items = [item_from_child(child, index) for index, child in enumerate(children)]
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


@app.get("/api/tasks/{task_id}/decompositions", response_model=list[DecompositionProposalOut], dependencies=[Depends(auth)])
def list_decompositions(task_id: str, db: Session = Depends(get_db)):
    if not db.get(Task, task_id):
        raise HTTPException(404, "task not found")
    return db.scalars(select(TaskDecompositionProposal).where(TaskDecompositionProposal.parent_id == task_id).order_by(TaskDecompositionProposal.created_at.desc())).all()


@app.post("/api/decompositions/{proposal_id}/approve", response_model=DecompositionApprovalOut, dependencies=[Depends(auth)])
def approve_decomposition(proposal_id: str, payload: DecompositionApprovalRequest | None = None, db: Session = Depends(get_db)):
    proposal = db.get(TaskDecompositionProposal, proposal_id)
    if not proposal:
        raise HTTPException(404, "decomposition proposal not found")
    if proposal.status != DecompositionStatus.PENDING:
        raise HTTPException(409, "decomposition proposal is already decided")
    parent = db.get(Task, proposal.parent_id)
    if not parent:
        raise HTTPException(409, "decomposition parent no longer exists")
    selected_ids = set(payload.item_ids) if payload else {item.id for item in proposal.items}
    selected_items = [item for item in proposal.items if item.id in selected_ids]
    if len(selected_items) != len(selected_ids) or not selected_items:
        raise HTTPException(422, "selecteer geldige subtaken")
    existing = {" ".join(child.title.split()).casefold() for child in db.scalars(select(Task).where(Task.parent_id == parent.id)).all()}
    if any(" ".join(item.title.split()).casefold() in existing for item in selected_items):
        raise HTTPException(409, "a proposed child task already exists")
    try:
        tasks = []
        for item in selected_items:
            child = Task(title=item.title, description=item.description, parent_id=parent.id, source_type="decomposition", status=TaskStatus.INBOX)
            db.add(child)
            db.flush()
            tasks.append(child)
        proposal.status = DecompositionStatus.ACCEPTED
        db.commit()
        db.refresh(proposal)
        for task in tasks:
            db.refresh(task)
        return {"proposal": proposal, "tasks": tasks}
    except Exception:
        db.rollback()
        raise HTTPException(409, "decomposition could not be approved")


@app.post("/api/decompositions/{proposal_id}/reject", response_model=DecompositionProposalOut, dependencies=[Depends(auth)])
def reject_decomposition(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.get(TaskDecompositionProposal, proposal_id)
    if not proposal:
        raise HTTPException(404, "decomposition proposal not found")
    if proposal.status != DecompositionStatus.PENDING:
        raise HTTPException(409, "decomposition proposal is already decided")
    proposal.status = DecompositionStatus.REJECTED
    db.commit()
    db.refresh(proposal)
    return proposal


@app.get("/api/tasks", response_model=list[TaskOut])
def list_tasks(status: TaskStatus | None = None, db: Session = Depends(get_db)):
    q = select(Task).order_by(Task.created_at.desc())
    if status: q = q.where(Task.status == status)
    return db.scalars(q).all()


@app.get("/api/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    if task.children:
        all_children_done = all(child.status == TaskStatus.DONE for child in task.children)
        if all_children_done and task.status != TaskStatus.DONE:
            task.status = TaskStatus.DONE
        elif not all_children_done and task.status == TaskStatus.DONE:
            task.status = TaskStatus.ACTIVE
        db.commit(); db.refresh(task)
    return task


@app.get("/api/tasks/{task_id}/actions", response_model=list[ActionOut])
def list_task_actions(task_id: str, db: Session = Depends(get_db)):
    if not db.get(Task, task_id):
        raise HTTPException(404, "task not found")
    return db.scalars(select(Action).where(Action.task_id == task_id).order_by(Action.position.asc(), Action.created_at.asc())).all()


@app.post("/api/tasks/{task_id}/actions", response_model=ActionOut, dependencies=[Depends(auth)])
def create_task_action(task_id: str, payload: ActionCreate, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    action = Action(task_id=task.id, **payload.model_dump())
    if task.status == TaskStatus.INBOX:
        task.status = TaskStatus.ACTIVE
    db.add(action); db.commit(); db.refresh(action)
    return action


def smart_view_query(filters: SmartViewFilters, db: Session):
    try:
        zone = ZoneInfo(filters.timezone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(400, "invalid timezone") from error
    now_utc = datetime.now(timezone.utc)
    statement = select(Task).where(Task.status.notin_([TaskStatus.DONE, TaskStatus.ARCHIVED]))
    if filters.period:
        local_now = now_utc.astimezone(zone)
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        if filters.period == "week":
            start_local -= timedelta(days=start_local.weekday())
            end_local = start_local + timedelta(days=7)
        else:
            end_local = start_local + timedelta(days=1)
        statement = statement.where(Task.planned_at >= start_local.astimezone(timezone.utc), Task.planned_at < end_local.astimezone(timezone.utc))
    if filters.overdue:
        statement = statement.where(Task.deadline.is_not(None), Task.deadline < now_utc)
    if filters.source:
        statement = statement.where(Task.source_type == filters.source)
    if filters.priority:
        statement = statement.where(Task.priority == filters.priority)
    if filters.blocked:
        statement = statement.where(Task.id.in_(select(Action.task_id).where(Action.status == ActionStatus.BLOCKED)))
    if filters.unplanned:
        statement = statement.where(Task.planned_at.is_(None))
    return db.scalars(statement.order_by(Task.deadline.asc().nullslast(), Task.created_at.desc()).limit(100)).all()


@app.get("/api/smart-views", response_model=list[SmartViewOut], dependencies=[Depends(auth)])
def list_smart_views(db: Session = Depends(get_db)):
    return db.scalars(select(SavedView).order_by(SavedView.created_at.asc())).all()


@app.post("/api/smart-views", response_model=SmartViewOut, dependencies=[Depends(auth)])
def create_smart_view(payload: SmartViewCreate, db: Session = Depends(get_db)):
    if (db.scalar(select(func.count(SavedView.id))) or 0) >= 3:
        raise HTTPException(409, "maximaal drie opgeslagen views toegestaan")
    if db.scalar(select(SavedView).where(func.lower(SavedView.name) == payload.name.strip().lower())):
        raise HTTPException(409, "view name already exists")
    try:
        ZoneInfo(payload.filters.timezone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(422, "invalid timezone") from error
    view = SavedView(name=payload.name.strip(), filters=payload.filters.model_dump(mode="json"))
    db.add(view); db.commit(); db.refresh(view)
    return view


@app.delete("/api/smart-views/{view_id}", dependencies=[Depends(auth)])
def delete_smart_view(view_id: str, db: Session = Depends(get_db)):
    view = db.get(SavedView, view_id)
    if not view:
        raise HTTPException(404, "view not found")
    db.delete(view); db.commit()
    return {"id": view_id, "deleted": True}


@app.get("/api/smart-views/query", response_model=list[TaskOut], dependencies=[Depends(auth)])
def query_smart_view(period: str | None = Query(default=None, pattern="^(today|week)$"), overdue: bool = False, source: str | None = Query(default=None, max_length=40), priority: TaskPriority | None = None, blocked: bool = False, unplanned: bool = False, timezone_name: str = Query(default="Europe/Amsterdam", alias="timezone"), db: Session = Depends(get_db)):
    # The route pattern above already restricts this to the two literals the
    # schema accepts; the cast only states that to the type checker.
    filters = SmartViewFilters(period=cast(Literal["today", "week"] | None, period), overdue=overdue, source=source, priority=priority, blocked=blocked, unplanned=unplanned, timezone=timezone_name)
    return smart_view_query(filters, db)


@app.get("/api/smart-views/{view_id}/tasks", response_model=list[TaskOut], dependencies=[Depends(auth)])
def query_saved_smart_view(view_id: str, db: Session = Depends(get_db)):
    view = db.get(SavedView, view_id)
    if not view:
        raise HTTPException(404, "view not found")
    return smart_view_query(SmartViewFilters.model_validate(view.filters), db)


@app.patch("/api/tasks/{task_id}", response_model=TaskOut, dependencies=[Depends(auth)])
def update_task(task_id: str, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    values = payload.model_dump(exclude_unset=True)
    if "parent_id" in values:
        try:
            validate_parent(db, task, values["parent_id"])
        except ValueError as error:
            raise HTTPException(409, str(error))
    for key, value in values.items():
        setattr(task, key, value)
    if task.parent_id and task.status == TaskStatus.DONE:
        parent = db.get(Task, task.parent_id)
        if parent and parent.children and all(child.status == TaskStatus.DONE for child in parent.children):
            parent.status = TaskStatus.DONE
    elif task.parent_id:
        parent = db.get(Task, task.parent_id)
        if parent and parent.status == TaskStatus.DONE:
            parent.status = TaskStatus.ACTIVE
    db.commit(); db.refresh(task)
    return task


@app.delete("/api/tasks/{task_id}", dependencies=[Depends(auth)])
def remove_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    try:
        delete_task(db, task)
    except ValueError as error:
        raise HTTPException(409, str(error))
    return {"id": task_id, "deleted": True}


@app.get("/api/now", response_model=ActionOut | None)
def now_action(is_home: bool = True, energy: str = "medium", computer_available: bool = True, max_minutes: int | None = Query(default=None, ge=1), strategy: str = Query(default="deterministic", pattern="^(deterministic|weighted_random)$"), seed: int | None = None, db: Session = Depends(get_db)):
    return choose_action(db, is_home=is_home, energy=energy, computer_available=computer_available, max_minutes=max_minutes, strategy=strategy, seed=seed)


@app.get("/api/widget")
def widget_read_model(db: Session = Depends(get_db)):
    action = choose_action(db)
    proposals = db.scalar(select(func.count(TaskSuggestionRecord.id)).where(TaskSuggestionRecord.status == SuggestionStatus.PENDING)) or 0
    return {
        "next_action": ActionOut.model_validate(action).model_dump(mode="json") if action else None,
        "open_proposals": proposals,
        "capture_url": "/intake?quick=1",
        "review_url": "/review",
        "execute_url": "/execute",
        "read_only": True,
    }


@app.post("/api/actions/{action_id}/start", response_model=StartOut)
def start(action_id: str, db: Session = Depends(get_db), duration_seconds: int = Query(default=600, ge=60, le=7200)):
    if not isinstance(duration_seconds, int): duration_seconds = 600
    action = db.get(Action, action_id)
    if not action: raise HTTPException(404, "action not found")
    try:
        session = start_action(db, action)
        session.duration_seconds = duration_seconds
        db.commit(); db.refresh(session)
    except ValueError as e: raise HTTPException(409, str(e))
    return {"session_id": session.id, "action": action, "started_at": session.started_at, "duration_seconds": session.duration_seconds, "paused_at": session.paused_at, "paused_seconds": session.paused_seconds}


@app.get("/api/sessions/active", response_model=StartOut | None)
def active_session(db: Session = Depends(get_db)):
    session = db.scalar(select(ExecutionSession).where(ExecutionSession.outcome == SessionOutcome.RUNNING).order_by(ExecutionSession.started_at.desc()))
    if not session:
        return None
    action = db.get(Action, session.action_id)
    if not action:
        return None
    return {"session_id": session.id, "action": action, "started_at": session.started_at, "duration_seconds": session.duration_seconds, "paused_at": session.paused_at, "paused_seconds": session.paused_seconds}


@app.post("/api/sessions/{session_id}/pause", response_model=StartOut)
def pause(session_id: str, db: Session = Depends(get_db)):
    session = db.get(ExecutionSession, session_id)
    if not session: raise HTTPException(404, "session not found")
    try: pause_session(db, session)
    except ValueError as error: raise HTTPException(409, str(error))
    action = db.get(Action, session.action_id)
    return {"session_id": session.id, "action": action, "started_at": session.started_at, "duration_seconds": session.duration_seconds, "paused_at": session.paused_at, "paused_seconds": session.paused_seconds}


@app.post("/api/sessions/{session_id}/resume", response_model=StartOut)
def resume(session_id: str, db: Session = Depends(get_db)):
    session = db.get(ExecutionSession, session_id)
    if not session: raise HTTPException(404, "session not found")
    try: resume_session(db, session)
    except ValueError as error: raise HTTPException(409, str(error))
    action = db.get(Action, session.action_id)
    return {"session_id": session.id, "action": action, "started_at": session.started_at, "duration_seconds": session.duration_seconds, "paused_at": session.paused_at, "paused_seconds": session.paused_seconds}


@app.post("/api/sessions/{session_id}/finish", response_model=SessionResult)
def finish(session_id: str, payload: SessionResult, db: Session = Depends(get_db)):
    session = db.get(ExecutionSession, session_id)
    if not session: raise HTTPException(404, "session not found")
    try: finish_session(db, session, payload.outcome, payload.stuck_reason)
    except ValueError as e: raise HTTPException(409, str(e))
    return payload


@app.post("/api/offline/complete")
def offline_complete(payload: OfflineCompletion, db: Session = Depends(get_db)):
    action = db.get(Action, payload.action_id)
    if not action: raise HTTPException(409, "offline conflict: action no longer exists")
    if action.status != ActionStatus.READY: raise HTTPException(409, "offline conflict: action is no longer ready")
    try:
        session = start_action(db, action)
        session.started_at = payload.started_at
        finish_session(db, session, payload.outcome, payload.stuck_reason)
    except ValueError as error:
        raise HTTPException(409, f"offline conflict: {error}")
    return {"status": "synced", "session_id": session.id, "action_id": action.id}


@app.post("/api/accountability/start", response_model=AccountabilityOut)
def start_accountability_session(payload: AccountabilityStartRequest, db: Session = Depends(get_db)):
    session = db.get(ExecutionSession, payload.execution_session_id)
    if not session: raise HTTPException(404, "execution session not found")
    try: return start_accountability(db, session, payload.participant_label)
    except ValueError as e: raise HTTPException(409, str(e))


@app.post("/api/accountability/{accountability_id}/finish", response_model=AccountabilityOut)
def finish_accountability_session(accountability_id: str, payload: AccountabilityFinishRequest, db: Session = Depends(get_db)):
    accountability = db.get(AccountabilitySession, accountability_id)
    if not accountability: raise HTTPException(404, "accountability session not found")
    try: return finish_accountability(db, accountability, payload.status)
    except ValueError as e: raise HTTPException(409, str(e))


@app.get("/api/actions", response_model=list[ActionOut])
def list_actions(status: ActionStatus | None = None, db: Session = Depends(get_db)):
    q = select(Action).order_by(Action.created_at.desc())
    if status: q = q.where(Action.status == status)
    return db.scalars(q).all()


@app.get("/api/completions", response_model=list[CompletionOut])
def list_completions(db: Session = Depends(get_db)):
    logs = db.scalars(select(CompletionLog).order_by(CompletionLog.created_at.desc()).limit(100)).all()
    result = []
    for log in logs:
        action = db.get(Action, log.action_id)
        task = db.get(Task, action.task_id) if action else None
        result.append({"id": log.id, "action_id": log.action_id, "session_id": log.session_id, "outcome": log.outcome, "created_at": log.created_at, "action_text": action.text if action else None, "task_title": task.title if task else None})
    return result


@app.post("/api/day/check")
def day_check(payload: DayCheckRequest, db: Session = Depends(get_db)):
    target = payload.date or datetime.now(ZoneInfo(payload.timezone)).date()
    try:
        return check_day_rollover(db, target, payload.timezone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise HTTPException(400, str(error))


def aware_utc(value: datetime) -> datetime:
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(timezone.utc)


def plan_block_out(block: PlanBlock):
    return {"id": block.id, "task_id": block.task_id, "start_at": block.start_at, "end_at": block.end_at, "task_title": block.task.title, "task_status": block.task.status}


@app.get("/api/today-plan", response_model=list[PlanBlockOut])
def today_plan(day: date | None = Query(default=None), timezone_name: str = Query(default="UTC", alias="timezone"), db: Session = Depends(get_db)):
    try:
        target = day or datetime.now(ZoneInfo(timezone_name)).date()
        start, end, _ = day_window(target, timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise HTTPException(400, str(error))
    blocks = db.scalars(select(PlanBlock).where(PlanBlock.start_at < end.astimezone(timezone.utc), PlanBlock.end_at > start.astimezone(timezone.utc)).order_by(PlanBlock.start_at.asc())).all()
    return [plan_block_out(block) for block in blocks]


@app.post("/api/plan-blocks", response_model=PlanBlockOut, dependencies=[Depends(auth)])
def create_plan_block(payload: PlanBlockCreate, db: Session = Depends(get_db)):
    task = db.get(Task, payload.task_id)
    if not task:
        raise HTTPException(404, "task not found")
    start_at, end_at = aware_utc(payload.start_at), aware_utc(payload.end_at)
    if end_at <= start_at:
        raise HTTPException(422, "end_at must be after start_at")
    conflict = db.scalar(select(PlanBlock).where(PlanBlock.start_at < end_at, PlanBlock.end_at > start_at).limit(1))
    if conflict:
        raise HTTPException(409, "plan block overlaps an existing block")
    block = PlanBlock(task_id=task.id, start_at=start_at, end_at=end_at)
    task.planned_at = start_at
    db.add(block); db.commit(); db.refresh(block)
    return plan_block_out(block)


def scheduled_range(db: Session, start_value: datetime | None, duration_minutes: int | None, exclude_block_id: str | None = None):
    if start_value is None or duration_minutes is None:
        raise HTTPException(422, "start_at and duration_minutes are required for a time block")
    start_at = aware_utc(start_value)
    if start_at < datetime.now(timezone.utc) - timedelta(minutes=1):
        raise HTTPException(422, "start_at cannot be in the past")
    end_at = start_at + timedelta(minutes=duration_minutes)
    query = select(PlanBlock).where(PlanBlock.start_at < end_at, PlanBlock.end_at > start_at)
    if exclude_block_id:
        query = query.where(PlanBlock.id != exclude_block_id)
    if db.scalar(query.limit(1)):
        raise HTTPException(409, "plan block overlaps an existing block")
    return start_at, end_at


def next_available_range(db: Session, duration_minutes: int):
    candidate = datetime.now(timezone.utc) + timedelta(minutes=2)
    candidate = candidate.replace(second=0, microsecond=0)
    candidate += timedelta(minutes=(5 - candidate.minute % 5) % 5)
    for _ in range(100):
        end_at = candidate + timedelta(minutes=duration_minutes)
        conflict = db.scalar(select(PlanBlock).where(PlanBlock.start_at < end_at, PlanBlock.end_at > candidate).order_by(PlanBlock.end_at.desc()).limit(1))
        if not conflict:
            return candidate, end_at
        candidate = conflict.end_at + timedelta(minutes=5)
    raise HTTPException(409, "geen vrije plek gevonden voor vandaag")


def plan_block_result(block: PlanBlock | None, destination: str, *, decision_id: str | None = None, suggestion_id: str | None = None, task_id: str, idempotent: bool = False):
    return {"decision_id": decision_id, "suggestion_id": suggestion_id, "task_id": task_id, "destination": destination, "idempotent": idempotent, "block": (plan_block_out(block) if block else None)}


@app.post("/api/inbox/review/{suggestion_id}/plan", response_model=PlanningDecisionOut, dependencies=[Depends(auth)])
def plan_reviewed_suggestion(suggestion_id: str, payload: PlanSuggestionRequest, db: Session = Depends(get_db)):
    record = db.get(TaskSuggestionRecord, suggestion_id)
    if not record:
        raise HTTPException(404, "suggestion not found")
    if record.status != SuggestionStatus.PENDING:
        raise HTTPException(409, "suggestion already decided")
    start_at = end_at = None
    if payload.destination == "at":
        start_at, end_at = scheduled_range(db, payload.start_at, payload.duration_minutes)
    elif payload.destination == "today":
        duration_minutes = payload.duration_minutes or record.suggested_estimated_minutes or 10
        start_at, end_at = next_available_range(db, duration_minutes) if payload.start_at is None else scheduled_range(db, payload.start_at, duration_minutes)
    task = Task(title=record.title, description=record.description, source_type=record.source_type, source_ref=record.source_ref, deadline=record.deadline, planned_at=start_at, tags=record.tags or [], priority=TaskPriority.HIGH if payload.urgent else TaskPriority.MEDIUM, status=TaskStatus.ACTIVE)
    db.add(task); db.flush()
    db.add(Action(task_id=task.id, text=record.suggested_next_action, estimated_minutes=record.suggested_estimated_minutes or 10))
    block = None
    if start_at and end_at:
        block = PlanBlock(task_id=task.id, start_at=start_at, end_at=end_at)
        db.add(block); db.flush()
    record.status = SuggestionStatus.ACCEPTED
    record.task_id = task.id
    decision = PlanningDecision(operation="plan", suggestion_id=record.id, task_id=task.id, block_id=block.id if block else None, to_planned_at=start_at, to_start_at=start_at, to_end_at=end_at)
    db.add(decision); db.commit()
    if block: db.refresh(block)
    return plan_block_result(block, payload.destination, decision_id=decision.id, suggestion_id=record.id, task_id=task.id)


@app.post("/api/tasks/{task_id}/replan", response_model=PlanningDecisionOut, dependencies=[Depends(auth)])
def replan_task(task_id: str, payload: ReplanRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    block = db.scalar(select(PlanBlock).where(PlanBlock.task_id == task.id).order_by(PlanBlock.created_at.asc()))
    if payload.destination == "inbox" and not block and task.planned_at is None:
        return plan_block_result(None, "inbox", task_id=task.id, idempotent=True)
    old_planned, old_start, old_end = task.planned_at, block.start_at if block else None, block.end_at if block else None
    if payload.destination == "inbox":
        if block:
            db.delete(block)
            block = None
        task.planned_at = None
        destination = "inbox"
        new_start = new_end = None
    else:
        if payload.destination == "next_free":
            duration = payload.duration_minutes or (round((old_end - old_start).total_seconds() / 60) if old_start and old_end else None)
            candidate = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            candidate += timedelta(minutes=(15 - candidate.minute % 15) % 15)
            while True:
                try:
                    new_start, new_end = scheduled_range(db, candidate, duration, block.id if block else None)
                    break
                except HTTPException as error:
                    if error.status_code != 409: raise
                    candidate += timedelta(minutes=15)
        else:
            new_start, new_end = scheduled_range(db, payload.start_at, payload.duration_minutes, block.id if block else None)
        if block and aware_utc(block.start_at) == new_start and aware_utc(block.end_at) == new_end and task.planned_at and aware_utc(task.planned_at) == new_start:
            return plan_block_result(block, payload.destination, task_id=task.id, idempotent=True)
        if not block:
            block = PlanBlock(task_id=task.id, start_at=new_start, end_at=new_end); db.add(block); db.flush()
        else:
            block.start_at, block.end_at = new_start, new_end
        task.planned_at = new_start
        destination = payload.destination
    decision = PlanningDecision(operation="replan", task_id=task.id, block_id=block.id if block else None, from_planned_at=old_planned, to_planned_at=task.planned_at, from_start_at=old_start, from_end_at=old_end, to_start_at=block.start_at if block else None, to_end_at=block.end_at if block else None)
    db.add(decision); db.commit()
    if block: db.refresh(block)
    return plan_block_result(block, destination, decision_id=decision.id, task_id=task.id)


@app.post("/api/tasks/{task_id}/block", dependencies=[Depends(auth)])
def block_task(task_id: str, payload: BlockTaskRequest, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "task not found")
    action = db.scalar(select(Action).where(Action.task_id == task.id, Action.status.in_([ActionStatus.READY, ActionStatus.ACTIVE])).order_by(Action.position.asc(), Action.created_at.asc()))
    if not action:
        action = Action(task_id=task.id, text=task.title, estimated_minutes=10)
        db.add(action); db.flush()
    running = db.scalar(select(ExecutionSession).where(ExecutionSession.action_id == action.id, ExecutionSession.outcome == SessionOutcome.RUNNING).order_by(ExecutionSession.started_at.desc()).limit(1))
    if running:
        try:
            finish_session(db, running, SessionOutcome.STUCK, payload.reason)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
    action.status = ActionStatus.BLOCKED
    old_planned = task.planned_at
    old_block = db.scalar(select(PlanBlock).where(PlanBlock.task_id == task.id).order_by(PlanBlock.created_at.asc()))
    old_start, old_end = (old_block.start_at, old_block.end_at) if old_block else (None, None)
    if old_block:
        db.delete(old_block)
    task.planned_at = None
    decision = PlanningDecision(operation="blocked", task_id=task.id, block_id=old_block.id if old_block else None, from_planned_at=old_planned, from_start_at=old_start, from_end_at=old_end)
    db.add(decision)
    replacement = None
    if payload.resolution == "smaller":
        if not payload.smaller_title or not payload.smaller_action:
            raise HTTPException(422, "smaller_title and smaller_action are required")
        replacement = Task(title=payload.smaller_title, description=f"Kleinere stap voor: {task.title}", status=TaskStatus.ACTIVE, parent_id=task.id, source_type="stuck_resolver", planned_at=old_start)
        db.add(replacement); db.flush()
        db.add(Action(task_id=replacement.id, text=payload.smaller_action, estimated_minutes=10))
        if old_start and old_end:
            db.add(PlanBlock(task_id=replacement.id, start_at=old_start, end_at=old_end))
    db.commit()
    return {"task_id": task.id, "action_id": action.id, "status": "blocked", "resolution": payload.resolution, "replacement_task_id": replacement.id if replacement else None, "reason": payload.reason}


@app.post("/api/planning/undo", response_model=PlanningDecisionOut, dependencies=[Depends(auth)])
def undo_latest_planning(db: Session = Depends(get_db)):
    decision = db.scalar(select(PlanningDecision).where(PlanningDecision.undone_at.is_(None)).order_by(PlanningDecision.created_at.desc()).limit(1))
    if not decision:
        raise HTTPException(404, "no planning decision to undo")
    if decision.operation == "plan":
        suggestion = db.get(TaskSuggestionRecord, decision.suggestion_id) if decision.suggestion_id else None
        block = db.get(PlanBlock, decision.block_id) if decision.block_id else None
        if block: db.delete(block)
        task = db.get(Task, decision.task_id)
        if task: db.delete(task)
        if suggestion:
            suggestion.status = SuggestionStatus.PENDING
            suggestion.task_id = None
        decision.undone_at = datetime.now(timezone.utc)
        db.commit()
        return plan_block_result(None, "undone", decision_id=decision.id, suggestion_id=decision.suggestion_id, task_id=decision.task_id)
    task = db.get(Task, decision.task_id)
    if not task: raise HTTPException(409, "task no longer exists")
    block = db.get(PlanBlock, decision.block_id) if decision.block_id else None
    if decision.from_start_at and decision.from_end_at:
        if not block:
            block = PlanBlock(id=decision.block_id or str(uuid4()), task_id=task.id, start_at=decision.from_start_at, end_at=decision.from_end_at)
            db.add(block)
        else:
            block.start_at, block.end_at = decision.from_start_at, decision.from_end_at
    elif block:
        db.delete(block); block = None
    task.planned_at = decision.from_planned_at
    decision.undone_at = datetime.now(timezone.utc)
    db.commit()
    if block: db.refresh(block)
    return plan_block_result(block, "undone", decision_id=decision.id, task_id=task.id)


@app.get("/api/today-summary")
def today_summary(day: date | None = Query(default=None), timezone_name: str = Query(default="UTC", alias="timezone"), db: Session = Depends(get_db)):
    try:
        target = day or datetime.now(ZoneInfo(timezone_name)).date()
        start, end, tz = day_window(target, timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise HTTPException(400, str(error))
    start_utc, end_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    counts = {"done": 0, "continue": 0, "stuck": 0, "stop_for_today": 0}
    for log in db.scalars(select(CompletionLog)).all():
        created = log.created_at.replace(tzinfo=timezone.utc) if log.created_at and log.created_at.tzinfo is None else log.created_at
        if created and start_utc <= created.astimezone(timezone.utc) <= end_utc and log.outcome in counts:
            counts[log.outcome] += 1
    ready = db.scalar(select(func.count(Action.id)).where(Action.status == ActionStatus.READY)) or 0
    blocked = db.scalar(select(func.count(Action.id)).where(Action.status == ActionStatus.BLOCKED)) or 0
    important_done, small_done = daily_completion_counts(db)
    deadline_task = db.scalar(select(Task).where(Task.deadline.is_not(None), Task.status != TaskStatus.DONE).order_by(Task.deadline.asc()))
    minutes = 0
    now_utc = datetime.now(timezone.utc)
    for session in db.scalars(select(ExecutionSession).where(ExecutionSession.started_at < end_utc)).all():
        started = session.started_at.replace(tzinfo=timezone.utc) if session.started_at.tzinfo is None else session.started_at
        ended = session.ended_at.replace(tzinfo=timezone.utc) if session.ended_at and session.ended_at.tzinfo is None else (session.ended_at or now_utc)
        if ended and ended > start_utc and started < end_utc:
            minutes += max(0, round((min(ended, end_utc) - max(started, start_utc)).total_seconds() / 60))
    rolled_over = db.scalar(select(func.count(TaskRolloverEvent.id)).where(TaskRolloverEvent.rollover_date == target)) or 0
    long_open = db.scalars(select(Task).where(Task.status.not_in((TaskStatus.DONE, TaskStatus.ARCHIVED)), Task.created_at < start_utc - timedelta(days=7)).order_by(Task.created_at.asc()).limit(3)).all()
    return {**counts, "ready": ready, "blocked": blocked, "important_done": important_done, "small_done": small_done, "total_minutes": minutes, "rolled_over": rolled_over, "postponed": counts["stop_for_today"], "long_open_count": len(long_open), "long_open_titles": [task.title for task in long_open], "headline": "Goed bezig." if counts["done"] else "Elke start telt.", "next_deadline": deadline_task.deadline if deadline_task else None, "next_deadline_title": deadline_task.title if deadline_task else None}


@app.get("/api/daily-review", dependencies=[Depends(auth)])
def daily_review(timezone_name: str = Query(default="Europe/Amsterdam", alias="timezone"), db: Session = Depends(get_db)):
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(400, "invalid timezone") from error
    local_now = datetime.now(timezone.utc).astimezone(zone)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc, end_utc = start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
    open_proposals = db.scalars(select(TaskSuggestionRecord).where(TaskSuggestionRecord.status == SuggestionStatus.PENDING).order_by(TaskSuggestionRecord.created_at.asc()).limit(20)).all()
    active = [Task.status != TaskStatus.DONE, Task.status != TaskStatus.ARCHIVED]
    unplanned = db.scalars(select(Task).where(*active, Task.planned_at.is_(None), Task.status.in_([TaskStatus.INBOX, TaskStatus.ACTIVE])).order_by(Task.created_at.asc()).limit(20)).all()
    overdue = db.scalars(select(Task).where(*active, Task.deadline.is_not(None), Task.deadline < datetime.now(timezone.utc)).order_by(Task.deadline.asc()).limit(20)).all()
    today = db.scalars(select(Task).where(Task.status != TaskStatus.ARCHIVED, Task.planned_at >= start_utc, Task.planned_at < end_utc).order_by(Task.planned_at.asc()).limit(20)).all()
    blocked = db.scalars(select(Task).where(*active, Task.id.in_(select(Action.task_id).where(Action.status == ActionStatus.BLOCKED))).order_by(Task.created_at.asc()).limit(20)).all()
    if open_proposals:
        next_decision = "review"
        next_label = "Open eerste voorstel"
        next_href = "/review"
    elif unplanned:
        next_decision = "plan"
        next_label = "Plan ongepland werk"
        next_href = "/views"
    elif blocked:
        next_decision = "blocked"
        next_label = "Evalueer vastgelopen werk"
        next_href = "/daily-review#blocked"
    elif overdue:
        next_decision = "overdue"
        next_label = "Bekijk achterstallig werk"
        next_href = "/views"
    elif today:
        next_decision = "today"
        next_label = "Bekijk vandaag"
        next_href = "/today"
    else:
        next_decision = "quiet"
        next_label = "Geen review nodig"
        next_href = "/"
    return {
        "timezone": timezone_name,
        "date": start_local.date().isoformat(),
        "next_decision": next_decision,
        "next_label": next_label,
        "next_href": next_href,
        "open_proposals": [SuggestionOut.model_validate(item).model_dump(mode="json") for item in open_proposals],
        "unplanned_inbox": [TaskOut.model_validate(item).model_dump(mode="json") for item in unplanned],
        "overdue": [TaskOut.model_validate(item).model_dump(mode="json") for item in overdue],
        "today": [TaskOut.model_validate(item).model_dump(mode="json") for item in today],
        "blocked": [{"id": item.id, "title": item.title, "planned_at": item.planned_at, "action_id": next((action.id for action in item.actions if action.status == ActionStatus.BLOCKED), None), "reason": "Deze taak is gemarkeerd als vastgelopen."} for item in blocked],
    }


@app.post("/api/daily-review/complete", response_model=DailyReviewCompleteOut, dependencies=[Depends(auth)])
def complete_daily_review(payload: DailyReviewCompleteRequest, db: Session = Depends(get_db)):
    try:
        zone = ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(400, "invalid timezone") from error
    local_now = datetime.now(timezone.utc).astimezone(zone)
    review_date = local_now.date()
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc, end_utc = start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
    planned_today = db.scalars(select(Task).where(Task.planned_at >= start_utc, Task.planned_at < end_utc, Task.status != TaskStatus.ARCHIVED)).all()
    open_tasks = [task for task in planned_today if task.status != TaskStatus.DONE]
    blocked_tasks = db.scalars(select(Task).where(Task.status.not_in((TaskStatus.DONE, TaskStatus.ARCHIVED)), Task.id.in_(select(Action.task_id).where(Action.status == ActionStatus.BLOCKED)))).all()
    if open_tasks or blocked_tasks:
        for task in open_tasks:
            blocks = db.scalars(select(PlanBlock).where(PlanBlock.task_id == task.id)).all()
            first_block = blocks[0] if blocks else None
            for block in blocks:
                db.delete(block)
            db.add(PlanningDecision(operation="daily_review_replan", task_id=task.id, block_id=first_block.id if first_block else None, from_planned_at=task.planned_at, from_start_at=first_block.start_at if first_block else None, from_end_at=first_block.end_at if first_block else None))
            task.planned_at = None
        db.commit()
        message = "Open taken staan weer in je backlog voor een nieuwe planning." if not blocked_tasks else "Er staan nog vastgelopen taken klaar voor evaluatie. Ze blijven in je backlog tot je ze hebt aangepast."
        return DailyReviewCompleteOut(result="replanned", date=review_date, next_day=review_date + timedelta(days=1), completed_count=len(planned_today) - len(open_tasks), replanned_count=len(open_tasks), message=message, next_href="/daily-review#blocked" if blocked_tasks else "/views?day=tomorrow")
    db.commit()
    return DailyReviewCompleteOut(result="success", date=review_date, next_day=review_date + timedelta(days=1), completed_count=len(planned_today), replanned_count=0, message="Je plan voor vandaag is gelukt. Neem dit succes mee naar morgen.", next_href="/views?day=tomorrow")


@app.post("/api/actions/{action_id}/resolve", response_model=dict)
def resolve_action(action_id: str, payload: ResolveBlockedActionRequest, db: Session = Depends(get_db)):
    action = db.get(Action, action_id)
    if not action: raise HTTPException(404, "action not found")
    try:
        result = resolve_blocked_action(db, action, payload.resolution, payload.prerequisite_title, payload.prerequisite_action)
    except ValueError as e: raise HTTPException(409, str(e))
    return {"action": ActionOut.model_validate(result["action"]).model_dump(mode="json"), "prerequisite": TaskOut.model_validate(result["prerequisite"]).model_dump(mode="json") if result["prerequisite"] else None}


@app.post("/api/mcp/task-suggestions", response_model=SuggestionOut, dependencies=[Depends(auth)])
def suggestion(payload: TaskSuggestion, db: Session = Depends(get_db)):
    record = TaskSuggestionRecord(**payload.model_dump())
    db.add(record); db.commit(); db.refresh(record)
    return record


def external_suggestion(db: Session, source_type: str, source_ref: str | None):
    """Return an existing provider proposal for a stable external identifier.

    Provider deliveries are commonly retried. Only identifiers supplied by the
    provider participate in deduplication; manual/demo payloads without one
    remain valid independent proposals.
    """
    if not source_ref:
        return None
    return db.scalar(select(TaskSuggestionRecord).where(
        TaskSuggestionRecord.source_type == source_type,
        TaskSuggestionRecord.source_ref == str(source_ref),
    ).order_by(TaskSuggestionRecord.created_at.asc()))


@app.post("/api/connectors/gmail/intake", response_model=SuggestionOut, dependencies=[Depends(auth)])
def gmail_intake(payload: dict, db: Session = Depends(get_db)):
    title = str(payload.get("subject") or "Gmail-bericht")
    action = str(payload.get("suggested_next_action") or f"Lees het bericht: {title}")
    source_ref = str(payload["message_id"]) if payload.get("message_id") is not None else None
    existing = external_suggestion(db, "gmail", source_ref)
    if existing: return existing
    record = TaskSuggestionRecord(title=title, description=payload.get("snippet"), source_type="gmail", source_ref=source_ref, suggested_next_action=action, confidence=float(payload.get("confidence", .75)))
    db.add(record); db.commit(); db.refresh(record); return record


@app.post("/api/connectors/calendar/intake", response_model=SuggestionOut, dependencies=[Depends(auth)])
def calendar_intake(payload: dict, db: Session = Depends(get_db)):
    title = str(payload.get("title") or "Agenda-item")
    action = str(payload.get("suggested_next_action") or f"Bereid voor: {title}")
    deadline = datetime.fromisoformat(payload["start"]) if payload.get("start") else None
    source_ref = str(payload["event_id"]) if payload.get("event_id") is not None else None
    existing = external_suggestion(db, "calendar", source_ref)
    if existing: return existing
    record = TaskSuggestionRecord(title=title, description=payload.get("location"), source_type="calendar", source_ref=source_ref, deadline=deadline, suggested_next_action=action, confidence=float(payload.get("confidence", .8)))
    db.add(record); db.commit(); db.refresh(record); return record


@app.post("/api/connectors/whatsapp/intake", response_model=SuggestionOut, dependencies=[Depends(auth)])
def whatsapp_intake(payload: dict, db: Session = Depends(get_db)):
    sender = str(payload.get("sender") or "WhatsApp-contact")
    message = str(payload.get("message") or "Nieuw WhatsApp-bericht")
    source_ref = str(payload["message_id"]) if payload.get("message_id") is not None else None
    existing = external_suggestion(db, "whatsapp", source_ref)
    if existing: return existing
    record = TaskSuggestionRecord(title=f"WhatsApp van {sender}", description=message, source_type="whatsapp", source_ref=source_ref, suggested_next_action=str(payload.get("suggested_next_action") or f"Beantwoord WhatsApp-bericht van {sender}"), confidence=float(payload.get("confidence", .75)))
    db.add(record); db.commit(); db.refresh(record); return record


@app.get("/api/mcp/task-suggestions", response_model=list[SuggestionOut], dependencies=[Depends(auth)])
def list_suggestions(status: SuggestionStatus | None = None, db: Session = Depends(get_db)):
    q = select(TaskSuggestionRecord).order_by(TaskSuggestionRecord.created_at.desc())
    if status: q = q.where(TaskSuggestionRecord.status == status)
    return db.scalars(q).all()


@app.get("/api/inbox/review", response_model=SuggestionOut, dependencies=[Depends(auth)])
def next_inbox_review(db: Session = Depends(get_db)):
    record = db.scalar(select(TaskSuggestionRecord).where(TaskSuggestionRecord.status == SuggestionStatus.PENDING).order_by(TaskSuggestionRecord.created_at.asc()))
    if not record:
        raise HTTPException(404, "no pending inbox proposals")
    return record


@app.post("/api/inbox/review/{suggestion_id}/estimate", response_model=SuggestionOut, dependencies=[Depends(auth)])
def estimate_inbox_review(suggestion_id: str, gateway: LLMGateway = Depends(get_llm_gateway), db: Session = Depends(get_db)):
    record = db.get(TaskSuggestionRecord, suggestion_id)
    if not record:
        raise HTTPException(404, "suggestion not found")
    if record.status != SuggestionStatus.PENDING:
        raise HTTPException(409, "suggestion already decided")
    try:
        estimate = estimate_suggestion(gateway, record.title, record.description, record.suggested_next_action)
    except LLMError as exc:
        raise HTTPException(503, "Tijdsschatting is tijdelijk niet beschikbaar.") from exc
    record.suggested_estimated_minutes = estimate.estimated_minutes
    db.commit(); db.refresh(record)
    return record


@app.post("/api/mcp/task-suggestions/{suggestion_id}/approve", response_model=TaskOut, dependencies=[Depends(auth)])
def approve_suggestion(suggestion_id: str, payload: SuggestionApproval | None = None, db: Session = Depends(get_db)):
    record = db.get(TaskSuggestionRecord, suggestion_id)
    if not record: raise HTTPException(404, "suggestion not found")
    if record.status != SuggestionStatus.PENDING: raise HTTPException(409, "suggestion already decided")
    urgent = bool(payload and payload.urgent)
    task = Task(title=record.title, description=record.description, source_type=record.source_type, source_ref=record.source_ref, deadline=record.deadline, planned_at=record.planned_at, tags=record.tags or [], priority=TaskPriority.HIGH if urgent else TaskPriority.MEDIUM, status=TaskStatus.ACTIVE)
    db.add(task); db.flush()
    estimate = payload.estimated_minutes if payload and payload.estimated_minutes is not None else record.suggested_estimated_minutes
    db.add(Action(task_id=task.id, text=record.suggested_next_action, **({"estimated_minutes": estimate} if estimate is not None else {})))
    record.status = SuggestionStatus.ACCEPTED; record.task_id = task.id
    db.commit(); db.refresh(task); return task


@app.post("/api/mcp/task-suggestions/{suggestion_id}/reject", response_model=SuggestionOut, dependencies=[Depends(auth)])
def reject_suggestion(suggestion_id: str, db: Session = Depends(get_db)):
    record = db.get(TaskSuggestionRecord, suggestion_id)
    if not record: raise HTTPException(404, "suggestion not found")
    if record.status != SuggestionStatus.PENDING: raise HTTPException(409, "suggestion already decided")
    record.status = SuggestionStatus.REJECTED; db.commit(); db.refresh(record); return record


@app.get("/api/mcp/current-action", response_model=ActionOut, dependencies=[Depends(auth)])
def mcp_current(db: Session = Depends(get_db)):
    action = choose_action(db)
    if not action: raise HTTPException(404, "no current action")
    return action


@app.get("/api/mcp/today-status", response_model=TodayStatus, dependencies=[Depends(auth)])
def today_status(db: Session = Depends(get_db)):
    counts = {status: 0 for status in ActionStatus}
    for status, count in db.execute(select(Action.status, func.count(Action.id)).group_by(Action.status)):
        counts[status] = count
    important_done, small_done = daily_completion_counts(db)
    return {"ready": counts[ActionStatus.READY], "active": counts[ActionStatus.ACTIVE], "done": counts[ActionStatus.DONE], "blocked": counts[ActionStatus.BLOCKED], "important_done": important_done, "small_done": small_done}


@app.get("/api/mcp/search-tasks", response_model=list[TaskOut], dependencies=[Depends(auth)])
def search_tasks(q: str = Query(min_length=1), db: Session = Depends(get_db)):
    return db.scalars(select(Task).where(Task.title.ilike(f"%{q}%")).order_by(Task.created_at.desc()).limit(20)).all()


@app.post("/api/mcp/create-message-draft", dependencies=[Depends(auth)])
def create_message_draft(payload: MessageDraft):
    return {"status": "draft", "recipient": payload.recipient, "body": payload.body, "send_required": True}


@app.post("/api/mcp/send-message", dependencies=[Depends(auth)])
def send_message(payload: SendMessageRequest):
    if not payload.confirmed:
        raise HTTPException(409, "explicit confirmation required")
    return {"status": "sent", "recipient": payload.recipient, "body": payload.body, "confirmed": True}


def text_assistance_error(exc: LLMError) -> HTTPException:
    return HTTPException(503, "Teksthulp is tijdelijk niet beschikbaar.")


@app.post("/api/text/rewrite", response_model=TextRewriteResponse, dependencies=[Depends(auth)])
def rewrite_text_endpoint(payload: TextRewriteRequest, gateway: LLMGateway = Depends(get_llm_gateway)):
    try:
        return rewrite_text(gateway, payload.text, payload.tone)
    except LLMError as exc:
        raise text_assistance_error(exc) from exc


@app.post("/api/text/analyze", response_model=ToneAnalysisResponse, dependencies=[Depends(auth)])
def analyze_tone_endpoint(payload: ToneAnalysisRequest, gateway: LLMGateway = Depends(get_llm_gateway)):
    try:
        return analyze_tone(gateway, payload.text)
    except LLMError as exc:
        raise text_assistance_error(exc) from exc


@app.get("/api/ha/now", response_model=ActionOut, dependencies=[Depends(auth)])
def ha_now(is_home: bool = True, energy: str = "medium", computer_available: bool = True, max_minutes: int | None = Query(default=None, ge=1), db: Session = Depends(get_db)):
    action = choose_action(db, is_home=is_home, energy=energy, computer_available=computer_available, max_minutes=max_minutes)
    if not action: raise HTTPException(404, "no current action")
    return action


@app.get("/api/ha/todo-mirror", dependencies=[Depends(auth)])
def ha_todo_mirror(db: Session = Depends(get_db)):
    tasks = db.scalars(select(Task).where(Task.status != TaskStatus.ARCHIVED).order_by(Task.created_at.desc())).all()
    return [{"task_id": task.id, "title": task.title, "status": task.status.value, "deadline": task.deadline, "current_action": next((a.text for a in task.actions if a.status in (ActionStatus.READY, ActionStatus.ACTIVE)), None)} for task in tasks]


@app.post("/api/ha/sync", dependencies=[Depends(auth)])
def ha_sync(db: Session = Depends(get_db)):
    items = ha_todo_mirror(db)
    connection = ha_connection(db)
    envelope = {"origin": "add", "items": items}
    event = OutboxEvent(event_type="home_assistant.todo_mirror", payload=json.dumps(envelope), status="pending")
    db.add(event)
    db.commit()
    if not connection.get("webhook_url"):
        return {"status": "disabled", "items": items}
    headers = {"Authorization": f"Bearer {connection.get('token')}"} if connection.get("token") else {}
    try:
        response = httpx.post(connection["webhook_url"], json=envelope, headers=headers, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        event.status = "failed"; event.error = str(exc); db.commit()
        raise HTTPException(502, f"Home Assistant sync failed: {exc}") from exc
    event.status = "delivered"; event.delivered_at = datetime.now(timezone.utc); db.commit()
    return {"status": "sent", "items": len(items)}


@app.get("/api/ha/config", dependencies=[Depends(auth)])
def ha_config(db: Session = Depends(get_db)):
    connection = ha_connection(db)
    return {
        "webhook_configured": bool(connection.get("webhook_url")), "context_configured": bool(connection.get("context_url")),
        "webhook_token_configured": bool(connection.get("token")), "delivery_mode": "webhook" if connection.get("webhook_url") else "preview-only", "poll_mode": "live" if connection.get("context_url") else "manual-context",
    }


@app.post("/api/ha/test", dependencies=[Depends(auth)])
def ha_test(payload: dict, db: Session = Depends(get_db)):
    mode = payload.get("mode", "preview")
    connection = ha_connection(db)
    connection.update({key: payload[key] for key in ("webhook_url", "context_url", "token") if payload.get(key)})
    if mode == "webhook":
        return {"ok": bool(connection.get("webhook_url")), "mode": mode, "message": "Webhook is geconfigureerd." if connection.get("webhook_url") else "Geen webhook geconfigureerd; preview blijft actief."}
    if mode == "poll":
        if not connection.get("context_url"): return {"ok": False, "mode": mode, "message": "Geen context-URL geconfigureerd."}
        try:
            headers = {"Authorization": f"Bearer {connection.get('token')}"} if connection.get("token") else {}
            response = httpx.get(connection["context_url"], headers=headers, timeout=10); response.raise_for_status(); HAContext.model_validate(response.json())
            return {"ok": True, "mode": mode, "message": "Context-poll geslaagd."}
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "mode": mode, "message": f"Context-poll mislukt: {exc}"}
    return {"ok": True, "mode": "preview", "message": "Preview-modus is lokaal beschikbaar."}


@app.get("/api/ha/outbox", dependencies=[Depends(auth)])
def ha_outbox(db: Session = Depends(get_db)):
    events = db.scalars(select(OutboxEvent).order_by(OutboxEvent.created_at.desc()).limit(100)).all()
    return [{"id": event.id, "event_type": event.event_type, "status": event.status, "created_at": event.created_at, "delivered_at": event.delivered_at, "error": event.error} for event in events]


@app.post("/api/ha/outbox/{event_id}/retry", dependencies=[Depends(auth)])
def retry_ha_outbox(event_id: str, db: Session = Depends(get_db)):
    event = db.get(OutboxEvent, event_id)
    if not event:
        raise HTTPException(404, "outbox event not found")
    if event.status == "delivered":
        raise HTTPException(409, "outbox event already delivered")
    connection = ha_connection(db)
    if not connection.get("webhook_url"):
        return {"status": "disabled", "event_id": event.id}
    headers = {"Authorization": f"Bearer {connection.get('token')}"} if connection.get("token") else {}
    try:
        response = httpx.post(connection["webhook_url"], content=event.payload, headers={**headers, "Content-Type": "application/json"}, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        event.status = "failed"
        event.error = str(exc)
        db.commit()
        raise HTTPException(502, f"Home Assistant retry failed: {exc}") from exc
    event.status = "delivered"
    event.error = None
    event.delivered_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "sent", "event_id": event.id}


@app.post("/api/ha/poll", dependencies=[Depends(auth)])
def ha_poll(db: Session = Depends(get_db)):
    connection = ha_connection(db)
    if not connection.get("context_url"):
        return {"status": "disabled"}
    headers = {"Authorization": f"Bearer {connection.get('token')}"} if connection.get("token") else {}
    try:
        response = httpx.get(connection["context_url"], headers=headers, timeout=10)
        response.raise_for_status()
        context = HAContext.model_validate(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Home Assistant poll failed: {exc}") from exc
    action = choose_action(db, is_home=context.is_home, energy=context.energy, computer_available=context.computer_available, max_minutes=context.max_minutes)
    return {"status": "polled", "context": context.model_dump(), "action": ActionOut.model_validate(action).model_dump(mode="json") if action else None}


@app.post("/api/ha/events", response_model=SuggestionOut, dependencies=[Depends(auth)])
def ha_event(payload: HAEvent, db: Session = Depends(get_db)):
    if payload.origin == "add":
        raise HTTPException(409, "ignored mirrored ADD event")
    source_ref = str(payload.source_ref) if payload.source_ref is not None else None
    existing = external_suggestion(db, "home_assistant", source_ref)
    if existing: return existing
    record = TaskSuggestionRecord(title=payload.title, suggested_next_action=payload.action, source_type="home_assistant", source_ref=source_ref, deadline=payload.deadline, confidence=1.0)
    db.add(record); db.commit(); db.refresh(record); return record


@app.post("/api/mcp", dependencies=[Depends(auth)])
@app.post("/api/mcp/rpc", dependencies=[Depends(auth)])
def mcp_rpc(request: dict, db: Session = Depends(get_db)):
    """Small JSON-RPC bridge for Hermes until a full MCP transport is configured."""
    if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        raise HTTPException(400, "invalid JSON-RPC request")
    if request["method"] == "notifications/initialized":
        return Response(status_code=202)
    if "id" not in request:
        raise HTTPException(400, "request id required")
    request_id = request["id"]
    method = request["method"]
    params = request.get("params") or {}
    tools = {
        "execution_get_current_action": {"type": "object", "properties": {}, "additionalProperties": False},
        "execution_get_today_status": {"type": "object", "properties": {}, "additionalProperties": False},
        "execution_search_tasks": {"type": "object", "required": ["q"], "properties": {"q": {"type": "string", "minLength": 1}}, "additionalProperties": False},
        "execution_create_task_suggestion": {"type": "object", "required": ["title", "suggested_next_action", "confidence"], "properties": {"title": {"type": "string"}, "suggested_next_action": {"type": "string"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}}, "additionalProperties": True},
        "execution_create_message_draft": {"type": "object", "required": ["recipient", "body"], "properties": {"recipient": {"type": "string"}, "body": {"type": "string"}}, "additionalProperties": False},
        "execution_start_action": {"type": "object", "required": ["action_id"], "properties": {"action_id": {"type": "string"}}, "additionalProperties": False},
        "execution_complete_action": {"type": "object", "required": ["session_id", "outcome"], "properties": {"session_id": {"type": "string"}, "outcome": {"enum": ["done", "continue", "stuck", "stop_for_today"]}, "stuck_reason": {"type": ["string", "null"]}}, "additionalProperties": False},
        "execution_mark_stuck": {"type": "object", "required": ["session_id"], "properties": {"session_id": {"type": "string"}, "stuck_reason": {"type": ["string", "null"]}}, "additionalProperties": False},
        "get_mail_summary": {"type": "object", "properties": {}, "additionalProperties": False},
        "get_mail_triage_queue": {"type": "object", "properties": {}, "additionalProperties": False},
        "approve_mail_action": {"type": "object", "required": ["message_id", "action"], "properties": {"message_id": {"type": "string"}, "action": {"enum": ["archive", "trash", "unsubscribe"]}}, "additionalProperties": False},
        "retry_mail_sync": {"type": "object", "properties": {}, "additionalProperties": False},
        "create_task_from_email": {"type": "object", "required": ["message_id"], "properties": {"message_id": {"type": "string"}}, "additionalProperties": False},
        "draft_reply_from_email": {"type": "object", "required": ["message_id"], "properties": {"message_id": {"type": "string"}}, "additionalProperties": False},
    }
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {"listChanged": False}, "resources": {}, "prompts": {"listChanged": False}}, "serverInfo": {"name": "add-execution", "version": app.version}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": [
            {"name": "decompose_task", "description": "Maak één concrete volgende actie uit een gewenst resultaat."},
            {"name": "draft_message", "description": "Maak een kort berichtconcept dat altijd expliciete bevestiging vereist."},
            {"name": "resolve_stuck", "description": "Verklein een geblokkeerde actie of stel een prerequisite voor."},
        ]}}
    if method == "prompts/get":
        name = params.get("name") or ""
        templates = {
            "decompose_task": "Gewenst resultaat: {task}. Geef precies één uitvoerbare volgende actie.",
            "draft_message": "Context: {context}. Schrijf een kort concept aan {recipient}; verstuur niets.",
            "resolve_stuck": "Geblokkeerde actie: {action}. Stel één kleinere stap of prerequisite voor.",
        }
        if name not in templates:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "prompt not found"}}
        text = templates[name]
        for key, value in (params.get("arguments") or {}).items():
            text = text.replace("{" + str(key) + "}", str(value))
        return {"jsonrpc": "2.0", "id": request_id, "result": {"description": name, "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [{"name": name, "inputSchema": schema} for name, schema in tools.items()]}}
    if method != "tools/call" or params.get("name") not in tools:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "method or tool not found"}}
    name = params["name"]; arguments = params.get("arguments") or {}
    try:
        if name == "execution_get_current_action":
            result = mcp_current(db)
        elif name == "execution_get_today_status":
            result = today_status(db)
        elif name == "execution_search_tasks":
            result = search_tasks(arguments.get("q", ""), db)
        elif name == "execution_create_task_suggestion":
            result = suggestion(TaskSuggestion.model_validate(arguments), db)
        elif name == "execution_start_action":
            result = start(arguments.get("action_id", ""), db)
        elif name == "execution_complete_action":
            result = finish(arguments.get("session_id", ""), SessionResult.model_validate(arguments), db)
        elif name == "execution_mark_stuck":
            result = finish(arguments.get("session_id", ""), SessionResult(outcome=SessionOutcome.STUCK, stuck_reason=arguments.get("stuck_reason")), db)
        else:
            result = create_message_draft(MessageDraft.model_validate(arguments))
    except (ValidationError, ValueError) as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "invalid tool arguments", "data": str(exc)}}
    if hasattr(result, "model_dump"):
        result = result.model_dump(mode="json")
    elif isinstance(result, list):
        result = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in result]
    return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "json", "json": result}]}}
