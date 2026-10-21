"""Authentication router – login and user management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db import get_db
from app.models.user import (
    CurrentUser,
    TokenRequest,
    TokenResponse,
    UserCreate,
    UserDocument,
    UserResponse,
    UserRole,
)
from app.security.jwt_auth import create_access_token, hash_password, verify_password
from app.security.rbac import get_current_user, require_roles

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/token", response_model=TokenResponse, summary="Obtain JWT access token")
async def login(
    data: TokenRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
) -> TokenResponse:
    """Authenticate with username/password and receive a JWT."""
    user_doc = await db.users.find_one({"username": data.username})
    if not user_doc or not verify_password(data.password, user_doc["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    if not user_doc.get("active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled.",
        )
    token, expires_in = create_access_token(
        username=user_doc["username"],
        role=UserRole(user_doc["role"]),
    )
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        role=UserRole(user_doc["role"]),
    )


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (hr_admin only)",
)
async def create_user(
    data: UserCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    current_user: CurrentUser = Depends(require_roles(UserRole.hr_admin)),
) -> UserResponse:
    """Create a new system user. Only hr_admin can do this."""
    existing = await db.users.find_one({"username": data.username})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{data.username}' already exists.",
        )
    doc = UserDocument(
        username=data.username,
        hashed_password=hash_password(data.password),
        role=data.role,
    )
    insert_dict = doc.model_dump(by_alias=True)
    insert_dict["_id"] = str(insert_dict["_id"])
    await db.users.insert_one(insert_dict)
    return UserResponse(
        id=insert_dict["_id"],
        username=doc.username,
        role=doc.role,
        active=doc.active,
        created_at=doc.created_at,
    )


@router.get("/me", response_model=UserResponse, summary="Get current user info")
async def get_me(
    db: AsyncIOMotorDatabase = Depends(get_db),  # type: ignore[type-arg]
    current_user: CurrentUser = Depends(get_current_user),
) -> UserResponse:
    """Return the current authenticated user's profile."""
    doc = await db.users.find_one({"username": current_user.username})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    return UserResponse(
        id=str(doc["_id"]),
        username=doc["username"],
        role=UserRole(doc["role"]),
        active=doc.get("active", True),
        created_at=doc["created_at"],
    )
