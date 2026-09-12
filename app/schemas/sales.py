from datetime import date, datetime

from pydantic import BaseModel, Field


class SaleCreate(BaseModel):
    amount: float = Field(..., gt=0, description="Sale amount, must be positive")
    sale_date: date = Field(..., description="Date the sale occurred")
    voucher_reference: str | None = Field(
        default=None, description="Optional voucher/receipt reference or URL"
    )


class SaleOut(BaseModel):
    id: str
    org_id: str
    user_id: str
    amount: float
    voucher_reference: str | None = None
    sale_date: date
    created_at: datetime
