"""Payments received against sales/invoices."""

from datetime import date

from pydantic import BaseModel

from app.models.common import ORMBase


class PaymentBase(BaseModel):
    sale_id: str | None = None
    invoice_id: str | None = None
    customer_id: str | None = None
    amount: float
    payment_date: date
    method: str = "cash"  # cash | card | bank_transfer | check | other
    reference: str | None = None
    notes: str | None = None


class PaymentCreate(PaymentBase):
    pass


class PaymentUpdate(BaseModel):
    amount: float | None = None
    payment_date: date | None = None
    method: str | None = None
    reference: str | None = None
    notes: str | None = None


class Payment(PaymentBase, ORMBase):
    pass
