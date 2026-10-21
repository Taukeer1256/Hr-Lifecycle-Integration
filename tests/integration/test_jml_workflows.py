"""
Integration tests for the full JML (Joiner/Mover/Leaver) workflow.

These tests use the FastAPI TestClient with an in-memory MongoDB mock
to test the complete request/response cycle including DB writes.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestJoinerFlow:
    """Test the employee creation (Joiner) workflow."""

    async def test_create_employee_success(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        response = await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["employee_id"] == "EMP001"
        assert data["employment_status"] == "pending"
        assert data["name"] == "Alice Smith"

    async def test_create_employee_duplicate_id(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        response = await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    async def test_create_employee_duplicate_email(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Different ID, same email
        payload2 = {**sample_employee_payload, "employee_id": "EMP002"}
        response = await async_client.post(
            "/api/v1/employees",
            json=payload2,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 409

    async def test_create_employee_viewer_forbidden(
        self, async_client: AsyncClient, viewer_token: str, sample_employee_payload: dict
    ):
        response = await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert response.status_code == 403

    async def test_create_employee_unauthenticated(
        self, async_client: AsyncClient, sample_employee_payload: dict
    ):
        response = await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
        )
        assert response.status_code == 401

    async def test_activate_employee(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        response = await async_client.post(
            "/api/v1/employees/EMP001/activate",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["employment_status"] == "active"


class TestMoverFlow:
    """Test the employee update (Mover) workflow."""

    async def _create_and_activate(
        self, async_client: AsyncClient, admin_token: str, payload: dict
    ):
        await async_client.post(
            "/api/v1/employees",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await async_client.post(
            f"/api/v1/employees/{payload['employee_id']}/activate",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    async def test_mover_department_change(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        await self._create_and_activate(async_client, admin_token, sample_employee_payload)
        response = await async_client.patch(
            "/api/v1/employees/EMP001",
            json={"department": "Product"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["department"] == "Product"

    async def test_mover_multiple_fields(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        await self._create_and_activate(async_client, admin_token, sample_employee_payload)
        response = await async_client.patch(
            "/api/v1/employees/EMP001",
            json={"department": "Design", "job_title": "Lead Designer", "location": "Berlin"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["department"] == "Design"
        assert data["job_title"] == "Lead Designer"
        assert data["location"] == "Berlin"

    async def test_mover_terminated_employee_fails(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Terminate directly from pending
        await async_client.post(
            "/api/v1/employees/EMP001/terminate",
            json={"end_date": "2024-12-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Try to move a terminated employee
        response = await async_client.patch(
            "/api/v1/employees/EMP001",
            json={"department": "HR"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 409
        assert "terminated" in response.json()["detail"].lower()

    async def test_mover_empty_update_fails(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        await self._create_and_activate(async_client, admin_token, sample_employee_payload)
        response = await async_client.patch(
            "/api/v1/employees/EMP001",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 422


class TestLeaverFlow:
    """Test the employee termination (Leaver) workflow."""

    async def test_terminate_employee(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        response = await async_client.post(
            "/api/v1/employees/EMP001/terminate",
            json={"end_date": "2024-12-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["employment_status"] == "terminated"

    async def test_terminate_already_terminated_fails(
        self, async_client: AsyncClient, admin_token: str, sample_employee_payload: dict
    ):
        await async_client.post(
            "/api/v1/employees",
            json=sample_employee_payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await async_client.post(
            "/api/v1/employees/EMP001/terminate",
            json={"end_date": "2024-12-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Try to terminate again
        response = await async_client.post(
            "/api/v1/employees/EMP001/terminate",
            json={"end_date": "2024-12-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 409

    async def test_terminate_nonexistent_employee(
        self, async_client: AsyncClient, admin_token: str
    ):
        response = await async_client.post(
            "/api/v1/employees/NONEXISTENT/terminate",
            json={"end_date": "2024-12-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404


class TestListEmployees:
    """Test employee listing and filtering."""

    async def test_list_employees_empty(
        self, async_client: AsyncClient, viewer_token: str
    ):
        response = await async_client.get(
            "/api/v1/employees",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_list_employees_with_data(
        self, async_client: AsyncClient, admin_token: str, viewer_token: str
    ):
        # Create employee
        await async_client.post(
            "/api/v1/employees",
            json={
                "employee_id": "EMP001",
                "name": "Alice",
                "email": "alice@example.com",
                "department": "Engineering",
                "job_title": "Engineer",
                "location": "London",
                "start_date": "2024-01-01",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        response = await async_client.get(
            "/api/v1/employees",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_integration_admin_cannot_list_employees(
        self, async_client: AsyncClient, integration_token: str
    ):
        response = await async_client.get(
            "/api/v1/employees",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert response.status_code == 403
