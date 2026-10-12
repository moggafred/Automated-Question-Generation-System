import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session", autouse=True)
def isolated_database(tmp_path_factory):
    """Redirects the persistence layer to a throwaway file so tests never touch the repo database."""
    import services.database as database

    original_path = database.DB_PATH
    original_schema_ready = database._schema_ready

    database.DB_PATH = str(tmp_path_factory.mktemp("aqg-db") / "quizzes.db")
    database._schema_ready = False
    database.init_db()

    yield database

    database.DB_PATH = original_path
    database._schema_ready = original_schema_ready


@pytest.fixture
def temp_database(isolated_database, monkeypatch, tmp_path):
    """Points the persistence layer at a per-test database file."""
    monkeypatch.setattr(isolated_database, "DB_PATH", str(tmp_path / "quizzes.db"))
    monkeypatch.setattr(isolated_database, "_schema_ready", False)
    isolated_database.init_db()
    return isolated_database
