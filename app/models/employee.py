"""Employee domain model and Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr, Field, model_validator


class EmploymentStatus(str, Enum):
    pending = "pending"
    active = "active"
    on_leave = "on_leave"
    terminated = "terminated"


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------
ALLOWED_TRANSITIONS: dict[EmploymentStatus, set[EmploymentStatus]] = {
    EmploymentStatus.pending: {EmploymentStatus.active, EmploymentStatus.terminated},
    EmploymentStatus.active: {EmploymentStatus.on_leave, EmploymentStatus.terminated},
    EmploymentStatus.on_leave: {EmploymentStatus.active, EmploymentStatus.terminated},
    EmploymentStatus.terminated: set(),  # terminal state
}


def validate_status_transition(
    current: EmploymentStatus, next_status: EmploymentStatus
) -> None:
    """Raise ValueError if the requested status transition is invalid."""
    if next_status not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(
            f"Cannot transition from '{current}' to '{next_status}'. "
            f"Allowed: {[s.value for s in ALLOWED_TRANSITIONS[current]]}"
        )


# ---------------------------------------------------------------------------
# MongoDB document model (internal)
# ---------------------------------------------------------------------------
class EmployeeDocument(BaseModel):
    """Represents a MongoDB employee document."""

    model_config = {"populate_by_name": True}

    id: UUID = Field(default_factory=uuid4, alias="_id")
    employee_id: str
    name: str
    email: str
    department: str
    job_title: str
    manager_id: Optional[str] = None
    location: str
    employment_status: EmploymentStatus = EmploymentStatus.pending
    start_date: date
    end_date: Optional[date] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------
class EmployeeCreate(BaseModel):
    """Schema for creating a new employee (Joiner)."""

    employee_id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    department: str = Field(..., min_length=1, max_length=100)
    job_title: str = Field(..., min_length=1, max_length=100)
    manager_id: Optional[str] = None
    location: str = Field(..., min_length=1, max_length=100)
    start_date: date


class EmployeeUpdate(BaseModel):
    """Schema for moving an employee (Mover) – partial update."""

    department: Optional[str] = Field(default=None, min_length=1, max_length=100)
    job_title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    manager_id: Optional[str] = None
    location: Optional[str] = Field(default=None, min_length=1, max_length=100)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> EmployeeUpdate:
        if not any(
            v is not None
            for v in [
                self.department,
                self.job_title,
                self.manager_id,
                self.location,
                self.name,
                self.email,
            ]
        ):
            raise ValueError("At least one field must be provided for update.")
        return self


class EmployeeTerminate(BaseModel):
    """Schema for terminating an employee (Leaver)."""

    end_date: date


class EmployeeResponse(BaseModel):
    """Public employee response schema."""

    model_config = {"populate_by_name": True}

    employee_id: str
    name: str
    email: str
    department: str
    job_title: str
    manager_id: Optional[str] = None
    location: str
    employment_status: EmploymentStatus
    start_date: date
    end_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime


class EmployeeListResponse(BaseModel):
    """Paginated employee list."""

    total: int
    page: int
    page_size: int
    items: list[EmployeeResponse]
