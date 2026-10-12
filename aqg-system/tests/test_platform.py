"""Coverage for the platform surface added on top of the original quiz API.

Grounded in the real HTTP layer so the answer-key guarantee, the analytics
endpoints and the study-material lifecycle are all exercised end to end.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from models.quiz import Assessment
from services.database import save_quiz

client = TestClient(app)

SOURCE_TEXT = (
    "Photosynthesis converts sunlight into chemical energy inside chloroplasts. "
    "The light-dependent reactions produce ATP and NADPH which fuel the Calvin cycle. "
    "Chloroplasts absorb green wavelengths while reflecting red and blue light."
)


def _store_quiz(
    topic: str = "Biology",
    quiz_type: str = "multiple-choice",
    filename: str = "photosynthesis.txt",
) -> str:
    """Writes an assessment straight into the database so no LLM call is needed."""
    quiz_id = str(uuid.uuid4())
    save_quiz(
        quiz_id=quiz_id,
        topic=topic,
        quiz_type=quiz_type,
        num_questions=1,
        quiz_data={
            "quiz_title": f"{topic} assessment",
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
        source_filename=filename,
    )
    return quiz_id


# -- Answer key secrecy ----------------------------------------------------


def test_quiz_payload_never_contains_the_answer_key(temp_database):
    """The learner-facing assessment must carry questions only."""
    from services.evaluator import QuizEvaluationAgent

    quiz_id = _store_quiz()

    # Audit the payload exactly as generation would, so the correct option is
    # flagged in storage before it is read back over HTTP.
    audited = QuizEvaluationAgent.audit_assessment(
        {
            "quiz_title": "Biology assessment",
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
        }
    )
    assert any(option["is_correct"] for option in audited["questions"][0]["options"])
    assert audited["questions"][0]["correct_option_id"] == "A"

    response = client.get(f"/api/quiz/{quiz_id}")

    assert response.status_code == 200
    body = response.text
    assert "correct_answer" not in body
    assert "correct_option_id" not in body
    # The evaluator flags the right option in storage; that flag must not ship.
    assert "is_correct" not in body
    assert "Photosynthesis consumes CO2." not in body


def test_answer_key_requires_a_submitted_attempt(temp_database):
    """Without a matching attempt the key stays locked."""
    quiz_id = _store_quiz()

    missing = client.get(f"/api/quiz/{quiz_id}/answer-key")
    assert missing.status_code == 422

    invented = client.get(
        f"/api/quiz/{quiz_id}/answer-key", params={"attempt_id": str(uuid.uuid4())}
    )
    assert invented.status_code == 403
    assert invented.json()["error"] == "answer_key_locked"


def test_answer_key_unlocks_after_submission(temp_database):
    """Submitting first unlocks the key for that specific attempt."""
    quiz_id = _store_quiz()

    submitted = client.post(
        f"/api/assessment/{quiz_id}/submit",
        json={"answers": [{"question_id": 1, "answer": "Carbon dioxide"}]},
    )
    assert submitted.status_code == 200

    result = submitted.json()["result"]
    assert result["percentage"] == 100.0
    assert result["performance_band"] == "excellent"

    unlocked = client.get(
        f"/api/quiz/{quiz_id}/answer-key", params={"attempt_id": result["attempt_id"]}
    )
    assert unlocked.status_code == 200
    assert unlocked.json()["answers"][0]["correct_answer"] == "Carbon dioxide"


def test_answer_key_from_a_different_quiz_is_refused(temp_database):
    """An attempt ID only unlocks the assessment it was recorded against."""
    first = _store_quiz(topic="Biology")
    second = _store_quiz(topic="Chemistry")

    submitted = client.post(
        f"/api/assessment/{first}/submit",
        json={"answers": [{"question_id": 1, "answer": "Carbon dioxide"}]},
    )
    attempt_id = submitted.json()["result"]["attempt_id"]

    crossed = client.get(
        f"/api/quiz/{second}/answer-key", params={"attempt_id": attempt_id}
    )
    assert crossed.status_code == 403


def test_submission_rejects_answers_from_another_assessment(temp_database):
    """Answers must belong to the assessment being graded."""
    first = _store_quiz(topic="Biology")
    second = _store_quiz(topic="Chemistry")

    response = client.post(
        f"/api/assessment/{first}/submit",
        json={"answers": [{"question_id": 1, "answer": "Carbon dioxide"}]},
    )
    attempt_id = response.json()["result"]["attempt_id"]
    assert attempt_id

    mismatched = client.post(
        f"/api/assessment/{second}/submit",
        json={"answers": [{"question_id": 99, "answer": "Oxygen"}]},
    )
    assert mismatched.status_code == 400


def test_empty_submission_is_rejected(temp_database):
    """An assessment with no answers must not be graded or stored."""
    quiz_id = _store_quiz()
    response = client.post(f"/api/assessment/{quiz_id}/submit", json={"answers": []})
    assert response.status_code in (400, 422)


# -- Analytics honesty -----------------------------------------------------


def test_performance_reports_zero_when_nothing_was_attempted(temp_database):
    """No attempt history must render as an explicit empty state, never as fake numbers."""
    response = client.get("/api/performance")

    assert response.status_code == 200
    body = response.json()
    assert body["has_data"] is False
    assert body["total_assessments"] == 0
    assert body["average_score"] == 0.0
    assert body["topic_performance"] == []
    assert body["recent_attempts"] == []


def test_performance_aggregates_a_real_attempt(temp_database):
    """Aggregates must come from stored attempts."""
    quiz_id = _store_quiz(topic="Biology")
    client.post(
        f"/api/assessment/{quiz_id}/submit",
        json={"answers": [{"question_id": 1, "answer": "Oxygen"}]},
    )

    body = client.get("/api/performance").json()
    assert body["has_data"] is True
    assert body["total_assessments"] == 1
    assert body["highest_score"] == 0.0
    assert [entry["topic"] for entry in body["topic_performance"]] == ["Biology"]
    assert body["topic_performance"][0]["average_percentage"] == 0.0


def test_dashboard_counts_reflect_stored_records(temp_database):
    """Dashboard statistics must be derived, not hardcoded."""
    quiz_id = _store_quiz(topic="Biology")

    body = client.get("/api/dashboard").json()
    assert body["statistics"]["quizzes_generated"] >= 1
    assert body["statistics"]["assessments_completed"] == 0
    assert any(action["href"] == "#/generate" for action in body["quick_actions"])

    client.post(
        f"/api/assessment/{quiz_id}/submit",
        json={"answers": [{"question_id": 1, "answer": "Carbon dioxide"}]},
    )

    updated = client.get("/api/dashboard").json()
    assert updated["statistics"]["assessments_completed"] >= 1
    assert updated["recent_attempts"]
    assert updated["recent_activity"]


# -- History and search ----------------------------------------------------


def test_history_search_matches_topic_and_filename(temp_database):
    """Free-text search spans topic, title and filename."""
    _store_quiz(topic="Photosynthesis", filename="light-reactions.txt")
    _store_quiz(topic="Geology", filename="rocks.txt")

    by_topic = client.get("/api/quizzes", params={"search": "photo"})
    assert by_topic.status_code == 200
    assert by_topic.json()["filtered"] == 1

    by_filename = client.get("/api/quizzes", params={"search": "rocks"})
    assert by_filename.json()["filtered"] == 1

    missed = client.get("/api/quizzes", params={"search": "nothing-matches-this"})
    assert missed.status_code == 200
    assert missed.json()["quizzes"] == []


def test_history_reports_available_topics(temp_database):
    """The history filter is populated from stored data."""
    _store_quiz(topic="Astronomy")
    body = client.get("/api/quizzes").json()
    assert "Astronomy" in body["topics"]


def test_history_row_is_enriched_with_attempt_counts(temp_database):
    """Each row carries attempt count and best score for the history page."""
    quiz_id = _store_quiz(topic="Physics")
    client.post(
        f"/api/assessment/{quiz_id}/submit",
        json={"answers": [{"question_id": 1, "answer": "Carbon dioxide"}]},
    )

    row = next(
        item
        for item in client.get("/api/quizzes").json()["quizzes"]
        if item["quiz_id"] == quiz_id
    )
    assert row["attempt_count"] == 1
    assert row["best_percentage"] == 100.0
    assert row["quiz_type_label"] == "Multiple Choice"


# -- Study materials -------------------------------------------------------


def test_study_material_lifecycle(temp_database):
    """Generated resources are stored, listed, readable and deletable."""
    payload = {
        "summary": {
            "title": "Photosynthesis",
            "overview": "How plants convert light into chemical energy.",
            "points": ["Light-dependent reactions", "Calvin cycle"],
            "learning_outcomes": ["Describe the two stages"],
        },
        "key_concepts": [{"term": "Chloroplast", "definition": "Organelle hosting the reactions."}],
        "definitions": [{"term": "ATP", "definition": "Adenosine triphosphate."}],
        "flashcards": [{"front": "What is ATP?", "back": "Adenosine triphosphate."}],
        "revision_notes": [{"heading": "Remember", "body": "Light in, sugar out."}],
    }

    with patch(
        "services.generator.QuestionGeneratorService.generate_study_material",
        return_value=payload,
    ):
        created = client.post(
            "/api/generate-study-material",
            data={"type": "all", "topic": "Photosynthesis"},
            files={"file": ("photosynthesis.txt", SOURCE_TEXT.encode("utf-8"), "text/plain")},
        )

    assert created.status_code == 200
    body = created.json()
    material_id = body["material"]["id"]
    assert material_id
    assert body["document"]["filename"] == "photosynthesis.txt"
    assert body["material"]["summary"]["points"]
    assert body["material"]["flashcards"][0]["front"] == "What is ATP?"
    assert body["label"]

    listing = client.get("/api/study-materials").json()
    assert listing["total"] >= 1
    assert any(item["material_id"] == material_id for item in listing["materials"])

    fetched = client.get(f"/api/study-materials/{material_id}")
    assert fetched.status_code == 200
    stored = fetched.json()["material"]
    assert stored["material_id"] == material_id
    assert stored["summary"]["overview"]
    assert stored["definitions"][0]["term"] == "ATP"
    assert fetched.json()["label"]

    removed = client.delete(f"/api/study-materials/{material_id}")
    assert removed.status_code == 200
    assert client.get(f"/api/study-materials/{material_id}").status_code == 404


def test_unknown_study_material_returns_404(temp_database):
    """A missing resource must be a clean 404."""
    response = client.get(f"/api/study-materials/{uuid.uuid4()}")
    assert response.status_code == 404


def test_unsupported_study_material_type_is_rejected(temp_database):
    """An unknown study material type must fail before any generation happens."""
    response = client.post(
        "/api/generate-study-material",
        data={"type": "not-a-real-type"},
        files={"file": ("photosynthesis.txt", SOURCE_TEXT.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"


def test_empty_document_is_rejected(temp_database):
    """A file with no readable text must fail clearly."""
    response = client.post(
        "/api/generate-study-material",
        data={"type": "summary"},
        files={"file": ("blank.txt", b"   \n  ", "text/plain")},
    )
    assert response.status_code == 400


def test_documents_are_listed_after_upload(temp_database):
    """Processed uploads appear in the document browser."""
    with patch(
        "services.generator.QuestionGeneratorService.generate_study_material",
        return_value={"summary": {"overview": "Overview text for the document."}},
    ):
        client.post(
            "/api/generate-study-material",
            data={"type": "summary"},
            files={"file": ("photosynthesis.txt", SOURCE_TEXT.encode("utf-8"), "text/plain")},
        )

    documents = client.get("/api/documents").json()
    assert documents["total"] >= 1
    assert any(item["filename"] == "photosynthesis.txt" for item in documents["documents"])


# -- Client contracts ------------------------------------------------------


def test_limits_endpoint_exposes_configured_bounds():
    """The UI must never hardcode limits."""
    body = client.get("/api/limits").json()
    assert body["min_questions"] >= 1
    assert body["max_questions"] >= body["min_questions"]
    assert body["max_upload_bytes"] > 0
    assert ".pdf" in body["allowed_extensions"]


def test_status_reports_services_for_the_sidebar():
    """The sidebar status indicator reads these fields."""
    body = client.get("/api/status").json()
    assert body["app_name"]
    assert body["version"]
    assert "database" in body["services"]
    assert "llm" in body["services"]


def test_validation_errors_use_the_platform_envelope():
    """Request validation must not leak FastAPI's raw payload shape."""
    response = client.get("/api/quizzes", params={"limit": 0})

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert "limit" in body["detail"]
    assert body["fields"][0]["field"] == "query.limit"
    assert body["fields"][0]["message"] == "This value is below the minimum allowed."


def test_unknown_api_path_returns_a_clean_404():
    """An unrouted API path must not fall through to the static mount."""
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/css/tokens.css",
        "/css/app.css",
        "/js/app.js",
        "/js/router.js",
        "/js/api.js",
        "/js/icons.js",
        "/js/pages/dashboard.js",
        "/js/pages/generate.js",
        "/js/pages/quiz.js",
        "/js/pages/result.js",
        "/js/pages/study.js",
        "/js/pages/history.js",
        "/js/pages/assessments.js",
        "/js/pages/performance.js",
        "/js/pages/documents.js",
        "/js/pages/settings.js",
        "/js/pages/help.js",
        "/assets/logo.svg",
        "/assets/favicon.svg",
    ],
)
def test_every_spa_asset_is_served(path):
    """The static mount must serve the whole shell without a build step."""
    assert client.get(path).status_code == 200


# -- Legacy payload repair -------------------------------------------------


def test_legacy_question_shapes_are_repaired_on_read(temp_database):
    """Rows written by earlier releases must still load instead of 500."""
    legacy = Assessment.from_payload(
        {
            "quiz_title": "Legacy",
            "questions": [
                {"id": "q1", "type": "mcq", "q": "Define an array", "options": ["A list", "A loop"], "ans": "A list"},
                {"id": 2, "correct_answer": "Igneous"},
                {"id": 3},
            ],
        }
    )

    assert legacy.question_count == 2
    first = legacy.questions[0]
    assert first.id == 1
    assert first.type == "multiple-choice"
    assert first.question == "Define an array"
    assert first.correct_answer == "A list"

    # Missing wording is filled in so numbering and past attempts stay aligned.
    assert legacy.questions[1].question == "Question 2"

    # An item with neither wording nor an answer is dropped, not served broken.
    assert all(question.question for question in legacy.questions)