import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import main as main_module
from main import app
from config.settings import settings
from services.retriever import RetrievedChunk

client = TestClient(app)


def test_health_endpoint_reports_ok():
    """Load balancers and orchestrators must be able to probe service liveness."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generate_quiz_rejects_oversized_upload():
    """Uploads larger than MAX_UPLOAD_SIZE must be rejected with a 413 payload."""
    oversized_content = b"x" * 300

    with patch.object(main_module.settings, "MAX_UPLOAD_SIZE", 10):
        payload = {"type": "multiple-choice", "count": "1"}
        files = {"file": ("big.txt", oversized_content, "text/plain")}

        response = client.post("/api/v1/generate", data=payload, files=files)

        assert response.status_code == 413
        assert "larger than" in response.json()["detail"]


def test_file_upload_oversize_limit_returns_413():
    """An upload over the real 10MB default limit must be rejected with a 413 payload."""
    huge_mock_data = b"0" * (11 * 1024 * 1024)

    payload = {"type": "multiple-choice", "count": "5", "topic": ""}
    files = {"file": ("huge_document.txt", huge_mock_data, "text/plain")}

    response = client.post("/api/v1/generate", data=payload, files=files)

    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


def test_generate_quiz_success_with_retrieval_and_topic():
    """Retrieval must run with the user-supplied topic as the query and generation must succeed end-to-end."""
    mock_source_text = (
        "Photosynthesis converts sunlight into chemical energy. "
        "Chloroplasts absorb green wavelengths while reflecting red and blue light. "
        "The light-dependent reactions produce ATP and NADPH which fuel the Calvin cycle."
    )

    with patch("services.retriever.DocumentRetriever.build_context") as mock_build_context, \
         patch("services.generator.QuestionGeneratorService.generate_quiz") as mock_generate:

        mock_build_context.return_value = (
            "Photosynthesis converts sunlight into chemical energy inside chloroplasts.",
            [RetrievedChunk(text="Photosynthesis converts sunlight into chemical energy inside chloroplasts.", score=0.9, index=0)],
        )
        mock_generate.return_value = {
            "quiz_title": "Photosynthesis Assessment",
            "questions": [
                {
                    "id": 1,
                    "type": "multiple-choice",
                    "question": "What gas do plants absorb during photosynthesis?",
                    "options": ["Carbon dioxide", "Oxygen", "Nitrogen", "Hydrogen"],
                    "correct_answer": "Carbon dioxide",
                    "explanation": "Photosynthesis consumes CO2 to synthesize carbohydrates."
                },
                {
                    "id": 2,
                    "type": "multiple-choice",
                    "question": "Where does photosynthesis occur?",
                    "options": ["Chloroplast", "Nucleus", "Ribosome", "Cell membrane"],
                    "correct_answer": "Chloroplast",
                    "explanation": "Chloroplasts host the light-dependent reaction machinery."
                }
            ]
        }

        payload = {"type": "multiple-choice", "count": "2", "topic": "Photosynthesis"}
        files = {"file": ("photosynthesis.txt", mock_source_text.encode("utf-8"), "text/plain")}

        response = client.post("/api/v1/generate", data=payload, files=files)

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["quiz_title"] == "Photosynthesis Assessment"
        assert len(json_data["questions"]) == 2

        # The retriever must be queried with the topic supplied by the learner.
        from services.generation import default_retrieval_query

        assert mock_build_context.call_count == 1
        assert mock_build_context.call_args.args[0] == default_retrieval_query("Photosynthesis")


def test_generate_quiz_without_topic_uses_default_query():
    """An empty topic must fall back to the default semantic query instead of failing."""
    mock_source_text = (
        "Thermodynamics describes heat flow, entropy and the second law of energy. "
        "Energy transfers always increase total system entropy over time."
    )

    with patch("services.retriever.DocumentRetriever.build_context") as mock_build_context, \
         patch("services.generator.QuestionGeneratorService.generate_quiz") as mock_generate:

        mock_build_context.return_value = (
            "Thermodynamics describes heat flow and the second law of energy.",
            [RetrievedChunk(text="Thermodynamics describes heat flow and the second law of energy.", score=0.9, index=0)],
        )
        mock_generate.return_value = {
            "quiz_title": "Thermodynamics Quiz",
            "questions": [
                {
                    "id": 1,
                    "type": "short-answer",
                    "question": "State the second law of thermodynamics.",
                    "options": [],
                    "correct_answer": "Entropy of an isolated system never decreases.",
                    "explanation": "Directly derived from the retrieved thermodynamics context."
                }
            ]
        }

        payload = {"type": "short-answer", "count": "1", "topic": ""}
        files = {"file": ("thermo.txt", mock_source_text.encode("utf-8"), "text/plain")}

        response = client.post("/api/v1/generate", data=payload, files=files)

        assert response.status_code == 200

        from services.generation import default_retrieval_query

        assert mock_build_context.call_count == 1
        assert mock_build_context.call_args.args[0] == default_retrieval_query("")


def test_generate_quiz_fails_loudly_on_llm_error():
    """An upstream generation failure must surface a 502 without leaking internals."""
    mock_source_text = (
        "Biology is the study of living organisms, their structure, function and evolution."
    )

    with patch("services.generator.QuestionGeneratorService.generate_quiz") as mock_generate:
        mock_generate.side_effect = Exception("API connection timed out or quota exceeded.")

        payload = {"type": "multiple-choice", "count": "2", "topic": "Biology"}
        files = {"file": ("biology.txt", mock_source_text.encode("utf-8"), "text/plain")}

        response = client.post("/api/v1/generate", data=payload, files=files)

        # Fail loudly, but never echo the upstream error back to the caller.
        assert response.status_code == 502
        assert response.json()["error"] == "generation_failed"
        assert "timed out" not in response.text
        assert "quota" not in response.text