"""Triggers the resilient background financial-advice agent job.

Per spec section 5: this NEVER runs the agent synchronously. It only creates
an `agent_jobs` row and fires an Inngest event, returning 202 Accepted with
the job_id right away.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from supabase import Client

from app.security import CurrentUser
from routers.deps import get_current_user, get_db
from services import agent_job_service

router = APIRouter(prefix="/agent-jobs", tags=["agent-jobs"])


@router.post("/financial-advice", status_code=202)
async def request_financial_advice(response: Response, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    job = await agent_job_service.trigger_financial_advice_job(db, org_id=user.org_id, user_id=user.user_id)
    return {"job_id": job["id"], "status": job["status"], "message": "Financial advice job accepted for background processing."}


@router.get("/{job_id}")
def get_job_status(job_id: str, user: CurrentUser = Depends(get_current_user), db: Client = Depends(get_db)):
    job = agent_job_service.get_job_status(db, org_id=user.org_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
