"""Repository functions for the `orgs` table. Only Supabase queries live here."""
from app.db.client import get_client


def create_org(name: str, owner_id: str) -> dict:
    client = get_client()
    response = (
        client.table("orgs").insert({"name": name, "owner_id": owner_id}).execute()
    )
    return response.data[0]


def get_org_by_id(org_id: str) -> dict | None:
    client = get_client()
    response = client.table("orgs").select("*").eq("id", org_id).limit(1).execute()
    return response.data[0] if response.data else None


def list_orgs_for_owner(owner_id: str) -> list[dict]:
    client = get_client()
    response = client.table("orgs").select("*").eq("owner_id", owner_id).execute()
    return response.data or []
