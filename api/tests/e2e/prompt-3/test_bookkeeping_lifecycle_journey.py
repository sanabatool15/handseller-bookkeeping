"""Scenario 1: full sales + expense bookkeeping lifecycle for one org.

Real-infra e2e (see PROMPT_V3.md): narrated step-by-step, with every
assertion explaining itself using the actual request/response on failure.
"""
from __future__ import annotations

import uuid


def unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


def expect(condition: bool, *, request_desc: str, response, message: str) -> None:
    if condition:
        return
    if response is not None:
        detail = (
            f"{message}\n"
            f"  request sent:      {request_desc}\n"
            f"  response status:   {response.status_code}\n"
            f"  response body:     {response.text}"
        )
    else:
        detail = f"{message}\n  request sent: {request_desc}"
    raise AssertionError(detail)


def _register(client, cleanup, story, tag: str):
    email = unique_email(tag)
    payload = {"email": email, "password": "correct-horse-1", "full_name": "E2E Tester", "org_name": f"Org-{tag}"}
    story.say(f"Registering user {email!r} for org 'Org-{tag}'")
    resp = client.post("/auth/register", json=payload, headers={"Idempotency-Key": f"reg-{tag}"})
    expect(
        resp.status_code == 201,
        request_desc=f"POST /auth/register json={payload}",
        response=resp,
        message="register should return 201",
    )
    body = resp.json()
    org_id = body["org"]["id"]
    user_id = body["user"]["id"]
    story.say(f"Registered: user_id={user_id} org_id={org_id}, got access token")
    cleanup.track_row("users", user_id, org_id, email=email)
    cleanup.track_row("orgs", org_id, org_name=f"Org-{tag}")
    return body["access_token"], org_id, user_id


def test_full_bookkeeping_lifecycle(client, cleanup, story):
    token, org_id, _user_id = _register(client, cleanup, story, "lifecycle")
    headers = {"Authorization": f"Bearer {token}"}

    story.say("Creating sale 1: amount=120.50 category=retail customer=Alice")
    sale1_payload = {"amount": 120.50, "category": "retail", "customer_name": "Alice"}
    sale1 = client.post("/sales", json=sale1_payload, headers={**headers, "Idempotency-Key": "life-sale-1"})
    expect(sale1.status_code == 201, request_desc=f"POST /sales json={sale1_payload}", response=sale1,
           message="creating sale 1 should return 201")
    sale1_id = sale1.json()["id"]
    story.say(f"Asserting status 201 -- got it. sale1_id={sale1_id}")
    cleanup.track_row("sales", sale1_id, org_id, **sale1_payload)

    story.say("Creating sale 2: amount=75.00 category=wholesale customer=Bob")
    sale2_payload = {"amount": 75.00, "category": "wholesale", "customer_name": "Bob"}
    sale2 = client.post("/sales", json=sale2_payload, headers={**headers, "Idempotency-Key": "life-sale-2"})
    expect(sale2.status_code == 201, request_desc=f"POST /sales json={sale2_payload}", response=sale2,
           message="creating sale 2 should return 201")
    sale2_id = sale2.json()["id"]
    story.say(f"sale2_id={sale2_id}")
    cleanup.track_row("sales", sale2_id, org_id, **sale2_payload)

    story.say("Creating expense 1: amount=30.00 category=supplies description=Boxes")
    exp1_payload = {"amount": 30.00, "category": "supplies", "description": "Boxes"}
    expense1 = client.post("/expenses", json=exp1_payload, headers={**headers, "Idempotency-Key": "life-exp-1"})
    expect(expense1.status_code == 201, request_desc=f"POST /expenses json={exp1_payload}", response=expense1,
           message="creating expense 1 should return 201")
    expense1_id = expense1.json()["id"]
    story.say(f"expense1_id={expense1_id}")
    cleanup.track_row("expenses", expense1_id, org_id, **exp1_payload)

    story.say("Creating expense 2: amount=15.25 category=travel description=Gas")
    exp2_payload = {"amount": 15.25, "category": "travel", "description": "Gas"}
    expense2 = client.post("/expenses", json=exp2_payload, headers={**headers, "Idempotency-Key": "life-exp-2"})
    expect(expense2.status_code == 201, request_desc=f"POST /expenses json={exp2_payload}", response=expense2,
           message="creating expense 2 should return 201")
    expense2_id = expense2.json()["id"]
    story.say(f"expense2_id={expense2_id}")
    cleanup.track_row("expenses", expense2_id, org_id, **exp2_payload)

    story.say("Listing sales -- expecting both sale1 and sale2 present")
    sales_list = client.get("/sales", headers=headers)
    expect(sales_list.status_code == 200, request_desc="GET /sales", response=sales_list,
           message="listing sales should return 200")
    listed_sale_ids = {s["id"] for s in sales_list.json()}
    expect({sale1_id, sale2_id} <= listed_sale_ids, request_desc="GET /sales", response=sales_list,
           message=f"expected sale ids {{sale1_id, sale2_id}}={{ {sale1_id}, {sale2_id} }} to be a subset of listed ids {listed_sale_ids}")

    story.say("Listing expenses -- expecting both expense1 and expense2 present")
    expenses_list = client.get("/expenses", headers=headers)
    expect(expenses_list.status_code == 200, request_desc="GET /expenses", response=expenses_list,
           message="listing expenses should return 200")
    listed_expense_ids = {e["id"] for e in expenses_list.json()}
    expect({expense1_id, expense2_id} <= listed_expense_ids, request_desc="GET /expenses", response=expenses_list,
           message=f"expected expense ids {{expense1_id, expense2_id}}={{ {expense1_id}, {expense2_id} }} to be a subset of listed ids {listed_expense_ids}")

    story.say(f"Updating sale {sale1_id} amount -> 999.99")
    upd_sale_payload = {"amount": 999.99}
    upd_sale = client.put(f"/sales/{sale1_id}", json=upd_sale_payload, headers={**headers, "Idempotency-Key": "life-sale-1-upd"})
    expect(upd_sale.status_code == 200, request_desc=f"PUT /sales/{sale1_id} json={upd_sale_payload}", response=upd_sale,
           message="updating sale 1 should return 200")
    expect(float(upd_sale.json()["amount"]) == 999.99, request_desc=f"PUT /sales/{sale1_id} json={upd_sale_payload}",
           response=upd_sale, message="updated sale amount should be 999.99")

    story.say(f"Updating expense {expense1_id} category -> office")
    upd_exp_payload = {"category": "office"}
    upd_expense = client.put(f"/expenses/{expense1_id}", json=upd_exp_payload, headers={**headers, "Idempotency-Key": "life-exp-1-upd"})
    expect(upd_expense.status_code == 200, request_desc=f"PUT /expenses/{expense1_id} json={upd_exp_payload}", response=upd_expense,
           message="updating expense 1 should return 200")
    expect(upd_expense.json()["category"] == "office", request_desc=f"PUT /expenses/{expense1_id} json={upd_exp_payload}",
           response=upd_expense, message="updated expense category should be 'office'")

    story.say(f"Deleting sale {sale2_id}")
    del_sale = client.delete(f"/sales/{sale2_id}", headers={**headers, "Idempotency-Key": "life-sale-2-del"})
    expect(del_sale.status_code == 204, request_desc=f"DELETE /sales/{sale2_id}", response=del_sale,
           message="deleting sale 2 should return 204")

    story.say(f"Deleting expense {expense2_id}")
    del_expense = client.delete(f"/expenses/{expense2_id}", headers={**headers, "Idempotency-Key": "life-exp-2-del"})
    expect(del_expense.status_code == 204, request_desc=f"DELETE /expenses/{expense2_id}", response=del_expense,
           message="deleting expense 2 should return 204")

    story.say("Final state check: sale1/expense1 remain (updated), sale2/expense2 are gone")
    final_sales_resp = client.get("/sales", headers=headers)
    final_sales = final_sales_resp.json()
    final_sale_ids = {s["id"] for s in final_sales}
    expect(sale1_id in final_sale_ids, request_desc="GET /sales", response=final_sales_resp,
           message=f"sale1_id {sale1_id} should still be listed")
    expect(sale2_id not in final_sale_ids, request_desc="GET /sales", response=final_sales_resp,
           message=f"sale2_id {sale2_id} should have been deleted and not be listed")

    final_expenses_resp = client.get("/expenses", headers=headers)
    final_expenses = final_expenses_resp.json()
    final_expense_ids = {e["id"] for e in final_expenses}
    expect(expense1_id in final_expense_ids, request_desc="GET /expenses", response=final_expenses_resp,
           message=f"expense1_id {expense1_id} should still be listed")
    expect(expense2_id not in final_expense_ids, request_desc="GET /expenses", response=final_expenses_resp,
           message=f"expense2_id {expense2_id} should have been deleted and not be listed")

    get_sale1 = client.get(f"/sales/{sale1_id}", headers=headers)
    expect(get_sale1.status_code == 200, request_desc=f"GET /sales/{sale1_id}", response=get_sale1,
           message="fetching sale1 by id should return 200")
    expect(float(get_sale1.json()["amount"]) == 999.99, request_desc=f"GET /sales/{sale1_id}", response=get_sale1,
           message="sale1's amount should reflect the earlier update (999.99)")
    story.say("Lifecycle scenario complete.")
