from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class OrgCreate(BaseModel):
    """Body for creating an org. owner_id is always the authenticated user, never client-supplied."""

    name: str = Field(..., min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("'name' must not be blank")
        return v


class OrgOut(BaseModel):
    id: str
    name: str
    owner_id: str
    created_at: datetime | None = None
