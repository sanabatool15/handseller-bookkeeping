from fastapi import APIRouter, Depends, status

from app.core.auth import CurrentUser, get_current_user
from app.schemas.agent import AgentRunRequest, AgentRunResult
from app.services import agent_service

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run", response_model=AgentRunResult, status_code=status.HTTP_201_CREATED)
def run_agent(payload: AgentRunRequest, current_user: CurrentUser = Depends(get_current_user)):
    return agent_service.run_agent(
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        month=payload.month,
        year=payload.year,
    )
