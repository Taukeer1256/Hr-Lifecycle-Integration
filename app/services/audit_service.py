"""Audit log service – writes immutable entries to audit_log collection."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.audit import AuditDocument, AuditListResponse, AuditResponse

logger = logging.getLogger(__name__)


def _diff_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Return list of keys that changed between before and after."""
    all_keys = set(before.keys()) | set(after.keys())
    return [k for k in all_keys if before.get(k) != after.get(k)]


async def write_audit(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    *,
    collection: str,
    document_id: str,
    action: str,
    actor: str,
    actor_role: str,
    before: Optional[dict[str, Any]] = None,
    after: Optional[dict[str, Any]] = None,
    employee_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> None:
    """Insert an audit log entry."""
    changed_fields: list[str] = []
    if before is not None and after is not None:
        changed_fields = _diff_fields(before, after)

    entry = AuditDocument(
        collection=collection,
        document_id=document_id,
        employee_id=employee_id,
        action=action,
        actor=actor,
        actor_role=actor_role,
        before=before,
        after=after,
        changed_fields=changed_fields,
        correlation_id=correlation_id,
    )

    doc = entry.model_dump(by_alias=True)
    doc["_id"] = str(doc["_id"])
    await db.audit_log.insert_one(doc)
    logger.debug("Audit entry written: action=%s doc=%s", action, document_id)


async def list_audit(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    *,
    employee_id: Optional[str] = None,
    actor: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 20,
) -> AuditListResponse:
    """Query audit log with optional filters and pagination."""
    query: dict[str, Any] = {}
    if employee_id:
        query["employee_id"] = employee_id
    if actor:
        query["actor"] = actor
    if from_date or to_date:
        query["created_at"] = {}
        if from_date:
            query["created_at"]["$gte"] = from_date
        if to_date:
            query["created_at"]["$lte"] = to_date

    skip = (page - 1) * page_size
    total = await db.audit_log.count_documents(query)
    cursor = db.audit_log.find(query).sort("created_at", -1).skip(skip).limit(page_size)
    docs = await cursor.to_list(length=page_size)

    items = [
        AuditResponse(
            id=str(doc["_id"]),
            collection=doc["collection"],
            document_id=doc["document_id"],
            employee_id=doc.get("employee_id"),
            action=doc["action"],
            actor=doc["actor"],
            actor_role=doc["actor_role"],
            before=doc.get("before"),
            after=doc.get("after"),
            changed_fields=doc.get("changed_fields", []),
            correlation_id=doc.get("correlation_id"),
            created_at=doc["created_at"],
        )
        for doc in docs
    ]
    return AuditListResponse(total=total, page=page, page_size=page_size, items=items)
