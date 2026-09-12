from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class ExpenseCreate(BaseModel):
    """Body for logging a new expense. org_id comes from the path, never trusted from here."""

    amount: Decimal = Field(..., gt=0, description="Expense amount, must be greater than 0.")
    category: str = Field(
        ..., min_length=1, max_length=100, description="Category the expense belongs to."
    )
    expense_date: date | None = Field(
        default=None, description="Date of the expense. Defaults to today if omitted."
    )

    @field_validator("category")
    @classmethod
    def category_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("'category' must not be blank")
        return v

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("'amount' must be greater than 0")
        return v


class ExpenseOut(BaseModel):
    id: str
    org_id: str
    amount: Decimal
    category: str
    expense_date: date
    created_at: datetime | None = None
