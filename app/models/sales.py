"""Sales / transactions — a seller selling one or more products to a customer."""

from datetime import date

from pydantic import BaseModel

from app.models.common import ORMBase


class SaleItem(BaseModel):
    product_id: str
    quantity: int
    unit_price: float


class SaleBase(BaseModel):
    seller_id: str
    customer_id: str | None = None
    sale_date: date
    items: list[SaleItem]
    status: str = "completed"  # completed | refunded | voided
    notes: str | None = None


class SaleCreate(SaleBase):
    pass


class SaleUpdate(BaseModel):
    customer_id: str | None = None
    sale_date: date | None = None
    items: list[SaleItem] | None = None
    status: str | None = None
    notes: str | None = None


class Sale(SaleBase, ORMBase):
    total_amount: float = 0.0
