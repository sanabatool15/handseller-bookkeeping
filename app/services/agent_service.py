"""Orchestrates the autonomous financial advisor agent run and guarantees
that every run is recorded in agent_logs.
"""
from app.agents.financial_advisor import run_financial_advisor
from app.repository import agent_repository


def _get_or_create_agent() -> dict:
    agent = agent_repository.get_agent_by_name("financial-advisor")
    if agent is None:
        agent = agent_repository.create_agent(
            name="financial-advisor",
            description=(
                "Autonomous financial advisor that analyzes expenses/sales and "
                "proposes cost + pricing actions."
            ),
        )
    return agent


def run_agent(org_id: str, user_id: str, month: int, year: int) -> dict:
    agent = _get_or_create_agent()

    result = run_financial_advisor(org_id=org_id, month=month, year=year)

    log = agent_repository.log_agent_execution(
        agent_id=agent["id"],
        org_id=org_id,
        user_id=user_id,
        action_summary=result["action_summary"],
        insights_generated=result["insights"],
    )
    return log
