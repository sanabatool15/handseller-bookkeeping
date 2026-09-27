"""Sales business logic + validation. No direct DB access here — only via repository."""
from __future__ import annotations

from typing import Any

from supabase import Client

from repository import sales_repository


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


def create_sale(db: Client, *, org_id: str, user_id: str, amount: float, category: str, description: str | None = None, customer_name: str | None = None) -> dict[str, Any]:
    if amount <= 0:
        raise ValidationError("Sale amount must be positive")
    return sales_repository.create_sale(
        db, org_id=org_id, created_by=user_id, amount=amount, category=category or "general",
        description=description, customer_name=customer_name,
    )


def list_sales(db: Client, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return sales_repository.list_sales(db, org_id=org_id, limit=limit, offset=offset)


def get_sale(db: Client, *, org_id: str, sale_id: str) -> dict[str, Any]:
    sale = sales_repository.get_sale_scoped(db, sale_id=sale_id, org_id=org_id)
    if sale is None:
        raise NotFoundError("Sale not found")
    return sale


def update_sale(db: Client, *, org_id: str, sale_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if "amount" in updates and updates["amount"] is not None and updates["amount"] <= 0:
        raise ValidationError("Sale amount must be positive")
    clean_updates = {k: v for k, v in updates.items() if v is not None}
    updated = sales_repository.update_sale_scoped(db, sale_id=sale_id, org_id=org_id, updates=clean_updates)
    if updated is None:
        raise NotFoundError("Sale not found")
    return updated


def delete_sale(db: Client, *, org_id: str, sale_id: str) -> None:
    deleted = sales_repository.delete_sale_scoped(db, sale_id=sale_id, org_id=org_id)
    if not deleted:
        raise NotFoundError("Sale not found")
