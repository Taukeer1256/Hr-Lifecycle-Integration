"""Integration tests for authentication and authorization."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestAuthentication:
    """Test JWT authentication flows."""

    async def test_login_success(
        self, async_client: AsyncClient, seeded_admin, mock_db
    ):
        resp = await async_client.post(
            "/api/v1/auth/token",
            json={"username": "admin", "password": "Admin1234!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "hr_admin"
        assert data["expires_in"] > 0

    async def test_login_wrong_password(
        self, async_client: AsyncClient, seeded_admin, mock_db
    ):
        resp = await async_client.post(
            "/api/v1/auth/token",
            json={"username": "admin", "password": "WrongPassword"},
        )
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, async_client: AsyncClient, mock_db):
        resp = await async_client.post(
            "/api/v1/auth/token",
            json={"username": "ghost", "password": "Password123"},
        )
        assert resp.status_code == 401

    async def test_get_me(
        self, async_client: AsyncClient, seeded_admin, admin_token: str, mock_db
    ):
        resp = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    async def test_unauthenticated_request_rejected(self, async_client: AsyncClient):
        resp = await async_client.get("/api/v1/employees")
        assert resp.status_code == 401

    async def test_invalid_token_rejected(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/v1/employees",
            headers={"Authorization": "Bearer totally.invalid.token"},
        )
        assert resp.status_code == 401


class TestRBAC:
    """Test role-based access control enforcement."""

    async def test_hr_viewer_cannot_create_employee(
        self, async_client: AsyncClient, viewer_token: str
    ):
        resp = await async_client.post(
            "/api/v1/employees",
            json={
                "employee_id": "EMP_RBAC",
                "name": "RBAC Test",
                "email": "rbac@example.com",
                "department": "Test",
                "job_title": "Test",
                "location": "Test",
                "start_date": "2024-01-01",
            },
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 403

    async def test_hr_viewer_can_list_employees(
        self, async_client: AsyncClient, viewer_token: str
    ):
        resp = await async_client.get(
            "/api/v1/employees",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 200

    async def test_integration_admin_can_manage_outbox(
        self, async_client: AsyncClient, integration_token: str
    ):
        resp = await async_client.get(
            "/api/v1/admin/outbox",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert resp.status_code == 200

    async def test_hr_viewer_cannot_access_outbox(
        self, async_client: AsyncClient, viewer_token: str
    ):
        resp = await async_client.get(
            "/api/v1/admin/outbox",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 403

    async def test_integration_admin_cannot_create_employee(
        self, async_client: AsyncClient, integration_token: str
    ):
        resp = await async_client.post(
            "/api/v1/employees",
            json={
                "employee_id": "EMP_INTG",
                "name": "Integration Admin Test",
                "email": "intg@example.com",
                "department": "Test",
                "job_title": "Test",
                "location": "Test",
                "start_date": "2024-01-01",
            },
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert resp.status_code == 403

    async def test_hr_admin_can_create_user(
        self, async_client: AsyncClient, admin_token: str, mock_db
    ):
        resp = await async_client.post(
            "/api/v1/auth/users",
            json={"username": "newuser", "password": "NewPass123!", "role": "hr_viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201

    async def test_hr_viewer_cannot_create_user(
        self, async_client: AsyncClient, viewer_token: str
    ):
        resp = await async_client.post(
            "/api/v1/auth/users",
            json={"username": "newuser2", "password": "NewPass123!", "role": "hr_viewer"},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 403


class TestHealthEndpoints:
    """Test health and readiness endpoints."""

    async def test_health_endpoint(self, async_client: AsyncClient):
        resp = await async_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_root_endpoint(self, async_client: AsyncClient):
        resp = await async_client.get("/")
        assert resp.status_code == 200
        assert "HR Lifecycle" in resp.json()["service"]

    async def test_ready_endpoint(self, async_client: AsyncClient, mock_db):
        resp = await async_client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"


class TestAuthEdgeCases:
    async def test_disabled_user_login(self, async_client: AsyncClient, mock_db):
        from app.security.jwt_auth import hash_password
        await mock_db.users.insert_one({
            "_id": "disabled-id",
            "username": "disabled_user",
            "hashed_password": hash_password("Pass123!"),
            "role": "hr_viewer",
            "active": False,
        })
        resp = await async_client.post(
            "/api/v1/auth/token",
            json={"username": "disabled_user", "password": "Pass123!"},
        )
        assert resp.status_code == 403

    async def test_create_duplicate_user_conflict(
        self, async_client: AsyncClient, admin_token: str
    ):
        await async_client.post(
            "/api/v1/auth/users",
            json={"username": "dupuser", "password": "Password123!", "role": "hr_viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = await async_client.post(
            "/api/v1/auth/users",
            json={"username": "dupuser", "password": "Password123!", "role": "hr_viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

