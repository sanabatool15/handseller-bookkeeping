"""Shared fixtures for the prompt-4 planner-routing e2e suite.

Follows the same real-infra pattern as `tests/e2e/prompt-3/conftest.py`
(re-point `app.clients.get_supabase()`/`get_redis()` at real clients built
from `.env`, shadowing the repo-root autouse `_wire_fakes`), plus a `story`
narrator and an `expect()` self-explaining assertion helper, reused
verbatim in spirit.

What prompt-4 adds on top of prompt-3: fixtures for building the actual
three-agent chain (`ai_agents.api.financial_advisor_agent.build_agents`)
against a live org/user, and a strict, autouse-independent `cleanup`
fixture (yield + finally) so any DB rows created while driving the agents
directly (bypassing the HTTP layer) are still guaranteed to be deleted even
when an assertion raises mid-test.

Everything in this directory is gated behind `RUN_E2E=1`, same convention
as `tests/e2e/test_full_inngest_workflow.py`, because it requires a real
`OPENAI_API_KEY` (to actually drive `Runner.run_streamed()` against a live
model) plus real Supabase/Redis. Without RUN_E2E=1 the whole module is
skipped, not faked -- these tests are written to prove real planner
routing behavior, not to pass against a mock.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("APP_ENV", "test")

RUN_E2E = os.environ.get("RUN_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_E2E,
    reason="Requires RUN_E2E=1 plus real Supabase/Redis/OPENAI_API_KEY to drive Runner.run_streamed() live. "
    "Set RUN_E2E=1 (and fill in .env) to run this suite for real.",
)

LOG_PATH = Path(__file__).parent / "test_run.log"

_run_logger = logging.getLogger("prompt4.e2e")
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
    _run_logger.info("prompt-4 e2e run log -- tests/e2e/prompt-4/test_run.log")
    _run_logger.info("This file is fully overwritten at the start of every run.")
    _run_logger.info("=" * 88)


def unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


class Story:
    """Narrates a test's steps to both stdout and the shared per-run log
    file, mirroring tests/e2e/prompt-3/conftest.py's Story."""

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


def expect(condition: bool, *, request_desc: str, response, message: str) -> None:
    """Assert-with-context. `response` may be None (no HTTP response
    involved -- e.g. asserting on a stream_events() list), or anything with
    `.status_code`/`.text`."""
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
        detail = f"{message}\n  context: {request_desc}"
    raise AssertionError(detail)


# ---------------------------------------------------------------------------
# Real-infra client wiring (only actually exercised when RUN_E2E=1; imports
# are deferred into the fixture body so collection never requires a real
# .env / network access).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _wire_fakes():
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
    """Strict id+org_id-scoped teardown: every row/key registered via
    track_row/track_redis_key is deleted in `flush()`, which the `cleanup`
    fixture below runs inside a try/finally so cleanup ALWAYS happens, even
    when the test body raises an assertion error."""

    def __init__(self, db, story: Story):
        self._db = db
        self._story = story
        self._rows: list[tuple[str, str, str | None, dict]] = []
        self._redis_keys: list[str] = []

    def track_row(self, table: str, record_id: str, org_id: str | None = None, **fields) -> None:
        record = {"table": table, "id": record_id, "org_id": org_id, **fields}
        self._rows.append((table, record_id, org_id, record))
        self._story.record(f"created {table}", record)

    def track_redis_key(self, key: str) -> None:
        self._redis_keys.append(key)
        self._story.say(f"tracking redis key for cleanup: {key}")

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
        for key in self._redis_keys:
            self._story.say(f"deleting redis key {key}")
            try:
                from app.clients import get_redis

                r = get_redis()
                asyncio.get_event_loop().run_until_complete(r.delete(key))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"redis cleanup failed for {key}: {exc!r}")
                self._story.say(f"redis cleanup FAILED for {key}: {exc!r}")
        return errors


@pytest.fixture
def cleanup(db, story):
    """Autouse-independent strict cleanup fixture: yield + finally so
    teardown runs unconditionally, guaranteeing no DB row/Redis key created
    by a test in this directory survives the test, even on assertion
    failure or unexpected exception."""
    c = Cleanup(db, story)
    try:
        yield c
    finally:
        story.say("=== teardown: deleting everything this test created ===")
        errors = c.flush()
        if errors:
            import warnings

            warnings.warn("prompt-4 e2e cleanup issues: " + "; ".join(errors))
