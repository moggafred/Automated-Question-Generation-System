"""Return-to-feature validation and OAuth state persistence.

Anonymous visitors who request a protected feature are remembered and resumed
after sign-in. The destination travels through the Google OAuth ``state`` row, so
its validator is a security boundary: only same-origin SPA paths may pass, or the
callback would become an open redirect.
"""

import uuid

import pytest

from api.routers.auth import _safe_return_to
from services import auth
from services import database as db

pytestmark = pytest.mark.real_auth


# -- Validator -----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "/",
        "/index.html",
        "/#/generate",
        "/#/generate?type=essay",
        "/?section=features",
        "/#/dashboard",
    ],
)
def test_safe_return_to_accepts_same_origin_spa_paths(value):
    assert _safe_return_to(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "https://evil.example/steal",
        "http://evil.example",
        "//evil.example",
        "/\\evil.example",
        "\\evil.example",
        "/../etc/passwd",
        "/other/page",
        "/#/generate\x01injected",
        "/?x=" + "a" * 2100,
    ],
)
def test_safe_return_to_rejects_unsafe_or_foreign_destinations(value):
    assert _safe_return_to(value) == ""


# -- Persistence round trip ----------------------------------------------


def test_oauth_state_round_trips_the_return_to(temp_database):
    state = uuid.uuid4().hex
    db.create_oauth_state(
        state=state,
        code_verifier="verifier-value",
        redirect_uri="http://localhost/api/auth/google/callback",
        expires_at=auth.oauth_state_expiry_iso(),
        return_to="/#/generate?type=case-study",
    )

    record = db.consume_oauth_state(state)
    assert record is not None
    assert record["return_to"] == "/#/generate?type=case-study"
    assert record["code_verifier"] == "verifier-value"

    # State is single-use: a replay must not resolve again.
    assert db.consume_oauth_state(state) is None


def test_oauth_state_defaults_to_empty_return_to(temp_database):
    state = uuid.uuid4().hex
    db.create_oauth_state(
        state=state,
        code_verifier="verifier-value",
        redirect_uri="http://localhost/api/auth/google/callback",
        expires_at=auth.oauth_state_expiry_iso(),
    )

    record = db.consume_oauth_state(state)
    assert record is not None
    assert record["return_to"] == ""
