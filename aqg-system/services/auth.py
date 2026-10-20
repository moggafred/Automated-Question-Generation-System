"""Authentication primitives for the AQG platform.

This module owns three concerns and nothing else:

* **Password credentials** -- hashing and verification via ``pwdlib``
  (argon2id). Legacy scrypt hashes from earlier releases are still verified so
  existing accounts keep working; they are rehashed on the next successful
  password sign-in.
* **Opaque server-side sessions** -- random bearer tokens are handed to the
  browser, while only their SHA-256 digest ever touches the database. A stolen
  database therefore cannot be replayed against the running service.
* **Google account resolution** -- turning a verified OIDC userinfo payload
  (delivered by authlib in the router) into a local user row.

Nothing here fabricates identity: every session traces back to a stored user row
and every Google sign-in to a verified provider response.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pwdlib import PasswordHash

from config.settings import settings
from errors import AuthProviderError, ValidationError
from services import database

logger = logging.getLogger("aqg.auth")

#: Argon2id parameters recommended by pwdlib; memory-hard and offline-cracking resistant.
password_hasher = PasswordHash.recommended()

# --- Legacy scrypt parameters (verification only) --------------------------
# Older accounts were hashed with hashlib.scrypt; these constants are retained
# so those credentials can still be verified during the migration window.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64
_SCRYPT_SALT_BYTES = 16


# ==========================================================================
# Password credentials
# ==========================================================================
def validate_password_strength(password: str) -> str:
    """Ensures a candidate password meets the configured length policy."""
    if not isinstance(password, str) or not password:
        raise ValidationError("Please choose a password.")
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValidationError(
            f"Your password must be at least {settings.PASSWORD_MIN_LENGTH} characters long."
        )
    if len(password) > settings.PASSWORD_MAX_LENGTH:
        raise ValidationError(
            f"Your password must be at most {settings.PASSWORD_MAX_LENGTH} characters long."
        )
    if not password.strip():
        raise ValidationError("Please choose a password that is not only whitespace.")
    return password


def hash_password(password: str) -> str:
    """Derives an argon2id hash for storage."""
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string.")
    return password_hasher.hash(password)


def _verify_legacy_scrypt(password: str, stored_hash: str) -> bool:
    """Verifies a password against a legacy self-describing scrypt hash."""
    try:
        scheme, n_raw, r_raw, p_raw, salt_hex, digest_hex = stored_hash.split("$")
        if scheme != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_raw),
            r=int(r_raw),
            p=int(p_raw),
            dklen=len(bytes.fromhex(digest_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived.hex(), digest_hex)


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    """Constant-time verification; understands argon2id and legacy scrypt hashes."""
    if not password or not stored_hash:
        return False
    try:
        return password_hasher.verify(password, stored_hash)
    except Exception:  # noqa: BLE001 - unrecognised or malformed hash
        return _verify_legacy_scrypt(password, stored_hash)


def needs_rehash(stored_hash: str) -> bool:
    """True when a stored hash predates the current argon2id scheme."""
    try:
        return password_hasher.check_needs_rehash(stored_hash)
    except Exception:  # noqa: BLE001 - legacy hashes always need rehashing
        return True


async def async_hash_password(password: str) -> str:
    """Hashes a password off the event loop (scrypt is intentionally CPU-heavy)."""
    return await asyncio.to_thread(hash_password, password)


async def async_verify_password(password: str, stored_hash: Optional[str]) -> bool:
    return await asyncio.to_thread(verify_password, password, stored_hash)


# --- Opaque session tokens -------------------------------------------------
def generate_session_token() -> str:
    """Returns a high-entropy, URL-safe bearer token for the session cookie."""
    return secrets.token_urlsafe(48)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """SHA-256 digests the bearer token; only this digest is persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def session_expiry_iso() -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=max(60, settings.SESSION_TTL_SECONDS))
    ).isoformat(timespec="microseconds")


def new_user_id() -> str:
    return uuid.uuid4().hex


async def create_session_for_user(user_id: str) -> dict[str, str]:
    """Creates a persisted session and returns the browser-facing token bundle.

    The returned ``token`` is the only copy that will ever exist in plaintext.
    """
    token = generate_session_token()
    csrf_token = generate_csrf_token()
    session_id = uuid.uuid4().hex
    expires_at = session_expiry_iso()

    await database.async_create_session(
        session_id=session_id,
        user_id=user_id,
        token_hash=hash_session_token(token),
        csrf_token=csrf_token,
        expires_at=expires_at,
    )
    return {
        "session_id": session_id,
        "token": token,
        "csrf_token": csrf_token,
        "expires_at": expires_at,
    }


async def resolve_session(token: Optional[str]) -> Optional[dict[str, Any]]:
    """Returns the joined session+user record for a live token, else ``None``."""
    if not token:
        return None
    return await database.async_get_session_by_token_hash(hash_session_token(token))


async def revoke_session(token: Optional[str]) -> bool:
    if not token:
        return False
    return await database.async_delete_session_by_token_hash(hash_session_token(token))


# --- Cookie attributes -----------------------------------------------------
def session_cookie_settings() -> dict[str, Any]:
    """Attribute bundle for the HttpOnly session cookie."""
    return {
        "key": settings.SESSION_COOKIE_NAME,
        "httponly": True,
        "secure": bool(settings.SESSION_COOKIE_SECURE),
        "samesite": settings.SESSION_COOKIE_SAMESITE,
        "max_age": max(60, settings.SESSION_TTL_SECONDS),
        "path": "/",
    }


def csrf_cookie_settings() -> dict[str, Any]:
    """Attribute bundle for the readable CSRF cookie (double-submit pattern).

    This cookie must be readable by JavaScript so the SPA can echo it back in the
    ``X-CSRF-Token`` header, hence ``httponly=False``.
    """
    return {
        "key": settings.CSRF_COOKIE_NAME,
        "httponly": False,
        "secure": bool(settings.SESSION_COOKIE_SECURE),
        "samesite": settings.SESSION_COOKIE_SAMESITE,
        "max_age": max(60, settings.SESSION_TTL_SECONDS),
        "path": "/",
    }


async def upsert_google_user(userinfo: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Resolves a Google profile to a local user, creating one on first sign-in.

    Returns ``(user_record, is_new)``. An existing email/password account is
    linked to the Google identity rather than duplicated.
    """
    subject = str(userinfo.get("sub") or "").strip()
    email = (userinfo.get("email") or "").strip().lower()
    if not subject or not email:
        raise AuthProviderError(
            "Google did not return the information needed to sign you in.",
            detail="userinfo missing sub/email",
        )

    existing = await database.async_get_user_by_provider("google", subject)
    if existing:
        updated = await database.async_update_user_login(
            existing["user_id"],
            full_name=userinfo.get("name") or existing.get("full_name") or "",
            picture_url=userinfo.get("picture") or existing.get("picture_url") or "",
        )
        return updated or existing, False

    by_email = await database.async_get_user_by_email(email)
    if by_email:
        # Link the Google identity onto the pre-existing local account.
        await database.async_link_user_provider(by_email["user_id"], "google", subject)
        updated = await database.async_update_user_login(
            by_email["user_id"],
            full_name=userinfo.get("name") or by_email.get("full_name") or "",
            picture_url=userinfo.get("picture") or by_email.get("picture_url") or "",
        )
        return updated or by_email, False

    created = await database.async_create_user(
        user_id=new_user_id(),
        email=email,
        full_name=userinfo.get("name") or "",
        picture_url=userinfo.get("picture") or "",
        provider="google",
        provider_subject=subject,
    )
    return created, True


__all__ = [
    "async_hash_password",
    "async_verify_password",
    "create_session_for_user",
    "csrf_cookie_settings",
    "generate_csrf_token",
    "generate_session_token",
    "hash_password",
    "hash_session_token",
    "needs_rehash",
    "new_user_id",
    "password_hasher",
    "resolve_session",
    "revoke_session",
    "session_cookie_settings",
    "upsert_google_user",
    "validate_password_strength",
    "verify_password",
]
