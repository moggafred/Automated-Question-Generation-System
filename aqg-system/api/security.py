"""Authentication dependencies and cookie helpers for the API layer.

The public surface is intentionally tiny:

* :func:`get_current_user` -- a FastAPI dependency that resolves the caller from
  the session cookie, enforces the double-submit CSRF token on state-changing
  requests and raises :class:`~errors.AuthenticationError` when there is no live
  session. Every protected router depends on it.
* :func:`set_auth_cookies` / :func:`clear_auth_cookies` -- the single place that
  knows how the session token and CSRF token are written to the browser.
"""

from __future__ import annotations

import hmac
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import Response

from config.settings import settings
from errors import AuthenticationError, CSRFError
from models.user import AuthenticatedUser
from services import auth

#: HTTP methods that never mutate state and therefore skip CSRF validation.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _extract_user(session: dict[str, Any]) -> AuthenticatedUser:
    user = session.get("user") or {}
    return AuthenticatedUser(
        id=user.get("id") or session.get("user_id") or "",
        email=user.get("email") or "",
        full_name=user.get("full_name") or "",
        picture_url=user.get("picture_url") or "",
        provider=user.get("provider") or "password",
        created_at=user.get("created_at") or "",
        last_login_at=user.get("last_login_at") or "",
        session_id=session.get("session_id") or "",
        csrf_token=session.get("csrf_token") or "",
    )


async def get_optional_user(request: Request) -> Optional[AuthenticatedUser]:
    """Resolves the caller when a session exists, otherwise returns ``None``."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None

    session = await auth.resolve_session(token)
    if not session:
        return None

    if request.method not in _SAFE_METHODS:
        supplied = request.headers.get("x-csrf-token", "")
        expected = session.get("csrf_token") or ""
        if not supplied or not expected or not hmac.compare_digest(supplied, expected):
            raise CSRFError()
    return _extract_user(session)


async def get_current_user(request: Request) -> AuthenticatedUser:
    """FastAPI dependency that requires an authenticated, CSRF-valid caller."""
    user = await get_optional_user(request)
    if user is None:
        raise AuthenticationError()
    return user


#: Alias with a name that reads well in router signatures.
require_user = get_current_user


def set_auth_cookies(response: Response, token: str, csrf_token: str) -> None:
    """Writes the HttpOnly session cookie and the readable CSRF cookie."""
    session_cookie = auth.session_cookie_settings()
    csrf_cookie = auth.csrf_cookie_settings()
    response.set_cookie(
        key=session_cookie["key"],
        value=token,
        httponly=session_cookie["httponly"],
        secure=session_cookie["secure"],
        samesite=session_cookie["samesite"],
        max_age=session_cookie["max_age"],
        path=session_cookie["path"],
    )
    response.set_cookie(
        key=csrf_cookie["key"],
        value=csrf_token,
        httponly=csrf_cookie["httponly"],
        secure=csrf_cookie["secure"],
        samesite=csrf_cookie["samesite"],
        max_age=csrf_cookie["max_age"],
        path=csrf_cookie["path"],
    )


def clear_auth_cookies(response: Response) -> None:
    """Expires both cookies in the browser."""
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path="/")


__all__ = [
    "clear_auth_cookies",
    "get_current_user",
    "get_optional_user",
    "require_user",
    "set_auth_cookies",
]
