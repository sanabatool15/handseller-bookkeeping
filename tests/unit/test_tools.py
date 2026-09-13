from agents.tools.deep_link import build_deep_link


def test_build_deep_link_basic():
    link = build_deep_link(org_id="org-1", resource="sales")
    assert link == "https://app.handseller.example/orgs/org-1/sales"


def test_build_deep_link_with_id_and_query():
    link = build_deep_link(org_id="org-1", resource="sales", resource_id="sale-9", highlight="true")
    assert "orgs/org-1/sales/sale-9" in link
    assert "highlight=true" in link
