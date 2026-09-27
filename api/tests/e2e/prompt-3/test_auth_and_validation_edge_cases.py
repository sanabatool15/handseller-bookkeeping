"""Scenario 5: auth and input-validation edge cases, against real Supabase.

Real-infra e2e (see PROMPT_V3.md): narrated, self-explanatory-on-failure
version of prompt-2's auth/validation edge cases.
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


def _register(client, cleanup, story, tag: str, email: str | None = None):
    email = email or unique_email(tag)
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
    return email, body["access_token"], org_id, user_id


def test_duplicate_email_registration_is_rejected(client, cleanup, story):
    email, _token, _org_id, _user_id = _register(client, cleanup, story, "dup-email")

    dup_payload = {"email": email, "password": "some-other-pass", "full_name": "Dup", "org_name": "Dup Co"}
    story.say(f"Attempting to register the SAME email {email!r} a second time -- expecting rejection")
    dup = client.post("/auth/register", json=dup_payload, headers={"Idempotency-Key": "dup-email-attempt"})
    expect(dup.status_code == 409, request_desc=f"POST /auth/register json={dup_payload}", response=dup,
           message="registering a duplicate email should return 409 Conflict")
    story.say("Asserting status 409 -- got it. Duplicate-email scenario complete.")


def test_login_with_wrong_password_is_rejected(client, cleanup, story):
    email, _token, _org_id, _user_id = _register(client, cleanup, story, "wrong-pw")

    login_payload = {"email": email, "password": "definitely-not-it"}
    story.say(f"Logging in as {email!r} with a WRONG password -- expecting rejection")
    bad_login = client.post("/auth/login", json=login_payload)
    expect(bad_login.status_code == 401, request_desc=f"POST /auth/login json={login_payload}", response=bad_login,
           message="login with the wrong password should return 401 Unauthorized")
    story.say("Asserting status 401 -- got it. Wrong-password scenario complete.")


def test_unauthenticated_request_to_protected_route_is_rejected(client, story):
    story.say("GETing /sales with NO Authorization header -- expecting rejection")
    resp = client.get("/sales")
    expect(resp.status_code == 401, request_desc="GET /sales (no Authorization header)", response=resp,
           message="an unauthenticated request to a protected route should return 401")
    story.say("Asserting status 401 -- got it. Unauthenticated-request scenario complete.")


def test_malformed_bearer_token_is_rejected(client, story):
    story.say("GETing /sales with a malformed bearer token -- expecting rejection")
    resp = client.get("/sales", headers={"Authorization": "Bearer not-a-real-jwt"})
    expect(resp.status_code == 401, request_desc="GET /sales (Authorization: Bearer not-a-real-jwt)", response=resp,
           message="a malformed bearer token should return 401")
    story.say("Asserting status 401 -- got it. Malformed-token scenario complete.")


def test_non_positive_sale_amount_is_rejected(client, cleanup, story):
    _email, token, _org_id, _user_id = _register(client, cleanup, story, "nonpos-sale")
    headers = {"Authorization": f"Bearer {token}"}

    zero_payload = {"amount": 0, "category": "retail"}
    story.say("POSTing a sale with amount=0 -- expecting rejection")
    resp = client.post("/sales", json=zero_payload, headers={**headers, "Idempotency-Key": "nonpos-sale-attempt"})
    expect(resp.status_code == 422, request_desc=f"POST /sales json={zero_payload}", response=resp,
           message="a sale with amount=0 should return 422 Unprocessable Entity")
    story.say("Asserting status 422 for amount=0 -- got it.")

    negative_payload = {"amount": -5.0, "category": "retail"}
    story.say("POSTing a sale with amount=-5.0 -- expecting rejection")
    resp_negative = client.post("/sales", json=negative_payload, headers={**headers, "Idempotency-Key": "nonpos-sale-attempt-2"})
    expect(resp_negative.status_code == 422, request_desc=f"POST /sales json={negative_payload}", response=resp_negative,
           message="a sale with amount=-5.0 should return 422 Unprocessable Entity")
    story.say("Asserting status 422 for amount=-5.0 -- got it. Non-positive-sale-amount scenario complete.")


def test_non_positive_expense_amount_is_rejected(client, cleanup, story):
    _email, token, _org_id, _user_id = _register(client, cleanup, story, "nonpos-expense")
    headers = {"Authorization": f"Bearer {token}"}

    zero_payload = {"amount": 0, "category": "supplies"}
    story.say("POSTing an expense with amount=0 -- expecting rejection")
    resp = client.post("/expenses", json=zero_payload, headers={**headers, "Idempotency-Key": "nonpos-expense-attempt"})
    expect(resp.status_code == 422, request_desc=f"POST /expenses json={zero_payload}", response=resp,
           message="an expense with amount=0 should return 422 Unprocessable Entity")
    story.say("Asserting status 422 -- got it. Non-positive-expense-amount scenario complete.")
