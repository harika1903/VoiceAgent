"""WebSocket entrypoints.

Legacy dev mode: browser connects directly over WebSocket to a single-process
uvicorn server. Production mode uses LiveKit rooms instead (see routes_calls.py).
"""

from fastapi import APIRouter, WebSocket
from loguru import logger

from app.agent.config import DEFAULT_AGENT_ID
from app.agent.pipeline import run_agent_legacy
from app.transports.browser import build_browser_transport

router = APIRouter()


@router.websocket("/ws/web")
async def web_call(websocket: WebSocket, agent_id: str = DEFAULT_AGENT_ID):
    """Legacy browser transport — single-process dev mode (no Redis, no LiveKit)."""
    app = websocket.app
    settings = app.state.settings
    agents = app.state.agents
    sessions = app.state.sessions

    await websocket.accept()

    # In dev mode, agents is the InMemoryAgentRepository (no org_id needed)
    agent = await agents.get(agent_id)
    if agent is None:
        await websocket.close(code=4404, reason="unknown agent")
        return
    if missing := settings.missing_keys():
        logger.error(f"missing API keys: {missing}")
        await websocket.close(code=4500, reason=f"server missing {', '.join(missing)}")
        return

    session = await sessions.create(
        org_id="dev",
        agent_id=agent.id,
        agent_version=agent.version,
        call_type="web_inbound",
    )
    transport = build_browser_transport(websocket, settings)
    await run_agent_legacy(
        transport=transport,
        agent=agent,
        session=session,
        sessions=sessions,
        settings=settings,
        embedder=app.state.embedder,
        kb=getattr(app.state, "kb", None),
    )
