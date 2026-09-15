"""FastMCP server (stdio transport) exposing all 5 MCP primitives.

Run with:  python mcp_gateway/server.py
(or:       fastmcp run mcp_gateway/server.py)

FIXED (previously documented limitation): this package used to be named
`mcp/`, which collided with the top-level `mcp` package installed by the
`mcp` Python SDK (a dependency of `fastmcp`) — importing this directory as
a package (i.e. giving it an `__init__.py`) shadowed the real SDK and
broke `import fastmcp` entirely (verified:
`ModuleNotFoundError: No module named 'mcp.server'`). This package is now
named `mcp_gateway/` specifically to free up the `mcp` import for the real
SDK, so it can now have a normal `__init__.py` and be imported normally
(`from mcp_gateway.server import mcp`) — see `tests/unit/test_mcp_server.py`,
which no longer needs the `importlib.util` workaround this file's old
version required.
"""
from __future__ import annotations

import datetime as dt
import logging

from fastmcp import Context, FastMCP

from app.clients import get_supabase
from app.config import get_settings
from ai_agents.prompt_loader import load_prompt
from repository import agent_jobs_repository
from services import expenses_service, sales_service
from services.financial_report_service import monthly_ledger_csv, monthly_summary

logger = logging.getLogger("handseller.mcp")
logging.basicConfig(level=logging.INFO)

mcp = FastMCP(
    name="handseller-bookkeeping",
    instructions="MCP server exposing bookkeeping tools/resources/prompts for the handseller app.",
)


# ---------------------------------------------------------------------------
# 1) Tools
# ---------------------------------------------------------------------------
@mcp.tool
async def log_sale(org_id: str, user_id: str, amount: float, category: str = "general", description: str | None = None, customer_name: str | None = None, ctx: Context | None = None) -> dict:
    """Log a new sale for the given org."""
    db = get_supabase()
    sale = sales_service.create_sale(
        db, org_id=org_id, user_id=user_id, amount=amount, category=category,
        description=description, customer_name=customer_name,
    )
    if ctx:
        await ctx.log(f"Logged sale {sale['id']} for org {org_id}: ${amount}", level="info")
    return sale


@mcp.tool
async def log_expense(org_id: str, user_id: str, amount: float, category: str = "general", voucher_reference: str | None = None, description: str | None = None, ctx: Context | None = None) -> dict:
    """Log a new expense for the given org."""
    db = get_supabase()
    expense = expenses_service.create_expense(
        db, org_id=org_id, user_id=user_id, amount=amount, category=category,
        voucher_reference=voucher_reference, description=description,
    )
    if ctx:
        await ctx.log(f"Logged expense {expense['id']} for org {org_id}: ${amount}", level="info")
    return expense


@mcp.tool
async def trigger_financial_agent_job(org_id: str, user_id: str, ctx: Context | None = None) -> dict:
    """Trigger the async Inngest financial-advisor job for this org and return the job_id immediately."""
    from services.agent_job_service import trigger_financial_advice_job

    db = get_supabase()
    job = await trigger_financial_advice_job(db, org_id=org_id, user_id=user_id)
    if ctx:
        # 5) Logging: stream execution logs of Inngest job triggering back to the MCP client.
        await ctx.log(f"Triggered financial_advisor job {job['id']} for org {org_id}", level="info")
    return {"job_id": job["id"], "status": job["status"]}


# ---------------------------------------------------------------------------
# 2) Resources — virtual CSV ledger, read live from the database
# ---------------------------------------------------------------------------
@mcp.resource("ledger://{org_id}/monthly.csv")
async def monthly_ledger_resource(org_id: str) -> str:
    """Returns the current month's sales+expenses ledger as raw CSV text."""
    db = get_supabase()
    now = dt.datetime.utcnow()
    return monthly_ledger_csv(db, org_id=org_id, year=now.year, month=now.month)


# ---------------------------------------------------------------------------
# 3) Prompts — financial_audit template pulled from agents/prompts/*.md
# ---------------------------------------------------------------------------
@mcp.prompt
async def financial_audit(org_id: str) -> str:
    """Pre-filled financial-audit prompt for the given org's current-month ledger."""
    db = get_supabase()
    now = dt.datetime.utcnow()
    ledger_csv = monthly_ledger_csv(db, org_id=org_id, year=now.year, month=now.month)
    return load_prompt("financial_audit", org_id=org_id, year=now.year, month=now.month, ledger_csv=ledger_csv)


# ---------------------------------------------------------------------------
# 4) Sampling — server asks the MCP CLIENT's LLM to do inference (client pays,
#    not the server). Uses the raw MCP session's `create_message` (the
#    standard "sampling/createMessage" request) rather than the server's own
#    OpenAI key.
# ---------------------------------------------------------------------------
@mcp.tool
async def summarize_ledger_via_client_llm(org_id: str, ctx: Context) -> str:
    """Ask the CLIENT's LLM (via MCP sampling) to summarize this org's monthly ledger.

    This tool intentionally does NOT call OpenAI/any server-side LLM: it
    issues an MCP `sampling/createMessage` request back to the connected
    client, which is responsible for actually running the completion (and
    paying for it). Requires a client that supports sampling; if the client
    declines/doesn't support it, the underlying call raises and we surface
    a clear error instead of silently calling a server-side LLM instead.
    """
    db = get_supabase()
    now = dt.datetime.utcnow()
    ledger_csv = monthly_ledger_csv(db, org_id=org_id, year=now.year, month=now.month)

    from mcp.types import SamplingMessage, TextContent  # the MCP SDK types module (not this file)

    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"Summarize this month's ledger for org {org_id} in 3 bullet points:\n\n{ledger_csv}",
                ),
            )
        ],
        max_tokens=300,
    )
    text = getattr(result.content, "text", str(result.content))
    await ctx.log(f"Client-side sampling completed for org {org_id}", level="info")
    return text


# ---------------------------------------------------------------------------
# 5) Logging — stream server + Inngest job logs to the MCP client's log stream
# ---------------------------------------------------------------------------
@mcp.tool
async def stream_job_logs(org_id: str, job_id: str, ctx: Context) -> list[dict]:
    """Reads agent_logs for a job and re-emits each as an MCP log notification
    to the client's log stream (in addition to returning them as data)."""
    db = get_supabase()
    job = agent_jobs_repository.get_job_scoped(db, job_id=job_id, org_id=org_id)
    if job is None:
        await ctx.error(f"Job {job_id} not found for org {org_id}")
        return []

    resp = db.table("agent_logs").select("*").eq("job_id", job_id).order("executed_at").execute()
    logs = resp.data or []
    for log in logs:
        await ctx.log(f"[{log['step_name']}] {log['action_summary']}", level="info")
    return logs


if __name__ == "__main__":
    # Explicit stdio transport per spec section 6.
    mcp.run(transport="stdio")
