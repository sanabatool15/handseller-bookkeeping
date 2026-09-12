from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ExpenseBase(BaseModel):
    expense_date: date
    description: str = Field(min_length=1, max_length=500)
    amount: float = Field(gt=0)
    category: str | None = Field(default=None, max_length=100)


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    expense_date: date | None = None
    description: str | None = Field(default=None, min_length=1, max_length=500)
    amount: float | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, max_length=100)


class Expense(ExpenseBase):
    id: UUID
    org_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
