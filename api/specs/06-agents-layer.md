# Agents Layer (`ai_agents/`, formerly `agents/`)

## What we did

Split the AI-facing code into four purpose-specific subfolders, exactly as
the spec for this step demanded:

- **`ai_agents/prompts/*.md`** — every system/agent prompt as a Markdown
  file (`financial_advisor_system.md` — legacy, kept for reference;
  `planner_agent.md`, `investigate_agent.md`, `record_agent.md` — the
  current three-agent architecture; `financial_audit.md`), loaded at
  runtime by `ai_agents/prompt_loader.py`. **No prompt text is ever a
  Python string literal in this codebase.**
- **`ai_agents/api/financial_advisor_agent.py`** — orchestration against
  the OpenAI Agents SDK, now a **planner + handoff, three-agent
  architecture** instead of one agent:
  - `planner_agent` holds zero tools and only routes, via `handoff()`, to
    `investigate_agent` (read-only summary/breakdown/`web_search` tools) or
    `record_agent` (record-creation tools + `deep_link`). A handoff passes
    the full conversation history by default, so the planner's stated
    reasoning carries over to whichever specialist it hands off to.
  - Both specialists declare `output_type=BookkeepingResult` (a pydantic
    model: `mode`, `summary`, `root_cause`, `recommendation`,
    `used_web_search`, `record_reference`). The planner deliberately does
    **not** set `output_type` — its only action is a handoff, never a
    final answer (see `ai_agents/api/financial_advisor_agent.py`'s module
    docstring for why `output_type` + `handoffs` on the same agent was left
    unconfirmed against the SDK docs and sidestepped rather than guessed
    at).
  - `run_bookkeeping_agent(db, org_id, user_id, user_message, ...)` drives
    the whole chain with **one** `Runner.run_streamed(planner_agent, ...)`
    call, `max_turns=10`, and `error_handlers={"max_turns": on_max_turns}`
    falling back to `rule_based_financial_advice`. The event stream
    (`stream_events()`) surfaces `agent_updated_stream_event` on every
    handoff and `run_item_stream_event` for each tool call.
  - `run_financial_advisor(db, monthly_summary)` is the backward-compatible
    entry point the proactive monthly-advice job still calls: it
    synthesizes an investigation-style question from the summary (so it
    always routes to `investigate_agent`) and returns the specialist's
    `summary`/`recommendation` as a plain string, same shape as before.
  - Tool functions themselves are unchanged business logic — see
    `ai_agents/tools/bookkeeping_tools.py`, which wraps the existing
    `services/financial_report_service.py`, `services/expenses_service.py`
    and `services/sales_service.py` calls as `@function_tool` closures
    scoped to one run's `org_id`/`user_id` (never supplied by the LLM).
- **`ai_agents/rules/fallback_engine.py`** — a fully deterministic, offline
  rule engine (`rule_based_financial_advice`) that produces useful advice
  from the same monthly-summary input **without any network call or LLM**.
- **`ai_agents/tools/`** — small standalone utilities (`web_search.py`,
  `deep_link.py`) available to agent code, kept separate from orchestration
  logic so they can be tested/reused independently.

This package was originally named `agents/`, exactly matching the spec's
literal directory-name requirement. It has since been **renamed to
`ai_agents/`** to fix a real package-name collision — see below. The
subfolder names and every file's responsibility are otherwise unchanged
from the original design.

## Why we did it: prompts as files, not strings

Keeping prompts in `.md` files rather than Python strings means:

1. **Prompts can be edited, reviewed, and diffed like content, not code.**
   A non-engineer (or a future you, months later) can tune the financial
   advisor's tone or add a constraint without touching `.py` files or
   understanding string formatting/escaping inside Python source.
2. **Prompts are versioned independently of orchestration logic.** A change
   to how the agent is *prompted* doesn't require a code review of how it's
   *invoked* — these are genuinely different concerns and earlier ladder
   steps (before this constraint existed) mixed them together, making a
   simple wording tweak look like a code change in diffs.
3. **The same prompt is reusable across surfaces.** `financial_audit.md` is
   loaded both if you build a CLI/script around it later and by
   `mcp_gateway/server.py`'s `financial_audit` MCP prompt primitive — one
   file, one source of truth, instead of the prompt text duplicated in two
   Python modules.

## Why we did it: a deterministic rule-based fallback

The requirement to have `ai_agents/rules/` as an **offline fallback
engine** (not just error handling) exists because a bookkeeping tool's
users depend on getting *some* actionable answer when they ask "how's my
business doing this month" — and an AI agent call is one of the least
reliable parts of the whole system (network dependency, API key
configuration, rate limits, cost). `jobs/financial_agent_job.py`'s
`_step_run_agent` catches *any* exception from `run_financial_advisor` and
calls `rule_based_financial_advice` instead — this means a misconfigured
`OPENAI_API_KEY`, a network outage, or the SDK simply not being installed
never results in "sorry, no advice today," only in a simpler,
non-AI-generated version of the same advice. This is exercised directly in
`tests/unit/test_fallback_engine.py`.

## The `agents` package-name collision — fixed

This package was renamed from `agents/` to `ai_agents/` to resolve a name
collision with the third-party `openai-agents` SDK (which also installs as
a top-level `agents` module). This is fixed — do not rename it back.

## Where this is tested

- `tests/unit/test_financial_advisor_agent.py` — asserts
  `run_financial_advisor` behaves correctly under **either** valid outcome
  now that the SDK is genuinely reachable: it either returns a non-empty
  string (the live SDK ran successfully) or raises the documented
  `AgentUnavailableError` (SDK not installed / no network / no API key /
  the live call failed) — never anything else. Which outcome actually
  happens in a given test run depends on real environment configuration
  (is `openai-agents` installed, is `OPENAI_API_KEY` set), not on an import
  bug, which is the whole point of the fix.
- `tests/unit/test_fallback_engine.py` — confirms the rule-based path
  produces sensible advice from a given monthly summary.
- `tests/unit/test_prompt_loader.py` — confirms prompts load from the
  `.md` files (and fail loudly, not silently with an empty string, if a
  prompt file is missing/renamed).
- `tests/unit/test_tools.py` — covers `ai_agents/tools/`.
