from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth import CurrentUser, get_current_user
from app.models.expenses import Expense, ExpenseCreate, ExpenseUpdate
from app.services import expenses_service

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.post("", response_model=Expense, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    current: CurrentUser = Depends(get_current_user),
) -> Expense:
    return expenses_service.log_expense(current, payload)


@router.get("", response_model=list[Expense])
def list_expenses(
    start: date | None = None,
    end: date | None = None,
    current: CurrentUser = Depends(get_current_user),
) -> list[Expense]:
    return expenses_service.list_expenses(current, start, end)


@router.get("/{expense_id}", response_model=Expense)
def get_expense(
    expense_id: UUID,
    current: CurrentUser = Depends(get_current_user),
) -> Expense:
    return expenses_service.get_expense(current, expense_id)


@router.patch("/{expense_id}", response_model=Expense)
def update_expense(
    expense_id: UUID,
    payload: ExpenseUpdate,
    current: CurrentUser = Depends(get_current_user),
) -> Expense:
    return expenses_service.update_expense(current, expense_id, payload)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: UUID,
    current: CurrentUser = Depends(get_current_user),
) -> None:
    expenses_service.delete_expense(current, expense_id)
