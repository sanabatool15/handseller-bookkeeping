"""Sellers (handsellers) — the people who sell products door-to-door / in person."""

from pydantic import BaseModel, EmailStr

from app.models.common import ORMBase


class SellerBase(BaseModel):
    full_name: str
    email: EmailStr | None = None
    phone: str | None = None
    commission_rate: float = 0.0  # e.g. 0.10 == 10%
    is_active: bool = True
    notes: str | None = None


class SellerCreate(SellerBase):
    pass


class SellerUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    commission_rate: float | None = None
    is_active: bool | None = None
    notes: str | None = None


class Seller(SellerBase, ORMBase):
    pass
