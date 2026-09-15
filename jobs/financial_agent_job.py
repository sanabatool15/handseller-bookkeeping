"""Inngest workflow: `financial/advice.requested`.

Runs the financial-advisor agent as a resilient, multi-step background job.
Each step is wrapped in `ctx.step.run(...)`, which Inngest memoizes: if the
function crashes/retries after step 2, step 1's memoized result is replayed
instead of re-executed. On top of Inngest's own step memoization we ALSO
persist progress to `agent_jobs`/`agent_logs` in Postgres (per the spec), so
job state is visible to the rest of the app (e.g. a status-polling endpoint)
independently of Inngest's internal step cache.

Assumption (documented): pinned against the `inngest` PyPI package's 0.5.x
API — `ctx.step.run(step_id, async_handler)`, function definition via
`inngest_client.create_function(trigger=..., fn_id=...)(handler)`, and the
handler signature `async def handler(ctx: inngest.Context, step: inngest.Step)`.
Older/newer SDK versions may differ slightly; see README "Inngest assumptions".
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import inngest

from app.clients import get_supabase
from jobs.inngest_client import inngest_client
from repository import agent_jobs_repository
from agents.api.financial_advisor_agent import run_financial_advisor
from agents.rules.fallback_engine import rule_based_financial_advice

EVENT_NAME = "financial/advice.requested"


async def _step_gather_data(job_id: str, org_id: str) -> dict[str, Any]:
    db = get_supabase()
    from services.financial_report_service import monthly_summary

    now = dt.datetime.utcnow()
    summary = monthly_summary(db, org_id=org_id, year=now.year, month=now.month)
    agent_jobs_repository.add_log(
        db, job_id=job_id, step_name="gather_data",
        action_summary="Collected current-month sales/expense totals from the ledger.",
        insights_generated=summary,
    )
    agent_jobs_repository.update_job_status(db, job_id=job_id, org_id=org_id, status="processing", current_step="gather_data")
    return summary


async def _step_run_agent(job_id: str, org_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    db = get_supabase()
    try:
        advice = await run_financial_advisor(summary)
        source = "openai_agent"
    except Exception:  # noqa: BLE001 - deliberate fallback on ANY agent/API failure
        advice = rule_based_financial_advice(summary)
        source = "rule_based_fallback"

    result = {"advice": advice, "source": source}
    agent_jobs_repository.add_log(
        db, job_id=job_id, step_name="run_agent",
        action_summary=f"Generated financial advice via {source}.",
        insights_generated=result,
    )
    agent_jobs_repository.update_job_status(db, job_id=job_id, org_id=org_id, status="processing", current_step="run_agent")
    return result


async def _step_finalize(job_id: str, org_id: str, result: dict[str, Any]) -> dict[str, Any]:
    db = get_supabase()
    agent_jobs_repository.add_log(
        db, job_id=job_id, step_name="finalize",
        action_summary="Marked job completed and persisted final result.",
        insights_generated=result,
    )
    agent_jobs_repository.update_job_status(db, job_id=job_id, org_id=org_id, status="completed", current_step="finalize", result=result)
    return result


@inngest_client.create_function(
    fn_id="financial-advisor-job",
    name="Financial Advisor Background Job",
    trigger=inngest.TriggerEvent(event=EVENT_NAME),
    retries=3,
)
async def financial_advisor_job(ctx: inngest.Context, step: inngest.Step) -> dict[str, Any]:
    job_id = ctx.event.data["job_id"]
    org_id = ctx.event.data["org_id"]

    summary = await step.run("gather-data", lambda: _step_gather_data(job_id, org_id))
    agent_result = await step.run("run-agent", lambda: _step_run_agent(job_id, org_id, summary))
    final = await step.run("finalize", lambda: _step_finalize(job_id, org_id, agent_result))
    return final


async def on_failure_handler(ctx: inngest.Context, step: inngest.Step) -> None:
    """Registered via on_failure so exhausted retries still mark the job failed."""
    db = get_supabase()
    job_id = ctx.event.data.get("job_id")
    org_id = ctx.event.data.get("org_id")
    if job_id and org_id:
        agent_jobs_repository.update_job_status(
            db, job_id=job_id, org_id=org_id, status="failed",
            error_details={"message": "All retries exhausted", "event": ctx.event.data},
        )


ALL_FUNCTIONS = [financial_advisor_job]
