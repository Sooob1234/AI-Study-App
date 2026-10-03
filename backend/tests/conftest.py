"""Test set-up.

The checks in test_api.py need a real PostgreSQL database that they are
allowed to wipe. Point TEST_DATABASE_URL at an empty database whose name
contains "test"; without it those checks are skipped.

    TEST_DATABASE_URL=postgresql+psycopg2://ai_study:ai_study_password@localhost:5433/ai_study_test python -m pytest
"""

import os
import tempfile

import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

if TEST_DATABASE_URL:
    if "test" not in TEST_DATABASE_URL.rsplit("/", 1)[-1]:
        raise RuntimeError(
            "TEST_DATABASE_URL must point to a database with 'test' in its "
            "name, because the tests erase everything in it."
        )

    # These must be set before the app is imported.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["UPLOAD_ROOT"] = tempfile.mkdtemp(prefix="ai-study-uploads-")
    os.environ["JWT_SECRET"] = "test-secret-key-only-for-automated-tests"


@pytest.fixture(scope="session")
def app():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")

    from sqlalchemy import text

    from app.core.database import engine

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    # Importing the app builds the database structure from the migrations.
    from app.main import app as fastapi_app

    return fastapi_app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


_counter = {"n": 0}


@pytest.fixture()
def new_user(client):
    """Register a fresh user and return (auth headers, user)."""

    def make():
        _counter["n"] += 1
        email = f"user{_counter['n']}@example.com"
        password = "a-long-password"

        response = client.post(
            "/auth/register",
            json={"name": "Test", "email": email, "password": password},
        )
        assert response.status_code == 200, response.text

        login = client.post(
            "/auth/login",
            data={"username": email, "password": password},
        )
        assert login.status_code == 200, login.text

        token = login.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}, response.json()

    return make
