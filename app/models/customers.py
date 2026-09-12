"""Customers who purchase products from sellers."""

from pydantic import BaseModel, EmailStr

from app.models.common import ORMBase


class CustomerBase(BaseModel):
    full_name: str
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    notes: str | None = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    notes: str | None = None


class Customer(CustomerBase, ORMBase):
    pass
