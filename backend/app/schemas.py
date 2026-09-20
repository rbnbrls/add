from datetime import date as date_type, datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from .models import ActionStatus, DecompositionStatus, SessionOutcome, SuggestionStatus, TaskPriority, TaskStatus


def normalize_tags(value: list[str]) -> list[str]:
    normalized = []
    for tag in value:
        item = tag.strip()
        if not item:
            raise ValueError("tags mogen geen lege waarden bevatten")
        if item not in normalized:
            normalized.append(item)
    return normalized


class ActionCreate(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    estimated_minutes: int = Field(default=10, ge=1, le=180)
    energy: str = "medium"
    requires_home: bool = False
    requires_computer: bool = False


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = None
    category: str | None = None
    deadline: datetime | None = None
    planned_at: datetime | None = None
    actual_minutes: int = Field(default=0, ge=0)
    parent_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    priority: TaskPriority = TaskPriority.MEDIUM
    source_type: str = "manual"
    source_ref: str | None = None
    next_action: ActionCreate | None = None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value):
        return normalize_tags(value)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    status: TaskStatus | None = None
    category: str | None = None
    deadline: datetime | None = None
    planned_at: datetime | None = None
    actual_minutes: int | None = Field(default=None, ge=0)
    parent_id: str | None = None
    tags: list[str] | None = None
    priority: TaskPriority | None = None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value):
        return None if value is None else normalize_tags(value)


class TaskChildOut(BaseModel):
    id: str
    title: str
    status: TaskStatus
    model_config = {"from_attributes": True}


class ActionOut(BaseModel):
    id: str; text: str; status: ActionStatus; estimated_minutes: int; energy: str
    requires_home: bool; requires_computer: bool; task_id: str
    model_config = {"from_attributes": True}


class TaskOut(BaseModel):
    id: str; title: str; description: str | None; status: TaskStatus; category: str | None
    deadline: datetime | None; planned_at: datetime | None; actual_minutes: int
    parent_id: str | None; tags: list[str]; priority: TaskPriority
    source_type: str; source_ref: str | None; created_at: datetime; children: list[TaskChildOut] = Field(default_factory=list)
    model_config = {"from_attributes": True}


class SmartViewFilters(BaseModel):
    period: Literal["today", "week"] | None = None
    overdue: bool = False
    source: str | None = Field(default=None, min_length=1, max_length=40)
    priority: TaskPriority | None = None
    blocked: bool = False
    unplanned: bool = False
    timezone: str = "Europe/Amsterdam"


class SmartViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    filters: SmartViewFilters


class SmartViewOut(BaseModel):
    id: str
    name: str
    filters: SmartViewFilters
    created_at: datetime
    model_config = {"from_attributes": True}


class WorkflowSourceCountOut(BaseModel):
    source_type: str
    count: int


class WorkflowStageOut(BaseModel):
    count: int
    sources: list[WorkflowSourceCountOut] = Field(default_factory=list)
    long_open_count: int = 0
    today_count: int = 0
    upcoming_count: int = 0
    missed_count: int = 0
    breakdown: dict[str, int] = Field(default_factory=dict)
    href: str


class WorkflowNextOut(BaseModel):
    key: str
    label: str
    href: str


class WorkflowSummaryOut(BaseModel):
    inbox: WorkflowStageOut
    later: WorkflowStageOut
    planned: WorkflowStageOut
    review: WorkflowStageOut
    next: WorkflowNextOut


class AppPreferenceOut(BaseModel):
    workflow_badge_mode: Literal["hidden", "dot", "count"]
    task_assistant_prompt: str
    llm_provider: str
    llm_base_url: str
    llm_model: str
    model_config = {"from_attributes": True}


class LLMSettingsOut(BaseModel):
    provider: Literal["openrouter"]
    base_url: str
    model: str
    configured: bool


class FreeLLMModelOut(BaseModel):
    id: str
    name: str
    context_length: int | None = None


class FreeLLMModelCatalogOut(BaseModel):
    configured: bool
    models: list[FreeLLMModelOut] = Field(default_factory=list)


class AppPreferenceUpdate(BaseModel):
    workflow_badge_mode: Literal["hidden", "dot", "count"]
    task_assistant_prompt: str | None = Field(default=None, min_length=1, max_length=2000)
    llm_provider: Literal["openrouter"] | None = None
    llm_base_url: str | None = Field(default=None, min_length=1, max_length=240)
    llm_model: str | None = Field(default=None, min_length=1, max_length=160)
    llm_api_key: str | None = Field(default=None, max_length=500)


class DecompositionApprovalRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=8)


class DecompositionRequest(BaseModel):
    child_count: int = Field(ge=2, le=8)


class DecompositionChild(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=4000)


class DecompositionResult(BaseModel):
    children: list[DecompositionChild] = Field(min_length=2, max_length=8)


class DecompositionItemOut(BaseModel):
    id: str
    title: str
    description: str | None
    position: int
    model_config = {"from_attributes": True}


class DecompositionProposalOut(BaseModel):
    id: str
    parent_id: str
    requested_count: int
    status: DecompositionStatus
    created_at: datetime
    updated_at: datetime
    items: list[DecompositionItemOut] = Field(default_factory=list)
    model_config = {"from_attributes": True}


class DecompositionApprovalOut(BaseModel):
    proposal: DecompositionProposalOut
    tasks: list[TaskOut]


class StartOut(BaseModel):
    session_id: str; action: ActionOut; started_at: datetime; duration_seconds: int = 600; paused_at: datetime | None = None; paused_seconds: int = 0


class SessionResult(BaseModel):
    outcome: SessionOutcome
    stuck_reason: str | None = None


class FocusDuration(BaseModel):
    duration_seconds: int = Field(default=600, ge=60, le=7200)


class DayCheckRequest(BaseModel):
    date: date_type | None = None
    timezone: str = "UTC"


class PlanBlockCreate(BaseModel):
    task_id: str = Field(min_length=1)
    start_at: datetime
    end_at: datetime


class PlanBlockOut(BaseModel):
    id: str
    task_id: str
    start_at: datetime
    end_at: datetime
    task_title: str
    task_status: TaskStatus = TaskStatus.ACTIVE
    model_config = {"from_attributes": True}


class PlanSuggestionRequest(BaseModel):
    destination: Literal["today", "at", "inbox"] = "today"
    start_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=180)
    urgent: bool = False


class ReplanRequest(BaseModel):
    destination: Literal["inbox", "next_free", "at"]
    start_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=180)


class DailyReviewCompleteRequest(BaseModel):
    timezone: str = "Europe/Amsterdam"


class DailyReviewCompleteOut(BaseModel):
    result: Literal["success", "replanned"]
    date: date_type
    next_day: date_type
    completed_count: int
    replanned_count: int
    message: str
    next_href: str


class BlockTaskRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=40)
    resolution: Literal["backlog", "smaller"] = "backlog"
    smaller_title: str | None = Field(default=None, min_length=1, max_length=240)
    smaller_action: str | None = Field(default=None, min_length=1, max_length=300)


class PlanningDecisionOut(BaseModel):
    decision_id: str | None = None
    suggestion_id: str | None = None
    task_id: str
    destination: str
    idempotent: bool = False
    block: PlanBlockOut | None = None


class RoutineCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    action_text: str = Field(min_length=1, max_length=300)
    recurrence: Literal["daily", "weekly", "specific_day"]
    weekday: int | None = Field(default=None, ge=0, le=6)
    specific_date: date_type | None = None
    local_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "UTC"
    estimated_minutes: int = Field(default=10, ge=1, le=180)


class RoutineOut(RoutineCreate):
    id: str
    enabled: bool
    model_config = {"from_attributes": True}


class ReminderSettings(BaseModel):
    provider: Literal["none", "browser", "ha"] = "none"
    enabled: bool = False
    quiet_start: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "UTC"
    model_config = {"from_attributes": True}


class OfflineCompletion(BaseModel):
    action_id: str = Field(min_length=1)
    outcome: SessionOutcome
    started_at: datetime
    stuck_reason: str | None = None


class TaskSuggestion(BaseModel):
    title: str
    description: str | None = None
    source_type: str = "hermes"
    source_ref: str | None = None
    deadline: datetime | None = None
    suggested_next_action: str
    confidence: float = Field(ge=0, le=1)
    batch_id: str | None = None
    suggested_estimated_minutes: int | None = Field(default=None, ge=1, le=180)


class NaturalLanguageCaptureRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    source_type: Literal["natural_language", "shortcut", "web_link", "voice_transcript"] = "natural_language"
    source_ref: str | None = Field(default=None, min_length=1, max_length=240)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=240)
    timezone: str = "Europe/Amsterdam"

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("capture text may not be empty")
        return value


class NaturalLanguageCaptureResult(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=4000)
    planned_at: datetime | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    suggested_next_action: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)
    deadline: datetime | None = None
    parsed_duration_minutes: int | None = Field(default=None, ge=1, le=180)
    recurrence: str | None = Field(default=None, max_length=80)
    schedule_timezone: str | None = None
    schedule_status: Literal["none", "parsed", "ambiguous"] = "none"
    schedule_notes: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("planned_at")
    @classmethod
    def normalize_planned_at(cls, value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

    @field_validator("tags")
    @classmethod
    def validate_capture_tags(cls, value):
        return normalize_tags(value)


class BrainDumpProposal(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=4000)
    planned_at: datetime | None = None
    deadline: datetime | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    suggested_next_action: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)
    suggested_estimated_minutes: int | None = Field(default=None, ge=1, le=180)

    @field_validator("planned_at", "deadline")
    @classmethod
    def normalize_dates(cls, value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

    @field_validator("tags")
    @classmethod
    def validate_brain_dump_tags(cls, value):
        return normalize_tags(value)


class BrainDumpResult(BaseModel):
    proposals: list[BrainDumpProposal] = Field(min_length=1, max_length=8)


class SuggestionEstimateResult(BaseModel):
    estimated_minutes: int = Field(ge=1, le=180)


class SuggestionApproval(BaseModel):
    estimated_minutes: int | None = Field(default=None, ge=1, le=180)
    urgent: bool = False


class SuggestionOut(BaseModel):
    id: str
    title: str
    description: str | None
    source_type: str
    source_ref: str | None
    batch_id: str | None = None
    deadline: datetime | None
    original_input: str | None = None
    planned_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    suggested_next_action: str
    confidence: float
    suggested_estimated_minutes: int | None = None
    parsed_duration_minutes: int | None = None
    recurrence: str | None = None
    schedule_timezone: str | None = None
    schedule_status: str = "none"
    schedule_notes: list[str] = Field(default_factory=list)
    status: SuggestionStatus
    task_id: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class NaturalLanguageCaptureResponse(BaseModel):
    mode: Literal["parsed", "plain_text"]
    suggestion: SuggestionOut


class HAContext(BaseModel):
    is_home: bool = True
    energy: str = "medium"
    computer_available: bool = True
    max_minutes: int | None = Field(default=None, ge=1)


class HAEvent(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    action: str = Field(min_length=1, max_length=300)
    source_ref: str | None = None
    deadline: datetime | None = None
    origin: str = "home_assistant"


class MessageDraft(BaseModel):
    recipient: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=4000)


class SendMessageRequest(MessageDraft):
    confirmed: bool = False


class TextRewriteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    tone: Literal["formal", "informal"]

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("text may not be empty")
        return value


class TextRewriteResponse(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ToneAnalysisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("text may not be empty")
        return value


class ToneAnalysisResponse(BaseModel):
    tone: str = Field(min_length=1, max_length=1000)
    emotion: str = Field(min_length=1, max_length=1000)
    directness: str = Field(min_length=1, max_length=1000)
    attention_point: str = Field(min_length=1, max_length=2000)


class StartActionRequest(BaseModel):
    action_id: str = Field(min_length=1)


class AccountabilityStartRequest(BaseModel):
    execution_session_id: str = Field(min_length=1)
    participant_label: str = Field(default="lokale buddy", min_length=1, max_length=120)


class AccountabilityFinishRequest(BaseModel):
    status: str = Field(pattern="^(completed|stopped)$")


class AccountabilityOut(BaseModel):
    id: str
    execution_session_id: str
    participant_label: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    model_config = {"from_attributes": True}


class CompleteActionRequest(BaseModel):
    session_id: str = Field(min_length=1)
    outcome: SessionOutcome
    stuck_reason: str | None = None


class ResolveBlockedActionRequest(BaseModel):
    resolution: str = Field(pattern="^(retry|create_prerequisite)$")
    prerequisite_title: str | None = Field(default=None, min_length=1, max_length=240)
    prerequisite_action: str | None = Field(default=None, min_length=1, max_length=300)


class TodayStatus(BaseModel):
    ready: int
    active: int
    done: int
    blocked: int
    important_done: int = 0
    small_done: int = 0


class CompletionOut(BaseModel):
    id: str
    action_id: str
    session_id: str
    outcome: str
    created_at: datetime
    action_text: str | None = None
    task_title: str | None = None
    model_config = {"from_attributes": True}
