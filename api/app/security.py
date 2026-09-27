"""JWT encoding/decoding helpers and the CurrentUser model shared across the app."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import jwt

from app.config import get_settings


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    org_id: str
    role: str = "member"
    email: str | None = None


def create_access_token(*, user_id: str, org_id: str, role: str = "member", email: str | None = None) -> str:
    settings = get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TokenError(Exception):
    pass


def decode_access_token(token: str) -> CurrentUser:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    user_id = payload.get("sub")
    org_id = payload.get("org_id")
    if not user_id or not org_id:
        raise TokenError("Token missing sub/org_id claims")

    return CurrentUser(
        user_id=user_id,
        org_id=org_id,
        role=payload.get("role", "member"),
        email=payload.get("email"),
    )
