"""Session Dispatcher (architecture §4.2).

The SINGLE OWNER of the session lifecycle state machine. Every state transition
runs through here. Workers and the Backend never mutate session state directly.

Responsibilities:
  - Admission control (org concurrency, credit reservation, fleet capacity)
  - Room creation + client token minting (LiveKit)
  - Job enqueue on priority streams
  - Recovery reaper (lease expiry detection)
  - Event stream consumption (session events from workers)
  - Transfer orchestration (future)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from loguru import logger

from app.agent.config import AgentConfig
from app.config import Settings
from app.security import make_ws_token
from app.sessions.models import Session, SessionState, TERMINAL
from app.sessions.redis_store import RedisSessionStore

try:
    from livekit.api import AccessToken, VideoGrants, RoomServiceClient
except ImportError:
    AccessToken = None  # type: ignore[assignment,misc]


# ── Data returned to the Backend for the caller ────────────────────────────

class StartResult:
    __slots__ = ("session_id", "room", "livekit_url", "livekit_token", "ws_token")

    def __init__(
        self,
        session_id: str,
        room: str,
        livekit_url: str,
        livekit_token: str,
        ws_token: str,
    ):
        self.session_id = session_id
        self.room = room
        self.livekit_url = livekit_url
        self.livekit_token = livekit_token
        self.ws_token = ws_token


class AdmissionDenied(Exception):
    pass


class SessionDispatcher:
    """Stateless (all state is in Redis). Safe to run as 2+ replicas behind a LB."""

    def __init__(
        self,
        store: RedisSessionStore,
        settings: Settings,
    ):
        self._store = store
        self._settings = settings
        self._lk_url = getattr(settings, "livekit_url", "")
        self._lk_api_key = getattr(settings, "livekit_api_key", "")
        self._lk_api_secret = getattr(settings, "livekit_api_secret", "")

    # ── Web inbound (§8.1) ─────────────────────────────────────────────────

    async def start_web_session(
        self,
        *,
        org_id: str,
        agent: AgentConfig,
        max_concurrent: int | None = None,
    ) -> StartResult:
        """Called by the Backend API on POST /v1/calls/web.

        1. Admission control
        2. Create session in Redis
        3. Create LiveKit room + mint client token
        4. Enqueue job on p0 (inbound priority)
        5. Return immediately so the client can connect in parallel with worker startup
        """
        limit = max_concurrent or self._settings.default_max_concurrent_calls

        # ── Admission ──────────────────────────────────────────────────────
        if not await self._store.org_increment(org_id, limit):
            raise AdmissionDenied(f"org {org_id} at concurrency limit ({limit})")

        # TODO: credit reservation check
        # TODO: fleet spare-capacity check

        session = Session(
            org_id=org_id,
            agent_id=agent.id,
            agent_version=agent.version,
            call_type="web_inbound",
            status=SessionState.CREATED,
        )
        room_name = f"call-{session.id}"
        session.room = room_name

        try:
            await self._store.create(session)

            # ── Create room + token ────────────────────────────────────────
            lk_token = ""
            if AccessToken and self._lk_api_key:
                lk_token = self._mint_client_token(room_name, f"caller-{session.id}")
                # Room creation happens implicitly when a participant joins with
                # auto_create=true in LiveKit, or we can create it explicitly.
                # For now, auto_create handles it.

            # ── Transition CREATED -> QUEUED and enqueue ───────────────────
            deadline = time.time() + self._settings.start_timeout_secs
            ok = await self._store.transition(
                session.id,
                expected_status=SessionState.CREATED,
                expected_epoch=0,
                new_status=SessionState.QUEUED,
            )
            if not ok:
                raise RuntimeError(f"session {session.id}: failed to transition to QUEUED")

            await self._store.enqueue_job(
                session.id, epoch=0, deadline=deadline, priority=0,
            )

            # ── WS token (for legacy browser transport fallback) ───────────
            ws_token = make_ws_token(
                self._settings.ws_token_secret,
                session.id,
                self._settings.ws_token_ttl_secs,
            )

            logger.info(
                f"dispatcher: web session {session.id} queued "
                f"(org={org_id} agent={agent.id} room={room_name})"
            )

            return StartResult(
                session_id=session.id,
                room=room_name,
                livekit_url=self._lk_url,
                livekit_token=lk_token,
                ws_token=ws_token,
            )

        except Exception:
            # Roll back concurrency counter on any failure
            await self._store.org_decrement(org_id)
            raise

    # ── End session (§4.2 "one way to end any call") ───────────────────────

    async def end_session(
        self,
        sid: str,
        *,
        reason: str,
        failed: bool = False,
    ) -> bool:
        """Converge point for every end path: client hangup, end_call tool,
        credits exhausted, max duration, admin stop."""
        session = await self._store.get(sid)
        if session is None:
            logger.warning(f"dispatcher: end_session for unknown {sid}")
            return False
        if session.status in TERMINAL:
            return True  # already done

        target = SessionState.FAILED if failed else SessionState.ENDING
        # If session is in a state that can go to ENDING, try that first.
        # Otherwise go straight to terminal.
        from app.sessions.models import ALLOWED
        if target == SessionState.ENDING and SessionState.ENDING not in ALLOWED.get(
            session.status, set()
        ):
            target = SessionState.ENDED if not failed else SessionState.FAILED

        ok = await self._store.transition(
            sid,
            expected_status=session.status,
            expected_epoch=session.epoch,
            new_status=target,
            extra_fields={
                "end_reason": reason,
                "ended_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if ok:
            # Tell the worker to wrap up
            await self._store.send_control(sid, "wrap_up", {"reason": reason})
            # Emit event for Post-Call Processor
            await self._store.emit_session_event(
                "session.ending" if target == SessionState.ENDING else "session.ended",
                sid,
                reason=reason,
            )
            # Decrement org counter
            await self._store.org_decrement(session.org_id)
            await self._store.release_lease(sid)
        return ok

    # ── Recovery reaper (§9) ───────────────────────────────────────────────

    async def run_reaper_once(self) -> int:
        """Scan for expired leases and trigger recovery. Returns count recovered."""
        expired = await self._store.get_expired_leases()
        recovered = 0
        for sid in expired:
            session = await self._store.get(sid)
            if session is None or session.status in TERMINAL:
                await self._store.release_lease(sid)
                continue

            new_epoch = session.epoch + 1
            # TODO: check recovery attempt cap (§9: ~2 per session)
            ok = await self._store.transition(
                sid,
                expected_status=session.status,
                expected_epoch=session.epoch,
                new_status=SessionState.RECOVERING,
                extra_fields={"epoch": str(new_epoch)},
            )
            if ok:
                logger.warning(f"dispatcher: recovering session {sid} (epoch {session.epoch} -> {new_epoch})")
                await self._store.release_lease(sid)
                # Re-enqueue on p0 (recovery has inbound priority)
                deadline = time.time() + self._settings.start_timeout_secs
                # Transition RECOVERING -> QUEUED
                await self._store.transition(
                    sid,
                    expected_status=SessionState.RECOVERING,
                    expected_epoch=new_epoch,
                    new_status=SessionState.QUEUED,
                )
                await self._store.enqueue_job(sid, new_epoch, deadline, priority=0)
                await self._store.emit_session_event(
                    "session.recovering", sid, epoch=str(new_epoch),
                )
                recovered += 1
        return recovered

    async def reaper_loop(self, interval: float = 2.0) -> None:
        """Run the lease reaper on an interval. Meant to be an asyncio task."""
        while True:
            try:
                count = await self.run_reaper_once()
                if count:
                    logger.info(f"dispatcher: reaper recovered {count} session(s)")
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("dispatcher: reaper error")
            await asyncio.sleep(interval)

    # ── Session event consumer ─────────────────────────────────────────────

    async def consume_session_events(self) -> None:
        """Consume events:session stream. Runs as a background task."""
        group = "dispatcher"
        consumer = f"dispatcher-{id(self)}"
        try:
            await self._store._r.xgroup_create("events:session", group, id="0", mkstream=True)
        except Exception:
            pass  # BUSYGROUP is fine

        while True:
            try:
                entries = await self._store._r.xreadgroup(
                    group, consumer, {"events:session": ">"}, count=50, block=2000,
                )
                if not entries:
                    continue
                for _, messages in entries:
                    for msg_id, fields in messages:
                        await self._handle_session_event(fields)
                        await self._store._r.xack("events:session", group, msg_id)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("dispatcher: event consumer error")
                await asyncio.sleep(1)

    async def _handle_session_event(self, fields: dict) -> None:
        event = fields.get("event", "")
        sid = fields.get("sid", "")
        if event == "worker.crashed":
            # Supervisor reported a crash; reaper will handle via lease expiry.
            logger.warning(f"dispatcher: worker.crashed for {sid}")
        elif event == "session.ended":
            # Worker finished cleanly. Emit for Post-Call.
            session = await self._store.get(sid)
            if session and session.status not in TERMINAL:
                await self._store.transition(
                    sid,
                    expected_status=session.status,
                    expected_epoch=session.epoch,
                    new_status=SessionState.ENDED,
                    extra_fields={
                        "ended_at": datetime.now(timezone.utc).isoformat(),
                        "end_reason": fields.get("reason", "normal"),
                    },
                )
                await self._store.org_decrement(session.org_id)
                await self._store.release_lease(sid)

    # ── LiveKit helpers ────────────────────────────────────────────────────

    def _mint_client_token(self, room: str, identity: str) -> str:
        if not AccessToken:
            return ""
        token = AccessToken(self._lk_api_key, self._lk_api_secret)
        token.identity = identity
        token.add_grants(VideoGrants(room_join=True, room=room))
        token.ttl = 300  # 5 minutes
        return token.to_jwt()

    def _mint_agent_token(self, room: str, identity: str) -> str:
        """Token for the agent worker to join the room."""
        if not AccessToken:
            return ""
        token = AccessToken(self._lk_api_key, self._lk_api_secret)
        token.identity = identity
        token.add_grants(
            VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True)
        )
        token.ttl = 3600
        return token.to_jwt()
