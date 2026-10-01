"""Triggers the resilient background financial-advice agent job.

Per spec section 5: this NEVER runs the agent synchronously. It only creates
an `agent_jobs` row and fires an Inngest event, returning 202 Accepted with
the job_id right away.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from pydantic import BaseModel
from core.db import Db

from core.security import CurrentUser
from routers.deps import DB, get_current_user
from services import agent_job_service

router = APIRouter(prefix="/agent-jobs", tags=["agent-jobs"])


class FinancialAdviceRequest(BaseModel):
    question: str | None = None


@router.post("/financial-advice", status_code=202)
async def request_financial_advice(
    response: Response,
    body: FinancialAdviceRequest = Body(default_factory=FinancialAdviceRequest),
    user: CurrentUser = Depends(get_current_user),
    db: Db = DB,
):
    job = await agent_job_service.trigger_financial_advice_job(
        db, org_id=user.org_id, user_id=user.user_id, question=body.question
    )
    return {"job_id": job["id"], "status": job["status"], "message": "Financial advice job accepted for background processing."}


@router.get("/{job_id}")
def get_job_status(job_id: str, user: CurrentUser = Depends(get_current_user), db: Db = DB):
    job = agent_job_service.get_job_status(db, org_id=user.org_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
