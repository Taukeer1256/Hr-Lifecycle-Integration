"""
Integration tests for audit trail functionality.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestAuditTrail:
    """Test that audit entries are created for every mutation."""

    async def test_joiner_creates_audit_entry(
        self, async_client: AsyncClient, admin_token: str
    ):
        payload = {
            "employee_id": "EMP100",
            "name": "Bob Jones",
            "email": "bob.jones@example.com",
            "department": "Finance",
            "job_title": "Analyst",
            "location": "New York",
            "start_date": "2024-03-01",
        }
        create_resp = await async_client.post(
            "/api/v1/employees",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert create_resp.status_code == 201

        audit_resp = await async_client.get(
            "/api/v1/admin/audit",
            params={"employee_id": "EMP100"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert audit_resp.status_code == 200
        audit_data = audit_resp.json()
        assert audit_data["total"] >= 1
        entry = audit_data["items"][0]
        assert entry["action"] == "CREATE"
        assert entry["actor"] == "admin"
        assert entry["before"] is None
        assert entry["after"] is not None

    async def test_mover_creates_audit_entry(
        self, async_client: AsyncClient, admin_token: str
    ):
        payload = {
            "employee_id": "EMP101",
            "name": "Carol White",
            "email": "carol@example.com",
            "department": "Engineering",
            "job_title": "Engineer",
            "location": "London",
            "start_date": "2024-01-01",
        }
        await async_client.post(
            "/api/v1/employees",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await async_client.post(
            "/api/v1/employees/EMP101/activate",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await async_client.patch(
            "/api/v1/employees/EMP101",
            json={"department": "Design"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        audit_resp = await async_client.get(
            "/api/v1/admin/audit",
            params={"employee_id": "EMP101"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert audit_resp.status_code == 200
        items = audit_resp.json()["items"]
        actions = [i["action"] for i in items]
        assert "UPDATE" in actions

    async def test_leaver_creates_audit_entry(
        self, async_client: AsyncClient, admin_token: str
    ):
        payload = {
            "employee_id": "EMP102",
            "name": "Dave Brown",
            "email": "dave@example.com",
            "department": "Legal",
            "job_title": "Lawyer",
            "location": "Chicago",
            "start_date": "2023-06-01",
        }
        await async_client.post(
            "/api/v1/employees",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await async_client.post(
            "/api/v1/employees/EMP102/terminate",
            json={"end_date": "2024-12-31"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        audit_resp = await async_client.get(
            "/api/v1/admin/audit",
            params={"employee_id": "EMP102"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        items = audit_resp.json()["items"]
        actions = [i["action"] for i in items]
        assert "STATUS_CHANGE" in actions

    async def test_audit_entry_has_before_after_diff(
        self, async_client: AsyncClient, admin_token: str
    ):
        payload = {
            "employee_id": "EMP103",
            "name": "Eve Green",
            "email": "eve@example.com",
            "department": "Engineering",
            "job_title": "Engineer",
            "location": "Paris",
            "start_date": "2024-01-01",
        }
        await async_client.post(
            "/api/v1/employees",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await async_client.post(
            "/api/v1/employees/EMP103/activate",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await async_client.patch(
            "/api/v1/employees/EMP103",
            json={"department": "Marketing"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        audit_resp = await async_client.get(
            "/api/v1/admin/audit",
            params={"employee_id": "EMP103"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        items = audit_resp.json()["items"]
        update_entries = [i for i in items if i["action"] == "UPDATE"]
        assert len(update_entries) >= 1
        entry = update_entries[0]
        assert "department" in entry["changed_fields"]
        assert entry["before"]["department"] == "Engineering"
        assert entry["after"]["department"] == "Marketing"

    async def test_audit_viewer_can_read(
        self, async_client: AsyncClient, viewer_token: str
    ):
        """hr_viewer can read audit logs."""
        response = await async_client.get(
            "/api/v1/admin/audit",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert response.status_code == 200

    async def test_audit_integration_admin_forbidden(
        self, async_client: AsyncClient, integration_token: str
    ):
        """integration_admin cannot read audit logs."""
        response = await async_client.get(
            "/api/v1/admin/audit",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert response.status_code == 403
