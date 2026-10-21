"""JML (Joiner/Mover/Leaver) workflow service."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.employee import (
    EmployeeCreate,
    EmployeeTerminate,
    EmployeeUpdate,
    EmploymentStatus,
)
from app.models.event import EventType
from app.services.audit_service import write_audit
from app.services.employee_service import (
    _clean_for_audit,
    change_status,
    create_employee,
    update_employee,
)
from app.services.outbox_service import create_outbox_entries

logger = logging.getLogger(__name__)


def _build_event_payload(
    event_type: EventType,
    employee_doc: dict[str, Any],
    before: Optional[dict[str, Any]] = None,
    after: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the event payload sent to webhooks."""
    payload: dict[str, Any] = {
        "event_type": event_type.value,
        "employee_id": employee_doc["employee_id"],
        "employee_name": employee_doc["name"],
        "department": employee_doc["department"],
        "job_title": employee_doc["job_title"],
        "employment_status": employee_doc["employment_status"],
        "timestamp": datetime.utcnow().isoformat(),
    }
    if before and after:
        diff: dict[str, Any] = {}
        for key in set(before.keys()) | set(after.keys()):
            if key in ("_id", "updated_at", "created_at"):
                continue
            bval = before.get(key)
            aval = after.get(key)
            if bval != aval:
                diff[key] = {"before": bval, "after": aval}
        payload["diff"] = diff
    return payload


async def joiner_workflow(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    data: EmployeeCreate,
    actor: str,
    actor_role: str,
    correlation_id: Optional[str] = None,
    max_retries: int = 5,
) -> dict[str, Any]:
    """
    Joiner: Create employee with status=pending, emit employee.joined event.
    """
    after_doc, _ = await create_employee(db, data)

    event_id = str(uuid4())
    payload = _build_event_payload(EventType.employee_joined, after_doc)
    payload["start_date"] = (
        after_doc["start_date"].isoformat()
        if hasattr(after_doc["start_date"], "isoformat")
        else str(after_doc["start_date"])
    )

    # Write event to events collection
    await db.events.insert_one(
        {
            "_id": event_id,
            "event_type": EventType.employee_joined.value,
            "employee_id": data.employee_id,
            "payload": payload,
            "created_at": datetime.utcnow(),
            "correlation_id": correlation_id,
        }
    )

    # Write outbox entries (transactional pattern: same request, same op)
    await create_outbox_entries(
        db,
        event_id=event_id,
        event_type=EventType.employee_joined,
        employee_id=data.employee_id,
        payload=payload,
        correlation_id=correlation_id,
        max_retries=max_retries,
    )

    # Audit
    await write_audit(
        db,
        collection="employees",
        document_id=data.employee_id,
        action="CREATE",
        actor=actor,
        actor_role=actor_role,
        before=None,
        after=_clean_for_audit(after_doc),
        employee_id=data.employee_id,
        correlation_id=correlation_id,
    )

    logger.info("Joiner workflow complete for employee_id=%s", data.employee_id)
    return after_doc


async def mover_workflow(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    employee_id: str,
    data: EmployeeUpdate,
    actor: str,
    actor_role: str,
    correlation_id: Optional[str] = None,
    max_retries: int = 5,
) -> dict[str, Any]:
    """
    Mover: Update employee fields, emit employee.moved with before/after diff.
    """
    updates = data.model_dump(exclude_none=True)
    if "email" in updates:
        updates["email"] = str(updates["email"])
    after_doc, before_doc = await update_employee(db, employee_id, updates)

    event_id = str(uuid4())
    payload = _build_event_payload(
        EventType.employee_moved, after_doc, before=before_doc, after=after_doc
    )

    await db.events.insert_one(
        {
            "_id": event_id,
            "event_type": EventType.employee_moved.value,
            "employee_id": employee_id,
            "payload": payload,
            "created_at": datetime.utcnow(),
            "correlation_id": correlation_id,
        }
    )

    await create_outbox_entries(
        db,
        event_id=event_id,
        event_type=EventType.employee_moved,
        employee_id=employee_id,
        payload=payload,
        correlation_id=correlation_id,
        max_retries=max_retries,
    )

    await write_audit(
        db,
        collection="employees",
        document_id=employee_id,
        action="UPDATE",
        actor=actor,
        actor_role=actor_role,
        before=_clean_for_audit(before_doc),
        after=_clean_for_audit(after_doc),
        employee_id=employee_id,
        correlation_id=correlation_id,
    )

    logger.info("Mover workflow complete for employee_id=%s", employee_id)
    return after_doc


async def leaver_workflow(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    employee_id: str,
    data: EmployeeTerminate,
    actor: str,
    actor_role: str,
    correlation_id: Optional[str] = None,
    max_retries: int = 5,
) -> dict[str, Any]:
    """
    Leaver: Set terminated + end_date, emit employee.left event.
    """
    extra: dict[str, Any] = {
        "end_date": datetime.combine(data.end_date, datetime.min.time())
    }
    after_doc, before_doc = await change_status(
        db, employee_id, EmploymentStatus.terminated, extra_updates=extra
    )

    event_id = str(uuid4())
    payload = _build_event_payload(
        EventType.employee_left, after_doc, before=before_doc, after=after_doc
    )
    payload["end_date"] = (
        after_doc["end_date"].isoformat()
        if hasattr(after_doc.get("end_date"), "isoformat")
        else str(after_doc.get("end_date"))
    )

    await db.events.insert_one(
        {
            "_id": event_id,
            "event_type": EventType.employee_left.value,
            "employee_id": employee_id,
            "payload": payload,
            "created_at": datetime.utcnow(),
            "correlation_id": correlation_id,
        }
    )

    await create_outbox_entries(
        db,
        event_id=event_id,
        event_type=EventType.employee_left,
        employee_id=employee_id,
        payload=payload,
        correlation_id=correlation_id,
        max_retries=max_retries,
    )

    await write_audit(
        db,
        collection="employees",
        document_id=employee_id,
        action="STATUS_CHANGE",
        actor=actor,
        actor_role=actor_role,
        before=_clean_for_audit(before_doc),
        after=_clean_for_audit(after_doc),
        employee_id=employee_id,
        correlation_id=correlation_id,
    )

    logger.info("Leaver workflow complete for employee_id=%s", employee_id)
    return after_doc


async def activate_employee(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    employee_id: str,
    actor: str,
    actor_role: str,
    correlation_id: Optional[str] = None,
    max_retries: int = 5,
) -> dict[str, Any]:
    """Activate a pending employee (status: pending -> active)."""
    after_doc, before_doc = await change_status(
        db, employee_id, EmploymentStatus.active
    )

    event_id = str(uuid4())
    payload = _build_event_payload(
        EventType.employee_status_changed, after_doc, before=before_doc, after=after_doc
    )

    await db.events.insert_one(
        {
            "_id": event_id,
            "event_type": EventType.employee_status_changed.value,
            "employee_id": employee_id,
            "payload": payload,
            "created_at": datetime.utcnow(),
            "correlation_id": correlation_id,
        }
    )

    await create_outbox_entries(
        db,
        event_id=event_id,
        event_type=EventType.employee_status_changed,
        employee_id=employee_id,
        payload=payload,
        correlation_id=correlation_id,
        max_retries=max_retries,
    )

    await write_audit(
        db,
        collection="employees",
        document_id=employee_id,
        action="STATUS_CHANGE",
        actor=actor,
        actor_role=actor_role,
        before=_clean_for_audit(before_doc),
        after=_clean_for_audit(after_doc),
        employee_id=employee_id,
        correlation_id=correlation_id,
    )

    logger.info("Employee activated: employee_id=%s", employee_id)
    return after_doc
