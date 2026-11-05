"""Agent CRUD routes (architecture §4.1).

Agent config CRUD with immutable versions. Each publish creates a new version.
Delete is a soft delete: blocks new sessions while active calls finish.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.agent.config import AgentConfig, AgentExists, AgentSpec
from app.api.auth import AuthContext, get_auth
from app.api.deps import get_agent_repo

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.get("", response_model=list[AgentConfig])
async def list_agents(
    auth: AuthContext = Depends(get_auth),
    repo=Depends(get_agent_repo),
):
    return await repo.list(auth.org_id)


@router.get("/{agent_id}", response_model=AgentConfig)
async def get_agent(
    agent_id: str,
    auth: AuthContext = Depends(get_auth),
    repo=Depends(get_agent_repo),
):
    agent = await repo.get(auth.org_id, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


@router.post("/{agent_id}", response_model=AgentConfig, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent_id: str,
    spec: AgentSpec,
    auth: AuthContext = Depends(get_auth),
    repo=Depends(get_agent_repo),
):
    try:
        return await repo.create(auth.org_id, agent_id, spec)
    except AgentExists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Agent '{agent_id}' already exists")


@router.put("/{agent_id}", response_model=AgentConfig)
async def update_agent(
    agent_id: str,
    spec: AgentSpec,
    auth: AuthContext = Depends(get_auth),
    repo=Depends(get_agent_repo),
):
    result = await repo.update(auth.org_id, agent_id, spec)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return result


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    auth: AuthContext = Depends(get_auth),
    repo=Depends(get_agent_repo),
):
    deleted = await repo.delete(auth.org_id, agent_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
