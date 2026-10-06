"""Triggers the async financial-advice Inngest job and returns immediately.

The router calling this MUST return 202 Accepted with the job_id — the actual
agent work happens out-of-band in `jobs/financial_agent_job.py`.
"""
from __future__ import annotations

from typing import Any

import inngest
from supabase import Client

from jobs.inngest_client import inngest_client
from jobs.financial_agent_job import EVENT_NAME
from repository import agent_jobs_repository


async def trigger_financial_advice_job(
    db: Client, *, org_id: str, user_id: str, question: str | None = None
) -> dict[str, Any]:
    job = agent_jobs_repository.create_job(
        db,
        job_name="financial_advisor",
        org_id=org_id,
        requested_by=user_id,
        input_payload={"question": question} if question else None,
    )

    await inngest_client.send(
        inngest.Event(
            name=EVENT_NAME,
            data={"job_id": job["id"], "org_id": org_id, "requested_by": user_id, "question": question},
        )
    )
    return job


def get_job_status(db: Client, *, org_id: str, job_id: str) -> dict[str, Any] | None:
    return agent_jobs_repository.get_job_scoped(db, job_id=job_id, org_id=org_id)
