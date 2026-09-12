"""All Supabase queries for the `agents` and `agent_logs` tables."""
from app.core import db


def get_agent_by_name(name: str) -> dict | None:
    client = db.get_client()
    resp = client.table("agents").select("*").eq("name", name).execute()
    return resp.data[0] if resp.data else None


def create_agent(name: str, description: str) -> dict:
    client = db.get_client()
    resp = client.table("agents").insert({"name": name, "description": description}).execute()
    return resp.data[0]


def log_agent_execution(
    agent_id: str,
    org_id: str,
    user_id: str,
    action_summary: str,
    insights_generated: dict,
) -> dict:
    client = db.get_client()
    payload = {
        "agent_id": agent_id,
        "org_id": org_id,
        "user_id": user_id,
        "action_summary": action_summary,
        "insights_generated": insights_generated,
    }
    resp = client.table("agent_logs").insert(payload).execute()
    return resp.data[0]


def list_agent_logs_scoped(org_id: str, limit: int = 20) -> list[dict]:
    client = db.get_client()
    resp = (
        client.table("agent_logs")
        .select("*")
        .eq("org_id", org_id)
        .order("executed_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []
