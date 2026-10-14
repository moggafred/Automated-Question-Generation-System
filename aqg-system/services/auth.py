"""Authentication primitives for the AQG platform.

This module owns three concerns and nothing else:

* **Password credentials** -- hashing and verification built on the standard
  library's ``hashlib.scrypt`` (memory-hard, no native build step). Hashes are
  self-describing so the work factor can be raised later without a migration.
* **Opaque server-side sessions** -- random bearer tokens are handed to the
  browser, while only their SHA-256 digest ever touches the database. A stolen
  database therefore cannot be replayed against the running service.
* **Google OAuth 2.0 (Authorization Code + PKCE)** -- implemented directly over
  ``httpx`` against Google's discovery document. The ID token is never parsed
  locally; the profile is read from the userinfo endpoint over TLS, which keeps
  the flow free of JWT/signature-verification dependencies.

Nothing here fabricates identity: every session traces back to a stored user row
and every Google sign-in to a verified provider response.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from config.settings import settings
from errors import AuthConfigError, AuthProviderError, ValidationError
from services import database

logger = logging.getLogger("aqg.auth")

# --- Password hashing ------------------------------------------------------
# scrypt parameters: N=2**14, r=8, p=1 targets ~16MB of memory per hash, which
# is comfortably interactive while making offline cracking expensive.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64
_SCRYPT_SALT_BYTES = 16

# --- Google OAuth ----------------------------------------------------------
#: Cached Google discovery endpoints (authorization, token, userinfo).
_cached_endpoints: dict[str, str] = {}


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
    """Derives a self-describing scrypt hash for storage."""
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string.")

    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            salt.hex(),
            derived.hex(),
        )
    )


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    """Constant-time verification of a password against a stored scrypt hash."""
    if not password or not stored_hash:
        return False

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


def oauth_state_expiry_iso() -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=max(60, settings.OAUTH_STATE_TTL_SECONDS))
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


# --- Google OAuth 2.0 / OIDC ----------------------------------------------
_PKCE_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    """Returns a ``(code_verifier, code_challenge)`` pair using the S256 method."""
    verifier = "".join(secrets.choice(_PKCE_CHARSET) for _ in range(64))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def enumerate_google_endpoints(doc: dict[str, Any]) -> dict[str, str]:
    """Extracts the three endpoints the flow needs from a discovery document."""
    required = ("authorization_endpoint", "token_endpoint", "userinfo_endpoint")
    missing = [key for key in required if not doc.get(key)]
    if missing:
        raise AuthProviderError(
            "Google sign-in is temporarily unavailable.",
            detail=f"discovery document missing: {', '.join(missing)}",
        )
    return {key: str(doc[key]) for key in required}


async def fetch_google_endpoints(force: bool = False) -> dict[str, str]:
    """Fetches and caches Google's OpenID Connect discovery document."""
    global _cached_endpoints
    if not settings.google_oauth_enabled:
        raise AuthConfigError("Google sign-in is not configured on this deployment.")

    if not force and _cached_endpoints:
        return _cached_endpoints

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(settings.GOOGLE_DISCOVERY_URL)
            response.raise_for_status()
            doc = response.json()
    except httpx.HTTPError as exc:  # pragma: no cover - network dependent
        raise AuthProviderError(
            "We could not reach Google sign-in.",
            detail=f"discovery request failed: {exc}",
        ) from exc

    _cached_endpoints = enumerate_google_endpoints(doc)
    return _cached_endpoints


def build_authorization_url(
    authorization_endpoint: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    """Builds the Google consent-screen URL for the authorization-code flow."""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "include_granted_scopes": "true",
        "prompt": "select_account",
    }
    separator = "&" if "?" in authorization_endpoint else "?"
    return f"{authorization_endpoint}{separator}{urlencode(params)}"


async def exchange_code_for_tokens(
    token_endpoint: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchanges an authorization code for tokens at Google's token endpoint."""
    payload = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                token_endpoint,
                data=payload,
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:  # pragma: no cover - network dependent
        raise AuthProviderError(
            "We could not complete sign-in with Google.",
            detail=f"token exchange failed: {exc}",
        ) from exc

    if response.status_code >= 400:
        raise AuthProviderError(
            "Google rejected the sign-in attempt. Please try again.",
            detail=f"token endpoint returned {response.status_code}",
        )

    data = response.json()
    if not data.get("access_token"):
        raise AuthProviderError(
            "Google did not return an access token.",
            detail="token response missing access_token",
        )
    return data


async def fetch_userinfo(userinfo_endpoint: str, access_token: str) -> dict[str, Any]:
    """Reads the verified profile from Google's userinfo endpoint.

    Using userinfo (rather than decoding the ID token locally) means the profile
    is delivered by Google over TLS and needs no local signature verification.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
    except httpx.HTTPError as exc:  # pragma: no cover - network dependent
        raise AuthProviderError(
            "We could not read your Google profile.",
            detail=f"userinfo request failed: {exc}",
        ) from exc

    if response.status_code >= 400:
        raise AuthProviderError(
            "We could not read your Google profile. Please try again.",
            detail=f"userinfo endpoint returned {response.status_code}",
        )

    data = response.json()
    if not data.get("sub"):
        raise AuthProviderError(
            "Google did not return an account identifier.",
            detail="userinfo response missing sub",
        )
    return data


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
    "build_authorization_url",
    "create_session_for_user",
    "csrf_cookie_settings",
    "exchange_code_for_tokens",
    "fetch_google_endpoints",
    "fetch_userinfo",
    "generate_csrf_token",
    "generate_pkce_pair",
    "generate_session_token",
    "hash_session_token",
    "hash_password",
    "new_user_id",
    "oauth_state_expiry_iso",
    "resolve_session",
    "revoke_session",
    "session_cookie_settings",
    "upsert_google_user",
    "validate_password_strength",
    "verify_password",
]
