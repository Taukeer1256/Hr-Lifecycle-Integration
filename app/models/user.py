"""User model for authentication."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    hr_admin = "hr_admin"
    hr_viewer = "hr_viewer"
    integration_admin = "integration_admin"


class UserDocument(BaseModel):
    """MongoDB user document."""

    model_config = {"populate_by_name": True}

    id: UUID = Field(default_factory=uuid4, alias="_id")
    username: str
    hashed_password: str
    role: UserRole
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    role: UserRole


class UserResponse(BaseModel):
    id: str
    username: str
    role: UserRole
    active: bool
    created_at: datetime


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: UserRole


class TokenData(BaseModel):
    """Claims stored inside the JWT."""

    sub: str  # username
    role: UserRole
    jti: Optional[str] = None


class CurrentUser(BaseModel):
    """Resolved current-user injected via dependency."""

    username: str
    role: UserRole
