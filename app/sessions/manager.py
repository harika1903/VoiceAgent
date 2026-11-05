"""Session lifecycle helpers used by both Dispatcher and Worker.

The *Dispatcher* owns state transitions (via RedisSessionStore.transition).
This module keeps the convenience wrappers that the worker process uses to
append transcript turns and emit events through the store, plus the
InMemorySessionStore for tests and local dev without Redis.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Protocol

from loguru import logger

from app.sessions.models import ALLOWED, Session, SessionState, TranscriptTurn

PostCallHandler = Callable[[Session], Awaitable[None]]


# ── Protocol (tests can swap implementations) ──────────────────────────────

class SessionStore(Protocol):
    async def save(self, session: Session) -> None: ...
    async def get(self, session_id: str) -> Session | None: ...
    async def list(self) -> list[Session]: ...


class InMemorySessionStore:
    """Good enough for single-process dev mode and unit tests."""

    def __init__(self) -> None:
        self._items: dict[str, Session] = {}

    async def save(self, session: Session) -> None:
        self._items[session.id] = session

    async def get(self, session_id: str) -> Session | None:
        return self._items.get(session_id)

    async def list(self) -> list[Session]:
        return sorted(self._items.values(), key=lambda s: s.created_at, reverse=True)


class InvalidTransition(Exception):
    pass


# ── Worker-side session helper ──────────────────────────────────────────────

class SessionManager:
    """Used by the Worker to add turns and end sessions.

    In production the worker never transitions state directly — it emits events
    that the Dispatcher reacts to. But it does append transcript turns and emit
    usage events through the Redis store.
    """

    def __init__(self, store: SessionStore):
        self._store = store
        self.post_call_handlers: list[PostCallHandler] = []

    async def create(
        self,
        *,
        org_id: str,
        agent_id: str,
        agent_version: int,
        call_type: str = "web_inbound",
    ) -> Session:
        session = Session(
            org_id=org_id,
            agent_id=agent_id,
            agent_version=agent_version,
            call_type=call_type,
        )
        await self._store.save(session)
        logger.info(f"session {session.id} created (agent={agent_id} call_type={call_type})")
        return session

    async def _transition(self, session: Session, new: SessionState) -> bool:
        if new not in ALLOWED[session.status]:
            logger.debug(f"session {session.id}: ignoring {session.status} -> {new}")
            return False
        session.status = new
        return True

    async def mark_active(self, session: Session) -> None:
        if await self._transition(session, SessionState.ACTIVE):
            session.started_at = datetime.now(timezone.utc)
            await self._store.save(session)

    async def add_turn(self, session: Session, turn: TranscriptTurn) -> None:
        session.transcript.append(turn)
        await self._store.save(session)

    async def end(self, session: Session, *, reason: str, failed: bool = False) -> None:
        target = SessionState.FAILED if failed else SessionState.ENDED
        if not await self._transition(session, target):
            return
        session.ended_at = datetime.now(timezone.utc)
        session.end_reason = reason
        await self._store.save(session)
        logger.info(f"session {session.id} {target} ({reason}) duration={session.duration_secs}")
        for handler in self.post_call_handlers:
            try:
                await handler(session)
            except Exception:
                logger.exception(f"post-call handler {handler.__name__} failed")


async def log_summary_handler(session: Session) -> None:
    """Dev-mode Post-Call Processor: prints what a real one would persist."""
    logger.info(
        f"[post-call] session={session.id} turns={len(session.transcript)} "
        f"duration={session.duration_secs}s"
    )
    for t in session.transcript:
        logger.info(f"[post-call]   {t.role}: {t.text}")
