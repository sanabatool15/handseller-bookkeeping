"""Authentication dependency: extracts user_id and org_id from a JWT
carried in the Authorization header."""

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import get_settings

_bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    user_id: UUID
    org_id: UUID


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """Decode the bearer JWT and return the authenticated user's identity.

    Expects the token payload to contain `sub` (or `user_id`) and `org_id`
    claims, as issued by the auth provider at login time.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    user_id = payload.get("user_id") or payload.get("sub")
    org_id = payload.get("org_id")

    if not user_id or not org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user_id/org_id claims",
        )

    try:
        return CurrentUser(user_id=UUID(str(user_id)), org_id=UUID(str(org_id)))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user_id/org_id claims",
        ) from exc
