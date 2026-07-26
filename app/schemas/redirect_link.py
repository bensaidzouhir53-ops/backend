from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _normalize_slug(value: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned:
        raise ValueError("Slug is required")
    if not all(ch.isalnum() or ch == "-" for ch in cleaned):
        raise ValueError("Slug may only contain letters, numbers, and hyphens")
    return cleaned


def _normalize_target_path(value: str) -> str:
    cleaned = value.strip()
    if cleaned.lower().startswith(("http://", "https://")):
        parsed = urlparse(cleaned)
        cleaned = parsed.path or "/"
        if parsed.query:
            cleaned = f"{cleaned}?{parsed.query}"
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    if "?" not in cleaned and cleaned != "/" and cleaned.endswith("/"):
        cleaned = cleaned.rstrip("/")
    return cleaned


class RedirectLinkCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    target_path: str = Field(min_length=1, max_length=500)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        return _normalize_slug(value)

    @field_validator("target_path")
    @classmethod
    def validate_target_path(cls, value: str) -> str:
        return _normalize_target_path(value)


class RedirectLinkUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    target_path: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_slug(value)

    @field_validator("target_path")
    @classmethod
    def validate_target_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_target_path(value)


class RedirectLinkOut(BaseModel):
    id: UUID
    slug: str
    target_path: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RedirectLookupOut(BaseModel):
    slug: str
    target_path: str
