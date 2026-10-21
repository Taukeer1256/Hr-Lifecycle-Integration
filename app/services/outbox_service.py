"""Outbox service – manages outbox records and delivers events to webhooks."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.event import EventType
from app.models.outbox import OutboxDocument, OutboxListResponse, OutboxResponse, OutboxStatus

logger = logging.getLogger(__name__)


async def create_outbox_entries(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    *,
    event_id: str,
    event_type: EventType,
    employee_id: str,
    payload: dict[str, Any],
    correlation_id: Optional[str] = None,
    max_retries: int = 5,
) -> list[str]:
    """
    Find all active subscriptions for the event type and insert an outbox entry
    for each one. Returns list of inserted outbox document IDs.
    """
    # Find matching active subscriptions
    cursor = db.webhook_subscriptions.find(
        {"event_types": event_type.value, "active": True}
    )
    subscriptions = await cursor.to_list(length=None)

    if not subscriptions:
        logger.debug(
            "No active subscriptions for event_type=%s, skipping outbox insert.",
            event_type,
        )
        return []

    inserted_ids: list[str] = []
    for sub in subscriptions:
        sub_id = str(sub["_id"])
        idempotency_key = f"{event_id}:{sub_id}"

        # Check for duplicate (idempotency guard)
        existing = await db.outbox.find_one({"idempotency_key": idempotency_key})
        if existing:
            logger.warning(
                "Duplicate outbox entry skipped: idempotency_key=%s", idempotency_key
            )
            continue

        entry = OutboxDocument(
            idempotency_key=idempotency_key,
            event_id=event_id,
            event_type=event_type,
            employee_id=employee_id,
            payload=payload,
            subscription_id=sub_id,
            target_url=sub["target_url"],
            max_retries=max_retries,
            correlation_id=correlation_id,
        )
        doc = entry.model_dump(by_alias=True)
        doc["_id"] = str(doc["_id"])
        await db.outbox.insert_one(doc)
        inserted_ids.append(doc["_id"])
        logger.info(
            "Outbox entry created: id=%s target=%s event_type=%s",
            doc["_id"],
            sub["target_url"],
            event_type,
        )
    return inserted_ids


async def get_pending_outbox(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    batch_size: int = 50,
) -> list[dict[str, Any]]:
    """Fetch pending outbox entries that are due for delivery."""
    now = datetime.utcnow()
    cursor = db.outbox.find(
        {
            "status": {"$in": [OutboxStatus.pending, OutboxStatus.failed]},
            "next_attempt_at": {"$lte": now},
        }
    ).sort("next_attempt_at", 1).limit(batch_size)
    return await cursor.to_list(length=batch_size)


async def mark_delivered(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    outbox_id: str,
) -> None:
    await db.outbox.update_one(
        {"_id": outbox_id},
        {
            "$set": {
                "status": OutboxStatus.delivered,
                "delivered_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        },
    )


async def mark_failed(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    outbox_id: str,
    error: str,
    next_attempt_at: datetime,
    dead_letter: bool = False,
) -> None:
    new_status = OutboxStatus.dead_letter if dead_letter else OutboxStatus.failed
    await db.outbox.update_one(
        {"_id": outbox_id},
        {
            "$set": {
                "status": new_status,
                "last_error": error,
                "next_attempt_at": next_attempt_at,
                "updated_at": datetime.utcnow(),
            },
            "$inc": {"retry_count": 1},
        },
    )


async def reset_for_retry(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    outbox_id: str,
) -> bool:
    """Reset a dead-lettered or failed entry for immediate retry. Returns True if found."""
    result = await db.outbox.update_one(
        {"_id": outbox_id, "status": {"$in": [OutboxStatus.dead_letter, OutboxStatus.failed]}},
        {
            "$set": {
                "status": OutboxStatus.pending,
                "next_attempt_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "last_error": None,
            }
        },
    )
    return result.modified_count > 0


async def reset_all_dead_letters(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
) -> int:
    """Reset ALL dead-lettered entries for retry. Returns count modified."""
    result = await db.outbox.update_many(
        {"status": OutboxStatus.dead_letter},
        {
            "$set": {
                "status": OutboxStatus.pending,
                "next_attempt_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "last_error": None,
            }
        },
    )
    return result.modified_count


async def list_outbox(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    *,
    status: Optional[OutboxStatus] = None,
    employee_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> OutboxListResponse:
    query: dict[str, Any] = {}
    if status:
        query["status"] = status
    if employee_id:
        query["employee_id"] = employee_id

    skip = (page - 1) * page_size
    total = await db.outbox.count_documents(query)
    cursor = db.outbox.find(query).sort("created_at", -1).skip(skip).limit(page_size)
    docs = await cursor.to_list(length=page_size)

    items = [_doc_to_response(d) for d in docs]
    return OutboxListResponse(total=total, page=page, page_size=page_size, items=items)


def _doc_to_response(doc: dict[str, Any]) -> OutboxResponse:
    return OutboxResponse(
        id=str(doc["_id"]),
        idempotency_key=doc["idempotency_key"],
        event_id=doc["event_id"],
        event_type=doc["event_type"],
        employee_id=doc["employee_id"],
        subscription_id=doc["subscription_id"],
        target_url=doc["target_url"],
        status=doc["status"],
        retry_count=doc["retry_count"],
        max_retries=doc["max_retries"],
        next_attempt_at=doc["next_attempt_at"],
        last_error=doc.get("last_error"),
        delivered_at=doc.get("delivered_at"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )
