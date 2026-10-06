"""Prompt v1 — Scenario 1: full sales + expense bookkeeping lifecycle.

A handseller registers an org, logs several sales and expenses, lists them,
updates one of each, deletes one of each, and the final state reflects
exactly the remaining records. Exercises the full routers -> services ->
repository CRUD path for both `sales` and `expenses` in one continuous
journey, through the real HTTP surface via `TestClient`.
"""
from __future__ import annotations

from tests.integration.conftest import auth_headers, register_and_login


def test_full_sales_and_expense_lifecycle_for_one_org(client):
    org = register_and_login(client, email="lifecycle@example.com")
    token = org["access_token"]

    # Log three sales.
    sale_ids = []
    for i in range(3):
        resp = client.post(
            "/sales",
            json={"amount": 100.0 + i, "category": "retail", "customer_name": f"Customer {i}"},
            headers=auth_headers(token, f"lifecycle-sale-{i}"),
        )
        assert resp.status_code == 201, resp.text
        sale_ids.append(resp.json()["id"])

    # Log two expenses.
    expense_ids = []
    for i in range(2):
        resp = client.post(
            "/expenses",
            json={"amount": 20.0 + i, "category": "supplies", "voucher_reference": f"V-{i}"},
            headers=auth_headers(token, f"lifecycle-expense-{i}"),
        )
        assert resp.status_code == 201, resp.text
        expense_ids.append(resp.json()["id"])

    # List reflects everything created so far.
    sales_listing = client.get("/sales", headers=auth_headers(token, "unused")).json()
    assert {s["id"] for s in sales_listing} == set(sale_ids)

    expenses_listing = client.get("/expenses", headers=auth_headers(token, "unused")).json()
    assert {e["id"] for e in expenses_listing} == set(expense_ids)

    # Update one sale and one expense.
    updated_sale = client.put(
        f"/sales/{sale_ids[0]}",
        json={"amount": 500.0},
        headers=auth_headers(token, "lifecycle-sale-update"),
    )
    assert updated_sale.status_code == 200
    assert updated_sale.json()["amount"] == 500.0

    updated_expense = client.put(
        f"/expenses/{expense_ids[0]}",
        json={"amount": 999.0},
        headers=auth_headers(token, "lifecycle-expense-update"),
    )
    assert updated_expense.status_code == 200
    assert updated_expense.json()["amount"] == 999.0

    # Delete one sale and one expense.
    deleted_sale = client.delete(f"/sales/{sale_ids[1]}", headers=auth_headers(token, "unused"))
    assert deleted_sale.status_code == 204

    deleted_expense = client.delete(f"/expenses/{expense_ids[1]}", headers=auth_headers(token, "unused"))
    assert deleted_expense.status_code == 204

    # Final state: deleted records gone, remaining ones present with updates applied.
    final_sales = client.get("/sales", headers=auth_headers(token, "unused")).json()
    final_sale_ids = {s["id"] for s in final_sales}
    assert final_sale_ids == {sale_ids[0], sale_ids[2]}
    assert next(s for s in final_sales if s["id"] == sale_ids[0])["amount"] == 500.0

    final_expenses = client.get("/expenses", headers=auth_headers(token, "unused")).json()
    final_expense_ids = {e["id"] for e in final_expenses}
    assert final_expense_ids == {expense_ids[0]}
    assert next(e for e in final_expenses if e["id"] == expense_ids[0])["amount"] == 999.0

    # Deleted records are individually 404 now, not just absent from the list.
    assert client.get(f"/sales/{sale_ids[1]}", headers=auth_headers(token, "unused")).status_code == 404
    assert client.get(f"/expenses/{expense_ids[1]}", headers=auth_headers(token, "unused")).status_code == 404
