"""Shared fixtures for the prompt-5 OBSERVATIONAL agent e2e suite.

This suite is deliberately non-assertive about agent behavior/routing: its
job is to drive the real three-agent chain (planner -> record/investigate)
against real Supabase/Redis via `Runner.run_streamed()` and print the full
captured event stream so a human can review it (`pytest -s`). No test here
should assert on which agent/tool got chosen or on output content -- only
that the run completed without raising.

Follows the same real-infra convention as tests/e2e/prompt-3/conftest.py and
tests/e2e/prompt-4/conftest.py: re-point app.clients.get_supabase()/
get_redis() at real clients built from .env, shadowing the repo-root autouse
fake-wiring fixture. Gated behind RUN_E2E=1 since it needs a real
OPENAI_API_KEY plus real Supabase/Redis -- without RUN_E2E=1 the whole
directory is skipped, not faked.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("APP_ENV", "test")

RUN_E2E = os.environ.get("RUN_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_E2E,
    reason="Requires RUN_E2E=1 plus real Supabase/Redis/OPENAI_API_KEY to drive Runner.run_streamed() live "
    "for observation. Set RUN_E2E=1 (and fill in .env) to run this suite for real.",
)

LOG_PATH = Path(__file__).parent / "test_run.log"

_run_logger = logging.getLogger("prompt5.e2e")
_run_logger.setLevel(logging.INFO)


def pytest_configure(config):  # noqa: D401 -- pytest hook, not a test
    for h in list(_run_logger.handlers):
        _run_logger.removeHandler(h)
        h.close()

    handler = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _run_logger.addHandler(handler)
    _run_logger.propagate = False

    _run_logger.info("=" * 88)
    _run_logger.info("prompt-5 OBSERVATIONAL e2e run log -- tests/e2e/prompt-5/test_run.log")
    _run_logger.info("No pass/fail judgment on agent behavior lives here -- review manually.")
    _run_logger.info("=" * 88)


def unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


class Story:
    """Narrates a test's steps to both stdout (for `pytest -s`) and the
    shared per-run log file."""

    def __init__(self, test_name: str):
        self._test_name = test_name
        self.say(f"--- starting {test_name} ---")

    def say(self, message: str) -> None:
        line = f"[{self._test_name}] {message}"
        print(line)
        _run_logger.info(line)

    def record(self, label: str, record: dict) -> None:
        self.say(f"RECORD {label}: {record}")


@pytest.fixture
def story(request):
    s = Story(request.node.nodeid)
    yield s
    s.say(f"--- finished {request.node.nodeid} ---")


# ---------------------------------------------------------------------------
# Real-infra client wiring (only actually exercised when RUN_E2E=1; imports
# are deferred into the fixture body so collection never requires a real
# .env / network access).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _wire_real_infra():
    if not RUN_E2E:
        yield
        return

    from app.clients import set_redis, set_supabase
    from app.config import get_settings
    from supabase import create_client
    import redis.asyncio as aioredis

    settings = get_settings()
    set_supabase(create_client(settings.supabase_url, settings.supabase_service_key))
    set_redis(aioredis.from_url(settings.redis_url, decode_responses=True))
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    from app.clients import get_supabase

    return get_supabase()


class Cleanup:
    """Strict id+org_id-scoped teardown: every row registered via
    track_row is deleted in `flush()`, which the `cleanup` fixture below
    runs inside a try/finally so cleanup ALWAYS happens, even when the test
    body raises."""

    def __init__(self, db, story: Story):
        self._db = db
        self._story = story
        self._rows: list[tuple[str, str, str | None, dict]] = []

    def track_row(self, table: str, record_id: str, org_id: str | None = None, **fields) -> None:
        record = {"table": table, "id": record_id, "org_id": org_id, **fields}
        self._rows.append((table, record_id, org_id, record))
        self._story.record(f"created {table}", record)

    def flush(self) -> list[str]:
        errors: list[str] = []
        for table, record_id, org_id, record in reversed(self._rows):
            self._story.say(f"tearing down {table}:{record_id} -- {record}")
            try:
                q = self._db.table(table).delete().eq("id", record_id)
                if org_id is not None and table != "orgs":
                    q = q.eq("org_id", org_id)
                q.execute()
                self._story.say(f"deleted {table}:{record_id}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"cleanup failed for {table}:{record_id}: {exc!r}")
                self._story.say(f"cleanup FAILED for {table}:{record_id}: {exc!r}")
        return errors


@pytest.fixture
def cleanup(db, story):
    """Guaranteed teardown fixture: yield + finally so cleanup runs
    unconditionally, even on an unexpected exception mid-test."""
    c = Cleanup(db, story)
    try:
        yield c
    finally:
        story.say("=== teardown: deleting everything this test created ===")
        errors = c.flush()
        if errors:
            import warnings

            warnings.warn("prompt-5 e2e cleanup issues: " + "; ".join(errors))


def register_org(client, cleanup, story, tag: str):
    """Direct HTTP registration -- the real integration point for creating
    an org/user, per the existing e2e convention."""
    email = unique_email(tag)
    payload = {
        "email": email,
        "password": "correct-horse-1",
        "full_name": "E2E Observational Tester",
        "org_name": f"Org-{tag}",
    }
    story.say(f"Registering user {email!r} for org 'Org-{tag}'")
    resp = client.post(
        "/auth/register",
        json=payload,
        headers={"Idempotency-Key": f"reg-{tag}-{uuid.uuid4().hex[:6]}"},
    )
    if resp.status_code != 201:
        raise AssertionError(f"registration failed unexpectedly: {resp.status_code} {resp.text}")
    body = resp.json()
    org_id = body["org"]["id"]
    user_id = body["user"]["id"]
    story.say(f"Registered: user_id={user_id} org_id={org_id}")
    cleanup.track_row("users", user_id, org_id, email=email)
    cleanup.track_row("orgs", org_id, org_name=f"Org-{tag}")
    return org_id, user_id


class StreamCapture:
    """Buckets Runner.run_streamed() events into handoffs / tool_calls /
    outputs and prints every event as it arrives, for human review. Reads
    attributes defensively so an unrelated or SDK-version-shifted event
    shape is logged and skipped rather than crashing the observation run.
    """

    def __init__(self, story: Story):
        self.handoffs: list[str] = []
        self.tool_calls: list[tuple[str, dict]] = []
        self.outputs: list[str] = []
        self._story = story

    def record(self, event) -> None:
        etype = getattr(event, "type", None)
        if etype == "agent_updated_stream_event":
            name = getattr(getattr(event, "new_agent", None), "name", "?")
            self.handoffs.append(name)
            self._story.say(f"HANDOFF -> {name}")
            return
        if etype == "run_item_stream_event":
            item = getattr(event, "item", None)
            item_type = getattr(item, "type", None)
            if item_type == "tool_call_item":
                raw = getattr(item, "raw_item", None)
                name = getattr(raw, "name", "?")
                raw_args = getattr(raw, "arguments", "{}") or "{}"
                try:
                    args = json.loads(raw_args)
                except (TypeError, ValueError):
                    args = {"_raw": raw_args}
                self.tool_calls.append((name, args))
                self._story.say(f"TOOL_CALL {name}({args})")
            elif item_type == "tool_call_output_item":
                output = getattr(item, "output", None)
                self._story.say(f"TOOL_CALL_OUTPUT {output!r}")
            elif item_type == "message_output_item":
                self.outputs.append(str(item))
                self._story.say(f"MESSAGE_OUTPUT {item}")
            else:
                self._story.say(f"run_item_stream_event (unhandled item_type={item_type!r}), skipping")
            return
        self._story.say(f"unhandled stream event type={etype!r}, skipping")

    def tool_names(self) -> list[str]:
        return [name for name, _ in self.tool_calls]

    def args_for(self, tool_name: str) -> dict:
        for name, args in self.tool_calls:
            if name == tool_name:
                return args
        return {}

    def print_summary(self) -> None:
        self._story.say("=" * 72)
        self._story.say("STREAM SUMMARY (for human review -- no pass/fail judgment here)")
        self._story.say(f"  handoffs:   {self.handoffs}")
        self._story.say(f"  tool_calls: {self.tool_calls}")
        self._story.say(f"  outputs:    {self.outputs}")
        self._story.say("=" * 72)


async def run_planner(db, *, org_id: str, user_id: str, message: str, story: Story):
    """Builds the real three-agent chain via the production wiring
    (`build_agents`) and drives `Runner.run_streamed()` directly against the
    planner, capturing and printing every event -- the exact call shape
    `run_bookkeeping_agent()` uses internally, just with full observation
    instead of only a log line.
    """
    from agents import Runner

    from ai_agents.api.financial_advisor_agent import DEFAULT_MAX_TURNS, build_agents

    planner_agent, _investigate_agent, _record_agent = build_agents(db, org_id=org_id, user_id=user_id)

    capture = StreamCapture(story)
    result = Runner.run_streamed(planner_agent, message, max_turns=DEFAULT_MAX_TURNS)
    async for event in result.stream_events():
        capture.record(event)
    capture.print_summary()

    story.say(f"final_output: {getattr(result, 'final_output', None)!r}")
    return result, capture


async def run_agent_directly(agent, *, message: str, story: Story):
    """Drives Runner.run_streamed() against a single specialist agent
    directly (bypassing the planner), for tests that want to observe one
    specialist's behavior in isolation."""
    from agents import Runner

    from ai_agents.api.financial_advisor_agent import DEFAULT_MAX_TURNS

    capture = StreamCapture(story)
    result = Runner.run_streamed(agent, message, max_turns=DEFAULT_MAX_TURNS)
    async for event in result.stream_events():
        capture.record(event)
    capture.print_summary()

    story.say(f"final_output: {getattr(result, 'final_output', None)!r}")
    return result, capture
