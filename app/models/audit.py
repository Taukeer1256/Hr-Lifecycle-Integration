"""Audit log model."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AuditAction(str):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    STATUS_CHANGE = "STATUS_CHANGE"


class AuditDocument(BaseModel):
    """Immutable audit log entry."""

    model_config = {"populate_by_name": True}

    id: UUID = Field(default_factory=uuid4, alias="_id")
    collection: str  # e.g. "employees", "webhook_subscriptions"
    document_id: str
    employee_id: Optional[str] = None
    action: str  # CREATE / UPDATE / STATUS_CHANGE / DELETE
    actor: str  # username of the user who performed the action
    actor_role: str
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    changed_fields: list[str] = Field(default_factory=list)
    correlation_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditResponse(BaseModel):
    """Public audit log response."""

    id: str
    collection: str
    document_id: str
    employee_id: Optional[str] = None
    action: str
    actor: str
    actor_role: str
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    changed_fields: list[str]
    correlation_id: Optional[str] = None
    created_at: datetime


class AuditListResponse(BaseModel):
    """Paginated audit log response."""

    total: int
    page: int
    page_size: int
    items: list[AuditResponse]
