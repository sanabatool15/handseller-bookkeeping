"""Business logic for expenses. Delegates all persistence to repository/."""
from fastapi import HTTPException, status

from app.repository import expenses_repository
from app.schemas.expenses import ExpenseCreate


def log_expense(org_id: str, user_id: str, payload: ExpenseCreate) -> dict:
    return expenses_repository.create_expense(
        org_id=org_id,
        user_id=user_id,
        amount=payload.amount,
        category=payload.category,
        expense_date=payload.expense_date.isoformat(),
        description=payload.description,
    )


def get_expense(org_id: str, expense_id: str) -> dict:
    expense = expenses_repository.get_expense_scoped(expense_id=expense_id, org_id=org_id)
    if expense is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    return expense
