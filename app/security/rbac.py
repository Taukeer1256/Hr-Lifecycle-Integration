"""RBAC dependency helpers and HMAC signing utilities."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.models.user import CurrentUser, UserRole
from app.security.jwt_auth import decode_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Extract and validate JWT from Authorization header."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_data = decode_token(credentials.credentials)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(username=token_data.sub, role=token_data.role)


def require_roles(*roles: UserRole) -> Callable:
    """FastAPI dependency factory that enforces role-based access."""

    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' does not have access to this resource. "
                f"Required: {[r.value for r in roles]}",
            )
        return user

    return _check


# ---------------------------------------------------------------------------
# Convenience role dependencies
# ---------------------------------------------------------------------------
require_hr_admin = require_roles(UserRole.hr_admin)
require_hr_admin_or_viewer = require_roles(UserRole.hr_admin, UserRole.hr_viewer)
require_integration_admin = require_roles(UserRole.integration_admin, UserRole.hr_admin)
require_any_role = require_roles(
    UserRole.hr_admin, UserRole.hr_viewer, UserRole.integration_admin
)


# ---------------------------------------------------------------------------
# HMAC-SHA256 signature for outgoing webhooks
# ---------------------------------------------------------------------------
def sign_payload(payload: dict[str, Any]) -> str:
    """Return HMAC-SHA256 hex digest of the JSON payload."""
    settings = get_settings()
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    return hmac.new(
        settings.webhook_hmac_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()


def verify_signature(payload: dict[str, Any], signature: str) -> bool:
    """Verify an HMAC-SHA256 webhook signature."""
    expected = sign_payload(payload)
    return hmac.compare_digest(expected, signature)
