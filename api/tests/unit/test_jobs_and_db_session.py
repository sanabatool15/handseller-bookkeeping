"""core.clients.db_session/run_in_db (used by Inngest steps + MCP) and the job steps, against fakes."""
from __future__ import annotations

import pytest

from core.clients import db_session, run_in_db, set_db_factory
from repository import agent_jobs_repository as repo
from tests.fake_repos import FakeSqlDb


def test_db_session_commits_and_closes(sql_store):
    made = []
    set_db_factory(lambda: made.append(FakeSqlDb(sql_store)) or made[-1])
    with db_session() as db:
        pass
    assert (db.commits, db.rollbacks, db.closed) == (1, 0, True)


def test_db_session_rolls_back_and_closes_on_error(sql_store):
    made = []
    set_db_factory(lambda: made.append(FakeSqlDb(sql_store)) or made[-1])
    with pytest.raises(ValueError):
        with db_session() as db:
            repo.create_job(db, job_name="x", org_id="o", requested_by=None)
            raise ValueError("boom")
    assert (db.commits, db.rollbacks, db.closed) == (0, 1, True)
    assert sql_store.agent_jobs == {}  # rolled back


def test_run_in_db_retries_whole_unit_on_deadlock(sql_store):
    attempts = []

    def work(db):
        attempts.append(db)
        if len(attempts) == 1:
            raise RuntimeError("[40001] Transaction was deadlocked (1205)")
        return "ok"

    assert run_in_db(work) == "ok"
    assert len(attempts) == 2 and attempts[0] is not attempts[1]  # fresh connection per attempt


@pytest.mark.asyncio
async def test_job_steps_write_logs_and_status_through_repository(sql_store, monkeypatch):
    from jobs import financial_agent_job as job

    async def no_llm(*a, **k):  # hermetic: force the deterministic rule-based fallback
        raise RuntimeError("no network in unit tests")

    monkeypatch.setattr(job, "run_bookkeeping_agent", no_llm)

    j = repo.create_job(FakeSqlDb(sql_store), job_name="financial_advisor", org_id="org-1", requested_by=None)
    summary = await job._step_gather_data(j["id"], "org-1")
    assert summary["org_id"] == "org-1"
    result = await job._step_run_agent(j["id"], "org-1", "u1", None, summary)
    assert result["source"] == "rule_based_fallback"
    await job._step_finalize(j["id"], "org-1", result)

    stored = repo.get_job_scoped(FakeSqlDb(sql_store), job_id=j["id"], org_id="org-1")
    assert stored["status"] == "completed" and stored["current_step"] == "finalize" and stored["result"] == result
    assert repo.get_completed_steps(FakeSqlDb(sql_store), job_id=j["id"], org_id="org-1") == {"gather_data", "run_agent", "finalize"}
