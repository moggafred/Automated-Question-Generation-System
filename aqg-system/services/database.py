"""Thread-safe SQLite persistence layer for the AQG platform.

Design notes
------------
* ``sqlite3`` is a blocking, synchronous driver, so every database operation is
  dispatched to a worker thread by the ``async_*`` helpers. The FastAPI event
  loop is therefore never blocked by disk I/O.
* Each operation opens its own short-lived connection (``check_same_thread``
  stays at its safe default) which keeps the layer re-entrant across the
  threadpool, uvicorn workers and pytest alike.
* WAL journaling plus a busy timeout allow concurrent readers while a record is
  being committed.
* Quiz payloads are stored as serialized JSON text in a relational ``TEXT``
  column, and are rehydrated into plain Python structures on read.
* Every statement is parameterized; no user input is ever concatenated into SQL.

Tables
------
``generated_quizzes``    -- assessments produced by the generator (pre-existing)
``documents``            -- every ingested upload
``study_materials``      -- AI summaries, flashcards, revision notes
``assessment_attempts``  -- graded learner submissions
"""

import asyncio
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from config.settings import settings

DB_PATH = settings.DATABASE_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[1]

BUSY_TIMEOUT_MS = 30_000
MAX_HISTORY_PAGE_SIZE = 200

QUIZ_TABLE = "generated_quizzes"
DOCUMENT_TABLE = "documents"
STUDY_TABLE = "study_materials"
ATTEMPT_TABLE = "assessment_attempts"

_SCHEMA_STATEMENTS = (
    # --- Legacy generated quiz table (preserved verbatim) ---------------
    f"""
    CREATE TABLE IF NOT EXISTS {QUIZ_TABLE} (
        id TEXT PRIMARY KEY,
        topic TEXT NOT NULL,
        quiz_type TEXT NOT NULL,
        num_questions INTEGER NOT NULL,
        quiz_data TEXT NOT NULL,
        source_filename TEXT,
        created_at TEXT NOT NULL
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_generated_quizzes_created_at ON {QUIZ_TABLE} (created_at DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_generated_quizzes_topic ON {QUIZ_TABLE} (topic)",
    f"CREATE INDEX IF NOT EXISTS idx_generated_quizzes_quiz_type ON {QUIZ_TABLE} (quiz_type)",
    # --- Ingested documents --------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {DOCUMENT_TABLE} (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        extension TEXT NOT NULL,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        page_count INTEGER NOT NULL DEFAULT 0,
        character_count INTEGER NOT NULL DEFAULT 0,
        word_count INTEGER NOT NULL DEFAULT 0,
        chunk_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ready',
        created_at TEXT NOT NULL
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_documents_created_at ON {DOCUMENT_TABLE} (created_at DESC)",
    # --- AI study materials -------------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {STUDY_TABLE} (
        id TEXT PRIMARY KEY,
        document_id TEXT,
        topic TEXT NOT NULL DEFAULT '',
        material_type TEXT NOT NULL,
        title TEXT NOT NULL,
        source_filename TEXT,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (document_id) REFERENCES {DOCUMENT_TABLE} (id) ON DELETE SET NULL
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_study_materials_created_at ON {STUDY_TABLE} (created_at DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_study_materials_document_id ON {STUDY_TABLE} (document_id)",
    # --- Graded assessment attempts ------------------------------------
    f"""
    CREATE TABLE IF NOT EXISTS {ATTEMPT_TABLE} (
        id TEXT PRIMARY KEY,
        quiz_id TEXT NOT NULL,
        score REAL NOT NULL,
        total_score REAL NOT NULL DEFAULT 0,
        percentage REAL NOT NULL,
        correct_answers INTEGER NOT NULL DEFAULT 0,
        incorrect_answers INTEGER NOT NULL DEFAULT 0,
        unanswered INTEGER NOT NULL DEFAULT 0,
        partial_answers INTEGER NOT NULL DEFAULT 0,
        total_questions INTEGER NOT NULL DEFAULT 0,
        attempted INTEGER NOT NULL DEFAULT 0,
        answers TEXT NOT NULL,
        review TEXT NOT NULL DEFAULT '[]',
        topic TEXT NOT NULL DEFAULT '',
        time_spent_seconds REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (quiz_id) REFERENCES {QUIZ_TABLE} (id) ON DELETE CASCADE
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_assessment_attempts_created_at ON {ATTEMPT_TABLE} (created_at DESC)",
    f"CREATE INDEX IF NOT EXISTS idx_assessment_attempts_quiz_id ON {ATTEMPT_TABLE} (quiz_id)",
)

# Columns added after the initial release; applied on every boot via ALTER TABLE
# so an existing ``quizzes.db`` upgrades in place without data loss.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    (QUIZ_TABLE, "source_filename", "TEXT"),
    (QUIZ_TABLE, "difficulty", "TEXT NOT NULL DEFAULT 'medium'"),
    (QUIZ_TABLE, "document_id", "TEXT"),
)

_schema_lock = threading.Lock()
_schema_ready = False


def get_db_path() -> Path:
    """Resolves the active database file, anchoring relative paths to the project root."""
    configured = Path(DB_PATH)
    if configured.is_absolute():
        return configured
    return PROJECT_ROOT / configured


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yields a configured connection inside a transaction context and always closes it."""
    db_file = get_db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_file, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        conn.close()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _jsonable(value: Any) -> Any:
    """Coerces nested Pydantic/dataclass payloads into JSON-serializable primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _jsonable(dump(mode="json"))

    legacy_dump = getattr(value, "dict", None)
    if callable(legacy_dump):
        return _jsonable(legacy_dump())

    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]

    return str(value)


def serialize_quiz_data(quiz_data: Any) -> str:
    """Serializes a nested quiz payload into a compact UTF-8 JSON text record."""
    return json.dumps(
        _jsonable(quiz_data),
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )


def deserialize_quiz_data(raw_quiz_data: str) -> Any:
    """Rehydrates a stored JSON text record back into Python structures."""
    return json.loads(raw_quiz_data)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _apply_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)

    for table, column, definition in _MIGRATIONS:
        if column not in _table_columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_schema() -> None:
    """Creates the schema on first use so writes never depend on startup ordering."""
    global _schema_ready
    if _schema_ready:
        return

    with _schema_lock:
        if _schema_ready:
            return
        with get_connection() as conn, conn:
            _apply_schema(conn)
        _schema_ready = True


def init_db() -> None:
    """Initializes the database file and creates every table if it does not exist."""
    global _schema_ready

    with get_connection() as conn, conn:
        _apply_schema(conn)
    _schema_ready = True


# ==========================================================================
# generated_quizzes
# ==========================================================================
def save_quiz(
    quiz_id: str,
    topic: str,
    quiz_type: str,
    num_questions: int,
    quiz_data: Any,
    source_filename: Optional[str] = None,
    difficulty: Optional[str] = None,
    document_id: Optional[str] = None,
) -> str:
    """Saves a generated quiz payload safely into the database layer."""
    if not quiz_id or not str(quiz_id).strip():
        raise ValueError("quiz_id must be a non-empty tracking identifier.")

    _ensure_schema()

    record = (
        str(quiz_id).strip(),
        (topic or "").strip(),
        (quiz_type or "").strip(),
        int(num_questions),
        serialize_quiz_data(quiz_data),
        source_filename or None,
        _utc_now_iso(),
        (difficulty or "medium").strip().lower(),
        document_id or None,
    )

    with get_connection() as conn, conn:
        conn.execute(
            """
            INSERT INTO generated_quizzes
                (id, topic, quiz_type, num_questions, quiz_data, source_filename, created_at, difficulty, document_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            record,
        )

    return record[0]


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "quiz_id": row["id"],
        "topic": row["topic"],
        "quiz_type": row["quiz_type"],
        "num_questions": row["num_questions"],
        "quiz_data": deserialize_quiz_data(row["quiz_data"]),
        "source_filename": row["source_filename"],
        "created_at": row["created_at"],
        "difficulty": row["difficulty"] if "difficulty" in row.keys() else "medium",
        "document_id": row["document_id"] if "document_id" in row.keys() else None,
    }


def _summary_from_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = deserialize_quiz_data(row["quiz_data"])
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    keys = row.keys()
    return {
        "quiz_id": row["id"],
        "topic": row["topic"],
        "quiz_type": row["quiz_type"],
        "num_questions": row["num_questions"],
        "quiz_title": payload.get("quiz_title", "") if isinstance(payload, dict) else "",
        "question_count": len(questions) if isinstance(questions, list) else 0,
        "difficulty": row["difficulty"] if "difficulty" in keys else "medium",
        "document_id": row["document_id"] if "document_id" in keys else None,
        "source_filename": row["source_filename"],
        "created_at": row["created_at"],
    }


def get_quiz_by_id(quiz_id: str) -> Optional[dict[str, Any]]:
    """Retrieves a historically generated quiz by its unique tracking ID."""
    if not quiz_id:
        return None

    _ensure_schema()

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, topic, quiz_type, num_questions, quiz_data, source_filename, created_at, difficulty, document_id
            FROM generated_quizzes
            WHERE id = ?
            """,
            (str(quiz_id).strip(),),
        ).fetchone()

    if row is None:
        return None

    return _row_to_record(row)


def list_quizzes(
    limit: int = 20,
    offset: int = 0,
    topic: Optional[str] = None,
    quiz_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Returns historical quiz summaries, newest first, for history browsing nodes."""
    _ensure_schema()

    safe_limit = max(1, min(int(limit), MAX_HISTORY_PAGE_SIZE))
    safe_offset = max(0, int(offset))

    query = """
        SELECT id, topic, quiz_type, num_questions, quiz_data, source_filename, created_at, difficulty, document_id
        FROM generated_quizzes
    """
    params: list[Any] = []
    filters: list[str] = []
    if (topic or "").strip():
        filters.append("topic = ?")
        params.append(topic.strip())
    if (quiz_type or "").strip():
        filters.append("quiz_type = ?")
        params.append(quiz_type.strip())
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
    params.extend([safe_limit, safe_offset])

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [_summary_from_row(row) for row in rows]


def count_quizzes(topic: Optional[str] = None, quiz_type: Optional[str] = None) -> int:
    """Returns the number of persisted quizzes, optionally narrowed by topic/type."""
    _ensure_schema()

    query = "SELECT COUNT(*) AS total FROM generated_quizzes"
    params: list[Any] = []
    filters: list[str] = []
    if (topic or "").strip():
        filters.append("topic = ?")
        params.append(topic.strip())
    if (quiz_type or "").strip():
        filters.append("quiz_type = ?")
        params.append(quiz_type.strip())
    if filters:
        query += " WHERE " + " AND ".join(filters)

    with get_connection() as conn:
        row = conn.execute(query, params).fetchone()

    return int(row["total"]) if row else 0


def delete_quiz(quiz_id: str) -> bool:
    """Removes a historical quiz record. Returns True when a row was deleted."""
    if not quiz_id:
        return False

    _ensure_schema()

    with get_connection() as conn, conn:
        cursor = conn.execute("DELETE FROM generated_quizzes WHERE id = ?", (str(quiz_id).strip(),))
        return cursor.rowcount > 0


def distinct_topics() -> list[str]:
    """Returns every non-empty topic label currently stored, alphabetically."""
    _ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT topic FROM generated_quizzes WHERE topic != '' ORDER BY topic COLLATE NOCASE ASC"
        ).fetchall()
    return [row["topic"] for row in rows]


# ==========================================================================
# documents
# ==========================================================================
def save_document(
    document_id: str,
    filename: str,
    extension: str,
    size_bytes: int,
    page_count: int,
    character_count: int,
    word_count: int,
    chunk_count: int,
    status: str = "ready",
) -> str:
    """Persists metadata for an ingested document."""
    if not document_id:
        raise ValueError("document_id must be a non-empty identifier.")

    _ensure_schema()

    record = (
        str(document_id).strip(),
        filename,
        extension,
        int(size_bytes),
        int(page_count),
        int(character_count),
        int(word_count),
        int(chunk_count),
        status,
        _utc_now_iso(),
    )

    with get_connection() as conn, conn:
        conn.execute(
            """
            INSERT INTO documents
                (id, filename, extension, size_bytes, page_count, character_count, word_count, chunk_count, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            record,
        )
    return record[0]


def get_document(document_id: str) -> Optional[dict[str, Any]]:
    _ensure_schema()
    if not document_id:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, filename, extension, size_bytes, page_count, character_count, word_count, chunk_count, status, created_at
            FROM documents WHERE id = ?
            """,
            (str(document_id).strip(),),
        ).fetchone()
    return dict(row) if row else None


def list_documents(limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    """Returns ingested document rows, newest first."""
    _ensure_schema()
    safe_limit = max(1, min(int(limit), MAX_HISTORY_PAGE_SIZE))
    safe_offset = max(0, int(offset))

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, extension, size_bytes, page_count, character_count, word_count, chunk_count, status, created_at
            FROM documents
            ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?
            """,
            (safe_limit, safe_offset),
        ).fetchall()
    return [dict(row) for row in rows]


def count_documents() -> int:
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM documents").fetchone()
    return int(row["total"]) if row else 0


# ==========================================================================
# study_materials
# ==========================================================================
def save_study_material(
    material_id: str,
    material_type: str,
    title: str,
    content: Any,
    topic: str = "",
    source_filename: Optional[str] = None,
    document_id: Optional[str] = None,
) -> str:
    """Stores a generated study resource bundle as serialized JSON text."""
    if not material_id:
        raise ValueError("material_id must be a non-empty identifier.")

    _ensure_schema()

    record = (
        str(material_id).strip(),
        document_id or None,
        (topic or "").strip(),
        (material_type or "").strip(),
        (title or "Study Material").strip()[:240],
        source_filename or None,
        serialize_quiz_data(content),
        _utc_now_iso(),
    )

    with get_connection() as conn, conn:
        conn.execute(
            """
            INSERT INTO study_materials
                (id, document_id, topic, material_type, title, source_filename, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            record,
        )
    return record[0]


def _study_row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "material_id": row["id"],
        "document_id": row["document_id"],
        "topic": row["topic"],
        "material_type": row["material_type"],
        "title": row["title"],
        "source_filename": row["source_filename"],
        "content": deserialize_quiz_data(row["content"]),
        "created_at": row["created_at"],
    }


def get_study_material(material_id: str) -> Optional[dict[str, Any]]:
    _ensure_schema()
    if not material_id:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, document_id, topic, material_type, title, source_filename, content, created_at
            FROM study_materials WHERE id = ?
            """,
            (str(material_id).strip(),),
        ).fetchone()
    return _study_row_to_record(row) if row else None


def list_study_materials(limit: int = 20, offset: int = 0, material_type: Optional[str] = None) -> list[dict[str, Any]]:
    """Returns stored study resources, newest first."""
    _ensure_schema()
    safe_limit = max(1, min(int(limit), MAX_HISTORY_PAGE_SIZE))
    safe_offset = max(0, int(offset))

    query = "SELECT id, document_id, topic, material_type, title, source_filename, content, created_at FROM study_materials"
    params: list[Any] = []
    if (material_type or "").strip():
        query += " WHERE material_type = ?"
        params.append(material_type.strip())
    query += " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
    params.extend([safe_limit, safe_offset])

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_study_row_to_record(row) for row in rows]


def count_study_materials() -> int:
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM study_materials").fetchone()
    return int(row["total"]) if row else 0


def delete_study_material(material_id: str) -> bool:
    _ensure_schema()
    if not material_id:
        return False

    with get_connection() as conn, conn:
        cursor = conn.execute("DELETE FROM study_materials WHERE id = ?", (str(material_id).strip(),))
        return cursor.rowcount > 0


# ==========================================================================
# assessment_attempts
# ==========================================================================
def save_assessment_attempt(
    attempt_id: str,
    quiz_id: str,
    score: float,
    total_score: float,
    percentage: float,
    correct_answers: int,
    incorrect_answers: int,
    unanswered: int,
    partial_answers: int,
    total_questions: int,
    attempted: int,
    answers: Any,
    review: Any,
    topic: str = "",
    time_spent_seconds: float = 0.0,
) -> str:
    """Stores a graded learner attempt together with its answer key and review."""
    if not attempt_id:
        raise ValueError("attempt_id must be a non-empty identifier.")
    if not quiz_id:
        raise ValueError("quiz_id must be a non-empty identifier.")

    _ensure_schema()

    record = (
        str(attempt_id).strip(),
        str(quiz_id).strip(),
        float(score),
        float(total_score),
        float(percentage),
        int(correct_answers),
        int(incorrect_answers),
        int(unanswered),
        int(partial_answers),
        int(total_questions),
        int(attempted),
        serialize_quiz_data(answers),
        serialize_quiz_data(review or []),
        (topic or "").strip(),
        float(time_spent_seconds or 0.0),
        _utc_now_iso(),
    )

    with get_connection() as conn, conn:
        conn.execute(
            """
            INSERT INTO assessment_attempts
                (id, quiz_id, score, total_score, percentage, correct_answers, incorrect_answers, unanswered,
                 partial_answers, total_questions, attempted, answers, review, topic, time_spent_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            record,
        )
    return record[0]


_ATTEMPT_COLUMNS = (
    "id, quiz_id, score, total_score, percentage, correct_answers, incorrect_answers, unanswered, "
    "partial_answers, total_questions, attempted, answers, review, topic, time_spent_seconds, created_at"
)


def _attempt_row_to_record(row: sqlite3.Row, include_payloads: bool = True) -> dict[str, Any]:
    record: dict[str, Any] = {
        "attempt_id": row["id"],
        "quiz_id": row["quiz_id"],
        "score": round(float(row["score"]), 2),
        "total_score": round(float(row["total_score"]), 2),
        "percentage": round(float(row["percentage"]), 1),
        "correct_answers": int(row["correct_answers"]),
        "incorrect_answers": int(row["incorrect_answers"]),
        "unanswered": int(row["unanswered"]),
        "partial_answers": int(row["partial_answers"]),
        "total_questions": int(row["total_questions"]),
        "attempted": int(row["attempted"]),
        "topic": row["topic"],
        "time_spent_seconds": round(float(row["time_spent_seconds"]), 1),
        "created_at": row["created_at"],
    }
    if include_payloads:
        record["answers"] = deserialize_quiz_data(row["answers"])
        record["review"] = deserialize_quiz_data(row["review"])
    return record


def get_assessment_attempt(attempt_id: str) -> Optional[dict[str, Any]]:
    _ensure_schema()
    if not attempt_id:
        return None

    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {_ATTEMPT_COLUMNS} FROM {ATTEMPT_TABLE} WHERE id = ?",
            (str(attempt_id).strip(),),
        ).fetchone()
    return _attempt_row_to_record(row) if row else None


def list_assessment_attempts(
    limit: int = 20,
    offset: int = 0,
    quiz_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Returns graded attempts, newest first."""
    _ensure_schema()
    safe_limit = max(1, min(int(limit), MAX_HISTORY_PAGE_SIZE))
    safe_offset = max(0, int(offset))

    query = f"SELECT {_ATTEMPT_COLUMNS} FROM {ATTEMPT_TABLE}"
    params: list[Any] = []
    if (quiz_id or "").strip():
        query += " WHERE quiz_id = ?"
        params.append(quiz_id.strip())
    query += " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
    params.extend([safe_limit, safe_offset])

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_attempt_row_to_record(row, include_payloads=False) for row in rows]


def count_assessment_attempts(quiz_id: Optional[str] = None) -> int:
    _ensure_schema()
    query = f"SELECT COUNT(*) AS total FROM {ATTEMPT_TABLE}"
    params: list[Any] = []
    if (quiz_id or "").strip():
        query += " WHERE quiz_id = ?"
        params.append(quiz_id.strip())

    with get_connection() as conn:
        row = conn.execute(query, params).fetchone()
    return int(row["total"]) if row else 0


def delete_assessment_attempts(quiz_id: str) -> int:
    _ensure_schema()
    if not quiz_id:
        return 0

    with get_connection() as conn, conn:
        cursor = conn.execute("DELETE FROM assessment_attempts WHERE quiz_id = ?", (str(quiz_id).strip(),))
        return int(cursor.rowcount or 0)


# ==========================================================================
# Aggregates used by the dashboard and performance pages
# ==========================================================================
def get_platform_statistics() -> dict[str, Any]:
    """Returns the aggregate counters rendered on the dashboard.

    Every value is derived from persisted rows; nothing here is fabricated.
    """
    _ensure_schema()

    with get_connection() as conn:
        quiz_row = conn.execute(
            f"""
            SELECT COUNT(*) AS quiz_count,
                   COALESCE(SUM(num_questions), 0) AS question_count,
                   COALESCE(COUNT(DISTINCT topic), 0) AS topic_count
            FROM {QUIZ_TABLE} WHERE topic != ''
            """
        ).fetchone()
        total_quiz_row = conn.execute(f"SELECT COUNT(*) AS total FROM {QUIZ_TABLE}").fetchone()
        doc_row = conn.execute(f"SELECT COUNT(*) AS total FROM {DOCUMENT_TABLE}").fetchone()
        study_row = conn.execute(f"SELECT COUNT(*) AS total FROM {STUDY_TABLE}").fetchone()
        attempt_row = conn.execute(
            f"""
            SELECT COUNT(*) AS attempt_count,
                   COALESCE(AVG(percentage), 0) AS average_percentage,
                   COALESCE(MAX(percentage), 0) AS highest_percentage,
                   COALESCE(MIN(percentage), 0) AS lowest_percentage,
                   COALESCE(SUM(total_questions), 0) AS questions_answered
            FROM {ATTEMPT_TABLE}
            """
        ).fetchone()

    return {
        "documents_processed": int(doc_row["total"]) if doc_row else 0,
        "quizzes_generated": int(total_quiz_row["total"]) if total_quiz_row else 0,
        "questions_generated": int(quiz_row["question_count"]) if quiz_row else 0,
        "topics_covered": int(quiz_row["topic_count"]) if quiz_row else 0,
        "study_materials_generated": int(study_row["total"]) if study_row else 0,
        "assessments_completed": int(attempt_row["attempt_count"]) if attempt_row else 0,
        "questions_answered": int(attempt_row["questions_answered"]) if attempt_row else 0,
        "average_score": round(float(attempt_row["average_percentage"]), 1) if attempt_row else 0.0,
        "highest_score": round(float(attempt_row["highest_percentage"]), 1) if attempt_row else 0.0,
        "lowest_score": round(float(attempt_row["lowest_percentage"]), 1) if attempt_row else 0.0,
    }


def get_recent_activity(limit: int = 8) -> list[dict[str, Any]]:
    """Returns a unified, newest-first activity feed across every record type."""
    _ensure_schema()
    safe_limit = max(1, min(int(limit), MAX_HISTORY_PAGE_SIZE))

    with get_connection() as conn:
        quiz_rows = conn.execute(
            f"""
            SELECT id, topic, quiz_type, num_questions, source_filename, created_at
            FROM {QUIZ_TABLE}
            ORDER BY created_at DESC, rowid DESC LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        study_rows = conn.execute(
            f"SELECT id, topic, material_type, title, source_filename, created_at FROM {STUDY_TABLE} "
            f"ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
        attempt_rows = conn.execute(
            f"SELECT id, quiz_id, percentage, correct_answers, total_questions, created_at FROM {ATTEMPT_TABLE} "
            f"ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
        document_rows = conn.execute(
            f"SELECT id, filename, page_count, word_count, created_at FROM {DOCUMENT_TABLE} "
            f"ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()

    feed: list[dict[str, Any]] = []

    for row in quiz_rows:
        source = row["source_filename"] or "an uploaded document"
        feed.append(
            {
                "kind": "quiz",
                "id": row["id"],
                "title": f"{row['num_questions']} {row['quiz_type']} generated from {source}",
                "subtitle": row["topic"] or "Full document",
                "created_at": row["created_at"],
                "href": f"#/quiz/{row['id']}",
            }
        )

    for row in study_rows:
        feed.append(
            {
                "kind": "study_material",
                "id": row["id"],
                "title": f"{row['title']} generated from {row['source_filename'] or 'your document'}",
                "subtitle": row["material_type"],
                "created_at": row["created_at"],
                "href": f"#/study/{row['id']}",
            }
        )

    for row in attempt_rows:
        feed.append(
            {
                "kind": "assessment",
                "id": row["id"],
                "title": f"Assessment completed with {float(row['percentage']):.0f}%",
                "subtitle": f"{row['correct_answers']}/{row['total_questions']} correct",
                "created_at": row["created_at"],
                "href": f"#/result/{row['id']}",
            }
        )

    for row in document_rows:
        feed.append(
            {
                "kind": "document",
                "id": row["id"],
                "title": f"{row['filename']} processed successfully",
                "subtitle": f"{row['page_count']} page(s) - {row['word_count']} words indexed",
                "created_at": row["created_at"],
                "href": "#/documents",
            }
        )

    feed.sort(key=lambda item: (item["created_at"] or ""), reverse=True)
    return feed[:safe_limit]


def get_topic_performance() -> list[dict[str, Any]]:
    """Returns per-topic attempt averages, highest first."""
    _ensure_schema()

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT COALESCE(NULLIF(a.topic, ''), q.topic, 'Unlabelled topic') AS topic,
                   COUNT(*) AS attempts,
                   ROUND(AVG(a.percentage), 1) AS average_percentage,
                   ROUND(MAX(a.percentage), 1) AS highest_percentage,
                   ROUND(MIN(a.percentage), 1) AS lowest_percentage,
                   COALESCE(SUM(a.total_questions), 0) AS questions_answered
            FROM {ATTEMPT_TABLE} AS a
            LEFT JOIN {QUIZ_TABLE} AS q ON q.id = a.quiz_id
            GROUP BY COALESCE(NULLIF(a.topic, ''), q.topic, 'Unlabelled topic')
            ORDER BY average_percentage DESC, attempts DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_recent_attempts(limit: int = 5) -> list[dict[str, Any]]:
    """Returns the most recent attempts joined with their assessment titles."""
    _ensure_schema()
    safe_limit = max(1, min(int(limit), MAX_HISTORY_PAGE_SIZE))

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT a.id AS attempt_id, a.quiz_id, a.percentage, a.correct_answers, a.total_questions,
                   a.created_at, COALESCE(NULLIF(q.topic, ''), a.topic, 'Full document') AS topic,
                   json_extract(q.quiz_data, '$.quiz_title') AS quiz_title
            FROM {ATTEMPT_TABLE} AS a
            LEFT JOIN {QUIZ_TABLE} AS q ON q.id = a.quiz_id
            ORDER BY a.created_at DESC, a.rowid DESC LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    return [
        {
            "attempt_id": row["attempt_id"],
            "quiz_id": row["quiz_id"],
            "quiz_title": row["quiz_title"] or "Assessment",
            "topic": row["topic"],
            "percentage": round(float(row["percentage"]), 1),
            "correct_answers": int(row["correct_answers"]),
            "total_questions": int(row["total_questions"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


# ==========================================================================
# Async bridge -- every blocking sqlite3 call is dispatched to a worker thread
# ==========================================================================
async def _run_in_worker(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Offloads a blocking sqlite3 call to a worker thread to keep the event loop free."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


async def async_init_db() -> None:
    """Async counterpart of :func:`init_db` for use inside route handlers."""
    await _run_in_worker(init_db)


async def async_save_quiz(
    quiz_id: str,
    topic: str,
    quiz_type: str,
    num_questions: int,
    quiz_data: Any,
    source_filename: Optional[str] = None,
    difficulty: Optional[str] = None,
    document_id: Optional[str] = None,
) -> str:
    """Async counterpart of :func:`save_quiz`."""
    return await _run_in_worker(
        save_quiz, quiz_id, topic, quiz_type, num_questions, quiz_data, source_filename, difficulty, document_id
    )


async def async_get_quiz_by_id(quiz_id: str) -> Optional[dict[str, Any]]:
    """Async counterpart of :func:`get_quiz_by_id`."""
    return await _run_in_worker(get_quiz_by_id, quiz_id)


async def async_list_quizzes(
    limit: int = 20,
    offset: int = 0,
    topic: Optional[str] = None,
    quiz_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Async counterpart of :func:`list_quizzes`."""
    return await _run_in_worker(list_quizzes, limit, offset, topic, quiz_type)


async def async_count_quizzes(topic: Optional[str] = None, quiz_type: Optional[str] = None) -> int:
    """Async counterpart of :func:`count_quizzes`."""
    return await _run_in_worker(count_quizzes, topic, quiz_type)


async def async_delete_quiz(quiz_id: str) -> bool:
    """Async counterpart of :func:`delete_quiz`."""
    return await _run_in_worker(delete_quiz, quiz_id)


async def async_distinct_topics() -> list[str]:
    return await _run_in_worker(distinct_topics)


async def async_save_document(*args: Any, **kwargs: Any) -> str:
    return await _run_in_worker(save_document, *args, **kwargs)


async def async_get_document(document_id: str) -> Optional[dict[str, Any]]:
    return await _run_in_worker(get_document, document_id)


async def async_list_documents(limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    return await _run_in_worker(list_documents, limit, offset)


async def async_count_documents() -> int:
    return await _run_in_worker(count_documents)


async def async_save_study_material(*args: Any, **kwargs: Any) -> str:
    return await _run_in_worker(save_study_material, *args, **kwargs)


async def async_get_study_material(material_id: str) -> Optional[dict[str, Any]]:
    return await _run_in_worker(get_study_material, material_id)


async def async_list_study_materials(
    limit: int = 20,
    offset: int = 0,
    material_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    return await _run_in_worker(list_study_materials, limit, offset, material_type)


async def async_count_study_materials() -> int:
    return await _run_in_worker(count_study_materials)


async def async_delete_study_material(material_id: str) -> bool:
    return await _run_in_worker(delete_study_material, material_id)


async def async_save_assessment_attempt(*args: Any, **kwargs: Any) -> str:
    return await _run_in_worker(save_assessment_attempt, *args, **kwargs)


async def async_get_assessment_attempt(attempt_id: str) -> Optional[dict[str, Any]]:
    return await _run_in_worker(get_assessment_attempt, attempt_id)


async def async_list_assessment_attempts(
    limit: int = 20,
    offset: int = 0,
    quiz_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    return await _run_in_worker(list_assessment_attempts, limit, offset, quiz_id)


async def async_count_assessment_attempts(quiz_id: Optional[str] = None) -> int:
    return await _run_in_worker(count_assessment_attempts, quiz_id)


async def async_get_platform_statistics() -> dict[str, Any]:
    return await _run_in_worker(get_platform_statistics)


async def async_get_recent_activity(limit: int = 8) -> list[dict[str, Any]]:
    return await _run_in_worker(get_recent_activity, limit)


async def async_get_topic_performance() -> list[dict[str, Any]]:
    return await _run_in_worker(get_topic_performance)


async def async_get_recent_attempts(limit: int = 5) -> list[dict[str, Any]]:
    return await _run_in_worker(get_recent_attempts, limit)