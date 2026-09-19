"""OBSERVATIONAL e2e: planner routing/handoff behavior.

See agent_scenarios.md for the scenario write-up (grounded in
specs/06-agents-layer.md and ai_agents/prompts/planner_agent.md). These
tests do NOT assert which specialist the planner chooses or what it says --
they drive the real chain, print the full captured event stream, and leave
correctness judgment to a human reading the `pytest -s` output.

Requires RUN_E2E=1 (see conftest.py) plus a real OPENAI_API_KEY and real
Supabase/Redis. Without it, this whole module is skipped.
"""
from __future__ import annotations

import os

import pytest

from conftest import register_org, run_planner

RUN_E2E = os.environ.get("RUN_E2E") == "1"


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_h1_expense_message_observed(client, db, cleanup, story):
    """H1 happy path: a completed-expense message. Print the routing +
    tool-call trace; no assertion on which specialist was chosen."""
    org_id, user_id = register_org(client, cleanup, story, "h1-expense")
    message = "I spent $40 on packaging today"
    story.say(f"Sending planner message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None
    assert result.final_output is not None

    # Best-effort cleanup of whatever the agent may have created.
    rows = db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
    if rows.data:
        cleanup.track_row("expenses", rows.data[0]["id"], org_id)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_h2_sale_message_observed(client, db, cleanup, story):
    """H2 happy path: the planner prompt's own worked example for the
    record path. Print the trace only."""
    org_id, user_id = register_org(client, cleanup, story, "h2-sale")
    message = "sold 3 units to Acme for $150"
    story.say(f"Sending planner message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None
    assert result.final_output is not None

    rows = db.table("sales").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
    if rows.data:
        cleanup.track_row("sales", rows.data[0]["id"], org_id)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_e1_ambiguous_transaction_and_question_observed(client, db, cleanup, story):
    """E1 edge case: a message that satisfies both of the planner prompt's
    routing bullets at once ("I spent $200 on ads" is a completed
    transaction; "is that too much this month?" is a performance
    question). planner_agent.md gives no tie-breaking rule -- print
    whichever way it actually routes for a human to judge."""
    org_id, user_id = register_org(client, cleanup, story, "e1-ambiguous")
    message = "I spent $200 on ads, is that too much this month?"
    story.say(f"Sending deliberately ambiguous planner message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None
    assert result.final_output is not None
    story.say(
        f"OBSERVE: planner routed to {capture.handoffs!r} for an ambiguous message -- "
        "see agent_scenarios.md E1 for what to look for."
    )

    if "create_expense_record" in capture.tool_names():
        rows = db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
        if rows.data:
            cleanup.track_row("expenses", rows.data[0]["id"], org_id)
