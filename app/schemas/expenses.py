from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class ExpenseCategory(str, Enum):
    raw_materials = "raw materials"
    packaging = "packaging"
    logistics = "logistics"
    labor = "labor"
    rent = "rent"
    utilities = "utilities"
    marketing = "marketing"
    other = "other"


class ExpenseCreate(BaseModel):
    amount: float = Field(..., gt=0, description="Expense amount, must be positive")
    category: str = Field(..., min_length=1, description="Expense category, e.g. raw materials")
    description: str | None = Field(default=None, description="Optional free-text description")
    expense_date: date = Field(..., description="Date the expense occurred")


class ExpenseOut(BaseModel):
    id: str
    org_id: str
    user_id: str
    amount: float
    category: str
    description: str | None = None
    expense_date: date
    created_at: datetime
