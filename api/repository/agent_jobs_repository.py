"""agent_jobs / agent_logs repository (SQL Server / T-SQL) - resumable state tracking for Inngest jobs.

JSON columns (input_payload, result, error_details, insights_generated) are nvarchar(max) holding JSON
text; they are serialised on write and parsed on read so callers still see plain dicts (same shape
as the old Supabase jsonb columns).
"""
from __future__ import annotations

from typing import Any, Optional

from core.db import Db
from repository.base import from_json, to_json

_JOB_JSON = ("input_payload", "result", "error_details")

# agent_jobs / agent_logs have AFTER UPDATE triggers => OUTPUT ... INTO @table (SQL Server error 334).
_JOB_DECL = (
    "SET NOCOUNT ON; "
    "DECLARE @o TABLE (id uniqueidentifier, job_name nvarchar(100), org_id uniqueidentifier, "
    "requested_by uniqueidentifier, status nvarchar(20), current_step nvarchar(100), "
    "input_payload nvarchar(max), result nvarchar(max), error_details nvarchar(max), "
    "created_at datetimeoffset, updated_at datetimeoffset); "
)
_JOB_COLS = (
    "OUTPUT INSERTED.id, INSERTED.job_name, INSERTED.org_id, INSERTED.requested_by, INSERTED.status, "
    "INSERTED.current_step, INSERTED.input_payload, INSERTED.result, INSERTED.error_details, "
    "INSERTED.created_at, INSERTED.updated_at INTO @o "
)
_CREATE_JOB = (
    _JOB_DECL
    + "INSERT INTO agent_jobs (job_name, org_id, requested_by, status, input_payload) "
    + _JOB_COLS
    + "VALUES (?, ?, ?, N'pending', ?); SELECT * FROM @o;"
)
_GET_JOB = "SELECT TOP (1) * FROM agent_jobs WHERE id = ? AND org_id = ?"
# Only provided values change (COALESCE keeps the column otherwise); keeps the statement static.
_UPDATE_JOB = (
    _JOB_DECL
    + "UPDATE agent_jobs SET status = ?, current_step = COALESCE(?, current_step), "
    + "result = COALESCE(?, result), error_details = COALESCE(?, error_details) "
    + _JOB_COLS
    + "WHERE id = ? AND org_id = ?; SELECT * FROM @o;"
)

_LOG_DECL = (
    "SET NOCOUNT ON; "
    "DECLARE @o TABLE (id uniqueidentifier, job_id uniqueidentifier, org_id uniqueidentifier, "
    "step_name nvarchar(100), action_summary nvarchar(max), insights_generated nvarchar(max), "
    "executed_at datetimeoffset, created_at datetimeoffset, updated_at datetimeoffset); "
)
# INSERT ... SELECT FROM agent_jobs WHERE id AND org_id: the log row is only written if the job really
# belongs to that org (and the composite FK (job_id, org_id) backs this up inside the database).
_ADD_LOG = (
    _LOG_DECL
    + "INSERT INTO agent_logs (job_id, org_id, step_name, action_summary, insights_generated) "
    + "OUTPUT INSERTED.id, INSERTED.job_id, INSERTED.org_id, INSERTED.step_name, INSERTED.action_summary, "
    + "INSERTED.insights_generated, INSERTED.executed_at, INSERTED.created_at, INSERTED.updated_at INTO @o "
    + "SELECT id, org_id, ?, ?, ? FROM agent_jobs WHERE id = ? AND org_id = ?; SELECT * FROM @o;"
)
_COMPLETED_STEPS = "SELECT step_name FROM agent_logs WHERE job_id = ? AND org_id = ?"
_LIST_LOGS = "SELECT * FROM agent_logs WHERE job_id = ? AND org_id = ? ORDER BY executed_at, created_at, id"


def _decode_job(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {k: (from_json(v) if k in _JOB_JSON else v) for k, v in row.items()}


def _decode_log(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (from_json(v) if k == "insights_generated" else v) for k, v in row.items()}


def create_job(db: Db, *, job_name: str, org_id: str, requested_by: str | None, input_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    row = db.query_one(_CREATE_JOB, (job_name, org_id, requested_by, to_json(input_payload or {})))
    if row is None:
        raise RuntimeError("Failed to create agent job")
    return _decode_job(row)  # type: ignore[return-value]


def get_job_scoped(db: Db, *, job_id: str, org_id: str) -> Optional[dict[str, Any]]:
    return _decode_job(db.query_one(_GET_JOB, (job_id, org_id)))


def update_job_status(db: Db, *, job_id: str, org_id: str, status: str, current_step: str | None = None, result: dict[str, Any] | None = None, error_details: dict[str, Any] | None = None) -> Optional[dict[str, Any]]:
    params = (status, current_step, to_json(result), to_json(error_details), job_id, org_id)
    return _decode_job(db.query_one(_UPDATE_JOB, params))


def add_log(db: Db, *, job_id: str, org_id: str, step_name: str, action_summary: str, insights_generated: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append a log row to a job of THIS org. (`org_id` is new vs. the Supabase signature: agent_logs now carries org_id.)"""
    row = db.query_one(_ADD_LOG, (step_name, action_summary, to_json(insights_generated or {}), job_id, org_id))
    if row is None:
        raise RuntimeError("Failed to write agent log (job not found for this org)")
    return _decode_log(row)


def get_completed_steps(db: Db, *, job_id: str, org_id: str) -> set[str]:
    """Used by Inngest step functions to know which steps already ran, so a
    retried function invocation can skip re-doing completed work."""
    return {r["step_name"] for r in db.query(_COMPLETED_STEPS, (job_id, org_id))}


def list_logs_for_job(db: Db, *, job_id: str, org_id: str) -> list[dict[str, Any]]:
    """All logs of a job, oldest first, only if the job belongs to this org."""
    return [_decode_log(r) for r in db.query(_LIST_LOGS, (job_id, org_id))]
