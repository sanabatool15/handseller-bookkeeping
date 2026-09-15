# Model Context Protocol Server (`mcp_gateway/server.py`, formerly `mcp/server.py`)

## What we did

Built a `FastMCP`-based server, run over **stdio transport**, at
`mcp_gateway/server.py`, implementing all 5 MCP primitives against this
app's real `services/`/`repository/` layer (not a separate
reimplementation):

1. **Tools** — `log_sale`, `log_expense`, `trigger_financial_agent_job`
   (the three required by spec), plus two bonus tools that exist
   specifically to demonstrate primitives 4 and 5:
   `summarize_ledger_via_client_llm` (sampling) and `stream_job_logs`
   (logging).
2. **Resources** — `ledger://{org_id}/monthly.csv`, a resource *template*
   (the `{org_id}` is a variable segment) that reads live sales/expenses
   from Postgres via `services.financial_report_service.monthly_ledger_csv`
   and returns a raw CSV string — an MCP client can "open" this like a
   file/URI, not just call it like an API.
3. **Prompts** — `financial_audit(org_id)`, which loads
   `ai_agents/prompts/financial_audit.md` via `ai_agents/prompt_loader.py`
   and pre-fills it with the org's current-month ledger CSV, so a connected
   client (e.g. Claude Desktop) can offer "run a financial audit for this
   org" as a ready-made, context-filled prompt.
4. **Sampling** — `summarize_ledger_via_client_llm` issues an MCP
   `sampling/createMessage` request via `ctx.session.create_message(...)`.
   This tool **never calls OpenAI or any server-side LLM directly** — it
   asks the *connected MCP client* to run the completion, so the client
   (not this server) pays for and controls the inference.
5. **Logging** — every tool calls `await ctx.log(...)` (or `ctx.error(...)`
   on failure), streaming structured log notifications to the connected
   client's log stream in real time, in addition to returning normal tool
   results. `stream_job_logs` additionally re-emits a job's `agent_logs`
   rows as a sequence of log notifications on demand, so a client can
   "replay" a background job's history through the same log stream.

Every MCP tool calls the exact same `services.*` functions the HTTP routers
call — `log_sale`/`log_expense` go through `services.sales_service` /
`services.expenses_service`, and `trigger_financial_agent_job` goes through
`services.agent_job_service.trigger_financial_advice_job` (the same
function `POST /agent-jobs/financial-advice` uses). There is no parallel
MCP-specific business logic anywhere.

This server's package used to be named `mcp/`, exactly matching an earlier
version of the spec's literal directory-name requirement. It has since
been **renamed to `mcp_gateway/`** to fix a real package-name collision —
see below.

## Why we did it

The point of exposing an MCP server at all is to let external LLM clients
(Claude Desktop, other MCP-compatible tools) act as a front-end onto this
bookkeeping system — a handseller (or their accountant) using an AI chat
client should be able to log a sale, pull this month's ledger, or ask for
a financial audit, without that client needing a bespoke integration
against this app's REST API. MCP standardizes that integration surface.

**Why route through the same `services/` layer instead of writing
MCP-specific logic:** this guarantees an MCP-invoked action has *identical*
validation and multi-tenant scoping to the same action performed via the
REST API — there's no separate code path that could accidentally be less
strict. This is a direct consequence of the layering decision in
`01-architecture-layering.md`: because routers are thin adapters onto
services, MCP tools can be thin adapters onto the exact same services too.

**Why sampling matters specifically for this app:** a bookkeeping backend
that also called an LLM server-side for every "summarize my ledger"
request would mean *this server* pays OpenAI costs on behalf of every
connected client, with no natural way to attribute or limit that spend per
user. Client-side sampling inverts that — the MCP client (which already
has its own LLM relationship, e.g. the user's own Claude subscription)
performs the inference, and this server only supplies the data and the
question. This is the correct cost/ownership model for a tool meant to be
used by many different external clients.

## The `mcp` package-name collision — FIXED by renaming to `mcp_gateway/`

This was a real, previously reproduced problem (not theoretical), and it
is now fixed rather than merely worked around.

**The problem:** the `mcp` Python SDK (a dependency of `fastmcp`) installs
as a top-level package also named `mcp`. This repository used to have its
own top-level directory named `mcp/` (as an earlier version of the spec's
directory-name requirement demanded). If that directory were an importable
Python package (i.e. had an `__init__.py`) and got imported as `mcp`
*before* the real SDK's `mcp` package, it would shadow the SDK entirely.
**We verified this concretely**: with an `__init__.py` present and the
directory resolvable as `mcp`, `import fastmcp` failed with
`ModuleNotFoundError: No module named 'mcp.server'`, because `fastmcp`
internally does `from mcp.server import ...` and got this repo's own
`mcp/server.py` instead of the SDK's.

**Old workaround (no longer in place):** the directory was kept
deliberately package-less (no `__init__.py`), so it was never actually
importable as `mcp` at all — `server.py` was always either run directly as
a script, or loaded in tests via
`importlib.util.spec_from_file_location(...)` under a distinct module
name, sidestepping normal package import resolution entirely. This worked,
but meant the server could never be imported normally
(`from mcp.server import mcp` was permanently off-limits), which is an
awkward, easy-to-violate-by-accident constraint to carry forward
indefinitely.

**The fix, applied:** the directory was renamed from `mcp/` to
**`mcp_gateway/`**. There is no longer any local directory literally named
`mcp` anywhere in this repository, so:

- `mcp_gateway/` now has a normal `__init__.py` and is a normal importable
  Python package.
- `mcp_gateway/server.py` is imported normally —
  `tests/unit/test_mcp_server.py` now does
  `from mcp_gateway import server as mcp_module` instead of the old
  `importlib.util` workaround.
- `mcp_gateway/server.py`'s own third-party imports (`from fastmcp import
  Context, FastMCP`, and `from mcp.types import SamplingMessage,
  TextContent` inside `summarize_ledger_via_client_llm`) now unambiguously
  resolve to the real third-party packages, since our own package is no
  longer named `mcp` and can't shadow them.
- The old manual `sys.path` bootstrap that used to be needed to make
  `mcp/server.py` runnable as a bare script (inserting the repo root onto
  `sys.path` at the top of the file) is no longer needed for the package
  itself to import correctly, though `python mcp_gateway/server.py` as a
  direct script invocation is still the documented way to run it standalone
  (see "Running it" below).

**Why renaming was the right fix:** the old package-less-directory
workaround was correct but brittle — it worked only as long as *nothing*
ever imported the directory as a package, a constraint that's easy to
accidentally violate (e.g. someone adding an `__init__.py` "to make the
IDE happy" months later, not knowing why it was missing). Renaming the
directory removes the constraint at its root instead of relying on every
future contributor remembering a rule.

**Do not rename this package back to `mcp/`, and do not create any other
directory literally named `mcp` with an `__init__.py` in this repo** —
either would reintroduce the exact collision and silently break
`import fastmcp` throughout the app.

## Running it

```bash
python mcp_gateway/server.py
# or:
fastmcp run mcp_gateway/server.py
```

Connect any MCP-compatible client (Claude Desktop, the `mcp` CLI
inspector) over stdio by pointing its config at that command — see
`README.md`'s example Claude Desktop config entry.

## Documented SDK-version assumption

Verified against **`fastmcp==4.0.3`** by installing it and inspecting the
real decorator/context API (`@mcp.tool`, `@mcp.resource(...)`, `@mcp.prompt`,
`ctx.log`/`ctx.error`, `ctx.session.create_message`) rather than assuming
from documentation alone.

## Where this is tested

`tests/unit/test_mcp_server.py` imports `mcp_gateway.server` normally
(`from mcp_gateway import server as mcp_module`) and asserts all 5
primitives are registered (tools, resource template, prompt) — this is
what proves the rename fixed the collision for real, under this repo's
actual layout, not a simplified/isolated reproduction. Sampling and
logging are inherently interactive, client-driven MCP features (they
require a real connected client that supports the corresponding protocol
capability), so they are verified by confirming correct *registration* and
code review rather than an automated end-to-end test against a live
external client — see `10-known-limitations.md`.
