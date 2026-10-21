"""Events router – event listing and webhook subscriptions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.models.event import (
    EventResponse,
    EventType,
    WebhookSubscriptionCreate,
    WebhookSubscriptionDocument,
    WebhookSubscriptionResponse,
    WebhookSubscriptionUpdate,
)
from app.models.user import CurrentUser
from app.security.rbac import (
    require_hr_admin_or_viewer,
    require_integration_admin,
)
from app.services.audit_service import write_audit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Events & Subscriptions"])


# ── Events list ─────────────────────────────────────────────────────────────
@router.get("/events", response_model=list[EventResponse], summary="List events")
async def list_events(
    event_type: Optional[EventType] = None,
    employee_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    _user: CurrentUser = Depends(require_hr_admin_or_viewer),
) -> list[EventResponse]:
    query: dict = {}
    if event_type:
        query["event_type"] = event_type.value
    if employee_id:
        query["employee_id"] = employee_id
    skip = (page - 1) * page_size
    cursor = db.events.find(query).sort("created_at", -1).skip(skip).limit(page_size)
    docs = await cursor.to_list(length=page_size)
    return [
        EventResponse(
            id=str(d["_id"]),
            event_type=d["event_type"],
            employee_id=d["employee_id"],
            payload=d["payload"],
            created_at=d["created_at"],
            correlation_id=d.get("correlation_id"),
        )
        for d in docs
    ]


# ── Webhook Subscriptions ────────────────────────────────────────────────────
@router.get(
    "/subscriptions",
    response_model=list[WebhookSubscriptionResponse],
    summary="List webhook subscriptions",
)
async def list_subscriptions(
    active: Optional[bool] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    _user: CurrentUser = Depends(require_integration_admin),
) -> list[WebhookSubscriptionResponse]:
    query: dict = {}
    if active is not None:
        query["active"] = active
    cursor = db.webhook_subscriptions.find(query).sort("created_at", -1)
    docs = await cursor.to_list(length=None)
    return [_sub_to_response(d) for d in docs]


@router.post(
    "/subscriptions",
    response_model=WebhookSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create webhook subscription",
)
async def create_subscription(
    request: Request,
    data: WebhookSubscriptionCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    current_user: CurrentUser = Depends(require_integration_admin),
) -> WebhookSubscriptionResponse:
    doc = WebhookSubscriptionDocument(
        target_url=str(data.target_url),
        event_types=data.event_types,
        description=data.description,
    )
    insert_dict = doc.model_dump(by_alias=True)
    insert_dict["_id"] = str(insert_dict["_id"])
    insert_dict["event_types"] = [et.value for et in insert_dict["event_types"]]
    await db.webhook_subscriptions.insert_one(insert_dict)

    await write_audit(
        db,
        collection="webhook_subscriptions",
        document_id=insert_dict["_id"],
        action="CREATE",
        actor=current_user.username,
        actor_role=current_user.role.value,
        after={"target_url": str(data.target_url), "event_types": [et.value for et in data.event_types]},
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
    return _sub_to_response(insert_dict)


@router.get(
    "/subscriptions/{subscription_id}",
    response_model=WebhookSubscriptionResponse,
    summary="Get webhook subscription",
)
async def get_subscription(
    subscription_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    _user: CurrentUser = Depends(require_integration_admin),
) -> WebhookSubscriptionResponse:
    doc = await db.webhook_subscriptions.find_one({"_id": subscription_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    return _sub_to_response(doc)


@router.patch(
    "/subscriptions/{subscription_id}",
    response_model=WebhookSubscriptionResponse,
    summary="Update webhook subscription",
)
async def update_subscription(
    request: Request,
    subscription_id: str,
    data: WebhookSubscriptionUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    current_user: CurrentUser = Depends(require_integration_admin),
) -> WebhookSubscriptionResponse:
    doc = await db.webhook_subscriptions.find_one({"_id": subscription_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    before = dict(doc)

    updates: dict = {"updated_at": datetime.utcnow()}
    if data.target_url is not None:
        updates["target_url"] = str(data.target_url)
    if data.event_types is not None:
        updates["event_types"] = [et.value for et in data.event_types]
    if data.active is not None:
        updates["active"] = data.active
    if data.description is not None:
        updates["description"] = data.description

    await db.webhook_subscriptions.update_one({"_id": subscription_id}, {"$set": updates})
    after_doc = await db.webhook_subscriptions.find_one({"_id": subscription_id})

    await write_audit(
        db,
        collection="webhook_subscriptions",
        document_id=subscription_id,
        action="UPDATE",
        actor=current_user.username,
        actor_role=current_user.role.value,
        before={k: v for k, v in before.items() if k != "_id"},
        after={k: v for k, v in after_doc.items() if k != "_id"},  # type: ignore[union-attr]
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
    return _sub_to_response(after_doc)  # type: ignore[arg-type]


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete webhook subscription",
)
async def delete_subscription(
    request: Request,
    subscription_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    current_user: CurrentUser = Depends(require_integration_admin),
) -> Response:
    doc = await db.webhook_subscriptions.find_one({"_id": subscription_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    await db.webhook_subscriptions.delete_one({"_id": subscription_id})
    await write_audit(
        db,
        collection="webhook_subscriptions",
        document_id=subscription_id,
        action="DELETE",
        actor=current_user.username,
        actor_role=current_user.role.value,
        before={k: v for k, v in doc.items() if k != "_id"},
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _sub_to_response(doc: dict) -> WebhookSubscriptionResponse:
    return WebhookSubscriptionResponse(
        id=str(doc["_id"]),
        target_url=doc["target_url"],
        event_types=doc["event_types"],
        active=doc["active"],
        description=doc.get("description"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )
