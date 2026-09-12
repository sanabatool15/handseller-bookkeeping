"""Ownership verification queries.

`get_ownership` is the single source of truth for "does this user own/belong
to this org". Every service operation must call it before touching org-scoped
data (sales, expenses, reports). This is the ONLY module import path other
repositories use to check ownership — do not duplicate this logic elsewhere.
"""
from app.db.client import get_client


def get_ownership(user_id: str, org_id: str) -> bool:
    """Return True if `user_id` owns the org identified by `org_id`.

    Queries public.orgs directly: an org is "owned" by a user when
    orgs.owner_id == user_id. Returns False (never raises) for a
    non-existent org_id, so callers can treat "not found" and "not owned"
    uniformly as 403 at the service layer.
    """
    client = get_client()
    response = (
        client.table("orgs")
        .select("id")
        .eq("id", org_id)
        .eq("owner_id", user_id)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def org_exists(org_id: str) -> bool:
    """Return True if an org with this id exists at all (regardless of owner)."""
    client = get_client()
    response = client.table("orgs").select("id").eq("id", org_id).limit(1).execute()
    return bool(response.data)
