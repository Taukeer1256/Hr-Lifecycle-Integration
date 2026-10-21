"""JWT creation and validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Optional
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.models.user import TokenData, UserRole

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(username: str, role: UserRole) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    settings = get_settings()
    expires_delta = timedelta(minutes=settings.jwt_expire_minutes)
    expire = datetime.now(UTC) + expires_delta
    payload: dict = {
        "sub": username,
        "role": role.value,
        "exp": expire,
        "iat": datetime.now(UTC),
        "jti": str(uuid4()),
    }
    token = jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return token, int(expires_delta.total_seconds())


def decode_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT. Returns None if invalid."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        username: str = payload.get("sub", "")
        role_str: str = payload.get("role", "")
        if not username or not role_str:
            return None
        return TokenData(sub=username, role=UserRole(role_str))
    except (JWTError, ValueError):
        return None
