"""Scenario 3: idempotent retry of a flaky mobile client, against real Redis.

Real-infra e2e (see PROMPT_V3.md): narrated, self-explanatory-on-failure
version of prompt-2's idempotent-retry journey.
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


def test_same_key_retried_creates_exactly_one_row_and_replays_response(client, cleanup, story):
    token, org_id, _ = _register(client, cleanup, story, "idem-retry")
    headers = {"Authorization": f"Bearer {token}"}
    idem_key = f"retry-{uuid.uuid4().hex[:8]}"
    story.say(f"Using Idempotency-Key={idem_key} for two identical POSTs, simulating a flaky mobile client retry")

    sale_payload = {"amount": 42.0, "category": "retail"}
    story.say(f"POSTing sale of amount {sale_payload['amount']} (attempt 1)")
    first = client.post("/sales", json=sale_payload, headers={**headers, "Idempotency-Key": idem_key})
    expect(first.status_code == 201, request_desc=f"POST /sales json={sale_payload} Idempotency-Key={idem_key} (attempt 1)",
           response=first, message="first POST should return 201")
    sale_id = first.json()["id"]
    story.say(f"Asserting status 201 -- got it. sale_id={sale_id}")
    cleanup.track_row("sales", sale_id, org_id, **sale_payload)

    story.say(f"POSTing the exact same sale with the SAME Idempotency-Key={idem_key} (attempt 2 -- simulated retry)")
    second = client.post("/sales", json=sale_payload, headers={**headers, "Idempotency-Key": idem_key})
    expect(second.status_code == 201, request_desc=f"POST /sales json={sale_payload} Idempotency-Key={idem_key} (attempt 2)",
           response=second, message="retried POST should also return 201 (cached replay)")
    expect(
        second.json() == first.json(),
        request_desc=f"POST /sales json={sale_payload} Idempotency-Key={idem_key} (attempt 2)",
        response=second,
        message=f"retry must replay the exact cached response, not re-run the handler. first={first.json()} second={second.json()}",
    )
    story.say("Confirmed: second response is byte-for-byte the cached replay of the first")

    story.say("Listing sales to confirm exactly one row was created for this idempotency key")
    all_sales_resp = client.get("/sales", headers=headers)
    all_sales = all_sales_resp.json()
    matching = [s for s in all_sales if s["id"] == sale_id]
    expect(len(matching) == 1, request_desc="GET /sales", response=all_sales_resp,
           message=f"retry with the same Idempotency-Key must not create a second row; found {len(matching)} rows matching sale_id={sale_id}")
    story.say("Confirmed: exactly one row exists despite two POSTs. Idempotency scenario (a) complete.")


def test_missing_idempotency_key_is_rejected(client, cleanup, story):
    token, org_id, _ = _register(client, cleanup, story, "idem-missing")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {"amount": 10.0, "category": "retail"}
    story.say("POSTing a sale WITHOUT an Idempotency-Key header -- expecting rejection")
    resp = client.post("/sales", json=payload, headers=headers)
    expect(resp.status_code == 400, request_desc=f"POST /sales json={payload} (no Idempotency-Key header)", response=resp,
           message="missing Idempotency-Key on a mutating request should return 400")
    expect("Idempotency-Key" in resp.text, request_desc=f"POST /sales json={payload} (no Idempotency-Key header)", response=resp,
           message="the 400 error body should mention 'Idempotency-Key' so the caller knows why it was rejected")
    story.say("Asserting status 400 -- got it. Missing-key scenario (b) complete.")


def test_same_key_across_two_orgs_does_not_collide(client, cleanup, story):
    story.say("Setting up two separate orgs, A and B, that will reuse the SAME Idempotency-Key")
    token_a, org_a, _ = _register(client, cleanup, story, "idem-org-a")
    token_b, org_b, _ = _register(client, cleanup, story, "idem-org-b")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    shared_key = f"shared-{uuid.uuid4().hex[:8]}"
    story.say(f"Shared Idempotency-Key={shared_key} will be used by both org A and org B")

    payload_a = {"amount": 11.0, "category": "retail"}
    story.say(f"Org A POSTs a sale of amount {payload_a['amount']} using shared key")
    resp_a = client.post("/sales", json=payload_a, headers={**headers_a, "Idempotency-Key": shared_key})
    expect(resp_a.status_code == 201, request_desc=f"POST /sales json={payload_a} Idempotency-Key={shared_key} (org A)",
           response=resp_a, message="org A's POST should return 201")
    sale_a_id = resp_a.json()["id"]
    story.say(f"sale_a_id={sale_a_id}")
    cleanup.track_row("sales", sale_a_id, org_a, **payload_a)

    payload_b = {"amount": 22.0, "category": "wholesale"}
    story.say(f"Org B POSTs a DIFFERENT sale of amount {payload_b['amount']} reusing the SAME shared key")
    resp_b = client.post("/sales", json=payload_b, headers={**headers_b, "Idempotency-Key": shared_key})
    expect(resp_b.status_code == 201, request_desc=f"POST /sales json={payload_b} Idempotency-Key={shared_key} (org B)",
           response=resp_b, message="org B's POST should return 201 (per-org key scoping means no collision)")
    sale_b_id = resp_b.json()["id"]
    story.say(f"sale_b_id={sale_b_id}")
    cleanup.track_row("sales", sale_b_id, org_b, **payload_b)

    story.say("Asserting the two orgs got two DISTINCT rows with their own posted values (no cross-org cache collision)")
    expect(sale_a_id != sale_b_id, request_desc="comparing sale_a_id vs sale_b_id", response=None,
           message=f"org A and org B must get distinct sale ids for the same Idempotency-Key; got sale_a_id={sale_a_id} sale_b_id={sale_b_id}")
    expect(float(resp_a.json()["amount"]) == 11.0, request_desc=f"POST /sales json={payload_a} (org A)", response=resp_a,
           message="org A's response amount should be its own posted 11.0, not org B's")
    expect(float(resp_b.json()["amount"]) == 22.0, request_desc=f"POST /sales json={payload_b} (org B)", response=resp_b,
           message="org B's response amount should be its own posted 22.0, not org A's cached one")
    story.say("Confirmed per-org key scoping (idempotency:{org_id}:{key}). Scenario (c) complete.")
