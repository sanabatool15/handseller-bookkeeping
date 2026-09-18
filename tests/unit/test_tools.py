from ai_agents.tools.deep_link import build_deep_link
from ai_agents.tools.bookkeeping_tools import build_investigate_tools, build_record_tools
from tests.fakes import FakeSupabase


def test_build_deep_link_basic():
    link = build_deep_link(org_id="org-1", resource="sales")
    assert link == "https://app.handseller.example/orgs/org-1/sales"


def test_build_deep_link_with_id_and_query():
    link = build_deep_link(org_id="org-1", resource="sales", resource_id="sale-9", highlight="true")
    assert "orgs/org-1/sales/sale-9" in link
    assert "highlight=true" in link


def test_build_investigate_tools_are_scoped_and_named():
    """investigate_agent's tool set: read-only summary/breakdown + web_search,
    never a record-mutating tool (Section 4 of the design plan)."""
    db = FakeSupabase()
    tools = build_investigate_tools(db, org_id="org-1")
    names = {t.name for t in tools}
    assert names == {
        "get_monthly_summary",
        "get_expense_breakdown_by_category",
        "get_sales_breakdown_by_category",
        "web_search",
    }


def test_build_record_tools_are_scoped_and_named():
    """record_agent's tool set: record-creation + deep_link, never a
    read/investigate tool (Section 4 of the design plan)."""
    db = FakeSupabase()
    tools = build_record_tools(db, org_id="org-1", user_id="user-1")
    names = {t.name for t in tools}
    assert names == {"create_expense_record", "create_sales_record", "deep_link"}


def test_create_expense_record_tool_declares_amount_param():
    db = FakeSupabase()
    tools = {t.name: t for t in build_record_tools(db, org_id="org-1", user_id="user-1")}
    create_expense_record = tools["create_expense_record"]
    # FunctionTool's JSON schema is what the LLM sees; confirm the closure
    # over org_id/user_id didn't leak into the model-visible parameters
    # (they must never be settable by the LLM).
    props = create_expense_record.params_json_schema.get("properties", {})
    assert "amount" in props
    assert "org_id" not in props and "user_id" not in props
