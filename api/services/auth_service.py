"""Auth business logic: registration, login, password hashing."""
from __future__ import annotations

import hashlib
import hmac
import os

from core.db import Db
from repository import base as repo_base
from repository import orgs_repository, users_repository
from core.security import create_access_token


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


def register(db: Db, *, email: str, password: str, full_name: str | None, org_name: str) -> dict:
    # Cheap pre-check for the common case; the UNIQUE constraint on users.email is the
    # real guard (two concurrent registrations can both pass this check).
    if users_repository.get_user_by_email(db, email):
        raise AuthError("Email already registered")

    hashed = _hash_password(password)
    try:
        # ONE transaction: user (org_id NULL) -> org (owner_id = user) -> user.org_id = org.
        # SQL Server has no deferrable FKs, hence the nullable owner_id/org_id dance.
        # Any failure rolls everything back, so no orphan user/org remains.
        with repo_base.transaction(db):
            user = users_repository.create_user(db, email=email, hashed_password=hashed, full_name=full_name, org_id=None, role="owner")
            org = orgs_repository.create_org(db, name=org_name, owner_id=user["id"])
            user = users_repository.set_user_org(db, user_id=user["id"], org_id=org["id"])
    except repo_base.DuplicateRecordError as exc:
        raise AuthError("Email already registered") from exc

    token = create_access_token(user_id=user["id"], org_id=org["id"], role="owner", email=email)
    return {"access_token": token, "user": user, "org": org}


def login(db: Db, *, email: str, password: str) -> dict:
    user = users_repository.get_user_by_email(db, email)
    if not user or not _verify_password(password, user["hashed_password"]):
        raise AuthError("Invalid email or password")

    token = create_access_token(user_id=user["id"], org_id=user["org_id"], role=user.get("role", "member"), email=email)
    return {"access_token": token, "user": user}
