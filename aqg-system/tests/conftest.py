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


def pytest_configure(config):
    """Registers the custom marker used to opt out of the auth override."""
    config.addinivalue_line(
        "markers",
        "real_auth: exercise the real authentication dependency instead of the test override",
    )


@pytest.fixture(autouse=True)
def authenticated_client(request):
    """Signs in a deterministic principal for the pre-existing feature tests.

    Tests marked ``real_auth`` skip the override so they can drive the genuine
    cookie/session/CSRF flow end to end.
    """
    from api.security import get_current_user, get_optional_user
    from main import app
    from models.user import AuthenticatedUser

    if request.node.get_closest_marker("real_auth"):
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_optional_user, None)
        yield
        return

    principal = AuthenticatedUser(
        id="test-user",
        email="test@example.com",
        full_name="Test User",
        provider="password",
    )
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_optional_user] = lambda: principal
    try:
        yield principal
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_optional_user, None)
