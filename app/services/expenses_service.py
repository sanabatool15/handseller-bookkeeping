"""Business logic for expenses. Delegates all persistence to
app.repository.expenses_repository."""

from uuid import UUID

from fastapi import HTTPException, status

from app.auth import CurrentUser
from app.models.expenses import Expense, ExpenseCreate, ExpenseUpdate
from app.repository import expenses_repository


def log_expense(current: CurrentUser, payload: ExpenseCreate) -> Expense:
    data = payload.model_dump(mode="json")
    created = expenses_repository.create_expense(current.org_id, current.user_id, data)
    return Expense.model_validate(created)


def list_expenses(current: CurrentUser, start=None, end=None) -> list[Expense]:
    rows = expenses_repository.list_expenses_for_org(current.org_id, start, end)
    return [Expense.model_validate(row) for row in rows]


def get_expense(current: CurrentUser, expense_id: UUID) -> Expense:
    row = expenses_repository.get_expense_by_id(expense_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if str(row["org_id"]) != str(current.org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to access this expense")
    return Expense.model_validate(row)


def update_expense(current: CurrentUser, expense_id: UUID, payload: ExpenseUpdate) -> Expense:
    existing = expenses_repository.get_expense_by_id(expense_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if str(existing["org_id"]) != str(current.org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to modify this expense")

    updates = payload.model_dump(mode="json", exclude_unset=True)
    if not updates:
        return Expense.model_validate(existing)

    updated = expenses_repository.update_expense(expense_id, current.org_id, updates)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    return Expense.model_validate(updated)


def delete_expense(current: CurrentUser, expense_id: UUID) -> None:
    existing = expenses_repository.get_expense_by_id(expense_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    if str(existing["org_id"]) != str(current.org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to delete this expense")

    deleted = expenses_repository.delete_expense(expense_id, current.org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
