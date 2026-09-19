"""OBSERVATIONAL e2e: Investigate Agent behavior, run directly (bypassing
the planner) via `build_agents()`'s `investigate_agent`, with historical
sales/expenses data seeded DIRECTLY via the Supabase client (not through the
HTTP API), so the agent has something real to investigate.

No rigid assertions about tool choice, ordering, or output content -- only
that the run completes without raising. Full stream is printed for human
review (`pytest -s`). See agent_scenarios.md.

Requires RUN_E2E=1 (see conftest.py) plus a real OPENAI_API_KEY and real
Supabase/Redis.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid

import pytest

RUN_E2E = os.environ.get("RUN_E2E") == "1"


def unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


def register_org(client, cleanup, story, tag: str):
    email = unique_email(tag)
    payload = {
        "email": email,
        "password": "correct-horse-1",
        "full_name": "E2E Observational Tester",
        "org_name": f"Org-{tag}",
    }
    story.say(f"Registering user {email!r} for org 'Org-{tag}'")
    resp = client.post(
        "/auth/register",
        json=payload,
        headers={"Idempotency-Key": f"reg-{tag}-{uuid.uuid4().hex[:6]}"},
    )
    if resp.status_code != 201:
        raise AssertionError(f"registration failed unexpectedly: {resp.status_code} {resp.text}")
    body = resp.json()
    org_id = body["org"]["id"]
    user_id = body["user"]["id"]
    story.say(f"Registered: user_id={user_id} org_id={org_id}")
    cleanup.track_row("users", user_id, org_id, email=email)
    cleanup.track_row("orgs", org_id, org_name=f"Org-{tag}")
    return org_id, user_id


def seed_historical_data(db, cleanup, story, *, org_id: str, user_id: str) -> None:
    """Seeds sales/expenses rows directly via the Supabase client (setup,
    not the behavior under test) so the investigate agent's data-pull tools
    have something concrete to find. Deliberately skews expenses toward one
    category (packaging) so a human reviewer can sanity-check whether the
    agent actually names it as the driver."""
    now = dt.datetime.utcnow().isoformat()

    expense_rows = [
        {"org_id": org_id, "user_id": user_id, "amount": 500.0, "category": "packaging", "description": "bulk boxes", "created_at": now},
        {"org_id": org_id, "user_id": user_id, "amount": 480.0, "category": "packaging", "description": "bulk tape", "created_at": now},
        {"org_id": org_id, "user_id": user_id, "amount": 60.0, "category": "utilities", "description": "electricity", "created_at": now},
    ]
    for row in expense_rows:
        inserted = db.table("expenses").insert(row).execute()
        if inserted.data:
            record_id = inserted.data[0]["id"]
            cleanup.track_row("expenses", record_id, org_id)
            story.say(f"seeded expense {record_id}: {row}")

    sale_rows = [
        {"org_id": org_id, "user_id": user_id, "amount": 300.0, "category": "retail", "description": "storefront sales", "created_at": now},
    ]
    for row in sale_rows:
        inserted = db.table("sales").insert(row).execute()
        if inserted.data:
            record_id = inserted.data[0]["id"]
            cleanup.track_row("sales", record_id, org_id)
            story.say(f"seeded sale {record_id}: {row}")


class StreamCapture:
    def __init__(self, story):
        self.handoffs: list[str] = []
        self.tool_calls: list[tuple[str, dict]] = []
        self.outputs: list[str] = []
        self._story = story

    def record(self, event) -> None:
        etype = getattr(event, "type", None)
        if etype == "agent_updated_stream_event":
            name = getattr(getattr(event, "new_agent", None), "name", "?")
            self.handoffs.append(name)
            self._story.say(f"HANDOFF -> {name}")
            return
        if etype == "run_item_stream_event":
            item = getattr(event, "item", None)
            item_type = getattr(item, "type", None)
            if item_type == "tool_call_item":
                raw = getattr(item, "raw_item", None)
                name = getattr(raw, "name", "?")
                raw_args = getattr(raw, "arguments", "{}") or "{}"
                try:
                    args = json.loads(raw_args)
                except (TypeError, ValueError):
                    args = {"_raw": raw_args}
                self.tool_calls.append((name, args))
                self._story.say(f"TOOL_CALL {name}({args})")
            elif item_type == "tool_call_output_item":
                self._story.say(f"TOOL_CALL_OUTPUT {getattr(item, 'output', None)!r}")
            elif item_type == "message_output_item":
                self.outputs.append(str(item))
                self._story.say(f"MESSAGE_OUTPUT {item}")
            else:
                self._story.say(f"run_item_stream_event (unhandled item_type={item_type!r}), skipping")
            return
        self._story.say(f"unhandled stream event type={etype!r}, skipping")

    def tool_names(self) -> list[str]:
        return [name for name, _ in self.tool_calls]

    def print_summary(self) -> None:
        self._story.say("=" * 72)
        self._story.say("STREAM SUMMARY (for human review -- no pass/fail judgment here)")
        self._story.say(f"  handoffs:   {self.handoffs}")
        self._story.say(f"  tool_calls: {self.tool_calls}")
        self._story.say(f"  outputs:    {self.outputs}")
        self._story.say("=" * 72)


async def run_investigate_agent_directly(db, *, org_id: str, user_id: str, message: str, story):
    """Builds the real agents via build_agents() but drives
    Runner.run_streamed() against `investigate_agent` directly, skipping
    the planner handoff, to observe the specialist's own behavior against
    the seeded historical data."""
    from agents import Runner

    from ai_agents.api.financial_advisor_agent import DEFAULT_MAX_TURNS, build_agents

    _planner_agent, investigate_agent, _record_agent = build_agents(db, org_id=org_id, user_id=user_id)

    capture = StreamCapture(story)
    result = Runner.run_streamed(investigate_agent, message, max_turns=DEFAULT_MAX_TURNS)
    async for event in result.stream_events():
        capture.record(event)
    capture.print_summary()

    story.say(f"final_output: {getattr(result, 'final_output', None)!r}")
    return result, capture


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_performance_question_with_seeded_history_observation(client, db, cleanup, story):
    """H3: seed historical sales/expenses directly via Supabase (packaging
    expenses dominate), then ask 'why did we lose money last month?'.
    investigate_agent.md says: pull get_monthly_summary /
    breakdown tools before concluding, name a concrete driver, and only
    call web_search after a driver is identified. Print the full sequence
    for a human to judge whether that actually happened -- no hard
    assertion on tool order or root_cause content."""
    org_id, user_id = register_org(client, cleanup, story, "investigate-h3")
    seed_historical_data(db, cleanup, story, org_id=org_id, user_id=user_id)

    message = "why did we lose money last month?"
    story.say(f"Sending message directly to investigate_agent: {message!r}")

    result, capture = await run_investigate_agent_directly(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None, "expected a run result object, run appears to have crashed"

    story.say(
        "REVIEW NOTE: check whether the first tool call was a data-pull tool (get_monthly_summary / "
        "get_expense_breakdown_by_category / get_sales_breakdown_by_category) rather than web_search, "
        f"and whether root_cause names 'packaging' specifically. tool_calls={capture.tool_names()}"
    )


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_performance_question_with_no_history_observation(client, db, cleanup, story):
    """Edge case: ask the investigate agent a performance question for an
    org with NO historical sales/expenses data at all. Print how the agent
    handles pulling from an empty dataset -- human reviews whether it
    hallucinates a driver or correctly reports there's nothing to analyze
    yet. No seeding here deliberately."""
    org_id, user_id = register_org(client, cleanup, story, "investigate-e-empty")

    message = "why did we lose money last month?"
    story.say(f"Sending message directly to investigate_agent for an org with NO seeded data: {message!r}")

    result, capture = await run_investigate_agent_directly(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None, "expected a run result object, run appears to have crashed"

    story.say(
        "REVIEW NOTE: this org has no seeded sales/expenses. Check whether the agent's root_cause is "
        "grounded in the (empty) data or appears fabricated. "
        f"tool_calls={capture.tool_names()}, final_output={getattr(result, 'final_output', None)!r}"
    )
