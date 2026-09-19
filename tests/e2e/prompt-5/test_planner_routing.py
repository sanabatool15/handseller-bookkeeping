"""OBSERVATIONAL e2e: Planner Agent routing/handoff behavior.

No rigid assertions about which specialist gets chosen or what tools fire --
this suite's job is to drive Runner.run_streamed() against the real
three-agent chain (via build_agents()) and print the full captured event
stream so a human reviews it (`pytest -s`). See agent_scenarios.md.

Requires RUN_E2E=1 (see conftest.py) plus a real OPENAI_API_KEY and real
Supabase/Redis. Helper functions are duplicated here (rather than imported
across the hyphenated `prompt-5` directory name, which is not a valid Python
package path) following the same convention as tests/e2e/prompt-4.
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
    """Buckets Runner.run_streamed() events and prints every one, for human
    review. Reads attributes defensively so an SDK-version-shifted event
    shape is logged and skipped rather than crashing the observation run."""

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


async def run_planner(db, *, org_id: str, user_id: str, message: str, story):
    """Builds the real three-agent chain via build_agents() and drives
    Runner.run_streamed() directly against the planner, capturing and
    printing every event for human review -- the exact call shape
    run_bookkeeping_agent() uses internally."""
    from agents import Runner

    from ai_agents.api.financial_advisor_agent import DEFAULT_MAX_TURNS, build_agents

    planner_agent, _investigate_agent, _record_agent = build_agents(db, org_id=org_id, user_id=user_id)

    capture = StreamCapture(story)
    result = Runner.run_streamed(planner_agent, message, max_turns=DEFAULT_MAX_TURNS)
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
async def test_expense_message_observation(client, db, cleanup, story):
    """H1: 'I spent $40 on packaging today' -- expect (for human review) a
    handoff to Record agent, a create_expense_record call, and a deep_link
    call. No hard assertion on any of that -- just observe and print."""
    org_id, user_id = register_org(client, cleanup, story, "h1-expense")
    message = "I spent $40 on packaging today"
    story.say(f"Sending planner message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None, "expected a run result object, run appears to have crashed"

    if "create_expense_record" in capture.tool_names():
        rows = db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
        if rows.data:
            cleanup.track_row("expenses", rows.data[0]["id"], org_id)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_sale_message_observation(client, db, cleanup, story):
    """H2: 'sold 3 units to Acme for $150' -- expect (for human review) a
    handoff to Record agent and a create_sales_record call."""
    org_id, user_id = register_org(client, cleanup, story, "h2-sale")
    message = "sold 3 units to Acme for $150"
    story.say(f"Sending planner message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None, "expected a run result object, run appears to have crashed"

    if "create_sales_record" in capture.tool_names():
        rows = db.table("sales").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
        if rows.data:
            cleanup.track_row("sales", rows.data[0]["id"], org_id)


# ---------------------------------------------------------------------------
# Edge case -- planner ambiguity
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_ambiguous_message_observation(client, db, cleanup, story):
    """E1: 'I spent $200 on ads, is that too much this month?' -- satisfies
    both planner routing bullets at once (a completed transaction AND a
    performance question). planner_agent.md gives no tie-breaking rule.
    Print whichever specialist gets picked and whatever tools fire --
    a human reviews for reasonableness, no hard-coded expectation here."""
    org_id, user_id = register_org(client, cleanup, story, "e1-ambiguous")
    message = "I spent $200 on ads, is that too much this month?"
    story.say(f"Sending deliberately ambiguous planner message: {message!r}")

    result, capture = await run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    assert result is not None, "expected a run result object, run appears to have crashed"
    story.say(
        "REVIEW NOTE: this message satisfies both planner_agent.md routing bullets. "
        f"Observed handoff(s): {capture.handoffs}. No hard expectation on which is 'correct'."
    )

    if "create_expense_record" in capture.tool_names():
        rows = db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
        if rows.data:
            cleanup.track_row("expenses", rows.data[0]["id"], org_id)
