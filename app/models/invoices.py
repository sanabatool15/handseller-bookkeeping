"""Invoices issued to customers, generally derived from one or more sales."""

from datetime import date

from pydantic import BaseModel

from app.models.common import ORMBase


class InvoiceBase(BaseModel):
    customer_id: str
    sale_id: str | None = None
    invoice_number: str
    issue_date: date
    due_date: date | None = None
    amount_due: float
    status: str = "unpaid"  # unpaid | partially_paid | paid | overdue | cancelled
    notes: str | None = None


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceUpdate(BaseModel):
    invoice_number: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    amount_due: float | None = None
    status: str | None = None
    notes: str | None = None


class Invoice(InvoiceBase, ORMBase):
    pass
