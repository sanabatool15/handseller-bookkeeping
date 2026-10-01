"""Imports `mcp_gateway.server` normally and checks all 5 MCP primitives are
registered.

FIXED (previously documented limitation): this used to require loading
`mcp/server.py` via `importlib.util.spec_from_file_location(...)` to avoid
a package-name collision with the real `mcp` SDK (see git history / the
old spec doc). Now that the package is named `mcp_gateway/`, it's a normal
importable package with no collision, so a normal `from mcp_gateway.server
import ...` works and this test no longer needs the importlib workaround.
"""
from __future__ import annotations

import pytest

from mcp_gateway import server as mcp_module


@pytest.mark.asyncio
async def test_tools_registered():
    tools = await mcp_module.mcp.list_tools()
    names = {t.name for t in tools}
    assert {"log_sale", "log_expense", "trigger_financial_agent_job"}.issubset(names)


@pytest.mark.asyncio
async def test_resource_template_registered():
    templates = await mcp_module.mcp.list_resource_templates()
    uris = {t.uri_template for t in templates}
    assert "ledger://{org_id}/monthly.csv" in uris


@pytest.mark.asyncio
async def test_prompt_registered():
    prompts = await mcp_module.mcp.list_prompts()
    names = {p.name for p in prompts}
    assert "financial_audit" in names


@pytest.mark.asyncio
async def test_log_sale_tool_creates_a_sale(_wire_fakes):
    # Call the underlying handler directly (bypassing the MCP session/Context
    # machinery, which requires a live client connection) to unit-test the
    # tool's business logic without spinning up a full stdio session.
    sale = await mcp_module.log_sale(org_id="org-mcp", user_id="user-mcp", amount=25.0, category="retail")
    assert sale["amount"] == 25.0
    assert sale["org_id"] == "org-mcp"


class _Ctx:
    def __init__(self):
        self.logs, self.errors = [], []

    async def log(self, msg, level="info"):
        self.logs.append(msg)

    async def error(self, msg):
        self.errors.append(msg)


@pytest.mark.asyncio
async def test_log_expense_tool_creates_an_expense(_wire_fakes):
    exp = await mcp_module.log_expense(org_id="org-mcp", user_id="user-mcp", amount=7.5, category="rent", voucher_reference="V-1")
    assert exp["amount"] == 7.5 and exp["org_id"] == "org-mcp" and exp["voucher_reference"] == "V-1"


@pytest.mark.asyncio
async def test_stream_job_logs_goes_through_service_and_is_org_scoped(sql_store):
    from repository import agent_jobs_repository as repo
    from tests.fake_repos import FakeSqlDb

    db = FakeSqlDb(sql_store)
    job = repo.create_job(db, job_name="financial_advisor", org_id="org-a", requested_by=None)
    repo.add_log(db, job_id=job["id"], org_id="org-a", step_name="gather_data", action_summary="did it")

    ctx = _Ctx()
    logs = await mcp_module.stream_job_logs(org_id="org-a", job_id=job["id"], ctx=ctx)
    assert [l["step_name"] for l in logs] == ["gather_data"] and ctx.logs == ["[gather_data] did it"]

    other = _Ctx()
    assert await mcp_module.stream_job_logs(org_id="org-b", job_id=job["id"], ctx=other) == []  # cross-tenant: not found
    assert other.errors and not other.logs
