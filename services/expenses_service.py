"""Expenses business logic + validation. No direct DB access here — only via repository."""
from __future__ import annotations

from typing import Any

from supabase import Client

from repository import expenses_repository


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


def create_expense(db: Client, *, org_id: str, user_id: str, amount: float, category: str, voucher_reference: str | None = None, description: str | None = None) -> dict[str, Any]:
    if amount <= 0:
        raise ValidationError("Expense amount must be positive")
    return expenses_repository.create_expense(
        db, org_id=org_id, created_by=user_id, amount=amount, category=category or "general",
        voucher_reference=voucher_reference, description=description,
    )


def list_expenses(db: Client, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return expenses_repository.list_expenses(db, org_id=org_id, limit=limit, offset=offset)


def get_expense(db: Client, *, org_id: str, expense_id: str) -> dict[str, Any]:
    expense = expenses_repository.get_expense_scoped(db, expense_id=expense_id, org_id=org_id)
    if expense is None:
        raise NotFoundError("Expense not found")
    return expense


def update_expense(db: Client, *, org_id: str, expense_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    if "amount" in updates and updates["amount"] is not None and updates["amount"] <= 0:
        raise ValidationError("Expense amount must be positive")
    clean_updates = {k: v for k, v in updates.items() if v is not None}
    updated = expenses_repository.update_expense_scoped(db, expense_id=expense_id, org_id=org_id, updates=clean_updates)
    if updated is None:
        raise NotFoundError("Expense not found")
    return updated


def delete_expense(db: Client, *, org_id: str, expense_id: str) -> None:
    deleted = expenses_repository.delete_expense_scoped(db, expense_id=expense_id, org_id=org_id)
    if not deleted:
        raise NotFoundError("Expense not found")
