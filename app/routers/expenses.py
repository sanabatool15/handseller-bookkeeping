from fastapi import APIRouter, Depends
from supabase import Client

from app.core.crud import create_row, delete_row, get_row, list_rows, update_row
from app.core.supabase_client import get_supabase
from app.models.expenses import Expense, ExpenseCreate, ExpenseUpdate

router = APIRouter(prefix="/expenses", tags=["expenses"])
TABLE = "expenses"


@router.get("", response_model=list[Expense])
def list_expenses(
    limit: int = 100, offset: int = 0, db: Client = Depends(get_supabase)
):
    return list_rows(db, TABLE, limit=limit, offset=offset)


@router.post("", response_model=Expense, status_code=201)
def create_expense(payload: ExpenseCreate, db: Client = Depends(get_supabase)):
    return create_row(db, TABLE, payload.model_dump(mode="json"))


@router.get("/{expense_id}", response_model=Expense)
def get_expense(expense_id: str, db: Client = Depends(get_supabase)):
    return get_row(db, TABLE, expense_id)


@router.patch("/{expense_id}", response_model=Expense)
def update_expense(
    expense_id: str, payload: ExpenseUpdate, db: Client = Depends(get_supabase)
):
    return update_row(db, TABLE, expense_id, payload.model_dump(mode="json"))


@router.delete("/{expense_id}", status_code=204)
def delete_expense(expense_id: str, db: Client = Depends(get_supabase)):
    delete_row(db, TABLE, expense_id)
