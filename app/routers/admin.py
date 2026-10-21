"""Admin router – outbox management, retry, audit trail."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.models.audit import AuditListResponse
from app.models.outbox import OutboxListResponse, OutboxResponse, OutboxStatus
from app.models.user import CurrentUser
from app.security.rbac import require_hr_admin_or_viewer, require_integration_admin
from app.services.audit_service import list_audit
from app.services.outbox_service import (
    list_outbox,
    reset_all_dead_letters,
    reset_for_retry,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Outbox Management ────────────────────────────────────────────────────────
@router.get(
    "/outbox",
    response_model=OutboxListResponse,
    summary="List outbox events (with status filter)",
)
async def list_outbox_events(
    status: Optional[OutboxStatus] = None,
    employee_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    _user: CurrentUser = Depends(require_integration_admin),
) -> OutboxListResponse:
    return await list_outbox(
        db, status=status, employee_id=employee_id, page=page, page_size=page_size
    )


@router.post(
    "/outbox/{outbox_id}/retry",
    response_model=OutboxResponse,
    summary="Manually retry a failed or dead-lettered outbox event",
)
async def retry_outbox_event(
    outbox_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    _user: CurrentUser = Depends(require_integration_admin),
) -> OutboxResponse:
    success = await reset_for_retry(db, outbox_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outbox event '{outbox_id}' not found or not in a retryable state.",
        )
    doc = await db.outbox.find_one({"_id": outbox_id})
    return _outbox_doc_to_response(doc)  # type: ignore[arg-type]


@router.post(
    "/outbox/retry-all-dead-letters",
    summary="Retry ALL dead-lettered outbox events",
)
async def retry_all_dead_letters(
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    _user: CurrentUser = Depends(require_integration_admin),
) -> dict:
    count = await reset_all_dead_letters(db)
    logger.info("Queued %d dead-lettered events for retry.", count)
    return {"queued_for_retry": count}


# ── Audit Trail ───────────────────────────────────────────────────────────────
@router.get(
    "/audit",
    response_model=AuditListResponse,
    summary="Query immutable audit log",
)
async def get_audit_log(
    employee_id: Optional[str] = None,
    actor: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    _user: CurrentUser = Depends(require_hr_admin_or_viewer),
) -> AuditListResponse:
    return await list_audit(
        db,
        employee_id=employee_id,
        actor=actor,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )


def _outbox_doc_to_response(doc: dict) -> OutboxResponse:
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
