"""OBSERVATIONAL e2e: record_agent (create_expense_record/create_sales_record
+ deep_link). See agent_scenarios.md.

Drives the real chain via `Runner.run_streamed()` and prints the captured
event stream for human review -- no assertion on which tool fired, what
arguments it received, or the wording of the final output. The only
functional check is that the run completes without raising.

Requires RUN_E2E=1 plus real OPENAI_API_KEY/Supabase/Redis.
"""
from __future__ import annotations

import os

import pytest

from conftest import register_org, run_planner

RUN_E2E = os.environ.get("RUN_E2E") == "1"


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_expense_recording_message_observed(client, db, cleanup, story):
    """H1 (record-agent focused): a plain expense message. Prints the full
    handoff/tool-call/output trace for record_agent's behavior."""
    org_id, user_id = register_org(client, cleanup, story, "record-h1")
    message = "I spent $40 on packaging today"
    story.say(f"Sending message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None
    assert result.final_output is not None

    rows = db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
    if rows.data:
        cleanup.track_row("expenses", rows.data[0]["id"], org_id)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_sale_recording_message_observed(client, db, cleanup, story):
    """H2 (record-agent focused): the planner prompt's own worked example
    for a sale. Prints the full trace."""
    org_id, user_id = register_org(client, cleanup, story, "record-h2")
    message = "sold 3 units to Acme for $150"
    story.say(f"Sending message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None
    assert result.final_output is not None

    rows = db.table("sales").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
    if rows.data:
        cleanup.track_row("sales", rows.data[0]["id"], org_id)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_missing_amount_message_observed(client, db, cleanup, story):
    """E2 edge case: no amount given at all. record_agent.md says to ask a
    clarifying question instead of guessing -- print whatever the model
    actually does (tool call or not) for a human to judge against that
    rule. No hard assertion on the outcome."""
    org_id, user_id = register_org(client, cleanup, story, "record-e2")
    message = "log an expense for the packaging supplies"
    story.say(f"Sending message with no amount: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None
    assert result.final_output is not None
    story.say(
        f"OBSERVE: tool_calls={capture.tool_calls!r} for an amount-less message -- "
        "check against record_agent.md's 'ask, don't guess' rule (agent_scenarios.md E2)."
    )

    if "create_expense_record" in capture.tool_names():
        rows = db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
        if rows.data:
            cleanup.track_row("expenses", rows.data[0]["id"], org_id)
