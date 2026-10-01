"""Expenses business logic + validation. No direct DB access here - only via repository.

Expenses move CASH: create / delete / amount edits go through stored procedures (usp_RecordExpense, usp_VoidExpense,
usp_AdjustEntryAmount) that update the expense, the cash balance and the cash ledger in ONE transaction. Each call is
a complete unit of work wrapped in run_with_deadlock_retry (see specs/15)."""
from __future__ import annotations

from typing import Any, Callable

from core.db import Db, run_with_deadlock_retry

from repository import cash_repository, expenses_repository

# decimal(14,2) maximum; larger values would overflow in SQL Server (HTTP 500), so they are rejected here (422).
MAX_AMOUNT = 999_999_999_999.99
MAX_CATEGORY_LEN = 100
MAX_VOUCHER_LEN = 200


class ValidationError(Exception):
    pass


class NotFoundError(Exception):
    pass


def _check_amount(amount: float) -> None:
    if amount <= 0:
        raise ValidationError("Expense amount must be positive")
    if amount > MAX_AMOUNT:
        raise ValidationError("Expense amount is too large")


def _check_text(category: str | None, voucher_reference: str | None) -> None:
    if category is not None and len(category) > MAX_CATEGORY_LEN:
        raise ValidationError(f"Expense category must be at most {MAX_CATEGORY_LEN} characters")
    if voucher_reference is not None and len(voucher_reference) > MAX_VOUCHER_LEN:
        raise ValidationError(f"Expense voucher_reference must be at most {MAX_VOUCHER_LEN} characters")


def create_expense(
    db: Db, *, org_id: str, user_id: str, amount: float, category: str, voucher_reference: str | None = None,
    description: str | None = None, on_event: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Record an expense ATOMICALLY: the cash balance goes DOWN by `amount` (it may become negative: a handseller can
    spend before cashing up) and an 'expense' ledger entry is written. Raises ValidationError (422), NotFoundError (404 org)."""
    _check_amount(amount)
    _check_text(category, voucher_reference)
    outcome = run_with_deadlock_retry(
        lambda: expenses_repository.record_expense(
            db, org_id=org_id, created_by=user_id, amount=amount, category=category or "general",
            voucher_reference=voucher_reference, description=description,
        ),
        on_event=on_event,
    )
    if outcome["status"] != "committed":
        if outcome["error_number"] == 50005:
            raise NotFoundError("Organisation not found")
        raise ValidationError(outcome["message"] or "Expense rejected")
    return outcome["expense"]


def list_expenses(db: Db, *, org_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    return expenses_repository.list_expenses(db, org_id=org_id, limit=limit, offset=offset)


def get_expense(db: Db, *, org_id: str, expense_id: str) -> dict[str, Any]:
    expense = expenses_repository.get_expense_scoped(db, expense_id=expense_id, org_id=org_id)
    if expense is None:
        raise NotFoundError("Expense not found")
    return expense


def update_expense(
    db: Db, *, org_id: str, expense_id: str, updates: dict[str, Any], user_id: str | None = None,
    on_event: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Update an expense. A changed `amount` goes through usp_AdjustEntryAmount (posts the delta to the cash ledger);
    the other fields are updated in the same request/transaction (an error in either rolls both back)."""
    clean_updates = {k: v for k, v in updates.items() if v is not None}
    if "amount" in clean_updates:
        _check_amount(clean_updates["amount"])
    _check_text(clean_updates.get("category"), clean_updates.get("voucher_reference"))
    new_amount = clean_updates.pop("amount", None)
    if new_amount is not None:
        result = run_with_deadlock_retry(
            lambda: cash_repository.adjust_entry_amount(
                db, org_id=org_id, ref_type="expense", ref_id=expense_id, new_amount=new_amount, adjusted_by=user_id,
            ),
            on_event=on_event,
        )
        if result["status"] == "not_found":
            raise NotFoundError("Expense not found")
        if result["status"] not in ("adjusted", "unchanged"):
            raise ValidationError(result["message"] or "Amount change rejected")
    updated = expenses_repository.update_expense_scoped(db, expense_id=expense_id, org_id=org_id, updates=clean_updates)
    if updated is None:
        raise NotFoundError("Expense not found")
    return updated


def delete_expense(
    db: Db, *, org_id: str, expense_id: str, user_id: str | None = None, on_event: Callable[..., None] | None = None,
) -> None:
    """Void the expense (usp_VoidExpense): reversing cash entry (money back), expense deleted - one transaction."""
    result = run_with_deadlock_retry(
        lambda: expenses_repository.void_expense(db, org_id=org_id, expense_id=expense_id, voided_by=user_id),
        on_event=on_event,
    )
    if result["status"] == "not_found":
        raise NotFoundError("Expense not found")
