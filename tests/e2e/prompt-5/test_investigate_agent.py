"""OBSERVATIONAL e2e: investigate_agent (get_monthly_summary,
get_expense_breakdown_by_category, get_sales_breakdown_by_category,
web_search). See agent_scenarios.md.

Historical sales/expenses the investigator needs are seeded DIRECTLY via
the Supabase client in test setup (not through the HTTP API), per this
suite's setup convention. Drives the real chain and prints the captured
event stream for human review -- no assertion on which tool fired, its
arguments, or the wording/content of the final output.

Requires RUN_E2E=1 plus real OPENAI_API_KEY/Supabase/Redis.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest

from conftest import register_org, run_planner

RUN_E2E = os.environ.get("RUN_E2E") == "1"


def _seed_history(db, *, org_id: str, user_id: str, cleanup, story):
    """Seeds a sale and a couple of expenses directly via the Supabase
    client (not the HTTP API) so investigate_agent's summary/breakdown
    tools have real data to pull from this month."""
    now = dt.datetime.utcnow().isoformat()

    sale_row = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "amount": 50.0,
        "category": "retail",
        "description": "seed sale for investigate-agent observation",
        "created_at": now,
    }
    db.table("sales").insert(sale_row).execute()
    cleanup.track_row("sales", sale_row["id"], org_id)
    story.record("seeded sale", sale_row)

    expense_row = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "user_id": user_id,
        "amount": 300.0,
        "category": "packaging",
        "description": "seed expense for investigate-agent observation",
        "created_at": now,
    }
    db.table("expenses").insert(expense_row).execute()
    cleanup.track_row("expenses", expense_row["id"], org_id)
    story.record("seeded expense", expense_row)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_performance_question_observed(client, db, cleanup, story):
    """H3 happy path: a loss/performance question with seeded history.
    Prints the full handoff/tool-call/output trace so a human can judge
    whether investigate_agent pulled data before concluding anything, and
    whether it deferred web_search until it named a specific driver, per
    investigate_agent.md."""
    org_id, user_id = register_org(client, cleanup, story, "investigate-h3")
    _seed_history(db, org_id=org_id, user_id=user_id, cleanup=cleanup, story=story)

    message = "why did we lose money last month?"
    story.say(f"Sending message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None
    assert result.final_output is not None
    story.say(
        f"OBSERVE: first tool call was {capture.tool_names()[:1]!r} -- compare against "
        "investigate_agent.md's 'pull data before concluding, web_search never first' rule."
    )


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_ambiguous_transaction_and_question_observed(client, db, cleanup, story):
    """E1 edge case (investigate-agent focused): a message that could route
    to either specialist. Seeds a small amount of history first so that if
    it does land on investigate_agent, there is real data to pull. Prints
    the trace only -- see agent_scenarios.md E1 for the ambiguity this is
    designed to surface."""
    org_id, user_id = register_org(client, cleanup, story, "investigate-e1")
    _seed_history(db, org_id=org_id, user_id=user_id, cleanup=cleanup, story=story)

    message = "I spent $200 on ads, is that too much this month?"
    story.say(f"Sending deliberately ambiguous message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None
    assert result.final_output is not None
    story.say(f"OBSERVE: planner routed to {capture.handoffs!r} for this ambiguous message.")
