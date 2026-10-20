"""User, session and profile schemas for the AQG authentication layer.

The persistence layer stores these as relational rows; this module owns the
in-memory representation, input validation and the public projection that is
safe to return to the browser (never a password hash, never a session token).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from config.settings import settings

ProviderName = Literal["google", "password"]

#: Deliberately permissive: the authoritative check is the round-trip email we
#: may send later, so we only reject obviously malformed addresses here.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_NAME_LENGTH = 120
MAX_PICTURE_URL_LENGTH = 1024


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(slots=True)
class AuthenticatedUser:
    """A verified, signed-in principal resolved from a session cookie."""

    id: str
    email: str
    full_name: str = ""
    picture_url: str = ""
    provider: str = "password"
    created_at: str = ""
    last_login_at: str = ""
    session_id: str = ""
    csrf_token: str = ""
    is_new: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        """Projects the user without any secret or session material."""
        return {
            "user_id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "picture_url": self.picture_url,
            "provider": self.provider,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


def normalize_email(value: str) -> str:
    """Lower-cases and trims an email address for stable uniqueness checks."""
    return (value or "").strip().lower()


class RegisterRequest(BaseModel):
    """Email + password registration payload."""

    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=settings.PASSWORD_MAX_LENGTH)
    full_name: str = Field("", max_length=MAX_NAME_LENGTH)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not _EMAIL_PATTERN.match(normalized):
            raise ValueError("Please enter a valid email address.")
        return normalized

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return (value or "").strip()


class GuestSignInRequest(BaseModel):
    """Guest sign-in payload: an email plus optional display name, no password."""

    email: str = Field(..., min_length=3, max_length=254)
    full_name: str = Field("", max_length=MAX_NAME_LENGTH)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if not _EMAIL_PATTERN.match(normalized):
            raise ValueError("Please enter a valid email address.")
        return normalized

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return (value or "").strip()


class LoginRequest(BaseModel):
    """Email + password sign-in payload."""

    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=settings.PASSWORD_MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        return normalize_email(value)


class ProfileUpdateRequest(BaseModel):
    """Editable profile fields."""

    full_name: Optional[str] = Field(None, max_length=MAX_NAME_LENGTH)
    picture_url: Optional[str] = Field(None, max_length=MAX_PICTURE_URL_LENGTH)

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()

    @field_validator("picture_url")
    @classmethod
    def _clean_picture(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned and not cleaned.lower().startswith(("http://", "https://")):
            raise ValueError("Please provide a valid https image URL.")
        return cleaned


__all__ = [
    "AuthenticatedUser",
    "GuestSignInRequest",
    "LoginRequest",
    "ProfileUpdateRequest",
    "ProviderName",
    "RegisterRequest",
    "normalize_email",
]
