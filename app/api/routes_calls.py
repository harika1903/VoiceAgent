"""Call start / stop / history routes (architecture §4.1 + §8.1).

POST /v1/calls/web          — start a web inbound call
POST /v1/calls/{id}/end     — end a call
GET  /v1/calls/{id}         — get session state (Redis, live)
GET  /v1/calls              — list call history (Postgres, persisted)
GET  /v1/calls/{id}/transcript — get transcript + summary
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.auth import AuthContext, get_auth
from app.api.deps import get_agent_repo, get_db_pool, get_dispatcher, get_session_store

router = APIRouter(prefix="/v1/calls", tags=["calls"])


class StartWebCallRequest(BaseModel):
    agent_id: str = "default"


class StartWebCallResponse(BaseModel):
    session_id: str
    room: str
    livekit_url: str
    livekit_token: str
    ws_token: str
    worker_ws_url: str


class EndCallRequest(BaseModel):
    reason: str = "admin_stop"


class SessionResponse(BaseModel):
    id: str
    org_id: str
    agent_id: str
    agent_version: int
    call_type: str
    status: str
    epoch: int
    room: str | None
    worker_id: str | None
    worker_ws_url: str | None


class CallHistoryItem(BaseModel):
    id: str
    agent_id: str
    call_type: str
    status: str
    created_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_secs: float | None
    end_reason: str | None
    summary: str | None


class CallHistoryResponse(BaseModel):
    calls: list[CallHistoryItem]
    total: int
    limit: int
    offset: int


class TranscriptTurnResponse(BaseModel):
    seq: int
    role: str
    text: str
    at: datetime
    interrupted: bool


class TranscriptResponse(BaseModel):
    session_id: str
    agent_id: str
    status: str
    created_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_secs: float | None
    summary: str | None
    turns: list[TranscriptTurnResponse]


@router.post("/web", response_model=StartWebCallResponse, status_code=status.HTTP_201_CREATED)
async def start_web_call(
    body: StartWebCallRequest,
    auth: AuthContext = Depends(get_auth),
    repo=Depends(get_agent_repo),
    dispatcher=Depends(get_dispatcher),
):
    """Start a web inbound call (§8.1).

    Returns room + token immediately so the client can connect while
    the worker spins up (~1 s saved before the greeting).
    """
    agent = await repo.get(auth.org_id, body.agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Agent '{body.agent_id}' not found")

    from app.dispatcher.dispatcher import AdmissionDenied

    try:
        result = await dispatcher.start_web_session(org_id=auth.org_id, agent=agent)
    except AdmissionDenied as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))

    return StartWebCallResponse(
        session_id=result.session_id,
        room=result.room,
        livekit_url=result.livekit_url,
        livekit_token=result.livekit_token,
        ws_token=result.ws_token,
        worker_ws_url="",
    )


@router.post("/{session_id}/end", status_code=status.HTTP_200_OK)
async def end_call(
    session_id: str,
    body: EndCallRequest,
    auth: AuthContext = Depends(get_auth),
    dispatcher=Depends(get_dispatcher),
    store=Depends(get_session_store),
):
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if session.org_id != auth.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    ok = await dispatcher.end_session(session_id, reason=body.reason)
    if not ok:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session already ended")
    return {"ok": True}


@router.get("/{session_id}", response_model=SessionResponse)
async def get_call(
    session_id: str,
    auth: AuthContext = Depends(get_auth),
    store=Depends(get_session_store),
):
    session = await store.get(session_id)
    if session is None or session.org_id != auth.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return SessionResponse(
        id=session.id,
        org_id=session.org_id,
        agent_id=session.agent_id,
        agent_version=session.agent_version,
        call_type=session.call_type,
        status=session.status.value,
        epoch=session.epoch,
        room=session.room,
        worker_id=session.worker_id,
        worker_ws_url=session.worker_ws_url,
    )


# ── Call history (Postgres) ───────────────────────────────────────────────

@router.get("", response_model=CallHistoryResponse)
async def list_calls(
    auth: AuthContext = Depends(get_auth),
    pool=Depends(get_db_pool),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    agent_id: str | None = Query(None),
    call_status: str | None = Query(None, alias="status"),
):
    conditions = ["org_id = $1"]
    params: list = [auth.org_id]
    idx = 2

    if agent_id:
        conditions.append(f"agent_id = ${idx}")
        params.append(agent_id)
        idx += 1
    if call_status:
        conditions.append(f"status = ${idx}")
        params.append(call_status)
        idx += 1

    where = " AND ".join(conditions)

    total = await pool.fetchval(
        f"SELECT COUNT(*) FROM call_sessions WHERE {where}", *params
    )

    params.extend([limit, offset])
    rows = await pool.fetch(
        f"""SELECT id, agent_id, call_type, status, created_at, started_at,
                   ended_at, duration_secs, end_reason, summary
            FROM call_sessions WHERE {where}
            ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}""",
        *params,
    )

    return CallHistoryResponse(
        calls=[CallHistoryItem(**dict(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{session_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    session_id: str,
    auth: AuthContext = Depends(get_auth),
    pool=Depends(get_db_pool),
):
    session_row = await pool.fetchrow(
        """SELECT id, agent_id, status, created_at, started_at, ended_at,
                  duration_secs, summary, org_id
           FROM call_sessions WHERE id = $1""",
        session_id,
    )
    if session_row is None or session_row["org_id"] != auth.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")

    turns = await pool.fetch(
        """SELECT seq, role, text, at, interrupted
           FROM transcript_turns WHERE session_id = $1 ORDER BY seq""",
        session_id,
    )

    return TranscriptResponse(
        session_id=session_row["id"],
        agent_id=session_row["agent_id"],
        status=session_row["status"],
        created_at=session_row["created_at"],
        started_at=session_row["started_at"],
        ended_at=session_row["ended_at"],
        duration_secs=session_row["duration_secs"],
        summary=session_row["summary"],
        turns=[TranscriptTurnResponse(**dict(t)) for t in turns],
    )
