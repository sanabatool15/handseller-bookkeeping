"""Business expenses (supplies, travel, commissions paid out, etc.)."""

from datetime import date

from pydantic import BaseModel

from app.models.common import ORMBase


class ExpenseBase(BaseModel):
    seller_id: str | None = None
    category: str  # e.g. supplies, travel, commission, marketing, other
    amount: float
    expense_date: date
    description: str | None = None


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    seller_id: str | None = None
    category: str | None = None
    amount: float | None = None
    expense_date: date | None = None
    description: str | None = None


class Expense(ExpenseBase, ORMBase):
    pass
