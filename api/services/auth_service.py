"""Auth business logic: registration, login, password hashing."""
from __future__ import annotations

import hashlib
import hmac
import os

from supabase import Client

from repository import orgs_repository, users_repository
from app.security import create_access_token


class AuthError(Exception):
    pass


def _hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return hmac.compare_digest(expected.hex(), digest_hex)


def register(db: Client, *, email: str, password: str, full_name: str | None, org_name: str) -> dict:
    existing = users_repository.get_user_by_email(db, email)
    if existing:
        raise AuthError("Email already registered")

    hashed = _hash_password(password)
    # Create user first (owner_id FK is deferrable) then the org, then patch user.org_id.
    user = users_repository.create_user(db, email=email, hashed_password=hashed, full_name=full_name, org_id=None, role="owner")
    org = orgs_repository.create_org(db, name=org_name, owner_id=user["id"])
    db.table("users").update({"org_id": org["id"]}).eq("id", user["id"]).execute()
    user["org_id"] = org["id"]

    token = create_access_token(user_id=user["id"], org_id=org["id"], role="owner", email=email)
    return {"access_token": token, "user": user, "org": org}


def login(db: Client, *, email: str, password: str) -> dict:
    user = users_repository.get_user_by_email(db, email)
    if not user or not _verify_password(password, user["hashed_password"]):
        raise AuthError("Invalid email or password")

    token = create_access_token(user_id=user["id"], org_id=user["org_id"], role=user.get("role", "member"), email=email)
    return {"access_token": token, "user": user}
