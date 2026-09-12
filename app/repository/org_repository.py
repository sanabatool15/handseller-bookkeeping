"""Repository for orgs / org_members. This is the ONLY layer allowed to
execute Supabase queries related to organization membership.
"""
from app.core import db


def get_ownership(user_id: str, org_id: str) -> bool:
    """Verify that `user_id` belongs to `org_id` (as owner or member).

    Used during authentication setup to confirm organization membership
    before trusting an org_id claim from a client-supplied token.
    """
    client = db.get_client()

    owner_resp = (
        client.table("orgs")
        .select("id")
        .eq("id", org_id)
        .eq("owner_id", user_id)
        .execute()
    )
    if owner_resp.data:
        return True

    member_resp = (
        client.table("org_members")
        .select("org_id")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(member_resp.data)


def get_org_by_id_scoped(org_id: str, user_id: str) -> dict | None:
    """Fetch an org only if the requesting user owns/is a member of it."""
    if not get_ownership(user_id=user_id, org_id=org_id):
        return None
    client = db.get_client()
    resp = client.table("orgs").select("*").eq("id", org_id).execute()
    return resp.data[0] if resp.data else None


def create_org(name: str, owner_id: str) -> dict:
    client = db.get_client()
    resp = client.table("orgs").insert({"name": name, "owner_id": owner_id}).execute()
    return resp.data[0]
