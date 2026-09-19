"""OBSERVATIONAL e2e: Record Agent behavior, run directly (bypassing the
planner) via `build_agents()`'s `record_agent`, so the specialist's own
tool-calling/clarification behavior can be observed in isolation.

No rigid assertions about tool choice or output content -- only that the
run completes without raising. Full stream is printed for human review
(`pytest -s`). See agent_scenarios.md.

Requires RUN_E2E=1 (see conftest.py) plus a real OPENAI_API_KEY and real
Supabase/Redis.
"""
from __future__ import annotations

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


async def run_record_agent_directly(db, *, org_id: str, user_id: str, message: str, story):
    """Builds the real agents via build_agents() but drives
    Runner.run_streamed() against `record_agent` directly, skipping the
    planner handoff, to observe the specialist's own behavior in isolation."""
    from agents import Runner

    from ai_agents.api.financial_advisor_agent import DEFAULT_MAX_TURNS, build_agents

    _planner_agent, _investigate_agent, record_agent = build_agents(db, org_id=org_id, user_id=user_id)

    capture = StreamCapture(story)
    result = Runner.run_streamed(record_agent, message, max_turns=DEFAULT_MAX_TURNS)
    async for event in result.stream_events():
        capture.record(event)
    capture.print_summary()

    story.say(f"final_output: {getattr(result, 'final_output', None)!r}")
    return result, capture


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_expense_recording_observation(client, db, cleanup, story):
    """record_agent.md: given a clear expense description, expect (for
    human review) a create_expense_record call followed by a deep_link
    call, and a BookkeepingResult(mode='record_entry')."""
    org_id, user_id = register_org(client, cleanup, story, "record-h1-expense")
    message = "I spent $40 on packaging today"
    story.say(f"Sending message directly to record_agent: {message!r}")

    result, capture = await run_record_agent_directly(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None, "expected a run result object, run appears to have crashed"

    if "create_expense_record" in capture.tool_names():
        rows = db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
        if rows.data:
            cleanup.track_row("expenses", rows.data[0]["id"], org_id)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_sale_recording_observation(client, db, cleanup, story):
    """record_agent.md: given a clear sale description, expect (for human
    review) a create_sales_record call with amount/customer_name captured
    correctly."""
    org_id, user_id = register_org(client, cleanup, story, "record-h2-sale")
    message = "sold 3 units to Acme for $150"
    story.say(f"Sending message directly to record_agent: {message!r}")

    result, capture = await run_record_agent_directly(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None, "expected a run result object, run appears to have crashed"

    if "create_sales_record" in capture.tool_names():
        rows = db.table("sales").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
        if rows.data:
            cleanup.track_row("sales", rows.data[0]["id"], org_id)


# ---------------------------------------------------------------------------
# Edge case -- missing amount
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_missing_amount_observation(client, db, cleanup, story):
    """E2: 'log an expense for the packaging supplies' -- no amount given.
    record_agent.md step 2 says to ask a clarifying question instead of
    guessing. Print whatever the agent actually does (tool call with a
    placeholder amount, or a clarifying message) -- human judges whether
    the model is guessing, no hard assertion here."""
    org_id, user_id = register_org(client, cleanup, story, "record-e2-missing-amount")
    message = "log an expense for the packaging supplies"
    story.say(f"Sending message with no amount directly to record_agent: {message!r}")

    result, capture = await run_record_agent_directly(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None, "expected a run result object, run appears to have crashed"

    create_calls = [(n, a) for n, a in capture.tool_calls if n in ("create_expense_record", "create_sales_record")]
    if create_calls:
        story.say(
            f"REVIEW NOTE: agent called a create tool despite no amount in the message: {create_calls} "
            "-- check whether this looks like a guessed/placeholder amount."
        )
        for name, args in create_calls:
            if name == "create_expense_record":
                rows = (
                    db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
                )
                if rows.data:
                    cleanup.track_row("expenses", rows.data[0]["id"], org_id)
            elif name == "create_sales_record":
                rows = db.table("sales").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
                if rows.data:
                    cleanup.track_row("sales", rows.data[0]["id"], org_id)
    else:
        story.say("REVIEW NOTE: no create tool call fired -- consistent with asking a clarifying question.")
