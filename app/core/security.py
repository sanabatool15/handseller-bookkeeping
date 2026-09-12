"""JWT authentication dependency.

`get_current_user` extracts and verifies the authenticated user's identity
from the `Authorization: Bearer <jwt>` header. It never trusts a user_id or
org_id supplied by the client body/query — those are only ever used after
`get_ownership` verification in the services layer.
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import Settings, get_settings

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None = None


def _decode_token(token: str, settings: Settings) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired authentication token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """FastAPI dependency: resolves the authenticated user from the JWT.

    Raises 401 if the token is missing, malformed, or invalid. This is the
    ONLY source of `user_id` used by services/repositories for ownership
    checks — request bodies and query params are never trusted for identity.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token in Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode_token(credentials.credentials, settings)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing the 'sub' (user id) claim.",
        )

    return CurrentUser(user_id=str(user_id), email=payload.get("email"))
