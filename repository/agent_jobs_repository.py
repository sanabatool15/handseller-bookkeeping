"""agent_jobs / agent_logs repository — resumable state tracking for Inngest jobs."""
from __future__ import annotations

from typing import Any, Optional

from supabase import Client

from repository.base import unwrap_single


def create_job(db: Client, *, job_name: str, org_id: str, requested_by: str | None, input_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = (
        db.table("agent_jobs")
        .insert(
            {
                "job_name": job_name,
                "org_id": org_id,
                "requested_by": requested_by,
                "status": "pending",
                "input_payload": input_payload or {},
            }
        )
        .execute()
    )
    row = unwrap_single(resp.data)
    if row is None:
        raise RuntimeError("Failed to create agent job")
    return row


def get_job_scoped(db: Client, *, job_id: str, org_id: str) -> Optional[dict[str, Any]]:
    resp = db.table("agent_jobs").select("*").eq("id", job_id).eq("org_id", org_id).limit(1).execute()
    return unwrap_single(resp.data)


def update_job_status(db: Client, *, job_id: str, org_id: str, status: str, current_step: str | None = None, result: dict[str, Any] | None = None, error_details: dict[str, Any] | None = None) -> Optional[dict[str, Any]]:
    updates: dict[str, Any] = {"status": status}
    if current_step is not None:
        updates["current_step"] = current_step
    if result is not None:
        updates["result"] = result
    if error_details is not None:
        updates["error_details"] = error_details
    resp = db.table("agent_jobs").update(updates).eq("id", job_id).eq("org_id", org_id).execute()
    return unwrap_single(resp.data)


def add_log(db: Client, *, job_id: str, step_name: str, action_summary: str, insights_generated: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = (
        db.table("agent_logs")
        .insert(
            {
                "job_id": job_id,
                "step_name": step_name,
                "action_summary": action_summary,
                "insights_generated": insights_generated or {},
            }
        )
        .execute()
    )
    row = unwrap_single(resp.data)
    if row is None:
        raise RuntimeError("Failed to write agent log")
    return row


def get_completed_steps(db: Client, *, job_id: str) -> set[str]:
    """Used by Inngest step functions to know which steps already ran, so a
    retried function invocation can skip re-doing completed work."""
    resp = db.table("agent_logs").select("step_name").eq("job_id", job_id).execute()
    return {row["step_name"] for row in (resp.data or [])}
