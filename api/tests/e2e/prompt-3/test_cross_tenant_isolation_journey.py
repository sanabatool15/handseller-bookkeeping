"""Scenario 2: cross-tenant isolation across the full product surface.

Real-infra e2e (see PROMPT_V3.md): narrated, self-explanatory-on-failure
version of prompt-2's cross-tenant isolation journey.
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
    expect(resp.status_code == 201, request_desc=f"POST /auth/register json={payload}", response=resp,
           message="register should return 201")
    body = resp.json()
    org_id = body["org"]["id"]
    user_id = body["user"]["id"]
    story.say(f"Registered: user_id={user_id} org_id={org_id}")
    cleanup.track_row("users", user_id, org_id, email=email)
    cleanup.track_row("orgs", org_id, org_name=f"Org-{tag}")
    return body["access_token"], org_id, user_id


def test_cross_tenant_isolation(client, cleanup, story):
    story.say("Setting up two separate orgs: A and B")
    token_a, org_a, _ = _register(client, cleanup, story, "tenant-a")
    token_b, org_b, _ = _register(client, cleanup, story, "tenant-b")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    story.say(f"Org A ({org_a}) creates a sale of amount 200.0")
    sale_a_payload = {"amount": 200.0, "category": "retail"}
    sale_a = client.post("/sales", json=sale_a_payload, headers={**headers_a, "Idempotency-Key": "tenant-a-sale"})
    expect(sale_a.status_code == 201, request_desc=f"POST /sales json={sale_a_payload} (org A)", response=sale_a,
           message="org A creating a sale should return 201")
    sale_a_id = sale_a.json()["id"]
    story.say(f"sale_a_id={sale_a_id}")
    cleanup.track_row("sales", sale_a_id, org_a, **sale_a_payload)

    story.say(f"Org A ({org_a}) creates an expense of amount 50.0")
    expense_a_payload = {"amount": 50.0, "category": "supplies"}
    expense_a = client.post("/expenses", json=expense_a_payload, headers={**headers_a, "Idempotency-Key": "tenant-a-expense"})
    expect(expense_a.status_code == 201, request_desc=f"POST /expenses json={expense_a_payload} (org A)", response=expense_a,
           message="org A creating an expense should return 201")
    expense_a_id = expense_a.json()["id"]
    story.say(f"expense_a_id={expense_a_id}")
    cleanup.track_row("expenses", expense_a_id, org_a, **expense_a_payload)

    story.say(f"Org A ({org_a}) triggers a financial-advice agent job")
    job_a = client.post("/agent-jobs/financial-advice", headers={**headers_a, "Idempotency-Key": "tenant-a-job"})
    expect(job_a.status_code == 202, request_desc="POST /agent-jobs/financial-advice (org A)", response=job_a,
           message="org A triggering an agent job should return 202")
    job_a_id = job_a.json()["job_id"]
    story.say(f"job_a_id={job_a_id}")
    cleanup.track_row("agent_jobs", job_a_id, org_a)

    story.say(f"Org B ({org_b}) attempts to GET org A's sale {sale_a_id} -- must be 404, not 403 or 200")
    r = client.get(f"/sales/{sale_a_id}", headers=headers_b)
    expect(r.status_code == 404, request_desc=f"GET /sales/{sale_a_id} (as org B)", response=r,
           message="org B reading org A's sale by id must return 404 (never 403 or 200 -- 403 leaks existence)")

    story.say(f"Org B ({org_b}) attempts to PUT org A's sale {sale_a_id} -- must be 404")
    upd_payload = {"amount": 1.0}
    r = client.put(f"/sales/{sale_a_id}", json=upd_payload, headers={**headers_b, "Idempotency-Key": "tenant-b-tries-sale-upd"})
    expect(r.status_code == 404, request_desc=f"PUT /sales/{sale_a_id} json={upd_payload} (as org B)", response=r,
           message="org B updating org A's sale by id must return 404")

    story.say(f"Org B ({org_b}) attempts to DELETE org A's sale {sale_a_id} -- must be 404")
    r = client.delete(f"/sales/{sale_a_id}", headers={**headers_b, "Idempotency-Key": "tenant-b-tries-sale-del"})
    expect(r.status_code == 404, request_desc=f"DELETE /sales/{sale_a_id} (as org B)", response=r,
           message="org B deleting org A's sale by id must return 404")

    story.say(f"Org B ({org_b}) attempts to GET org A's expense {expense_a_id} -- must be 404")
    r = client.get(f"/expenses/{expense_a_id}", headers=headers_b)
    expect(r.status_code == 404, request_desc=f"GET /expenses/{expense_a_id} (as org B)", response=r,
           message="org B reading org A's expense by id must return 404")

    story.say(f"Org B ({org_b}) attempts to PUT org A's expense {expense_a_id} -- must be 404")
    upd_exp_payload = {"amount": 1.0}
    r = client.put(f"/expenses/{expense_a_id}", json=upd_exp_payload, headers={**headers_b, "Idempotency-Key": "tenant-b-tries-exp-upd"})
    expect(r.status_code == 404, request_desc=f"PUT /expenses/{expense_a_id} json={upd_exp_payload} (as org B)", response=r,
           message="org B updating org A's expense by id must return 404")

    story.say(f"Org B ({org_b}) attempts to DELETE org A's expense {expense_a_id} -- must be 404")
    r = client.delete(f"/expenses/{expense_a_id}", headers={**headers_b, "Idempotency-Key": "tenant-b-tries-exp-del"})
    expect(r.status_code == 404, request_desc=f"DELETE /expenses/{expense_a_id} (as org B)", response=r,
           message="org B deleting org A's expense by id must return 404")

    story.say(f"Org B ({org_b}) attempts to GET org A's agent job {job_a_id} -- must be 404")
    r = client.get(f"/agent-jobs/{job_a_id}", headers=headers_b)
    expect(r.status_code == 404, request_desc=f"GET /agent-jobs/{job_a_id} (as org B)", response=r,
           message="org B reading org A's agent job by id must return 404")

    story.say(f"Confirming sale A ({sale_a_id}) survived org B's failed delete attempt")
    r = client.get(f"/sales/{sale_a_id}", headers=headers_a)
    expect(r.status_code == 200, request_desc=f"GET /sales/{sale_a_id} (as org A)", response=r,
           message="org A's own sale must still exist and be readable after org B's failed cross-tenant delete")

    story.say("Confirming list endpoints never leak org A's rows to org B")
    b_sales_resp = client.get("/sales", headers=headers_b)
    b_sales = b_sales_resp.json()
    expect(sale_a_id not in {s["id"] for s in b_sales}, request_desc="GET /sales (as org B)", response=b_sales_resp,
           message=f"org B's sales list must not contain org A's sale_a_id {sale_a_id}")

    b_expenses_resp = client.get("/expenses", headers=headers_b)
    b_expenses = b_expenses_resp.json()
    expect(expense_a_id not in {e["id"] for e in b_expenses}, request_desc="GET /expenses (as org B)", response=b_expenses_resp,
           message=f"org B's expenses list must not contain org A's expense_a_id {expense_a_id}")
    story.say("Cross-tenant isolation scenario complete -- no leaks, no 403s, all 404s.")
