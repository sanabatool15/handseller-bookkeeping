from datetime import datetime

from pydantic import BaseModel


class AgentRunRequest(BaseModel):
    month: int
    year: int


class AgentRunResult(BaseModel):
    agent_id: str
    org_id: str
    user_id: str
    action_summary: str
    insights_generated: dict
    executed_at: datetime | None = None
