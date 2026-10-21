"""Outbox event model for the transactional outbox pattern."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.event import EventType


class OutboxStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    delivered = "delivered"
    failed = "failed"
    dead_letter = "dead_letter"


class OutboxDocument(BaseModel):
    """Represents an outbox event record in MongoDB."""

    model_config = {"populate_by_name": True}

    id: UUID = Field(default_factory=uuid4, alias="_id")
    idempotency_key: str  # unique per (event_id, subscription_id)
    event_id: str
    event_type: EventType
    employee_id: str
    payload: dict[str, Any]
    subscription_id: str
    target_url: str
    status: OutboxStatus = OutboxStatus.pending
    retry_count: int = 0
    max_retries: int = 5
    next_attempt_at: datetime = Field(default_factory=datetime.utcnow)
    last_error: Optional[str] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: Optional[str] = None


class OutboxResponse(BaseModel):
    """Public outbox event response."""

    id: str
    idempotency_key: str
    event_id: str
    event_type: EventType
    employee_id: str
    subscription_id: str
    target_url: str
    status: OutboxStatus
    retry_count: int
    max_retries: int
    next_attempt_at: datetime
    last_error: Optional[str] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class OutboxListResponse(BaseModel):
    """Paginated outbox list."""

    total: int
    page: int
    page_size: int
    items: list[OutboxResponse]
