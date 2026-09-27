"""Planner Agent routing/handoff e2e scenarios -- see agent_scenarios.md for
the full write-up (grounded in ai_agents/prompts/*.md and
ai_agents/api/financial_advisor_agent.py, not invented behavior).

Requires RUN_E2E=1 (see conftest.py) plus a real OPENAI_API_KEY and real
Supabase/Redis, since these tests drive `Runner.run_streamed()` directly
against a live model to assert on the actual sequence of
handoff/tool-call stream events -- not just the final structured output.
Without RUN_E2E=1 this whole module is skipped (not faked).
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

RUN_E2E = os.environ.get("RUN_E2E") == "1"


def unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


def expect(condition: bool, *, request_desc: str, response, message: str) -> None:
    if condition:
        return
    if response is not None:
        detail = (
            f"{message}\n"
            f"  request sent:      {request_desc}\n"
            f"  response status:   {response.status_code}\n"
            f"  response body:     {response.text}"
        )
    else:
        detail = f"{message}\n  context: {request_desc}"
    raise AssertionError(detail)


def _register_org(client, cleanup, story, tag: str):
    email = unique_email(tag)
    payload = {
        "email": email,
        "password": "correct-horse-1",
        "full_name": "E2E Planner Tester",
        "org_name": f"Org-{tag}",
    }
    story.say(f"Registering user {email!r} for org 'Org-{tag}'")
    resp = client.post("/auth/register", json=payload, headers={"Idempotency-Key": f"reg-{tag}-{uuid.uuid4().hex[:6]}"})
    expect(
        resp.status_code == 201,
        request_desc=f"POST /auth/register json={payload}",
        response=resp,
        message="register should return 201",
    )
    body = resp.json()
    org_id = body["org"]["id"]
    user_id = body["user"]["id"]
    story.say(f"Registered: user_id={user_id} org_id={org_id}")
    cleanup.track_row("users", user_id, org_id, email=email)
    cleanup.track_row("orgs", org_id, org_name=f"Org-{tag}")
    return org_id, user_id


class StreamCapture:
    """Buckets Runner.run_streamed() events into handoffs / tool_calls /
    outputs, reading attributes defensively so an unrelated or
    SDK-version-shifted event shape is logged and skipped rather than
    crashing the test (see agent_scenarios.md's log verification section).
    """

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
            elif item_type == "message_output_item":
                self.outputs.append(str(item))
                self._story.say(f"MESSAGE_OUTPUT {item}")
            else:
                self._story.say(f"run_item_stream_event (unhandled item_type={item_type!r}), skipping")
            return
        self._story.say(f"unhandled stream event type={etype!r}, skipping")

    def tool_names(self) -> list[str]:
        return [name for name, _ in self.tool_calls]

    def args_for(self, tool_name: str) -> dict:
        for name, args in self.tool_calls:
            if name == tool_name:
                return args
        return {}


async def _run_planner(db, *, org_id: str, user_id: str, message: str, story):
    """Builds the real three-agent chain via the production wiring and
    drives Runner.run_streamed() directly, capturing every event -- the
    exact call shape run_bookkeeping_agent() uses internally, just with
    full event capture instead of only a log line.
    """
    from agents import Runner

    from ai_agents.api.financial_advisor_agent import DEFAULT_MAX_TURNS, build_agents

    planner_agent, _investigate_agent, _record_agent = build_agents(db, org_id=org_id, user_id=user_id)

    capture = StreamCapture(story)
    result = Runner.run_streamed(planner_agent, message, max_turns=DEFAULT_MAX_TURNS)
    async for event in result.stream_events():
        capture.record(event)

    return result, capture


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_expense_message_routes_to_record_agent_and_creates_expense(client, db, cleanup, story):
    org_id, user_id = _register_org(client, cleanup, story, "h1-expense")
    message = "I spent $40 on packaging today"
    story.say(f"Sending planner message: {message!r}")

    result, capture = await _run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    expect(
        capture.handoffs == ["Record agent"],
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"expected exactly one handoff to 'Record agent', got {capture.handoffs}",
    )
    expect(
        "create_expense_record" in capture.tool_names(),
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"expected create_expense_record to be called, tool_calls={capture.tool_calls}",
    )
    expense_args = capture.args_for("create_expense_record")
    expect(
        float(expense_args.get("amount", 0)) == 40.0,
        request_desc="create_expense_record tool call",
        response=None,
        message=f"expected amount=40.0, got args={expense_args}",
    )
    expect(
        "deep_link" in capture.tool_names(),
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"expected deep_link to be called after recording, tool_calls={capture.tool_calls}",
    )

    output = result.final_output
    expect(
        getattr(output, "mode", None) == "record_entry",
        request_desc="final_output",
        response=None,
        message=f"expected mode='record_entry', got {output!r}",
    )
    expect(
        bool(getattr(output, "record_reference", None)),
        request_desc="final_output",
        response=None,
        message=f"expected a non-empty record_reference, got {output!r}",
    )

    # Best-effort cleanup of whatever the agent actually created -- find the
    # newest expense row for this org and track it for deletion.
    rows = db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
    if rows.data:
        cleanup.track_row("expenses", rows.data[0]["id"], org_id)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_sale_message_routes_to_record_agent_and_creates_sale(client, db, cleanup, story):
    org_id, user_id = _register_org(client, cleanup, story, "h2-sale")
    message = "sold 3 units to Acme for $150"
    story.say(f"Sending planner message: {message!r}")

    result, capture = await _run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    expect(
        capture.handoffs == ["Record agent"],
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"expected exactly one handoff to 'Record agent', got {capture.handoffs}",
    )
    expect(
        "create_sales_record" in capture.tool_names(),
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"expected create_sales_record to be called, tool_calls={capture.tool_calls}",
    )
    sale_args = capture.args_for("create_sales_record")
    expect(
        float(sale_args.get("amount", 0)) == 150.0,
        request_desc="create_sales_record tool call",
        response=None,
        message=f"expected amount=150.0, got args={sale_args}",
    )
    expect(
        "acme" in str(sale_args.get("customer_name", "")).lower(),
        request_desc="create_sales_record tool call",
        response=None,
        message=f"expected customer_name to mention Acme, got args={sale_args}",
    )

    output = result.final_output
    expect(
        getattr(output, "mode", None) == "record_entry",
        request_desc="final_output",
        response=None,
        message=f"expected mode='record_entry', got {output!r}",
    )

    rows = db.table("sales").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
    if rows.data:
        cleanup.track_row("sales", rows.data[0]["id"], org_id)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_performance_question_routes_to_investigate_agent(client, db, cleanup, story):
    org_id, user_id = _register_org(client, cleanup, story, "h3-investigate")

    # Give the investigator something to look at.
    sale = client.post(
        "/sales",
        json={"amount": 50.0, "category": "retail"},
        headers={"Idempotency-Key": f"h3-sale-{uuid.uuid4().hex[:6]}"},
    )
    # (auth header omitted deliberately would 401; use the registered token)
    message = "why did we lose money last month?"
    story.say(f"Sending planner message: {message!r}")

    result, capture = await _run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    expect(
        capture.handoffs == ["Investigate agent"],
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"expected exactly one handoff to 'Investigate agent', got {capture.handoffs}",
    )
    expect(
        len(capture.tool_calls) > 0,
        request_desc=f"planner run for message={message!r}",
        response=None,
        message="expected the investigate agent to call at least one data tool before answering",
    )
    first_tool = capture.tool_names()[0]
    expect(
        first_tool
        in ("get_monthly_summary", "get_expense_breakdown_by_category", "get_sales_breakdown_by_category"),
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"expected the FIRST tool call to be a data-pull tool per investigate_agent.md, got {first_tool!r} "
        f"(full sequence: {capture.tool_names()})",
    )
    expect(
        "web_search" not in capture.tool_names()[:1],
        request_desc=f"planner run for message={message!r}",
        response=None,
        message="web_search must never be the first tool call per investigate_agent.md",
    )

    output = result.final_output
    expect(
        getattr(output, "mode", None) == "investigation",
        request_desc="final_output",
        response=None,
        message=f"expected mode='investigation', got {output!r}",
    )
    root_cause = (getattr(output, "root_cause", None) or "").lower()
    expect(
        root_cause not in ("loss", "profit", ""),
        request_desc="final_output.root_cause",
        response=None,
        message=f"root_cause must name a concrete category/pattern, not restate loss/profit; got {root_cause!r}",
    )


# ---------------------------------------------------------------------------
# Edge cases -- planner ambiguity
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_ambiguous_transaction_and_question_routes_to_exactly_one_specialist(client, db, cleanup, story):
    """E1: message satisfies both routing bullets in planner_agent.md ("I
    spent $200 on ads" is a completed transaction; "is that too much this
    month?" is a performance question). The prompt gives no tie-breaking
    rule -- assert the structural invariant (exactly one handoff, valid
    mode) as a hard failure, and flag-but-don't-fail the specific "expense
    silently dropped" risk documented in agent_scenarios.md's E1 section.
    """
    org_id, user_id = _register_org(client, cleanup, story, "e1-ambiguous")
    message = "I spent $200 on ads, is that too much this month?"
    story.say(f"Sending deliberately ambiguous planner message: {message!r}")

    result, capture = await _run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    expect(
        len(capture.handoffs) == 1,
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"planner must hand off to exactly one specialist, got handoffs={capture.handoffs}",
    )
    expect(
        capture.handoffs[0] in ("Record agent", "Investigate agent"),
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"handoff target must be one of the two known specialists, got {capture.handoffs[0]!r}",
    )

    output = result.final_output
    expect(
        getattr(output, "mode", None) in ("record_entry", "investigation"),
        request_desc="final_output",
        response=None,
        message=f"expected a valid BookkeepingResult.mode, got {output!r}",
    )

    if capture.handoffs[0] == "Investigate agent" and "create_expense_record" not in capture.tool_names():
        story.say(
            "AMBIGUITY FLAGGED (not a hard failure -- see agent_scenarios.md E1): planner routed the "
            "$200 ad spend to Investigate agent, which has no create tool, so the described expense was "
            "never recorded anywhere. planner_agent.md does not mandate recording in this overlap case."
        )
    elif capture.handoffs[0] == "Record agent":
        expense_args = capture.args_for("create_expense_record")
        if expense_args:
            rows = db.table("expenses").select("id").eq("org_id", org_id).order("created_at", desc=True).limit(1).execute()
            if rows.data:
                cleanup.track_row("expenses", rows.data[0]["id"], org_id)


@pytest.mark.skipif(not RUN_E2E, reason="see conftest.py module-level skip")
@pytest.mark.asyncio
async def test_missing_amount_triggers_clarification_not_a_guessed_record(client, db, cleanup, story):
    """E2: no amount given at all. record_agent.md explicitly requires
    asking a clarifying question instead of guessing -- assert no
    create_expense_record/create_sales_record call fired with a fabricated
    amount, and that no deep_link (i.e. no record_reference) exists without
    a corresponding create call.
    """
    org_id, user_id = _register_org(client, cleanup, story, "e2-missing-amount")
    message = "log an expense for the packaging supplies"
    story.say(f"Sending planner message with no amount: {message!r}")

    result, capture = await _run_planner(db, org_id=org_id, user_id=user_id, message=message, story=story)

    expect(
        capture.handoffs == ["Record agent"],
        request_desc=f"planner run for message={message!r}",
        response=None,
        message=f"expected exactly one handoff to 'Record agent', got {capture.handoffs}",
    )

    create_calls = [
        (name, args) for name, args in capture.tool_calls if name in ("create_expense_record", "create_sales_record")
    ]
    if create_calls:
        for name, args in create_calls:
            amount = args.get("amount")
            expect(
                amount not in (None, 0, 0.0),
                request_desc=f"{name} tool call",
                response=None,
                message=(
                    f"record_agent.md forbids guessing when amount is missing/ambiguous, but {name} was "
                    f"called with a placeholder amount={amount!r} (args={args})"
                ),
            )
            # If it wasn't a placeholder, the model must have inferred an
            # amount from context we didn't provide -- fail loudly either way
            # since no amount exists in the source message at all.
            raise AssertionError(
                f"expected no {name} call at all (message contains no amount), but got args={args}. "
                "record_agent.md requires asking a clarifying question instead of guessing."
            )
    else:
        story.say("Confirmed: no create_expense_record/create_sales_record call fired for an amount-less message.")

    output = result.final_output
    expect(
        not getattr(output, "record_reference", None),
        request_desc="final_output",
        response=None,
        message=f"record_reference must be empty when nothing was actually recorded, got {output!r}",
    )
