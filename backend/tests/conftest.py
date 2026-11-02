"""Tests use a newly-created, isolated Postgres database, never the app DB."""
import os
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
admin_url = os.environ.get("TEST_POSTGRES_ADMIN_URL", "postgresql://postgres@127.0.0.1:54321/postgres")
database_name = "flowsentry_test_" + uuid.uuid4().hex
with psycopg.connect(admin_url, autocommit=True) as conn:
    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
from urllib.parse import urlsplit, urlunsplit
parts = urlsplit(admin_url)
test_url = urlunsplit(parts._replace(path="/" + database_name))
os.environ.update(DATABASE_URL=test_url, APP_ENV="test", WORKER_ENABLED="false",
    APP_SECRET_KEY="test-only-signing-key-32-characters", ENCRYPTION_KEY="ab" * 32)
from app.core import config, db
config.settings.database_url = test_url
config.settings.worker_enabled = False
from app.main import _init_database, create_app
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def database():
    assert _init_database()
    yield
    db.get_engine().dispose()
    # Only remove the exact random database this test process created.
    assert database_name.startswith("flowsentry_test_") and len(database_name) == len("flowsentry_test_") + 32
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))


@pytest.fixture
def client(database):
    # No lifespan worker/tail thread; tests call worker steps explicitly.
    with TestClient(create_app(), raise_server_exceptions=True) as value:
        yield value


@pytest.fixture
def owner(client):
    config.settings.registration_mode = "open"
    email = f"{uuid.uuid4().hex}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "local-test-password-123"})
    assert r.status_code == 201, r.text
    headers = {"X-CSRF-Token": client.cookies["flowsentry_csrf"]}
    r = client.post("/workspaces", json={"name": "Regression workspace"}, headers=headers)
    assert r.status_code == 201, r.text
    return {"workspace_id": r.json()["data"]["id"]}, headers
