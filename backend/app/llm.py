import json
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import select

from .config import Settings, settings
from .security import read_encrypted_credential
from .models import AppPreference

#: The gateway returns whichever schema the caller asked for. Without the
#: TypeVar every caller would receive a bare ``BaseModel`` and every schema
#: attribute access at the call site would be unverifiable.
ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMError(Exception):
    """Base class for safe, provider-independent gateway errors."""


class LLMConfigurationError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMProviderError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


def fetch_openrouter_free_models(base_url: str, api_key: str, timeout_seconds: float) -> list[dict]:
    """Return only models whose current OpenRouter text pricing is zero."""
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"output_modalities": "text", "sort": "most-popular"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise LLMProviderError("OpenRouter model catalog is unavailable") from exc
    free = []
    for item in data:
        pricing = item.get("pricing") or {}
        if str(pricing.get("prompt")) == "0" and str(pricing.get("completion")) == "0" and str(pricing.get("request", "0")) == "0":
            free.append({"id": item.get("id"), "name": item.get("name") or item.get("id"), "context_length": item.get("context_length")})
    return [item for item in free if item["id"]]


class LLMProvider(Protocol):
    def complete(self, *, model: str, messages: list[dict[str, str]], api_key: str) -> str:
        """Return the assistant message content from a provider."""


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, timeout_seconds: float):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def complete(self, *, model: str, messages: list[dict[str, str]], api_key: str) -> str:
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": 0},
                timeout=self.timeout_seconds,
            )
            if response.is_error:
                raise LLMProviderError(f"LLM provider returned HTTP {response.status_code}")
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("LLM provider request timed out") from exc
        except LLMProviderError:
            raise
        except httpx.RequestError as exc:
            raise LLMProviderError("LLM provider request failed") from exc

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("LLM provider returned an invalid response") from exc
        if not isinstance(content, str):
            raise LLMProviderError("LLM provider returned invalid message content")
        return content


def build_json_system_prompt(response_model: type[BaseModel]) -> str:
    schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    return (
        "Return exactly one JSON object and nothing else. Do not use Markdown code fences "
        "or explanatory text. The JSON object must conform to this JSON Schema: " + schema
    )


class LLMGateway:
    """Read-only structured-output gateway for OpenAI-compatible providers."""

    def __init__(
        self,
        db: Session,
        config: Settings = settings,
        provider: LLMProvider | None = None,
    ):
        self.db = db
        self.config = config
        self.provider = provider or OpenAICompatibleProvider(config.llm_base_url, config.llm_timeout_seconds)

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ModelT],
    ) -> ModelT:
        preference = self.db.scalar(select(AppPreference).order_by(AppPreference.id.asc()))
        base_url = preference.llm_base_url if preference else self.config.llm_base_url
        model = preference.llm_model if preference else self.config.llm_model
        api_key = self._api_key(preference)
        base_system_prompt = build_json_system_prompt(response_model)
        messages = [
            {"role": "system", "content": f"{system_prompt}\n\n{base_system_prompt}"},
            {"role": "user", "content": user_prompt},
        ]
        provider = self.provider if preference is None or base_url == self.config.llm_base_url else OpenAICompatibleProvider(base_url, self.config.llm_timeout_seconds)
        content = provider.complete(model=model, messages=messages, api_key=api_key)
        if not content.strip():
            raise LLMResponseError("LLM provider returned empty content")
        try:
            payload: Any = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError("LLM provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise LLMResponseError("LLM provider returned a JSON value instead of an object")
        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            raise LLMResponseError("LLM provider JSON did not match the requested schema") from exc

    def _api_key(self, preference: AppPreference | None = None) -> str:
        base_url = preference.llm_base_url if preference else self.config.llm_base_url
        model = preference.llm_model if preference else self.config.llm_model
        provider = preference.llm_credential_provider if preference else self.config.llm_credential_provider
        if not base_url.strip():
            raise LLMConfigurationError("LLM base URL is not configured")
        if not model.strip():
            raise LLMConfigurationError("LLM model is not configured")
        api_key = read_encrypted_credential(self.db, provider)
        if not api_key:
            raise LLMConfigurationError("LLM credential is not configured")
        return api_key
