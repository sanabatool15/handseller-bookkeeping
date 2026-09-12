from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class SaleCreate(BaseModel):
    """Body for logging a new sale. org_id comes from the path, never trusted from here."""

    amount: Decimal = Field(..., gt=0, description="Sale amount, must be greater than 0.")
    voucher_reference: str | None = Field(
        default=None,
        max_length=2048,
        description="Text or URL reference to the sale's voucher/receipt.",
    )
    sale_date: date | None = Field(
        default=None, description="Date of the sale. Defaults to today if omitted."
    )

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("'amount' must be greater than 0")
        return v


class SaleOut(BaseModel):
    id: str
    org_id: str
    amount: Decimal
    voucher_reference: str | None = None
    sale_date: date
    created_at: datetime | None = None
