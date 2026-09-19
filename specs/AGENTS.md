# Agents Architecture

Quick-reference overview of the AI agent layer. Full rationale and history
live in [`06-agents-layer.md`](06-agents-layer.md); this file is the short
version.

## Three agents, planner + handoff

```
user_message
     │
     ▼
planner_agent  (no tools — routing only)
     │
     ├── handoff ──▶ investigate_agent  (read-only tools)
     │
     └── handoff ──▶ record_agent       (mutating tools)
```

- **`planner_agent`** — holds zero tools. Its only job is deciding whether a
  message is a question to investigate or a transaction to record, then
  calling `handoff()` to the matching specialist. It never sets
  `output_type`, since its final action is always a handoff, not a
  structured answer.
- **`investigate_agent`** — read-only tools: `get_monthly_summary`,
  `get_expense_breakdown_by_category`, `get_sales_breakdown_by_category`,
  `web_search`. Answers "how's the business doing" / "why did we lose
  money" style questions.
- **`record_agent`** — mutating tools: `create_expense_record`,
  `create_sales_record`, `deep_link`. Turns a natural-language statement
  ("spent $40 on packaging") into an actual record and hands back a
  reference/link.

Both specialists return a structured `BookkeepingResult` (`mode`, `summary`,
`root_cause`, `recommendation`, `used_web_search`, `record_reference`). A
handoff passes the full conversation history by default, so the planner's
stated reasoning carries over automatically — no extra plumbing needed.

## Entry points

Both live in `ai_agents/api/financial_advisor_agent.py`:

- **`run_bookkeeping_agent(db, org_id, user_id, user_message, ...)`** — the
  general entry point. Drives the whole chain with one
  `Runner.run_streamed(planner_agent, ...)` call (`max_turns=10`), letting
  the planner route to either specialist based on `user_message`.
- **`run_financial_advisor(db, monthly_summary)`** — the backward-compatible
  entry point used by the proactive monthly-advice job
  (`jobs/financial_agent_job.py`). It synthesizes a fixed
  investigation-style question from the summary, so it **always** routes to
  `investigate_agent` — it never reaches `record_agent`. See
  `specs/10-known-limitations.md` (entry #9) for why `record_agent` has no
  production caller yet, even though it's fully implemented and tested.

Both raise `AgentUnavailableError` on any ordinary external-call failure
(SDK not installed, no network, no `OPENAI_API_KEY`, or the live call
erroring) or on exceeding `max_turns`. Callers never see raw SDK exceptions.

## Fallback: deterministic, offline, always available

`ai_agents/rules/fallback_engine.py`'s `rule_based_financial_advice`
produces useful advice from the same monthly-summary input with **no
network call or LLM**. `jobs/financial_agent_job.py`'s `_step_run_agent`
catches any exception from the agent call and falls back to this — a
misconfigured API key or a network outage never results in "no advice
today," only a simpler, non-AI version of the same advice.

## Prompts live in files, not Python strings

Every agent's system prompt is a Markdown file under `ai_agents/prompts/`
(`planner_agent.md`, `investigate_agent.md`, `record_agent.md`), loaded at
runtime by `ai_agents/prompt_loader.py`. No prompt text is ever a Python
string literal in this codebase — see `CLAUDE.md` rule #5.

## Package naming: `ai_agents/`, not `agents/`

This package was renamed from `agents/` to `ai_agents/` to fix a name
collision with the third-party `openai-agents` SDK (which installs as a
top-level `agents` module). **Do not rename it back** — see
`specs/06-agents-layer.md` for the full history of why this matters.

## Where this is tested

- `tests/unit/test_financial_advisor_agent.py`, `test_fallback_engine.py`,
  `test_prompt_loader.py`, `test_tools.py`
- `tests/e2e/prompt-4/` — planner routing/handoff assertions against real
  infra
- `tests/e2e/prompt-5/` — observational suite (no rigid assertions; prints
  full `Runner.run_streamed()` event traces for manual review)
