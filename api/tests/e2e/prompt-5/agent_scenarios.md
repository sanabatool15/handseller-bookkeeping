# Prompt-5 Agent Scenarios — Observational E2E

Basis: **`specs/06-agents-layer.md`** (primary), cross-checked against the
real implementation. No rigid pass/fail assertions here — captured streams
are for human review only.

## Sources read

- `specs/06-agents-layer.md` — planner + handoff, three-agent architecture
- `specs/09-testing-strategy.md` — real-infra e2e direction, `RUN_E2E=1` gate
- `specs/03-multi-tenancy-security.md` — id+org_id scoping, 404-not-403
- `ai_agents/prompts/planner_agent.md`, `record_agent.md`,
  `investigate_agent.md` — actual routing/tool-use rules
- `ai_agents/api/financial_advisor_agent.py` — `build_agents()`,
  `run_bookkeeping_agent()`, `BookkeepingResult`
- `ai_agents/tools/bookkeeping_tools.py` — `build_investigate_tools`,
  `build_record_tools`
- `tests/e2e/prompt-4/` — prior art for real-infra fixture/story pattern
  (reused here, but stripped of rigid `expect()` assertions per this task's
  instructions)

## Architecture recap (from specs/06-agents-layer.md)

- `planner_agent`: no tools, only `handoff()` to one of two specialists;
  conversation history carries over on handoff.
- `investigate_agent`: read-only tools (`get_monthly_summary`,
  `get_expense_breakdown_by_category`, `get_sales_breakdown_by_category`,
  `web_search`), `output_type=BookkeepingResult`.
- `record_agent`: mutating tools (`create_expense_record`,
  `create_sales_record`, `deep_link`), `output_type=BookkeepingResult`.
- One `Runner.run_streamed(planner_agent, ...)` call per turn,
  `max_turns=10`, `error_handlers={"max_turns": ...}` falls back to
  `rule_based_financial_advice`.
- Stream surfaces `agent_updated_stream_event` (handoffs) and
  `run_item_stream_event` (tool calls, message output).

## Happy-path inputs (3)

- **H1 — expense recording.** Input: `"I spent $40 on packaging today"`.
  Expect routing toward `record_agent` and a `create_expense_record` +
  `deep_link` tool-call sequence (per `record_agent.md`).
- **H2 — sale recording.** Input: `"sold 3 units to Acme for $150"` — the
  planner prompt's own worked example for the record path.
- **H3 — performance/loss investigation.** Input:
  `"why did we lose money last month?"`, with a seeded sale + expense so
  the investigator has real data to pull. Expect a data-pull tool
  (`get_monthly_summary` / breakdown) before any `web_search` call, per
  `investigate_agent.md`'s explicit ordering rule.

## Edge-case inputs (2)

- **E1 — ambiguous message (both a completed transaction and a question).**
  Input: `"I spent $200 on ads, is that too much this month?"`. The
  planner prompt gives no tie-breaking rule between its two routing
  bullets — observe which specialist actually gets chosen and whether the
  described expense ends up recorded.
- **E2 — missing required parameter.** Input:
  `"log an expense for the packaging supplies"` (no amount at all).
  `record_agent.md` says to ask a clarifying question instead of guessing
  — observe whether a tool call fires anyway and with what argument.

## What each test captures (for human review, not assertions)

- Every `agent_updated_stream_event` (handoff target agent name)
- Every `run_item_stream_event` tool_call_item (tool name + parsed
  arguments) and message_output_item (assistant prose)
- The final `result.final_output` (`BookkeepingResult` fields)
- Printed via `print()` so `pytest -s` shows the full trace

## Non-goals

- No assertion on which specialist was chosen, which tool fired, or on
  output content/wording — a human reviews the printed trace.
- The only functional check is that the run completes without raising
  (`result is not None`, `result.final_output is not None` or similar).
