from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SaleBase(BaseModel):
    sale_date: date
    description: str = Field(min_length=1, max_length=500)
    amount: float = Field(gt=0)
    quantity: int = Field(default=1, gt=0)


class SaleCreate(SaleBase):
    pass


class SaleUpdate(BaseModel):
    sale_date: date | None = None
    description: str | None = Field(default=None, min_length=1, max_length=500)
    amount: float | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, gt=0)


class Sale(SaleBase):
    id: UUID
    org_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
