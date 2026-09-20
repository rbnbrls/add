import base64
import hashlib
import json

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import IntegrationCredential


def credential_box() -> Fernet:
    if settings.credential_encryption_key:
        return Fernet(settings.credential_encryption_key.encode())
    # Keeps local development usable while making the fallback deterministic;
    # production deployments should always provide a dedicated key.
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.session_secret.encode()).digest())
    return Fernet(key)


def read_encrypted_credential(db: Session, provider: str) -> str | None:
    item = db.scalar(select(IntegrationCredential).where(IntegrationCredential.provider == provider))
    if not item:
        return None
    try:
        value = credential_box().decrypt(item.encrypted_value.encode()).decode()
    except Exception:
        return None
    return value or None


def read_json_credential(db: Session, provider: str) -> dict | None:
    value = read_encrypted_credential(db, provider)
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None
