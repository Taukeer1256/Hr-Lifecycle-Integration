"""Event and webhook subscription models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl


class EventType(str, Enum):
    employee_joined = "employee.joined"
    employee_moved = "employee.moved"
    employee_left = "employee.left"
    employee_status_changed = "employee.status_changed"


class EventDocument(BaseModel):
    """Represents an HR domain event."""

    model_config = {"populate_by_name": True}

    id: UUID = Field(default_factory=uuid4, alias="_id")
    event_type: EventType
    employee_id: str
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None


class EventResponse(BaseModel):
    """Public event response."""

    id: str
    event_type: EventType
    employee_id: str
    payload: dict[str, Any]
    created_at: datetime
    correlation_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Webhook Subscription
# ---------------------------------------------------------------------------
class WebhookSubscriptionCreate(BaseModel):
    """Request body for creating a webhook subscription."""

    target_url: HttpUrl
    event_types: list[EventType] = Field(..., min_length=1)
    description: Optional[str] = None


class WebhookSubscriptionUpdate(BaseModel):
    """Request body for updating a webhook subscription."""

    target_url: Optional[HttpUrl] = None
    event_types: Optional[list[EventType]] = None
    active: Optional[bool] = None
    description: Optional[str] = None


class WebhookSubscriptionDocument(BaseModel):
    """MongoDB document for webhook subscriptions."""

    model_config = {"populate_by_name": True}

    id: UUID = Field(default_factory=uuid4, alias="_id")
    target_url: str
    event_types: list[EventType]
    active: bool = True
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WebhookSubscriptionResponse(BaseModel):
    """Public webhook subscription response."""

    id: str
    target_url: str
    event_types: list[EventType]
    active: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
