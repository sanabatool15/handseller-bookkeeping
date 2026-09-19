# Prompt-5 Agent Scenarios — Observational E2E

Grounded in the real implementation (no `specs/` file covers the agent
prompts/tools directly, so this is based on code, same as prompt-4):

- `ai_agents/prompts/planner_agent.md` — planner routing rules
- `ai_agents/prompts/record_agent.md` — record specialist rules
- `ai_agents/prompts/investigate_agent.md` — investigate specialist rules
- `ai_agents/api/financial_advisor_agent.py` — `build_agents()`,
  `run_bookkeeping_agent()`, `DEFAULT_MAX_TURNS`
- `ai_agents/tools/bookkeeping_tools.py` — tool sets:
  - investigate: `get_monthly_summary`, `get_expense_breakdown_by_category`,
    `get_sales_breakdown_by_category`, `web_search`
  - record: `create_expense_record`, `create_sales_record`, `deep_link`

Purpose: OBSERVATIONAL only. No assertions on which agent/tool was chosen or
on output content. Each test's only functional job is: run without crashing,
print the full captured event stream (`pytest -s`) for a human to review.

## Happy paths

- **Planner: expense message** — `"I spent $40 on packaging today"`.
  Expect (for a human to eyeball): handoff to Record agent, a
  `create_expense_record` tool call, a `deep_link` tool call, final
  `BookkeepingResult`.
- **Planner: sale message** — `"sold 3 units to Acme for $150"`.
  Expect: handoff to Record agent, `create_sales_record` tool call.
- **Investigate: performance question with seeded history** — seed sales +
  expenses directly via Supabase, then ask
  `"why did we lose money last month?"`. Expect: handoff to Investigate
  agent, one or more of `get_monthly_summary` /
  `get_expense_breakdown_by_category` / `get_sales_breakdown_by_category`,
  possibly `web_search` after a driver is named.

## Edge cases

- **Ambiguous message (both transaction + performance question)** —
  `"I spent $200 on ads, is that too much this month?"`. Print whichever
  specialist gets picked and whatever tools fire — human reviews for
  reasonableness, no hard-coded expectation of which branch is "correct."
- **Missing amount** — `"log an expense for the packaging supplies"`. Print
  whether `create_expense_record` fires (and with what args) or whether the
  agent asks a clarifying question instead — human judges whether the model
  is guessing.

## Test files

- `conftest.py` — shared fixtures: RUN_E2E gating, real Supabase/Redis
  wiring, `story` narrator, `StreamCapture` printer, `cleanup` fixture with
  guaranteed teardown.
- `test_planner_routing.py` — planner handoff observation (record + sale
  inputs, ambiguous input).
- `test_record_agent.py` — record-agent-focused observation (expense, sale,
  missing-amount edge case), run directly against `build_agents()`.
- `test_investigate_agent.py` — investigate-agent-focused observation, with
  directly-seeded historical sales/expenses data via Supabase.
