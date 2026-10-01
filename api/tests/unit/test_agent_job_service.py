"""agent_job_service + agent_jobs repository fakes: org scoping, logs, commit-before-event."""
from __future__ import annotations

import pytest

from jobs import inngest_client as inngest_client_module
from repository import agent_jobs_repository as repo
from services import agent_job_service
from tests.fake_repos import FakeSqlDb


@pytest.fixture
def no_inngest(monkeypatch):
    sent = []

    async def fake_send(event):
        sent.append(event)

    monkeypatch.setattr(inngest_client_module.inngest_client, "send", fake_send)
    return sent


@pytest.mark.asyncio
async def test_trigger_commits_job_before_sending_event(sql_store, no_inngest, monkeypatch):
    db = FakeSqlDb(sql_store)
    seen = {}

    async def send(event):
        seen["commits_at_send"] = db.commits
        no_inngest.append(event)

    monkeypatch.setattr(inngest_client_module.inngest_client, "send", send)
    job = await agent_job_service.trigger_financial_advice_job(db, org_id="org-1", user_id="u1", question="q?")
    assert seen["commits_at_send"] == 1  # the worker can already see the row
    assert job["status"] == "pending" and job["input_payload"] == {"question": "q?"}
    assert no_inngest[0].data["job_id"] == job["id"]


def test_job_status_scoped_to_org(fake_db):
    job = repo.create_job(fake_db, job_name="financial_advisor", org_id="org-1", requested_by="u1")
    assert agent_job_service.get_job_status(fake_db, org_id="org-1", job_id=job["id"])["id"] == job["id"]
    assert agent_job_service.get_job_status(fake_db, org_id="org-2", job_id=job["id"]) is None


def test_update_job_status_cannot_touch_other_orgs_job(fake_db):
    job = repo.create_job(fake_db, job_name="x", org_id="org-1", requested_by=None)
    assert repo.update_job_status(fake_db, job_id=job["id"], org_id="org-2", status="failed") is None
    assert repo.get_job_scoped(fake_db, job_id=job["id"], org_id="org-1")["status"] == "pending"
    done = repo.update_job_status(fake_db, job_id=job["id"], org_id="org-1", status="completed", current_step="finalize", result={"a": 1})
    assert done["status"] == "completed" and done["result"] == {"a": 1}


def test_logs_are_org_scoped_and_ordered(fake_db):
    job = repo.create_job(fake_db, job_name="x", org_id="org-1", requested_by=None)
    repo.add_log(fake_db, job_id=job["id"], org_id="org-1", step_name="gather_data", action_summary="a", insights_generated={"k": 1})
    repo.add_log(fake_db, job_id=job["id"], org_id="org-1", step_name="finalize", action_summary="b")
    with pytest.raises(RuntimeError):  # a job of another org cannot receive logs
        repo.add_log(fake_db, job_id=job["id"], org_id="org-2", step_name="evil", action_summary="x")

    logs = agent_job_service.get_job_logs(fake_db, org_id="org-1", job_id=job["id"])
    assert [l["step_name"] for l in logs] == ["gather_data", "finalize"] and logs[0]["insights_generated"] == {"k": 1}
    assert agent_job_service.get_job_logs(fake_db, org_id="org-2", job_id=job["id"]) is None
    assert repo.list_logs_for_job(fake_db, job_id=job["id"], org_id="org-2") == []
    assert repo.get_completed_steps(fake_db, job_id=job["id"], org_id="org-1") == {"gather_data", "finalize"}
