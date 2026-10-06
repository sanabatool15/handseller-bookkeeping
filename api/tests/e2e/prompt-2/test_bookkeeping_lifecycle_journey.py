"""Scenario 1: full sales + expense bookkeeping lifecycle for one org.

Real-infra e2e: registers a real org/user row in the real Supabase/Postgres
instance, creates/updates/deletes real `sales` and `expenses` rows through
the live HTTP surface (TestClient -> routers -> services -> repository ->
real `supabase.Client`), and tears every created row down afterward.

See SCENARIOS.md in this directory for the full write-up.
"""
from __future__ import annotations

import uuid


def _unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, cleanup, tag: str):
    email = _unique_email(tag)
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-1", "full_name": "E2E Tester", "org_name": f"Org-{tag}"},
        headers={"Idempotency-Key": f"reg-{tag}"},
    )
    assert resp.status_code == 201, f"register failed: {resp.status_code} {resp.text}"
    body = resp.json()
    org_id = body["org"]["id"]
    user_id = body["user"]["id"]
    cleanup.track_row("users", user_id, org_id)
    cleanup.track_row("orgs", org_id)
    return body["access_token"], org_id, user_id


def test_full_bookkeeping_lifecycle(client, cleanup):
    token, org_id, _user_id = _register(client, cleanup, "lifecycle")
    headers = {"Authorization": f"Bearer {token}"}

    # --- Create two sales, two expenses ---
    sale1 = client.post(
        "/sales", json={"amount": 120.50, "category": "retail", "customer_name": "Alice"},
        headers={**headers, "Idempotency-Key": "life-sale-1"},
    )
    assert sale1.status_code == 201, sale1.text
    sale1_id = sale1.json()["id"]
    cleanup.track_row("sales", sale1_id, org_id)

    sale2 = client.post(
        "/sales", json={"amount": 75.00, "category": "wholesale", "customer_name": "Bob"},
        headers={**headers, "Idempotency-Key": "life-sale-2"},
    )
    assert sale2.status_code == 201, sale2.text
    sale2_id = sale2.json()["id"]
    cleanup.track_row("sales", sale2_id, org_id)

    expense1 = client.post(
        "/expenses", json={"amount": 30.00, "category": "supplies", "description": "Boxes"},
        headers={**headers, "Idempotency-Key": "life-exp-1"},
    )
    assert expense1.status_code == 201, expense1.text
    expense1_id = expense1.json()["id"]
    cleanup.track_row("expenses", expense1_id, org_id)

    expense2 = client.post(
        "/expenses", json={"amount": 15.25, "category": "travel", "description": "Gas"},
        headers={**headers, "Idempotency-Key": "life-exp-2"},
    )
    assert expense2.status_code == 201, expense2.text
    expense2_id = expense2.json()["id"]
    cleanup.track_row("expenses", expense2_id, org_id)

    # --- List: both sales, both expenses visible ---
    sales_list = client.get("/sales", headers=headers)
    assert sales_list.status_code == 200
    listed_sale_ids = {s["id"] for s in sales_list.json()}
    assert {sale1_id, sale2_id} <= listed_sale_ids

    expenses_list = client.get("/expenses", headers=headers)
    assert expenses_list.status_code == 200
    listed_expense_ids = {e["id"] for e in expenses_list.json()}
    assert {expense1_id, expense2_id} <= listed_expense_ids

    # --- Update one sale, one expense ---
    upd_sale = client.put(
        f"/sales/{sale1_id}", json={"amount": 999.99},
        headers={**headers, "Idempotency-Key": "life-sale-1-upd"},
    )
    assert upd_sale.status_code == 200, upd_sale.text
    assert float(upd_sale.json()["amount"]) == 999.99

    upd_expense = client.put(
        f"/expenses/{expense1_id}", json={"category": "office"},
        headers={**headers, "Idempotency-Key": "life-exp-1-upd"},
    )
    assert upd_expense.status_code == 200, upd_expense.text
    assert upd_expense.json()["category"] == "office"

    # --- Delete one sale, one expense ---
    del_sale = client.delete(
        f"/sales/{sale2_id}", headers={**headers, "Idempotency-Key": "life-sale-2-del"}
    )
    assert del_sale.status_code == 204, del_sale.text

    del_expense = client.delete(
        f"/expenses/{expense2_id}", headers={**headers, "Idempotency-Key": "life-exp-2-del"}
    )
    assert del_expense.status_code == 204, del_expense.text

    # --- Final state: exactly the remaining, updated records ---
    final_sales = client.get("/sales", headers=headers).json()
    final_sale_ids = {s["id"] for s in final_sales}
    assert sale1_id in final_sale_ids
    assert sale2_id not in final_sale_ids

    final_expenses = client.get("/expenses", headers=headers).json()
    final_expense_ids = {e["id"] for e in final_expenses}
    assert expense1_id in final_expense_ids
    assert expense2_id not in final_expense_ids

    get_sale1 = client.get(f"/sales/{sale1_id}", headers=headers)
    assert get_sale1.status_code == 200
    assert float(get_sale1.json()["amount"]) == 999.99
