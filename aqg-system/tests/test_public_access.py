"""Public-dashboard access rules.

The redesigned experience opens on a public dashboard: anonymous visitors can
read the status and provider endpoints, while every feature that creates or
reads user-owned data stays behind the session guard. These tests drive the real
authentication dependency so the boundary is exercised end to end.
"""

import pytest
from fastapi.testclient import TestClient

from main import app

pytestmark = pytest.mark.real_auth


def _client() -> TestClient:
    return TestClient(app)


# -- Reachable without signing in ----------------------------------------


def test_status_is_public_for_anonymous_visitors():
    response = _client().get("/api/status")
    assert response.status_code == 200
    body = response.json()
    # The public dashboard renders real platform facts from this payload.
    assert "services" in body
    assert body["readiness"]["status"] in {"ready", "degraded"}
    assert isinstance(body.get("question_types"), list)


def test_health_is_public():
    assert _client().get("/health").status_code == 200


def test_readiness_warns_about_serverless_sqlite(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")

    response = _client().get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["persistence"] == "ephemeral"
    assert any("not guaranteed to persist" in warning for warning in body["warnings"])


def test_index_shell_serves_the_public_dashboard():
    response = _client().get("/")
    assert response.status_code == 200
    # The shell must still expose the guarded workspace hook and the SPA entry.
    assert 'id="app-shell"' in response.text
    assert "/js/app.js" in response.text
    # The old full-screen gate must be gone: visitors land on a real page.
    assert 'id="auth-gate"' not in response.text


# -- Guarded until a session exists --------------------------------------


def test_dashboard_requires_a_session():
    assert _client().get("/api/dashboard").status_code == 401


def test_generate_quiz_requires_a_session():
    response = _client().post(
        "/api/generate-quiz",
        data={"type": "multiple-choice", "count": 3},
        files={"file": ("notes.txt", b"Photosynthesis converts light to energy.", "text/plain")},
    )
    assert response.status_code == 401


def test_generate_study_material_requires_a_session():
    response = _client().post(
        "/api/generate-study-material",
        data={"type": "summary"},
        files={"file": ("notes.txt", b"Entropy always increases in a closed system.", "text/plain")},
    )
    assert response.status_code == 401


def test_history_requires_a_session():
    assert _client().get("/api/quizzes").status_code == 401


def test_documents_require_a_session():
    assert _client().get("/api/documents").status_code == 401
