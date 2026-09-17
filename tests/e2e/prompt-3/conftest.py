"""Shared fixtures for the prompt-3 real-infra e2e suite.

Same real-infra approach as `tests/e2e/prompt-2/`: `app.clients.get_supabase()`
and `app.clients.get_redis()` are re-pointed (via a same-named `_wire_fakes`
override, shadowing the repo-root autouse fixture of that name) at real
`supabase.Client` / `redis.asyncio` clients built straight from `.env`. No
FakeSupabase, no fakeredis, no in-process job simulation anywhere in this
directory.

What prompt-3 adds on top of prompt-2 (see PROMPT_V3.md for the full
write-up):

1. **Narration** — a `story` fixture that every test uses to print a
   step-by-step account of what it's doing ("Registering user X for org Y",
   "POSTing sale of amount Z", "Asserting status 201", ...), so
   `pytest -v -s` produces a readable story of the test, not silent
   execution.
2. **Self-explanatory assertions** — an `expect()` helper that, on failure,
   always includes the actual HTTP method/URL/headers/body that was sent
   and the actual status code + body that came back, never a bare
   `assert 409 == 201`.
3. **Created-record logging before teardown** — the `cleanup` fixture logs
   the full record (table, id, org_id, and whatever fields the test handed
   it) via the story narrator before it deletes anything, so the run's log
   file preserves what existed even after cleanup deletes it.
4. **One overwritten-per-run log file** — `tests/e2e/prompt-3/test_run.log`,
   configured via `pytest_configure`/a session-scoped fixture below, is
   truncated (mode="w", not "a") at the start of every run and captures
   the complete narrated output of that run, so a run never leaves behind a
   mix of old and new content.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")

from app.clients import get_redis, get_supabase, set_redis, set_supabase  # noqa: E402
from app.main import app  # noqa: E402
from app.config import get_settings  # noqa: E402
from supabase import create_client  # noqa: E402
import redis.asyncio as aioredis  # noqa: E402


LOG_PATH = Path(__file__).parent / "test_run.log"


def unique_email(tag: str) -> str:
    return f"e2e-{tag}-{uuid.uuid4().hex[:10]}@example.com"


# ---------------------------------------------------------------------------
# Logging: one file, fully overwritten (not appended to) at the start of
# every run, containing the complete narrated output of that run.
# ---------------------------------------------------------------------------

_run_logger = logging.getLogger("prompt3.e2e")
_run_logger.setLevel(logging.INFO)


def pytest_configure(config):  # noqa: D401 -- pytest hook, not a test
    """Runs once per pytest invocation, before any test collection finishes.

    Opens LOG_PATH in "w" mode via FileHandler(mode="w"), which truncates any
    existing content -- guaranteeing this run's log file contains ONLY this
    run's output, never a mix of a previous run's content plus this one's.
    """
    # Remove any handlers a previous (in-process, e.g. re-run) configure call
    # left attached, so we never double-log or hold a stale file handle open.
    for h in list(_run_logger.handlers):
        _run_logger.removeHandler(h)
        h.close()

    handler = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _run_logger.addHandler(handler)
    _run_logger.propagate = False

    _run_logger.info("=" * 88)
    _run_logger.info("prompt-3 e2e run log — tests/e2e/prompt-3/test_run.log")
    _run_logger.info("This file is fully overwritten at the start of every run.")
    _run_logger.info("=" * 88)


class Story:
    """Narrates a test's steps to both stdout (so `pytest -v -s` shows a
    readable story live) and the shared per-run log file (so the story
    survives after cleanup deletes the data it describes)."""

    def __init__(self, test_name: str):
        self._test_name = test_name
        self.say(f"--- starting {test_name} ---")

    def say(self, message: str) -> None:
        line = f"[{self._test_name}] {message}"
        print(line)
        _run_logger.info(line)

    def record(self, label: str, record: dict) -> None:
        """Logs a full created/deleted record before it can be lost."""
        self.say(f"RECORD {label}: {record}")


@pytest.fixture
def story(request):
    s = Story(request.node.nodeid)
    yield s
    s.say(f"--- finished {request.node.nodeid} ---")


def expect(condition: bool, *, request_desc: str, response, message: str) -> None:
    """Assert-with-context: on failure, always includes the actual request
    sent and the actual response received (status + body), never a bare
    comparison. `response` is anything with `.status_code` and `.text`
    (an httpx/TestClient Response), or None if the assertion isn't about a
    response.
    """
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


# ---------------------------------------------------------------------------
# Real-infra client wiring (same shadowing trick as prompt-2's conftest.py,
# needed because tests/conftest.py's autouse `_wire_fakes` would otherwise
# silently inject FakeSupabase/fakeredis into every test under `tests/`).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _wire_fakes():
    settings = get_settings()
    set_supabase(create_client(settings.supabase_url, settings.supabase_service_key))
    set_redis(aioredis.from_url(settings.redis_url, decode_responses=True))
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    return get_supabase()


@pytest.fixture
def redis_client():
    return get_redis()


class Cleanup:
    """Same id+org_id-scoped teardown discipline as prompt-2, plus: logs the
    full record it's about to delete via the test's Story narrator BEFORE
    deleting it, so the log file retains a record of what existed during the
    run even after this teardown removes it from the real DB."""

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
            self._story.say(f"tearing down {table}:{record_id} -- logging record before delete: {record}")
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
                r = get_redis()
                asyncio.get_event_loop().run_until_complete(r.delete(key))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"redis cleanup failed for {key}: {exc!r}")
                self._story.say(f"redis cleanup FAILED for {key}: {exc!r}")
        return errors


@pytest.fixture
def cleanup(db, story):
    c = Cleanup(db, story)
    yield c
    story.say("=== teardown: deleting everything this test created ===")
    errors = c.flush()
    if errors:
        import warnings

        warnings.warn("prompt-3 e2e cleanup issues: " + "; ".join(errors))
