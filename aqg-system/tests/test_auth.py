"""End-to-end authentication coverage.

These tests opt out of the shared auth override (``real_auth``) so they exercise
the genuine cookie, session, CSRF and per-user ownership paths through the HTTP
layer. Argon2 hashing is intentionally slow, so the suite keeps the number of
registrations modest.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from main import app
from services.database import save_quiz

pytestmark = pytest.mark.real_auth

PASSWORD = "Sup3rSecret!"


def _client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient, *, email: str | None = None, password: str = PASSWORD):
    email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/auth/signup",
        json={"email": email, "password": password, "name": "Ada Lovelace"},
    )
    return response, email


def _client_with_cookies(**cookies) -> TestClient:
    client = TestClient(app)
    for key, value in cookies.items():
        client.cookies.set(key, value)
    return client


# -- Public surface ------------------------------------------------------


def test_providers_endpoint_is_public():
    response = _client().get("/auth/providers")
    assert response.status_code == 200
    body = response.json()
    assert body["email_password_enabled"] is True
    assert "google_enabled" in body
    assert "auth_configured" in body


def test_me_requires_a_session():
    assert _client().get("/auth/me").status_code == 401


def test_google_redirect_reports_not_configured():
    # No Google credentials are set in the test environment.
    response = _client().get("/auth/google", follow_redirects=False)
    assert response.status_code == 503
    assert response.json()["detail"] == "Google Sign-In is not configured"


# -- Sign-up and sign-in -----------------------------------------------


def test_signup_signs_in_and_sets_cookies(temp_database):
    client = _client()
    response, email = _register(client)

    assert response.status_code == 201
    assert response.json()["message"] == "Account created"
    assert response.json()["user"]["email"] == email
    assert response.json()["user"]["name"] == "Ada Lovelace"
    assert client.cookies.get("aqg_session")
    assert client.cookies.get("aqg_csrf")

    me = client.get("/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == email
    assert body["name"] == "Ada Lovelace"
    assert body["id"]
    assert "password_hash" not in body


def test_signup_rejects_duplicate_email(temp_database):
    client = _client()
    _, email = _register(client)

    again = _client().post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "Ada"},
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "An account already exists for this email"


def test_signup_rejects_short_password(temp_database):
    response = _client().post(
        "/auth/signup",
        json={"email": f"short-{uuid.uuid4().hex[:8]}@example.com", "password": "abc123"},
    )
    assert response.status_code == 422


def test_login_rejects_wrong_password(temp_database):
    client = _client()
    _, email = _register(client)

    bad = _client().post("/auth/login", json={"email": email, "password": "not-the-password"})
    assert bad.status_code == 401
    assert bad.json()["detail"] == "Invalid email or password"


def test_login_succeeds_with_correct_password(temp_database):
    client = _client()
    _, email = _register(client)

    login = _client()
    good = login.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert good.status_code == 200
    assert good.json()["message"] == "Login successful"
    assert login.get("/auth/me").status_code == 200


def test_logout_revokes_the_session(temp_database):
    client = _client()
    _register(client)
    token = client.cookies.get("aqg_session")
    assert token

    client.post("/auth/logout")

    # Replaying the old cookie must fail: the server-side session is gone.
    replay = _client_with_cookies(aqg_session=token)
    assert replay.get("/auth/me").status_code == 401


# -- CSRF double-submit --------------------------------------------------


def test_mutating_request_requires_csrf_token(temp_database):
    client = _client()
    _register(client)
    token = client.cookies.get("aqg_session")
    csrf = client.cookies.get("aqg_csrf")
    assert token and csrf

    without = _client_with_cookies(aqg_session=token)
    blocked = without.patch("/auth/profile", json={"full_name": "No CSRF"})
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "csrf_failed"

    with_token = _client_with_cookies(aqg_session=token, aqg_csrf=csrf)
    allowed = with_token.patch(
        "/auth/profile",
        json={"full_name": "Ada Byron"},
        headers={"X-CSRF-Token": csrf},
    )
    assert allowed.status_code == 200
    assert allowed.json()["user"]["name"] == "Ada Byron"


# -- Protected routers ---------------------------------------------------


def test_protected_route_blocks_anonymous_callers(temp_database):
    assert _client().get("/api/dashboard").status_code == 401


def test_protected_route_allows_signed_in_users(temp_database):
    client = _client()
    _register(client)
    assert client.get("/api/dashboard").status_code == 200


# -- Per-user ownership --------------------------------------------------


def test_history_is_scoped_to_the_owner(temp_database):
    owner = _client()
    owner_response, _ = _register(owner)
    owner_id = owner_response.json()["user"]["id"]

    quiz_id = str(uuid.uuid4())
    save_quiz(
        quiz_id=quiz_id,
        topic="Biology",
        quiz_type="multiple-choice",
        num_questions=1,
        quiz_data={
            "quiz_title": "Owned assessment",
            "questions": [
                {
                    "id": 1,
                    "type": "multiple-choice",
                    "question": "What gas do plants absorb?",
                    "options": ["Carbon dioxide", "Oxygen", "Nitrogen", "Hydrogen"],
                    "correct_answer": "Carbon dioxide",
                    "explanation": "Photosynthesis consumes CO2.",
                }
            ],
        },
        user_id=owner_id,
    )

    owner_list = owner.get("/api/v1/quizzes").json()
    assert quiz_id in {item["quiz_id"] for item in owner_list["quizzes"]}

    stranger = _client()
    _register(stranger)
    stranger_list = stranger.get("/api/v1/quizzes").json()
    assert quiz_id not in {item["quiz_id"] for item in stranger_list["quizzes"]}
