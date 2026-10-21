"""
Shared test fixtures and configuration.

Uses mongomock-motor for in-memory MongoDB to avoid requiring a real MongoDB
instance for tests. Provides FastAPI TestClient with pre-seeded users and
helper functions for authentication.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Set test environment BEFORE importing app modules
os.environ["MONGODB_URI"] = "mongodb://localhost:27017/test_hrdb"
os.environ["MONGODB_DB_NAME"] = "test_hrdb"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["WEBHOOK_HMAC_SECRET"] = "test-hmac-secret"
os.environ["OUTBOX_POLL_INTERVAL_SECONDS"] = "9999"  # Disable worker in tests
os.environ["MOCK_FAILURE_RATE"] = "0.0"  # No random failures in tests

import mongomock_motor

from app.main import app
from app.models.user import UserRole
from app.security.jwt_auth import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Event loop for async tests
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# In-memory MongoDB via mongomock_motor
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="function")
async def mock_db():
    """Provide an in-memory MongoDB database for each test."""
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test_hrdb"]

    # Patch get_db to return our mock db
    with patch("app.db._db", db), patch("app.db._client", client):
        yield db

    # Cleanup
    client.close()


# ---------------------------------------------------------------------------
# HTTP test client
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="function")
async def async_client(mock_db):
    """Async HTTP client with in-memory MongoDB."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Helper: create tokens for each role
# ---------------------------------------------------------------------------
def make_token(username: str, role: UserRole) -> str:
    token, _ = create_access_token(username, role)
    return token


@pytest.fixture
def admin_token() -> str:
    return make_token("admin", UserRole.hr_admin)


@pytest.fixture
def viewer_token() -> str:
    return make_token("test_viewer", UserRole.hr_viewer)


@pytest.fixture
def integration_token() -> str:
    return make_token("test_integration", UserRole.integration_admin)


# ---------------------------------------------------------------------------
# Helper: pre-seed a user into mock_db
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def seeded_admin(mock_db):
    """Insert an hr_admin user into the DB for login tests."""
    await mock_db.users.insert_one(
        {
            "_id": "admin-uuid",
            "username": "admin",
            "hashed_password": hash_password("Admin1234!"),
            "role": "hr_admin",
            "active": True,
            "created_at": __import__("datetime").datetime.utcnow(),
        }
    )
    return {"username": "admin", "password": "Admin1234!", "role": "hr_admin"}


# ---------------------------------------------------------------------------
# Helper: sample employee payload
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_employee_payload() -> dict:
    return {
        "employee_id": "EMP001",
        "name": "Alice Smith",
        "email": "alice.smith@example.com",
        "department": "Engineering",
        "job_title": "Software Engineer",
        "manager_id": None,
        "location": "London",
        "start_date": "2024-01-15",
    }
