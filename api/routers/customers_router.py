from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.db import Db

from core.security import CurrentUser
from routers.deps import DB, get_current_user
from services import customers_service

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerCreate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, customers_service.NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (customers_service.DuplicatePhoneError, customers_service.CustomerInUseError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


_DOMAIN_ERRORS = (
    customers_service.ValidationError,
    customers_service.NotFoundError,
    customers_service.DuplicatePhoneError,
    customers_service.CustomerInUseError,
)


@router.post("", status_code=201)
def create_customer(payload: CustomerCreate, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        return customers_service.create_customer(
            db, org_id=user.org_id, user_id=user.user_id, name=payload.name, phone=payload.phone,
            email=payload.email, address=payload.address, notes=payload.notes,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("")
def list_customers(limit: int = 100, offset: int = 0, q: str | None = None, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        return customers_service.list_customers(db, org_id=user.org_id, limit=limit, offset=offset, q=q)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("/{customer_id}/summary")
def get_customer_summary(customer_id: str, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        return customers_service.get_customer_summary(db, org_id=user.org_id, customer_id=customer_id)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.get("/{customer_id}")
def get_customer(customer_id: str, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        return customers_service.get_customer(db, org_id=user.org_id, customer_id=customer_id)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.put("/{customer_id}")
def update_customer(customer_id: str, payload: CustomerUpdate, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        # exclude_unset: only fields the client sent; an explicit null clears phone/email/address/notes.
        return customers_service.update_customer(db, org_id=user.org_id, customer_id=customer_id,
                                                 updates=payload.model_dump(exclude_unset=True))
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: str, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    try:
        customers_service.delete_customer(db, org_id=user.org_id, customer_id=customer_id)
    except _DOMAIN_ERRORS as exc:
        raise _http(exc) from exc
