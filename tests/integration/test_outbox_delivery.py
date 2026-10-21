"""
Integration tests for outbox delivery, retry logic, and dead-letter handling.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient

from app.models.outbox import OutboxStatus
from app.services.outbox_service import (
    create_outbox_entries,
    reset_all_dead_letters,
    reset_for_retry,
)
from app.workers.outbox_worker import deliver_event

pytestmark = pytest.mark.asyncio


class TestOutboxCreation:
    """Test outbox entry creation when events are emitted."""

    async def test_joiner_creates_outbox_entry(
        self, async_client: AsyncClient, admin_token: str, mock_db
    ):
        # First create a subscription
        from app.models.event import EventType
        await mock_db.webhook_subscriptions.insert_one(
            {
                "_id": "sub-001",
                "target_url": "http://mock:9000/webhook/payroll",
                "event_types": [EventType.employee_joined.value],
                "active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

        payload = {
            "employee_id": "EMP_OUT_001",
            "name": "Outbox Test",
            "email": "outbox.test@example.com",
            "department": "Test",
            "job_title": "Tester",
            "location": "Test City",
            "start_date": "2024-01-01",
        }
        resp = await async_client.post(
            "/api/v1/employees",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201

        # Verify outbox entry was created
        outbox_doc = await mock_db.outbox.find_one({"employee_id": "EMP_OUT_001"})
        assert outbox_doc is not None
        assert outbox_doc["status"] == OutboxStatus.pending
        assert outbox_doc["event_type"] == "employee.joined"

    async def test_idempotency_prevents_duplicate_outbox(self, mock_db):
        """Same event_id + subscription_id should not create duplicate outbox entries."""
        from app.models.event import EventType
        await mock_db.webhook_subscriptions.insert_one(
            {
                "_id": "sub-002",
                "target_url": "http://mock:9000/webhook/payroll",
                "event_types": [EventType.employee_joined.value],
                "active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

        payload = {"event": "employee.joined", "employee_id": "EMP001"}
        # Create first entry
        ids1 = await create_outbox_entries(
            mock_db,
            event_id="test-event-id",
            event_type=EventType.employee_joined,
            employee_id="EMP001",
            payload=payload,
        )
        # Try to create duplicate
        ids2 = await create_outbox_entries(
            mock_db,
            event_id="test-event-id",  # Same event_id
            event_type=EventType.employee_joined,
            employee_id="EMP001",
            payload=payload,
        )
        assert len(ids1) == 1
        assert len(ids2) == 0  # Duplicate was rejected

    async def test_no_subscription_no_outbox(self, mock_db):
        """Events with no active subscriptions should not create outbox entries."""
        from app.models.event import EventType
        ids = await create_outbox_entries(
            mock_db,
            event_id="test-event-no-sub",
            event_type=EventType.employee_joined,
            employee_id="EMP001",
            payload={"event": "test"},
        )
        assert ids == []


class TestOutboxDelivery:
    """Test outbox delivery and retry mechanics."""

    async def test_successful_delivery_marks_delivered(self, mock_db):
        """A successful HTTP 200 response marks the outbox entry as delivered."""
        from app.config import get_settings
        from app.models.event import EventType

        # Insert outbox entry
        await mock_db.outbox.insert_one(
            {
                "_id": "outbox-deliver-001",
                "idempotency_key": "event-001:sub-001",
                "event_id": "event-001",
                "event_type": EventType.employee_joined.value,
                "employee_id": "EMP001",
                "payload": {"event": "employee.joined"},
                "subscription_id": "sub-001",
                "target_url": "http://mock:9000/webhook/payroll",
                "status": OutboxStatus.pending,
                "retry_count": 0,
                "max_retries": 5,
                "next_attempt_at": datetime.utcnow(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

        # Mock the HTTP client to return 200
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.db._db", mock_db):
            await deliver_event(mock_client, await mock_db.outbox.find_one({"_id": "outbox-deliver-001"}), get_settings())

        doc = await mock_db.outbox.find_one({"_id": "outbox-deliver-001"})
        assert doc["status"] == OutboxStatus.delivered
        assert doc["delivered_at"] is not None

    async def test_failed_delivery_increments_retry(self, mock_db):
        """HTTP 503 response increments retry count and marks as failed."""
        from app.config import get_settings
        from app.models.event import EventType

        await mock_db.outbox.insert_one(
            {
                "_id": "outbox-retry-001",
                "idempotency_key": "event-002:sub-001",
                "event_id": "event-002",
                "event_type": EventType.employee_joined.value,
                "employee_id": "EMP001",
                "payload": {"event": "employee.joined"},
                "subscription_id": "sub-001",
                "target_url": "http://mock:9000/webhook/payroll",
                "status": OutboxStatus.pending,
                "retry_count": 0,
                "max_retries": 5,
                "next_attempt_at": datetime.utcnow(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.db._db", mock_db):
            await deliver_event(
                mock_client,
                await mock_db.outbox.find_one({"_id": "outbox-retry-001"}),
                get_settings(),
            )

        doc = await mock_db.outbox.find_one({"_id": "outbox-retry-001"})
        assert doc["status"] == OutboxStatus.failed
        assert doc["retry_count"] == 1
        assert doc["last_error"] is not None

    async def test_max_retries_dead_letters(self, mock_db):
        """After max retries, outbox entry becomes dead_letter."""
        from app.config import get_settings
        from app.models.event import EventType

        await mock_db.outbox.insert_one(
            {
                "_id": "outbox-dead-001",
                "idempotency_key": "event-003:sub-001",
                "event_id": "event-003",
                "event_type": EventType.employee_joined.value,
                "employee_id": "EMP001",
                "payload": {"event": "employee.joined"},
                "subscription_id": "sub-001",
                "target_url": "http://mock:9000/webhook/payroll",
                "status": OutboxStatus.pending,
                "retry_count": 4,  # One more will be max (5)
                "max_retries": 5,
                "next_attempt_at": datetime.utcnow(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.db._db", mock_db):
            await deliver_event(
                mock_client,
                await mock_db.outbox.find_one({"_id": "outbox-dead-001"}),
                get_settings(),
            )

        doc = await mock_db.outbox.find_one({"_id": "outbox-dead-001"})
        assert doc["status"] == OutboxStatus.dead_letter

    async def test_manual_retry_resets_dead_letter(self, mock_db):
        """Manual retry resets dead_letter back to pending."""
        await mock_db.outbox.insert_one(
            {
                "_id": "outbox-manual-retry-001",
                "idempotency_key": "event-004:sub-001",
                "event_id": "event-004",
                "event_type": "employee.joined",
                "employee_id": "EMP001",
                "payload": {},
                "subscription_id": "sub-001",
                "target_url": "http://mock:9000/webhook/payroll",
                "status": OutboxStatus.dead_letter,
                "retry_count": 5,
                "max_retries": 5,
                "next_attempt_at": datetime.utcnow() - timedelta(hours=1),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

        success = await reset_for_retry(mock_db, "outbox-manual-retry-001")
        assert success is True

        doc = await mock_db.outbox.find_one({"_id": "outbox-manual-retry-001"})
        assert doc["status"] == OutboxStatus.pending

    async def test_retry_all_dead_letters(self, mock_db):
        """reset_all_dead_letters resets all dead-lettered entries."""
        for i in range(3):
            await mock_db.outbox.insert_one(
                {
                    "_id": f"outbox-dl-{i}",
                    "idempotency_key": f"event-dl-{i}:sub-001",
                    "event_id": f"event-dl-{i}",
                    "event_type": "employee.joined",
                    "employee_id": f"EMP00{i}",
                    "payload": {},
                    "subscription_id": "sub-001",
                    "target_url": "http://mock:9000/webhook/payroll",
                    "status": OutboxStatus.dead_letter,
                    "retry_count": 5,
                    "max_retries": 5,
                    "next_attempt_at": datetime.utcnow(),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }
            )

        count = await reset_all_dead_letters(mock_db)
        assert count == 3

    async def test_network_error_marks_failed(self, mock_db):
        """Network errors should mark the entry as failed."""
        from app.config import get_settings
        from app.models.event import EventType

        await mock_db.outbox.insert_one(
            {
                "_id": "outbox-network-001",
                "idempotency_key": "event-005:sub-001",
                "event_id": "event-005",
                "event_type": EventType.employee_joined.value,
                "employee_id": "EMP001",
                "payload": {"event": "employee.joined"},
                "subscription_id": "sub-001",
                "target_url": "http://unreachable:9999/webhook",
                "status": OutboxStatus.pending,
                "retry_count": 0,
                "max_retries": 5,
                "next_attempt_at": datetime.utcnow(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch("app.db._db", mock_db):
            await deliver_event(
                mock_client,
                await mock_db.outbox.find_one({"_id": "outbox-network-001"}),
                get_settings(),
            )

        doc = await mock_db.outbox.find_one({"_id": "outbox-network-001"})
        assert doc["status"] == OutboxStatus.failed


class TestAdminOutboxEndpoints:
    """Test admin outbox management API endpoints."""

    async def test_list_outbox_events(
        self, async_client: AsyncClient, integration_token: str, mock_db
    ):
        await mock_db.outbox.insert_one(
            {
                "_id": "outbox-list-001",
                "idempotency_key": "e1:s1",
                "event_id": "e1",
                "event_type": "employee.joined",
                "employee_id": "EMP001",
                "payload": {},
                "subscription_id": "s1",
                "target_url": "http://mock:9000",
                "status": OutboxStatus.pending,
                "retry_count": 0,
                "max_retries": 5,
                "next_attempt_at": datetime.utcnow(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )
        resp = await async_client.get(
            "/api/v1/admin/outbox",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_manual_retry_endpoint(
        self, async_client: AsyncClient, integration_token: str, mock_db
    ):
        await mock_db.outbox.insert_one(
            {
                "_id": "outbox-retry-ep-001",
                "idempotency_key": "e2:s2",
                "event_id": "e2",
                "event_type": "employee.joined",
                "employee_id": "EMP001",
                "payload": {},
                "subscription_id": "s2",
                "target_url": "http://mock:9000",
                "status": OutboxStatus.dead_letter,
                "retry_count": 5,
                "max_retries": 5,
                "next_attempt_at": datetime.utcnow(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "last_error": "prev error",
            }
        )
        resp = await async_client.post(
            "/api/v1/admin/outbox/outbox-retry-ep-001/retry",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    async def test_retry_nonexistent_fails(
        self, async_client: AsyncClient, integration_token: str
    ):
        resp = await async_client.post(
            "/api/v1/admin/outbox/nonexistent-id/retry",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert resp.status_code == 404

    async def test_retry_all_dead_letters_endpoint(
        self, async_client: AsyncClient, integration_token: str, mock_db
    ):
        for i in range(2):
            await mock_db.outbox.insert_one(
                {
                    "_id": f"outbox-dl-ep-{i}",
                    "idempotency_key": f"e-dl-{i}:s1",
                    "event_id": f"e-dl-{i}",
                    "event_type": "employee.joined",
                    "employee_id": f"EMP00{i}",
                    "payload": {},
                    "subscription_id": "s1",
                    "target_url": "http://mock:9000",
                    "status": OutboxStatus.dead_letter,
                    "retry_count": 5,
                    "max_retries": 5,
                    "next_attempt_at": datetime.utcnow(),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }
            )
        resp = await async_client.post(
            "/api/v1/admin/outbox/retry-all-dead-letters",
            headers={"Authorization": f"Bearer {integration_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["queued_for_retry"] == 2
