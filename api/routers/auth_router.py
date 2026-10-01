from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from core.db import Db
from routers.deps import get_sql_db
from services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    org_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, db: Db = Depends(get_sql_db)):
    try:
        return auth_service.register(
            db, email=payload.email, password=payload.password,
            full_name=payload.full_name, org_name=payload.org_name,
        )
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/login")
def login(payload: LoginRequest, db: Db = Depends(get_sql_db)):
    try:
        return auth_service.login(db, email=payload.email, password=payload.password)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
