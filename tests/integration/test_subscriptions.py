"""Integration tests for webhook subscriptions."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestWebhookSubscriptions:
    """Test webhook subscription CRUD operations."""

    async def test_create_subscription(
        self, async_client: AsyncClient, integration_token: str
    ):
        resp = await async_client.post(
            "/api/v1/subscriptions",
            json={
                "target_url": "http://mock:9000/webhook/payroll",
                "event_types": ["employee.joined", "employee.left"],
                "description": "Payroll subscription",
            },
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["active"] is True
        assert "employee.joined" in data["event_types"]

    async def test_list_subscriptions(
        self, async_client: AsyncClient, integration_token: str
    ):
        # Create one
        await async_client.post(
            "/api/v1/subscriptions",
            json={
                "target_url": "http://mock:9000/webhook/it-access",
                "event_types": ["employee.moved"],
            },
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        resp = await async_client.get(
            "/api/v1/subscriptions",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_update_subscription(
        self, async_client: AsyncClient, integration_token: str
    ):
        create_resp = await async_client.post(
            "/api/v1/subscriptions",
            json={
                "target_url": "http://mock:9000/webhook/payroll",
                "event_types": ["employee.joined"],
            },
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        sub_id = create_resp.json()["id"]

        update_resp = await async_client.patch(
            f"/api/v1/subscriptions/{sub_id}",
            json={"active": False},
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["active"] is False

    async def test_delete_subscription(
        self, async_client: AsyncClient, integration_token: str
    ):
        create_resp = await async_client.post(
            "/api/v1/subscriptions",
            json={
                "target_url": "http://mock:9000/webhook/payroll",
                "event_types": ["employee.left"],
            },
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        sub_id = create_resp.json()["id"]

        del_resp = await async_client.delete(
            f"/api/v1/subscriptions/{sub_id}",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert del_resp.status_code == 204

        get_resp = await async_client.get(
            f"/api/v1/subscriptions/{sub_id}",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert get_resp.status_code == 404

    async def test_hr_viewer_cannot_manage_subscriptions(
        self, async_client: AsyncClient, viewer_token: str
    ):
        resp = await async_client.get(
            "/api/v1/subscriptions",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 403

    async def test_disabled_subscription_skipped_for_outbox(
        self, async_client: AsyncClient, admin_token: str, integration_token: str, mock_db
    ):
        """A disabled subscription should not receive outbox entries."""
        create_resp = await async_client.post(
            "/api/v1/subscriptions",
            json={
                "target_url": "http://mock:9000/webhook/payroll",
                "event_types": ["employee.joined"],
            },
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        sub_id = create_resp.json()["id"]

        # Disable the subscription
        await async_client.patch(
            f"/api/v1/subscriptions/{sub_id}",
            json={"active": False},
            headers={"Authorization": f"Bearer {integration_token}"},
        )

        # Create employee (should not create outbox entry for disabled sub)
        await async_client.post(
            "/api/v1/employees",
            json={
                "employee_id": "EMP_DISABLED_SUB",
                "name": "Disabled Sub Test",
                "email": "disabled.sub@example.com",
                "department": "Test",
                "job_title": "Test",
                "location": "Test",
                "start_date": "2024-01-01",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        # No outbox entry should be created for the disabled sub
        count = await mock_db.outbox.count_documents({"subscription_id": sub_id})
        assert count == 0
