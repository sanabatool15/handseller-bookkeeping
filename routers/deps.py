"""Shared FastAPI dependencies: current user + supabase client accessors."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from supabase import Client

from app.clients import get_supabase
from app.security import CurrentUser


def get_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_db() -> Client:
    return get_supabase()
