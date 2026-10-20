"""Authentication endpoints: registration, sign-in, sign-out and Google OAuth.

The router is deliberately thin -- it validates input, drives
:mod:`services.auth`, and is the only layer that writes cookies. All session and
credential logic lives in the service so the same rules apply to every caller.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from api.security import clear_auth_cookies, get_current_user, set_auth_cookies
from config.settings import settings
from errors import AuthConfigError, AuthenticationError, AuthProviderError, ValidationError
from models.user import (
    AuthenticatedUser,
    GuestSignInRequest,
    LoginRequest,
    ProfileUpdateRequest,
    RegisterRequest,
)
from services import auth, database

logger = logging.getLogger("aqg.api.auth")

router = APIRouter(prefix="/api/auth", tags=["authentication"])

#: Upper bound for a client-supplied post-sign-in destination.
_MAX_RETURN_TO_LENGTH = 2048


def _safe_return_to(raw: str | None) -> str:
    """Validates a post-sign-in destination so it can never leave this origin.

    Only same-origin, hash-based SPA paths are accepted (for example ``/#/generate``
    or ``/``). Absolute URLs, protocol-relative URLs (``//evil.example``) and values
    carrying control characters are rejected, which closes the open-redirect hole
    while still letting the user resume the feature they were trying to open.
    """
    if not raw:
        return ""
    value = raw.strip()
    if not value or len(value) > _MAX_RETURN_TO_LENGTH:
        return ""
    if not value.startswith("/") or value[1:2] in ("/", "\\"):
        return ""
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return ""
    # The path component (before any query or fragment) must be the SPA shell.
    path = value.split("#", 1)[0].split("?", 1)[0]
    if path not in ("/", "/index.html"):
        return ""
    return value


def _resolve_redirect_uri(request: Request) -> str:
    """Returns the OAuth redirect URI, from settings or derived from the request."""
    configured = settings.GOOGLE_REDIRECT_URI.strip()
    if configured:
        return configured
    return str(request.url_for("google_callback"))


def _frontend_redirect(path: str = "/", *, error: str = "") -> str:
    """Builds an absolute URL back to the SPA (or a same-origin path).

    ``error`` is inserted as a query parameter *before* the hash fragment so the
    single-page shell can surface it while still landing on ``path``.
    """
    base = settings.FRONTEND_URL.strip().rstrip("/")
    target = path if path.startswith("/") else f"/{path}"
    if error:
        head, _, fragment = target.partition("#")
        separator = "&" if "?" in head else "?"
        target = f"{head}{separator}auth_error={error}" + (f"#{fragment}" if fragment else "")
    return f"{base}{target}" if base else target


@router.get("/providers", summary="Which sign-in methods are available")
async def providers() -> dict:
    """Public probe used by the sign-in screen to render the right controls."""
    return {
        "google_enabled": settings.google_oauth_enabled,
        "email_password_enabled": settings.EMAIL_PASSWORD_ENABLED,
        "auth_configured": settings.auth_configured,
    }


@router.get("/me", summary="Return the signed-in user")
async def me(user: AuthenticatedUser = Depends(get_current_user)) -> dict:
    return {"user": user.to_public_dict()}


@router.post("/register", summary="Create an email + password account")
async def register(payload: RegisterRequest) -> JSONResponse:
    if not settings.EMAIL_PASSWORD_ENABLED:
        raise AuthConfigError("Email and password sign-up is disabled on this deployment.")

    auth.validate_password_strength(payload.password)

    if await database.async_get_user_by_email(payload.email):
        raise ValidationError("An account with that email address already exists.")

    password_hash = await auth.async_hash_password(payload.password)
    user = await database.async_create_user(
        user_id=auth.new_user_id(),
        email=payload.email,
        full_name=payload.full_name,
        provider="password",
        password_hash=password_hash,
    )

    session = await auth.create_session_for_user(user["user_id"])
    logger.info("New account registered: %s", user["user_id"])
    return _session_response(user, session)


@router.post("/login", summary="Sign in with email + password")
async def login(payload: LoginRequest) -> JSONResponse:
    if not settings.EMAIL_PASSWORD_ENABLED:
        raise AuthConfigError("Email and password sign-in is disabled on this deployment.")

    user = await database.async_get_user_by_email(payload.email)
    stored_hash = user.get("password_hash") if user else None

    if user and not stored_hash:
        raise ValidationError("This account signs in with Google. Please use the Google button.")

    if not user or not await auth.async_verify_password(payload.password, stored_hash):
        raise AuthenticationError("Your email or password is incorrect.")

    user = await database.async_update_user_login(user["user_id"]) or user
    session = await auth.create_session_for_user(user["user_id"])
    logger.info("Password sign-in: %s", user["user_id"])
    return _session_response(user, session)


@router.post("/logout", summary="End the current session")
async def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        await auth.revoke_session(token)
    response = JSONResponse({"ok": True})
    clear_auth_cookies(response)
    return response


@router.post("/logout-all", summary="End every other session for this account")
async def logout_all(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    except_hash = auth.hash_session_token(token) if token else None
    revoked = await database.async_delete_user_sessions(user.id, except_token_hash=except_hash)
    return {"ok": True, "revoked": revoked}


@router.patch("/profile", summary="Update the signed-in user's profile")
async def update_profile(
    payload: ProfileUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict:
    updated = await database.async_update_user_profile(
        user.id,
        full_name=payload.full_name,
        picture_url=payload.picture_url,
    )
    principal = user
    if updated:
        principal = AuthenticatedUser(
            id=updated["user_id"],
            email=updated["email"],
            full_name=updated.get("full_name") or "",
            picture_url=updated.get("picture_url") or "",
            provider=updated.get("provider") or "password",
            created_at=updated.get("created_at") or "",
            last_login_at=updated.get("last_login_at") or "",
        )
    return {"user": principal.to_public_dict()}


@router.get("/google/start", summary="Begin the Google sign-in redirect")
async def google_start(
    request: Request,
    next: str = Query("", description="Validated same-origin path to resume after sign-in."),
) -> dict:
    if not settings.google_oauth_enabled:
        raise AuthConfigError("Google sign-in is not configured on this deployment.")

    endpoints = await auth.fetch_google_endpoints()
    redirect_uri = _resolve_redirect_uri(request)
    verifier, challenge = auth.generate_pkce_pair()
    state = auth.generate_csrf_token()

    await database.async_create_oauth_state(
        state=state,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
        expires_at=auth.oauth_state_expiry_iso(),
        return_to=_safe_return_to(next),
    )

    authorization_url = auth.build_authorization_url(
        endpoints["authorization_endpoint"],
        redirect_uri,
        state,
        challenge,
    )
    return {"authorization_url": authorization_url}


@router.get("/google/callback", name="google_callback", summary="Google OAuth redirect target")
async def google_callback(request: Request) -> RedirectResponse:
    """Completes the OAuth handshake and returns the browser to the SPA."""
    error = request.query_params.get("error")
    if error:
        logger.info("Google sign-in cancelled: %s", error)
        return RedirectResponse(_frontend_redirect("/", error="google_cancelled"))

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return RedirectResponse(_frontend_redirect("/", error="google_invalid"))

    try:
        if not settings.google_oauth_enabled:
            raise AuthConfigError("Google sign-in is not configured on this deployment.")

        record = await database.async_consume_oauth_state(state)
        if not record:
            raise AuthProviderError(
                "That sign-in link has expired. Please try again.",
                detail="oauth state missing or expired",
            )

        endpoints = await auth.fetch_google_endpoints()
        tokens = await auth.exchange_code_for_tokens(
            endpoints["token_endpoint"],
            code,
            record["code_verifier"],
            record.get("redirect_uri") or _resolve_redirect_uri(request),
        )
        userinfo = await auth.fetch_userinfo(endpoints["userinfo_endpoint"], tokens["access_token"])
        user, is_new = await auth.upsert_google_user(userinfo)
    except (AuthProviderError, AuthConfigError) as exc:
        logger.warning("Google sign-in failed: %s (detail=%s)", exc.message, exc.detail)
        return RedirectResponse(_frontend_redirect("/", error="google_failed"))

    session = await auth.create_session_for_user(user["user_id"])
    logger.info("Google sign-in %s: %s", "created" if is_new else "linked", user["user_id"])

    # Send the browser back to the feature the visitor was trying to reach.
    return_to = _safe_return_to(record.get("return_to"))
    response = RedirectResponse(_frontend_redirect(return_to or "/"))
    set_auth_cookies(response, session["token"], session["csrf_token"])
    return response


def _session_response(user: dict, session: dict) -> JSONResponse:
    """Serialises a freshly-created session and attaches both cookies."""
    principal = AuthenticatedUser(
        id=user["user_id"],
        email=user.get("email") or "",
        full_name=user.get("full_name") or "",
        picture_url=user.get("picture_url") or "",
        provider=user.get("provider") or "password",
        created_at=user.get("created_at") or "",
        last_login_at=user.get("last_login_at") or "",
        session_id=session.get("session_id") or "",
        csrf_token=session.get("csrf_token") or "",
    )
    response = JSONResponse({"user": principal.to_public_dict()})
    set_auth_cookies(response, session["token"], session["csrf_token"])
    return response

@router.post('/google/guest', summary='Guest sign-in with Google identity')
async def google_guest(payload: GuestSignInRequest) -> JSONResponse:
    email = (payload.email or '').strip().lower()
    full_name = (payload.full_name or '').strip()
    if not email:
        raise ValidationError('Email is required.')
    if not full_name:
        full_name = email.split('@')[0].replace('.', ' ').title()
    existing = await database.async_get_user_by_email(email)
    if existing:
        updated = await database.async_update_user_login(existing['user_id'], full_name=full_name)
        user = updated or existing
        session = await auth.create_session_for_user(user['user_id'])
        return _session_response(user, session)
    created = await database.async_create_user(
        user_id=auth.new_user_id(),
        email=email,
        full_name=full_name,
        provider='google_guest',
        provider_subject=None,
    )
    session = await auth.create_session_for_user(created['user_id'])
    return _session_response(created, session)
