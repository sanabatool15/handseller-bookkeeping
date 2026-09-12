"""Shared model helpers."""

from datetime import datetime

from pydantic import BaseModel


class ORMBase(BaseModel):
    """Base for models returned from the database (includes id/timestamps)."""

    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
