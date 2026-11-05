"""Session = one call from start to finish (architecture §7.1 state machine).

States follow the architecture doc exactly. The Dispatcher is the single owner
of transitions; workers only emit events that the Dispatcher reacts to.
"""

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionState(StrEnum):
    CREATED = "created"        # row exists, nothing enqueued yet
    QUEUED = "queued"          # job is on the Redis stream, waiting for a worker
    CONNECTING = "connecting"  # worker claimed, waiting for caller to join the room
    ACTIVE = "active"          # audio flowing between caller and agent
    DIALING = "dialing"       # outbound only: SIP INVITE sent, waiting for answer
    ENDING = "ending"         # wrap_up sent to worker, draining
    RECOVERING = "recovering" # worker crashed, re-enqueued with epoch+1
    TRANSFERRING = "transferring"  # transfer in progress (AI still in room)
    HUMAN = "human"           # human agent connected, AI has left
    FAILED = "failed"         # terminal: unrecoverable error
    ENDED = "ended"           # terminal: normal completion


# Legal transitions. Enforced by the Dispatcher's CAS Lua script in Redis.
ALLOWED: dict[SessionState, set[SessionState]] = {
    SessionState.CREATED:      {SessionState.QUEUED, SessionState.FAILED},
    SessionState.QUEUED:       {SessionState.CONNECTING, SessionState.FAILED, SessionState.ENDED},
    SessionState.CONNECTING:   {SessionState.ACTIVE, SessionState.DIALING, SessionState.FAILED, SessionState.ENDED},
    SessionState.ACTIVE:       {SessionState.ENDING, SessionState.TRANSFERRING, SessionState.RECOVERING, SessionState.FAILED},
    SessionState.DIALING:      {SessionState.ACTIVE, SessionState.ENDING, SessionState.FAILED, SessionState.ENDED},
    SessionState.ENDING:       {SessionState.ENDED, SessionState.FAILED},
    SessionState.RECOVERING:   {SessionState.QUEUED, SessionState.FAILED, SessionState.ENDED},
    SessionState.TRANSFERRING: {SessionState.HUMAN, SessionState.ACTIVE, SessionState.ENDING, SessionState.FAILED},
    SessionState.HUMAN:        {SessionState.ENDING, SessionState.ACTIVE, SessionState.FAILED, SessionState.ENDED},
    SessionState.FAILED:       set(),
    SessionState.ENDED:        set(),
}

TERMINAL = {SessionState.FAILED, SessionState.ENDED}


class TranscriptTurn(BaseModel):
    role: str  # "user" | "assistant"
    text: str
    at: datetime = Field(default_factory=_now)
    interrupted: bool = False
    seq: int = 0  # filled by the store


class Session(BaseModel):
    """In-memory representation. The canonical state lives in Redis (sess:{sid} hash)."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    org_id: str
    agent_id: str
    agent_version: int
    call_type: str = "web_inbound"  # web_inbound | pstn_inbound | pstn_outbound
    status: SessionState = SessionState.CREATED
    epoch: int = 0
    room: str | None = None
    worker_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: str | None = None
    worker_ws_url: str | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)

    @property
    def duration_secs(self) -> float | None:
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None
