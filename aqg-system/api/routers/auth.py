"""Authentication endpoints: sign-up, sign-in, sign-out and Google OAuth.

The router mirrors the platform's standalone auth design: ``/auth/signup``,
``/auth/login``, ``/auth/me``, ``/auth/logout`` and the authlib-driven Google
redirect flow. Sessions, cookies and user persistence stay on the shared
services so every other feature (quizzes, documents, study materials) keeps
resolving the same principal.
"""

from __future__ import annotations

import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from api.security import clear_auth_cookies, get_current_user, set_auth_cookies
from config.settings import settings
from models.user import (
    MAX_NAME_LENGTH,
    AuthenticatedUser,
    ProfileUpdateRequest,
    normalize_email,
)
from services import auth, database

logger = logging.getLogger("aqg.api.auth")

router = APIRouter(prefix="/auth", tags=["authentication"])

#: Upper bound for a client-supplied post-sign-in destination.
_MAX_RETURN_TO_LENGTH = 2048


# ==========================================================================
# Request schemas
# ==========================================================================
class SignupRequest(BaseModel):
    """Email + password registration payload."""

    name: str = Field(min_length=2, max_length=MAX_NAME_LENGTH)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    """Email + password sign-in payload."""

    email: EmailStr
    password: str


# ==========================================================================
# Google OAuth (authlib)
# ==========================================================================
oauth = OAuth()

if settings.google_oauth_enabled:
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url=settings.GOOGLE_DISCOVERY_URL,
        client_kwargs={"scope": "openid email profile"},
    )


def _resolve_redirect_uri(request: Request) -> str:
    """Returns the OAuth redirect URI, from settings or derived from the request."""
    configured = settings.GOOGLE_REDIRECT_URI.strip()
    if configured:
        return configured
    return str(request.url_for("google_callback"))


def _home_redirect(error: str = "") -> RedirectResponse:
    """Builds the post-OAuth landing URL on the SPA origin."""
    base = settings.FRONTEND_URL.strip().rstrip("/")
    target = f"{base}/" if base else "/"
    if error:
        target = f"{target}?auth_error={error}"
    return RedirectResponse(target)


# ==========================================================================
# Helpers
# ==========================================================================
def public_user(user: dict) -> dict:
    """Projects a user row (or principal) without any secret material."""
    return {
        "id": user.get("user_id") or user.get("id") or "",
        "name": user.get("full_name") or user.get("name") or "",
        "email": user.get("email") or "",
        "avatar_url": user.get("picture_url") or user.get("avatar_url") or "",
        "provider": user.get("provider") or "password",
        "created_at": user.get("created_at") or "",
        "last_login_at": user.get("last_login_at") or "",
    }


def _session_response(user: dict, session: dict, *, message: str, status_code: int = 200) -> JSONResponse:
    """Serialises a freshly-created session and attaches both cookies."""
    response = JSONResponse(
        {"message": message, "user_id": user["user_id"], "user": public_user(user)},
        status_code=status_code,
    )
    set_auth_cookies(response, session["token"], session["csrf_token"])
    return response


# ==========================================================================
# Public surface
# ==========================================================================
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
    return public_user(user.to_public_dict())


# ==========================================================================
# Email + password
# ==========================================================================
@router.post("/signup", status_code=201, summary="Create an email + password account")
async def signup(payload: SignupRequest) -> JSONResponse:
    if not settings.EMAIL_PASSWORD_ENABLED:
        raise HTTPException(status_code=503, detail="Email and password sign-up is disabled on this deployment.")

    email = normalize_email(payload.email)
    name = payload.name.strip()

    if await database.async_get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account already exists for this email")

    password_hash = await auth.async_hash_password(payload.password)
    user = await database.async_create_user(
        user_id=auth.new_user_id(),
        email=email,
        full_name=name,
        provider="password",
        password_hash=password_hash,
    )

    session = await auth.create_session_for_user(user["user_id"])
    logger.info("New account registered: %s", user["user_id"])
    return _session_response(user, session, message="Account created", status_code=201)


@router.post("/login", summary="Sign in with email + password")
async def login(payload: LoginRequest) -> JSONResponse:
    if not settings.EMAIL_PASSWORD_ENABLED:
        raise HTTPException(status_code=503, detail="Email and password sign-in is disabled on this deployment.")

    email = normalize_email(payload.email)
    user = await database.async_get_user_by_email(email)
    stored_hash = user.get("password_hash") if user else None

    if user and not stored_hash:
        raise HTTPException(status_code=401, detail="This account signs in with Google. Please use the Google button.")

    if not user or not await auth.async_verify_password(payload.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if auth.needs_rehash(stored_hash):
        upgraded = await auth.async_hash_password(payload.password)
        await database.async_set_user_password(user["user_id"], upgraded)

    user = await database.async_update_user_login(user["user_id"]) or user
    session = await auth.create_session_for_user(user["user_id"])
    logger.info("Password sign-in: %s", user["user_id"])
    return _session_response(user, session, message="Login successful")


@router.post("/logout", summary="End the current session")
async def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        await auth.revoke_session(token)
    response = JSONResponse({"message": "Logged out"})
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
    return {"user": public_user(principal.to_public_dict())}


# ==========================================================================
# Google OAuth redirect flow
# ==========================================================================
@router.get("/google", summary="Begin the Google sign-in redirect")
async def google_login(request: Request) -> Response:
    if not settings.google_oauth_enabled:
        raise HTTPException(status_code=503, detail="Google Sign-In is not configured")
    return await oauth.google.authorize_redirect(request, _resolve_redirect_uri(request))


@router.get("/google/callback", name="google_callback", summary="Google OAuth redirect target")
async def google_callback(request: Request) -> RedirectResponse:
    """Completes the OAuth handshake and returns the browser to the SPA."""
    error = request.query_params.get("error")
    if error:
        logger.info("Google sign-in cancelled: %s", error)
        return _home_redirect("google_cancelled")

    try:
        if not settings.google_oauth_enabled:
            raise HTTPException(status_code=503, detail="Google Sign-In is not configured")

        token = await oauth.google.authorize_access_token(request)
        info = token.get("userinfo")
        if not info:
            info = await oauth.google.parse_id_token(request, token)
    except HTTPException:
        return _home_redirect("google_failed")
    except Exception as exc:  # noqa: BLE001 - authlib raises provider-specific errors
        logger.warning("Google sign-in failed: %s", exc)
        return _home_redirect("google_failed")

    if not info or not info.get("sub") or not info.get("email_verified"):
        return _home_redirect("google_unverified")

    email = normalize_email(info["email"])
    subject = str(info["sub"]).strip()

    existing = await database.async_get_user_by_provider("google", subject)
    if not existing:
        by_email = await database.async_get_user_by_email(email)
        if by_email and by_email.get("provider") != "google":
            logger.info("Google sign-in blocked: email already registered (%s)", email)
            return _home_redirect("google_conflict")

    user, is_new = await auth.upsert_google_user(info)
    session = await auth.create_session_for_user(user["user_id"])
    logger.info("Google sign-in %s: %s", "created" if is_new else "linked", user["user_id"])

    response = _home_redirect()
    set_auth_cookies(response, session["token"], session["csrf_token"])
    return response
