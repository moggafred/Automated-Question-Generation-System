import asyncio
import json
import sqlite3
import uuid as uuid_lib

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from services import database as database_module
from services.database import (
    DB_PATH,
    count_quizzes,
    delete_quiz,
    get_db_path,
    get_quiz_by_id,
    init_db,
    list_quizzes,
    save_quiz,
)
from services.generator import AssessmentSchema
from main import app

client = TestClient(app)


def _read_raw_table(db_file):
    """Reads the physical table definition and raw JSON cells straight from the SQLite file."""
    with sqlite3.connect(db_file) as conn:
        columns = conn.execute("PRAGMA table_info(generated_quizzes)").fetchall()
        rows = conn.execute("SELECT quiz_data FROM generated_quizzes").fetchall()
    return columns, rows


def test_database_lifecycle(temp_database):
    """End-to-end insert then read-back must round-trip every stored column."""
    init_db()

    test_id = "test-uuid-12345"
    test_topic = "Data Structures"
    test_type = "multiple-choice"
    test_questions = 2
    test_data = {"questions": [{"q": "Define Array", "options": ["A", "B"], "ans": "A"}]}

    save_quiz(test_id, test_topic, test_type, test_questions, test_data)

    fetched = get_quiz_by_id(test_id)
    assert fetched is not None
    assert fetched["quiz_id"] == test_id
    assert fetched["topic"] == test_topic
    assert fetched["quiz_type"] == test_type
    assert fetched["num_questions"] == test_questions
    assert fetched["quiz_data"] == test_data

    # Verify missing records return None gracefully
    assert get_quiz_by_id("non-existent-id") is None
    assert get_quiz_by_id("") is None


def test_init_db_is_idempotent_and_creates_indexes(temp_database):
    """Repeated startup initialization must not fail and must build the history indexes."""
    init_db()
    init_db()

    db_file = get_db_path()
    table_columns, rows = _read_raw_table(db_file)

    columns = {row[1] for row in table_columns}
    assert {
        "id",
        "topic",
        "quiz_type",
        "num_questions",
        "quiz_data",
        "source_filename",
        "created_at",
    }.issubset(columns)
    assert rows == []

    with sqlite3.connect(db_file) as conn:
        index_names = {row[1] for row in conn.execute("PRAGMA index_list(generated_quizzes)")}
    assert "idx_generated_quizzes_created_at" in index_names
    assert "idx_generated_quizzes_topic" in index_names


def test_quiz_payload_is_stored_as_serialized_json_text(temp_database):
    """The relational TEXT cell must hold a JSON string, not a Python object repr."""
    test_id = "serialization-check"
    test_data = {
        "quiz_title": "Nested Structures",
        "questions": [
            {"id": 1, "type": "short-answer", "options": [], "correct_answer": "Stack"},
            {"id": 2, "type": "fill-in-the-blank", "options": [], "correct_answer": "queue"},
        ],
    }

    save_quiz(test_id, "  Data Structures  ", "short-answer", 2, test_data, source_filename="notes.txt")

    with sqlite3.connect(get_db_path()) as conn:
        stored_topic, stored_payload, stored_source = conn.execute(
            "SELECT topic, quiz_data, source_filename FROM generated_quizzes WHERE id = ?",
            (test_id,),
        ).fetchone()

    assert stored_topic == "Data Structures"
    assert stored_source == "notes.txt"
    assert isinstance(stored_payload, str)
    assert json.loads(stored_payload) == test_data

    fetched = get_quiz_by_id(test_id)
    assert fetched["source_filename"] == "notes.txt"
    assert fetched["created_at"]


def test_pydantic_quiz_payload_is_serialized(temp_database):
    """Nested Pydantic assessment results must serialize into a rehydratable JSON record."""
    assessment = AssessmentSchema.model_validate(
        {
            "quiz_title": "Pydantic Serialization Assessment",
            "questions": [
                {
                    "id": 1,
                    "type": "multiple-choice",
                    "question": "Which structure enforces LIFO ordering?",
                    "options": ["Stack", "Queue", "Heap", "Graph"],
                    "correct_answer": "Stack",
                    "explanation": "A stack resolves the most recently pushed element first.",
                }
            ],
        }
    )

    test_id = "pydantic-payload"
    save_quiz(test_id, "Data Structures", "multiple-choice", 1, assessment)

    fetched = get_quiz_by_id(test_id)
    assert fetched["quiz_data"]["quiz_title"] == "Pydantic Serialization Assessment"
    assert fetched["quiz_data"]["questions"][0]["correct_answer"] == "Stack"
    assert fetched["quiz_data"]["questions"][0]["id"] == 1


def test_save_quiz_rejects_empty_tracking_id(temp_database):
    """A blank uuid4 identifier must never reach the primary key column."""
    with pytest.raises(ValueError):
        save_quiz("   ", "Topic", "multiple-choice", 1, {"questions": []})


def test_duplicate_tracking_id_is_rejected_by_primary_key(temp_database):
    """uuid4 collisions must surface loudly rather than silently overwriting history."""
    save_quiz("duplicate-id", "Topic", "multiple-choice", 1, {"questions": []})

    with pytest.raises(sqlite3.IntegrityError):
        save_quiz("duplicate-id", "Topic", "multiple-choice", 1, {"questions": []})


def test_list_quizzes_orders_newest_first_and_filters_by_topic(temp_database):
    """History indexing must support newest-first paging and exact topic filtering."""
    save_quiz("history-1", "Physics", "multiple-choice", 1, {"questions": [{"id": 1}]}, source_filename="a.txt")
    save_quiz("history-2", "Biology", "short-answer", 1, {"questions": [{"id": 1}, {"id": 2}]}, source_filename="b.txt")
    save_quiz("history-3", "Physics", "fill-in-the-blank", 1, {"questions": [{"id": 1}]}, source_filename="c.txt")

    newest_first = list_quizzes()
    assert [record["quiz_id"] for record in newest_first][0] == "history-3"
    assert len(newest_first) == 3

    physics_only = list_quizzes(topic="Physics")
    assert {record["quiz_id"] for record in physics_only} == {"history-1", "history-3"}
    assert physics_only[0]["question_count"] == 1

    paged = list_quizzes(limit=2, offset=1)
    assert len(paged) == 2

    # Oversized limits must clamp to the page-size ceiling instead of erroring
    clamped = list_quizzes(limit=10_000, offset=-5)
    assert len(clamped) == 3
    assert clamped == list_quizzes(limit=database_module.MAX_HISTORY_PAGE_SIZE)

    assert count_quizzes() == 3
    assert count_quizzes(topic="Physics") == 2
    assert count_quizzes(topic="Astrophysics") == 0


def test_delete_quiz_removes_history_record(temp_database):
    """Deletion must report success for existing rows and 404-style misses for absent ones."""
    save_quiz("delete-me", "Chemistry", "multiple-choice", 1, {"questions": []})

    assert delete_quiz("delete-me") is True
    assert get_quiz_by_id("delete-me") is None
    assert delete_quiz("delete-me") is False
    assert delete_quiz("") is False


def test_relative_db_path_is_anchored_to_project_root():
    """A relative DATABASE_PATH must resolve deterministically regardless of the CWD."""
    original = database_module.DB_PATH
    try:
        database_module.DB_PATH = "quizzes.db"
        resolved = get_db_path()
        assert resolved.is_absolute()
        assert resolved.name == "quizzes.db"
        assert resolved.parent == database_module.PROJECT_ROOT
    finally:
        database_module.DB_PATH = original


def test_default_db_path_constant_is_quizzes_db():
    """The shipped default database file name must remain quizzes.db."""
    assert DB_PATH.endswith("quizzes.db")


def test_async_helpers_do_not_block_and_round_trip(temp_database):
    """The async wrappers must perform identical work when awaited from an event loop."""
    save_quiz("sync-record", "Astronomy", "multiple-choice", 1, {"questions": [{"id": 1}]})

    async def scenario():
        await database_module.async_init_db()
        await database_module.async_save_quiz(
            "async-record",
            "Astronomy",
            "short-answer",
            1,
            {"questions": [{"id": 1}, {"id": 2}]},
            source_filename="stars.txt",
        )
        record = await database_module.async_get_quiz_by_id("async-record")
        listing = await database_module.async_list_quizzes(limit=5)
        total = await database_module.async_count_quizzes()
        removed = await database_module.async_delete_quiz("async-record")
        return record, listing, total, removed

    record, listing, total, removed = asyncio.run(scenario())

    assert record["quiz_id"] == "async-record"
    assert record["topic"] == "Astronomy"
    assert record["source_filename"] == "stars.txt"
    assert record["quiz_data"]["questions"][0]["id"] == 1
    assert any(item["quiz_id"] == "sync-record" for item in listing)
    assert total >= 2
    assert removed is True
    assert get_quiz_by_id("async-record") is None


def test_concurrent_async_writes_all_persist(temp_database):
    """Parallel worker-thread writes must not lose records or trip database locks."""

    async def scenario():
        await asyncio.gather(
            *(
                database_module.async_save_quiz(
                    f"concurrent-{index}",
                    "Concurrency",
                    "multiple-choice",
                    1,
                    {"questions": [{"id": 1}]},
                )
                for index in range(12)
            )
        )

    asyncio.run(scenario())

    stored = {record["quiz_id"] for record in list_quizzes(limit=200)}
    assert {f"concurrent-{index}" for index in range(12)}.issubset(stored)


def test_generation_endpoint_persists_and_returns_tracking_id(temp_database):
    """Generation must persist the quiz and expose the uuid4 tracking ID in the payload."""
    mock_quiz = {
        "quiz_title": "Persistence Assessment",
        "questions": [
            {
                "id": 1,
                "type": "multiple-choice",
                "question": "What does a write-ahead log guarantee?",
                "options": ["Durability", "Compression", "Sharding", "Encryption"],
                "correct_answer": "Durability",
                "explanation": "WAL journaling commits changes to an append-only log before the main database file.",
            }
        ],
    }

    with patch("services.generator.QuestionGeneratorService.generate_quiz") as mock_generator:
        mock_generator.return_value = mock_quiz
        payload = {"type": "multiple-choice", "count": "1", "topic": "Databases"}
        files = {"file": ("wal.txt", b"Write ahead logging protects committed transactions.", "text/plain")}

        response = client.post("/api/v1/generate", data=payload, files=files)

    assert response.status_code == 200
    body = response.json()
    quiz_id = body["quiz_id"]
    assert quiz_id
    assert body["topic"] == "Databases"

    # uuid4 shape validation
    assert uuid_lib.UUID(quiz_id).version == 4

    record = get_quiz_by_id(quiz_id)
    assert record is not None
    assert record["quiz_type"] == "multiple-choice"
    assert record["num_questions"] == 1
    assert record["source_filename"] == "wal.txt"
    assert record["quiz_data"]["quiz_title"] == "Persistence Assessment"
    assert record["quiz_data"]["questions"][0]["correct_answer"] == "Durability"
    assert "quiz_id" not in record["quiz_data"]


def test_retrieval_endpoint_returns_historical_quiz(temp_database):
    """The retrieval node must serve a previously generated quiz by its tracking ID."""
    quiz_id = "endpoint-retrieval-id"
    save_quiz(
        quiz_id,
        "Geology",
        "short-answer",
        1,
        {"quiz_title": "Rock Cycle", "questions": [{"id": 1, "correct_answer": "Igneous"}]},
        source_filename="rocks.txt",
    )

    response = client.get(f"/api/v1/quizzes/{quiz_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["quiz_id"] == quiz_id
    assert body["topic"] == "Geology"
    assert body["quiz_title"] == "Rock Cycle"
    assert body["created_at"]

    # Legacy rows are repaired on read and must never expose the answer key.
    assert body["questions"][0]["question"] == "Question 1"
    assert "correct_answer" not in response.text
    assert "Igneous" not in response.text

    source_response = client.get(f"/api/v1/quizzes/{quiz_id}/source")
    assert source_response.status_code == 200
    assert source_response.json()["source_filename"] == "rocks.txt"


def test_retrieval_endpoint_returns_404_for_unknown_id(temp_database):
    """Unknown tracking IDs must surface a clean 404 instead of a 500."""
    response = client.get("/api/v1/quizzes/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"] == "quiz_not_found"


def test_history_listing_and_delete_endpoints(temp_database):
    """History browsing and deletion must be exposed over HTTP."""
    save_quiz("history-endpoint-id", "Chemistry", "multiple-choice", 1, {"quiz_title": "Periodic Table", "questions": []})

    listing = client.get("/api/v1/quizzes", params={"topic": "Chemistry"})
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["total"] >= 1
    assert payload["count"] == len(payload["quizzes"])
    assert payload["limit"] == 20
    assert payload["offset"] == 0
    assert any(item["quiz_id"] == "history-endpoint-id" for item in payload["quizzes"])
    assert all(item["topic"] == "Chemistry" for item in payload["quizzes"])

    # A topic with no history must report an accurate zero total
    empty = client.get("/api/v1/quizzes", params={"topic": "Astrophysics"})
    assert empty.status_code == 200
    assert empty.json() == {
        "total": 0,
        "count": 0,
        "limit": 20,
        "offset": 0,
        "quizzes": [],
    }

    deleted = client.delete("/api/v1/quizzes/history-endpoint-id")
    assert deleted.status_code == 200
    assert deleted.json() == {"quiz_id": "history-endpoint-id", "deleted": True}

    assert client.delete("/api/v1/quizzes/history-endpoint-id").status_code == 404
    assert client.get("/api/v1/quizzes/history-endpoint-id").status_code == 404


def test_generate_endpoint_still_returns_static_ui():
    """The persistence layer must not shadow the mounted static client interface."""
    response = client.get("/")
    assert response.status_code == 200
    assert "/js/app.js" in response.text
    assert "<!DOCTYPE html>" in response.text
