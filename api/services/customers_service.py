"""Customers business logic + validation. No direct DB access here — only via repository."""
from __future__ import annotations

from typing import Any

from core.db import Db

from repository import base as repo_base
from repository import customers_repository

_LIMITS = {"name": 200, "phone": 32, "email": 320, "address": 500, "notes": 1000}
_OPTIONAL = ("phone", "email", "address", "notes")
MAX_SEARCH_LEN = 100


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


class DuplicatePhoneError(Exception):
    pass


class CustomerInUseError(Exception):
    pass


def _name(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        raise ValidationError("Customer name must not be empty")
    if len(text) > _LIMITS["name"]:
        raise ValidationError(f"Customer name must be at most {_LIMITS['name']} characters")
    return text


def _optional(field: str, value: str | None) -> str | None:
    """Blank => None (never store '': it would count as a value in the unique phone index)."""
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > _LIMITS[field]:
        raise ValidationError(f"Customer {field} must be at most {_LIMITS[field]} characters")
    if field == "email" and ("@" not in text or any(c.isspace() for c in text)):
        raise ValidationError("Customer email is not a valid address")
    return text


def create_customer(db: Db, *, org_id: str, user_id: str, name: str, phone: str | None = None, email: str | None = None,
                    address: str | None = None, notes: str | None = None) -> dict[str, Any]:
    clean = {"phone": phone, "email": email, "address": address, "notes": notes}
    clean = {k: _optional(k, v) for k, v in clean.items()}
    name = _name(name)
    try:
        return customers_repository.create_customer(db, org_id=org_id, created_by=user_id, name=name, **clean)
    except repo_base.DuplicateRecordError as exc:
        raise DuplicatePhoneError(f"A customer with phone '{clean['phone']}' already exists") from exc


def list_customers(db: Db, *, org_id: str, limit: int = 100, offset: int = 0, q: str | None = None) -> list[dict[str, Any]]:
    q = (q or "").strip() or None
    if q is not None and len(q) > MAX_SEARCH_LEN:
        raise ValidationError(f"Search text must be at most {MAX_SEARCH_LEN} characters")
    return customers_repository.list_customers(db, org_id=org_id, limit=limit, offset=offset, q=q)


def get_customer(db: Db, *, org_id: str, customer_id: str) -> dict[str, Any]:
    customer = customers_repository.get_customer_scoped(db, customer_id=customer_id, org_id=org_id)
    if customer is None:
        raise NotFoundError("Customer not found")
    return customer


def get_customer_summary(db: Db, *, org_id: str, customer_id: str) -> dict[str, Any]:
    summary = customers_repository.get_customer_summary_scoped(db, customer_id=customer_id, org_id=org_id)
    if summary is None:
        raise NotFoundError("Customer not found")
    return summary


def update_customer(db: Db, *, org_id: str, customer_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """`updates` holds only the fields the client sent. name: None is ignored; phone/email/address/notes:
    a present key is written, and null/blank clears the column."""
    clean: dict[str, Any] = {}
    if updates.get("name") is not None:
        clean["name"] = _name(updates["name"])
    for field in _OPTIONAL:
        if field in updates:
            clean[field] = _optional(field, updates[field])
    try:
        updated = customers_repository.update_customer_scoped(db, customer_id=customer_id, org_id=org_id, updates=clean)
    except repo_base.DuplicateRecordError as exc:
        raise DuplicatePhoneError(f"A customer with phone '{clean.get('phone')}' already exists") from exc
    if updated is None:
        raise NotFoundError("Customer not found")
    return updated


def delete_customer(db: Db, *, org_id: str, customer_id: str) -> None:
    """Refused (409) while the customer has sales: nothing is detached or lost silently."""
    if customers_repository.delete_customer_scoped(db, customer_id=customer_id, org_id=org_id):
        return
    # Zero rows: no such customer in this org (404) or it still has sales (409). The decision was taken by the
    # single DELETE statement; this scoped (id AND org_id) existence check only picks the error code.
    if repo_base.get_ownership(db, table="customers", record_id=customer_id, org_id=org_id):
        raise CustomerInUseError("Customer has sales; unlink or delete those sales first")
    raise NotFoundError("Customer not found")
