"""JWT authentication dependency for FastAPI routes.

The JWT is expected to carry `sub` (user_id) and `org_id` claims. On each
request we verify the token, then re-check organization membership via the
repository layer's `get_ownership` helper (not a cached/trusted claim alone),
so a stale or forged org_id claim cannot grant cross-tenant access.
"""
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.repository.org_repository import get_ownership


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    org_id: str


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    user_id = payload.get("sub")
    org_id = payload.get("org_id")
    if not user_id or not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claims (sub, org_id)",
        )

    if not get_ownership(user_id=user_id, org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of the requested organization",
        )

    return CurrentUser(user_id=user_id, org_id=org_id)
