# Agents Layer (`ai_agents/`, formerly `agents/`)

## What we did

Split the AI-facing code into four purpose-specific subfolders, exactly as
the spec for this step demanded:

- **`ai_agents/prompts/*.md`** — every system/agent prompt as a Markdown
  file (`financial_advisor_system.md`, `financial_audit.md`), loaded at
  runtime by `ai_agents/prompt_loader.py`. **No prompt text is ever a
  Python string literal in this codebase.**
- **`ai_agents/api/financial_advisor_agent.py`** — orchestration against
  the OpenAI Agents SDK: builds an `Agent` with instructions loaded from
  `ai_agents/prompts/financial_advisor_system.md`, runs it via
  `Runner.run(...)` against a JSON-serialized monthly summary, and returns
  the agent's final text output.
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

## The `agents` package-name collision — FIXED by renaming to `ai_agents/`

This was a real, previously reproduced problem (not theoretical), and it
is now fixed rather than merely worked around.

**The problem:** the `openai-agents` PyPI package installs as a top-level
module named `agents`. This repository's own AI-code directory was
*also* a top-level package named `agents` (as the original spec's
directory-name requirement demanded), and Python resolves `import agents`
to whichever `agents` package it finds first on `sys.path`. Critically,
when the import happened from *inside* this repo's own
`agents/api/financial_advisor_agent.py`, Python had already registered
this local package as the module named `agents` in `sys.modules` before
that submodule's code even ran (that's how Python imports work: the
parent package is imported before its submodules). So `import agents`
from inside this repo's own agent-orchestration code always resolved to
*itself*, never to the real SDK — **the real SDK was structurally
unreachable, permanently, regardless of installation or configuration.**

**Old workaround (no longer in place):** the code used to detect this
defensively — check whether the imported `agents` module had `Agent`/
`Runner` attributes, and if not, treat it exactly like "SDK unavailable"
and always raise `AgentUnavailableError`, routing every single request to
the rule-based fallback. This was a correct, honest way to *survive* the
collision, but it meant the "live AI advice" feature could never actually
run in this repo's own process, no matter what `OPENAI_API_KEY` was set to.

**The fix, applied:** the package was renamed from `agents/` to
**`ai_agents/`**. There is no longer any local package named `agents`
anywhere in this repository, so `import agents` inside
`ai_agents/api/financial_advisor_agent.py` now genuinely resolves to the
real `openai-agents` SDK's top-level `agents` module — verify this
yourself with `python -c "import agents; print(agents.__file__)"` from the
repo root; it should print a path inside your virtualenv's
`site-packages`, not anywhere inside this repo.

`financial_advisor_agent.py` was simplified accordingly — it no longer
needs the defensive attribute-sniffing, since there's nothing left to be
shadowed by:

```python
try:
    from agents import Agent as _SdkAgent
    from agents import Runner as _SdkRunner
    _sdk_available = True
except ImportError:
    _sdk_available = False
```

`run_financial_advisor` still raises `AgentUnavailableError` — but now
only for *genuine* reasons an external API can fail: the package isn't
installed (`ImportError`), or the live `Runner.run(...)` call itself
raises (network failure, invalid/missing `OPENAI_API_KEY`, rate limiting,
etc. — caught and re-raised as `AgentUnavailableError` so the caller's
fallback behavior is unchanged). The Inngest job step still catches this
exactly the same way and falls back to
`ai_agents/rules/fallback_engine.py` — **the resilience guarantee (a user
always gets advice) is unchanged; what changed is that the live SDK path
can now actually execute when it's genuinely configured**, instead of
being permanently dead code.

**Why renaming was the right fix (and not, say, a `sys.path` hack):** a
`sys.path` manipulation or import-order trick to "unshadow" the SDK from
inside the package that shadows it is fragile — it depends on import
timing that can silently break under any refactor, and it hides a real
architectural fact (two packages want the same name) behind "clever" code
a future maintainer has to reverse-engineer. Renaming this repo's own
package removes the ambiguity permanently and makes the fix visible in the
directory listing itself, not buried in an import-order workaround.

**Do not rename this package back to `agents/`** — that reintroduces the
exact collision and makes the live SDK path unreachable again, silently
(the code would still "work" by falling back every time, which is exactly
the kind of quiet regression this note exists to prevent).

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
