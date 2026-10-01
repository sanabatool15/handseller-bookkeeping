"""Triggers the async financial-advice Inngest job and returns immediately.

The router calling this MUST return 202 Accepted with the job_id — the actual
agent work happens out-of-band in `jobs/financial_agent_job.py`.
"""
from __future__ import annotations

from typing import Any

import inngest
from core.db import Db

from jobs.inngest_client import inngest_client
from jobs.financial_agent_job import EVENT_NAME
from repository import agent_jobs_repository
from repository import base as repo_base


async def trigger_financial_advice_job(
    db: Db, *, org_id: str, user_id: str, question: str | None = None
) -> dict[str, Any]:
    # Commit the job row BEFORE the event is sent: the Inngest worker may start immediately and
    # must find the row (its log INSERT ... SELECT FROM agent_jobs would otherwise see nothing).
    with repo_base.transaction(db):
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


def get_job_status(db: Db, *, org_id: str, job_id: str) -> dict[str, Any] | None:
    return agent_jobs_repository.get_job_scoped(db, job_id=job_id, org_id=org_id)


def get_job_logs(db: Db, *, org_id: str, job_id: str) -> list[dict[str, Any]] | None:
    """Logs of a job, or None if the job does not exist for this org (caller maps that to 404)."""
    if agent_jobs_repository.get_job_scoped(db, job_id=job_id, org_id=org_id) is None:
        return None
    return agent_jobs_repository.list_logs_for_job(db, job_id=job_id, org_id=org_id)
