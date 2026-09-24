import pytest
from fastapi.testclient import TestClient
from main import app
from unittest.mock import patch
from services.retriever import DocumentRetriever

client = TestClient(app)

def test_static_index_resolution():
    """Verify static hosting binds match expected asset paths index configurations properly."""
    response = client.get("/")
    assert response.status_code == 200
    assert "AQG Engine" in response.text

@patch("services.generator.QuestionGeneratorService.generate_quiz")
def test_generation_endpoint_lifecycle(mock_generator):
    """Verifies operational validity across endpoint layer parameters pipelines."""
    mock_generator.return_value = {
        "quiz_title": "Mock Physics Assessment",
        "questions": [
            {
                "id": 1,
                "type": "multiple-choice",
                "question": "What is the speed of light?",
                "options": ["299,792 km/s", "150,000 km/s", "300,000 km/s", "343 m/s"],
                "correct_answer": "299,792 km/s",
                "explanation": "True universal cosmic structural ceiling metrics constant values boundary conditions mapping."
            }
        ]
    }
    
    # Pack parameters inside boundaries
    payload = {
        "type": "multiple-choice",
        "count": 1
    }
    file_payload = {
        "file": ("test_context.txt", b"Light travel metric velocity constants are absolute configurations fields.", "text/plain")
    }
    
    response = client.post("/api/v1/generate", data=payload, files=file_payload)
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["quiz_title"] == "Mock Physics Assessment"
    assert len(json_data["questions"]) == 1
    assert json_data["questions"][0]["correct_answer"] == "299,792 km/s"


def test_generation_count_boundary_validation():
    """Count values outside the 1-10 boundary must be rejected with 400."""
    file_payload = {
        "file": ("boundary.txt", b"Some document body text used for parsing contexts.", "text/plain")
    }
    response = client.post("/api/v1/generate", data={"type": "multiple-choice", "count": 0}, files=file_payload)
    assert response.status_code == 400

    response = client.post("/api/v1/generate", data={"type": "multiple-choice", "count": 11}, files=file_payload)
    assert response.status_code == 400


def test_generation_endpoint_topic_parameter():
    """Optional RAG topic steering must be accepted without breaking the pipeline."""
    with patch("services.generator.QuestionGeneratorService.generate_quiz") as mock_generator:
        mock_generator.return_value = {
            "quiz_title": "Themed Quiz",
            "questions": [
                {
                    "id": 1,
                    "type": "short-answer",
                    "question": "State the core principle.",
                    "options": [],
                    "correct_answer": "Conservation of energy",
                    "explanation": "Derived from the retrieved context windows."
                }
            ]
        }
        payload = {"type": "short-answer", "count": 1, "topic": "conservation"}
        file_payload = {
            "file": ("topic.txt", b"Conservation of energy governs energy transfers in closed systems.", "text/plain")
        }
        response = client.post("/api/v1/generate", data=payload, files=file_payload)
        assert response.status_code == 200
        assert response.json()["questions"][0]["correct_answer"] == "Conservation of energy"


def test_retriever_ranked_context_return():
    """RAG layer must rank and return the top-k semantically relevant chunks."""
    chunks = [
        "Gravity pulls objects toward the center of the earth with constant acceleration.",
        "Photosynthesis converts sunlight into chemical energy inside chloroplasts.",
        "Electromagnetism unifies the physics of electric fields and magnetic waves.",
        "Thermodynamics describes heat flow, entropy and the second law of energy."
    ]
    retriever = DocumentRetriever(dim=128)
    retriever.index_chunks(chunks)

    result = retriever.retrieve("heat transfer and entropy", top_k=2)
    assert len(result) == 2
    assert "Thermodynamics" in result[0]

    result_all = retriever.retrieve("physics", top_k=10)
    assert len(result_all) == 4
    assert set(result_all) == set(chunks)