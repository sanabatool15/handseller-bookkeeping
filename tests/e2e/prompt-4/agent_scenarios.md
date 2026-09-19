# Prompt-4 Agent Scenarios — Planner Routing & Handoff E2E

Basis for everything below: there is no `specs/ai_agents.md` in this repo,
but `specs/06-agents-layer.md` documents this three-agent architecture, and
this document is cross-checked against the actual implementation:

- `ai_agents/prompts/planner_agent.md` — planner's routing instructions
- `ai_agents/prompts/record_agent.md` — record specialist's instructions
- `ai_agents/prompts/investigate_agent.md` — investigate specialist's
  instructions
- `ai_agents/api/financial_advisor_agent.py` — `build_agents()` wires the
  planner (no tools, `handoffs=[handoff(investigate_agent),
  handoff(record_agent)]`) and `run_bookkeeping_agent()` drives one
  `Runner.run_streamed()` call over that chain, with an
  `error_handlers={"max_turns": ...}` fallback to
  `ai_agents/rules/fallback_engine.rule_based_financial_advice`
- `ai_agents/tools/bookkeeping_tools.py` — the two tool sets:
  - `build_investigate_tools`: `get_monthly_summary`,
    `get_expense_breakdown_by_category`, `get_sales_breakdown_by_category`,
    `web_search` (read-only; investigate agent only)
  - `build_record_tools`: `create_expense_record`, `create_sales_record`,
    `deep_link` (record agent only)
- `routers/agent_jobs_router.py` / `services/agent_job_service.py` — the
  actual HTTP surface: `POST /agent-jobs/financial-advice` returns `202` +
  `job_id` immediately (CLAUDE.md rule 3 — agent work runs in
  `jobs/financial_agent_job.py` via Inngest, never inline in the router),
  and `GET /agent-jobs/{job_id}` polls status/result, scoped by org_id (404
  for another org, per CLAUDE.md rule 2).

The planner itself never calls a tool and never answers directly — its only
allowed action is a single handoff to exactly one specialist agent, chosen
from the message content alone (record vs. investigate).

## Happy paths

### H1 — expense recording -> `record_agent`
Input: `"I spent $40 on packaging today"`

Expected: planner reasons the message describes a transaction that already
happened and needs to be logged (per `planner_agent.md` bullet 1) and hands
off to `record_agent`. `record_agent` should call `create_expense_record`
(amount=40.0, category inferred as something like "packaging") exactly once,
then call `deep_link(resource="expenses", ...)`, and return a
`BookkeepingResult(mode="record_entry", record_reference=<link>)`.

Verification: an `agent_updated_stream_event` with `new_agent.name ==
"Record agent"`; a `run_item_stream_event`/`tool_call` for
`create_expense_record` with `amount == 40.0`; a subsequent tool call for
`deep_link`; final `result["mode"] == "record_entry"` and
`result["record_reference"]` non-empty.

### H2 — sale recording -> `record_agent`
Input: `"sold 3 units to Acme for $150"`

Expected: same routing rule (bullet 1: "sold 3 units to Acme for $150" is
the prompt's own worked example), hands off to `record_agent`, which calls
`create_sales_record(amount=150.0, customer_name="Acme", ...)` once, then
`deep_link(resource="sales", ...)`.

Verification: handoff to `"Record agent"`; tool call `create_sales_record`
with `amount == 150.0` and `customer_name` containing `"Acme"`; final
`result["mode"] == "record_entry"`.

### H3 — performance / loss question -> `investigate_agent`
Input: `"why did we lose money last month?"`

Expected: planner routes per bullet 2 ("asks about performance, profit/loss
... or 'why' something happened") to `investigate_agent`, which per
`investigate_agent.md` must call `get_monthly_summary` (and likely
`get_expense_breakdown_by_category` / `get_sales_breakdown_by_category`)
*before* concluding anything, and may only call `web_search` after it has
named a specific cost driver from that data — never as its first tool call.

Verification: handoff to `"Investigate agent"`; the first tool-call event's
name is one of `get_monthly_summary` /
`get_expense_breakdown_by_category`/`get_sales_breakdown_by_category`,
never `web_search`; final `result["mode"] == "investigation"` with a
`root_cause` that names a concrete category (not the literal words "loss"
or "profit" per the prompt's own explicit rule).

## Edge cases — planner confusion / ambiguity

### E1 — message mixes a completed transaction AND a performance question
Input: `"I spent $200 on ads, is that too much this month?"`

This message satisfies parts of *both* routing bullets: it describes a
transaction that already happened ("I spent $200 on ads") **and** asks a
performance/comparison question ("is that too much"). The planner prompt
gives no explicit tie-breaking rule for this overlap.

Expected/acceptable behavior: the planner must still hand off to **exactly
one** specialist (never zero, never both — enforced by `handoffs=[...]`
only ever accepting one target per turn and `BookkeepingResult` being a
single structured output). Either handoff is defensible given the prompt's
ambiguity:
- If routed to `record_agent`: it should record the $200 ad expense (the
  concrete, actionable half of the message) and may note in `summary` that
  it did not evaluate whether the spend was "too much."
- If routed to `investigate_agent`: it should first record nothing (it has
  no create tools) and instead pull monthly summary/expense-breakdown data
  to answer the comparison question, but then the $200 spend described in
  the message never actually gets recorded as a transaction anywhere —
  this is the concrete bug risk this scenario is designed to catch.

Test assertion strategy: assert exactly one handoff event occurred (not
zero, not two), assert `result["mode"]` is one of the two valid literals,
and **flag (via a soft assertion / explicit log line, not a hard failure)**
if it routed to `investigate_agent`, since that path silently drops the
expense with no compensating tool call — this is documented as ambiguity
#1 below rather than asserted as a hard failure, since the prompt does not
actually mandate recording.

### E2 — conflicting/missing parameters (no amount given)
Input: `"log an expense for the packaging supplies"`

No amount is present at all. Per `record_agent.md` step 2: "If required
details (amount, or whether it's a sale or expense) are missing or
ambiguous, ask a clarifying question instead of guessing." Since the
planner still routes this to `record_agent` (it's clearly a
transaction-to-be-logged, not a performance question), the specialist
should NOT call `create_expense_record` with a fabricated amount.

Expected: handoff to `"Record agent"` still occurs; **no** tool_call event
for `create_expense_record` (or, if the SDK forces a final structured
output regardless, `record_reference` must be `None`/absent since
`deep_link` should never be called without a created record); the
`summary` should read as a clarifying question rather than a confirmation
of a logged transaction.

Test assertion strategy: assert no `create_expense_record` or
`create_sales_record` tool_call fired with an `amount` of `0`, `None`, or a
hallucinated placeholder; if a tool call fired at all, fail loudly (this
would be exactly the "guessing" the prompt forbids).

### E3 (bonus / SDK-level fallback) — max_turns exhaustion
Not a prompt-ambiguity case but a structural fallback worth covering: if
the live run exceeds `DEFAULT_MAX_TURNS` (10), `error_handlers={"max_turns":
_on_max_turns}` in `run_bookkeeping_agent` must catch it and synthesize a
`BookkeepingResult(mode="investigation", summary=<rule_based_financial_advice
output>)` rather than raising. This is exercised indirectly by asserting
`result.get("source") in ("openai_agent", "rule_based_fallback")` at the
job-polling layer (mirroring `test_financial_advice_job_journey.py`), since
forcing a real 10-turn loop from outside the agent is impractical in an
e2e test.

## Log verification strategy: intercepting `Runner.run_streamed()`

`run_bookkeeping_agent()` (in `ai_agents/api/financial_advisor_agent.py`)
already iterates `result.stream_events()` and logs on
`agent_updated_stream_event`. For test purposes we need the *raw* event
stream, not just the log line, so the tests in this directory drive the SDK
directly rather than only asserting on the HTTP job's final JSON:

1. Build the same three agents the production code builds, via
   `financial_advisor_agent.build_agents(db, org_id=..., user_id=...)`, so
   the test exercises the exact same prompts/tools/model wiring as
   production — never a hand-rolled copy of the routing logic.
2. Call `Runner.run_streamed(planner_agent, user_message, max_turns=10)`
   directly (imported from `agents`, matching the production import) and
   iterate `async for event in result.stream_events()`.
3. Bucket events into three lists as they arrive:
   - `handoffs`: events where `event.type == "agent_updated_stream_event"`
     — record `event.new_agent.name`.
   - `tool_calls`: events where `event.type == "run_item_stream_event"` and
     `event.item.type == "tool_call_item"` — record the tool's name and
     parsed arguments (`event.item.raw_item.name`,
     `json.loads(event.item.raw_item.arguments)`), tolerating SDK version
     drift by reading attributes defensively (`getattr(..., default)`) and
     skipping/logging any event shape that doesn't match rather than
     crashing the test on an unrelated event type.
   - `outputs`: events carrying a `message_output_item` (assistant prose),
     kept for debugging/story narration only, not asserted on directly.
4. After the stream drains, assert against `result.final_output` (the
   structured `BookkeepingResult`) **and** the recorded `handoffs`/
   `tool_calls` lists — asserting on both the final answer and the actual
   sequence of tool calls / handoffs is the whole point of this suite (a
   test that only checks the final `summary` string could pass even if the
   planner secretly called the wrong specialist and the specialist
   guessed).
5. Everything (org_id, user_id, every raw event repr) is written through
   the same `Story`/`expect()` narration pattern as `tests/e2e/prompt-3`,
   so a failure shows the full event sequence, not just a bare assertion
   diff.

## Prompt evaluation

**Rating: 6/10.**

The planner prompt (`ai_agents/prompts/planner_agent.md`) is short, clear on
its two named examples, and correctly forbids the planner from touching
tools or answering directly — that part is solid and matches the code
(`tools=[]` on the planner Agent). The problems are all in what it leaves
unsaid:

1. **No tie-breaking rule for messages that are both a completed
   transaction and a performance question** (see E1). "I spent $200 on
   ads, is that too much this month?" satisfies both of the prompt's own
   bullets simultaneously, and nothing in the prompt says which wins, or
   whether the planner should ever synthesize two handoffs / ask the user
   to disambiguate. Today the SDK wiring only supports one specialist per
   turn, so this is a real behavioral gap, not just a theoretical one.
2. **No guidance for messages that fit neither bucket** — e.g. "what's the
   capital of France" or a pure greeting. The prompt says "always end your
   turn with a handoff to exactly one of the two specialists," which
   forces a routing decision even when the message clearly isn't a
   bookkeeping request at all, likely producing a confidently wrong
   handoff and a specialist trying to force the input into
   `BookkeepingResult`.
3. **No amount/currency normalization guidance** handed down to
   `record_agent` from the planner — e.g. "spent 40 bucks," "$40.00," "forty
   dollars" all need to reach `create_expense_record(amount=40.0, ...)`,
   but the planner prompt doesn't mention preserving or normalizing
   amounts through the handoff, and relies entirely on `record_agent.md`'s
   own (also informal) instruction to "read the transaction details out of
   the conversation."
4. **No explicit rule for multiple transactions in one message** (e.g. "I
   spent $40 on packaging and sold 3 units for $150") — this hits *both*
   specialists' domains at once and the planner can still only hand off to
   one.
5. Minor: the prompt never says what to do if the message is a follow-up
   in an ongoing conversation already mid-handoff (e.g. the user answering
   `record_agent`'s clarifying question) — could the planner get invoked a
   second time and re-route mid-conversation? The orchestration code
   always starts a fresh `Runner.run_streamed()` from the planner per
   `run_bookkeeping_agent()` call, so conversation continuity/threading is
   left entirely to the caller, and the prompt doesn't warn against
   re-answering as if it were a new, unrelated message.

None of these are fatal — the ladder of prompts is otherwise coherent, each
specialist's prompt is unusually precise about tool ordering
(`investigate_agent.md`'s "never call web_search as a first move" rule is a
good, testable constraint) — but the planner prompt is the weakest link
because it is the single point where all ambiguity gets forced into a
binary choice with no escape hatch (no "ask for clarification" option, no
"neither" option).
