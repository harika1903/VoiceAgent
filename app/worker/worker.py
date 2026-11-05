"""Agent Worker process (architecture §4.5).

One call per process, one Pipecat pipeline. The worker:
  1. Claims a job from the Redis stream with fencing (Lua CAS)
  2. Loads the pinned agent config (Redis cache -> Postgres fallback)
  3. Joins the LiveKit room (or sets up browser WebSocket transport)
  4. Builds and runs the pipeline
  5. Checkpoints every turn, renews lease every second
  6. On finish: emits session.ended, releases lease, exits

The worker NEVER writes to Postgres. Transcript and usage go to Redis;
the Post-Call Processor persists them later.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import signal
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis
from loguru import logger

from app.agent.config import AgentConfig
from app.config import Settings, get_settings
from app.infra.redis import make_redis
from app.observability import setup_logging
from app.sessions.models import Session, SessionState, TranscriptTurn
from app.sessions.redis_store import RedisSessionStore, _sk


class FencedOffError(Exception):
    """Raised when a lease renewal fails the epoch check — worker must exit NOW."""
    pass


class WorkerContext:
    """Everything the pipeline needs from the worker's infrastructure."""

    def __init__(
        self,
        *,
        session: Session,
        agent: AgentConfig,
        store: RedisSessionStore,
        settings: Settings,
        worker_id: str,
        checkpoint: dict | None = None,
    ):
        self.session = session
        self.agent = agent
        self.store = store
        self.settings = settings
        self.worker_id = worker_id
        self.checkpoint = checkpoint
        self._lease_task: asyncio.Task | None = None
        self._fenced = False

    async def start_lease_renewal(self) -> None:
        """Background task: renew the lease every lease_ttl/3 seconds."""
        interval = self.settings.lease_ttl_secs / 3.0
        self._lease_task = asyncio.create_task(self._renew_loop(interval))

    async def _renew_loop(self, interval: float) -> None:
        while not self._fenced:
            try:
                ok = await self.store.renew_lease(
                    self.session.id,
                    self.session.epoch,
                    self.worker_id,
                    self.settings.lease_ttl_secs,
                )
                if not ok:
                    logger.error(f"worker {self.worker_id}: fenced off! Exiting.")
                    self._fenced = True
                    raise FencedOffError()
            except FencedOffError:
                raise
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("lease renewal error")
            await asyncio.sleep(interval)

    async def stop_lease_renewal(self) -> None:
        if self._lease_task:
            self._lease_task.cancel()
            try:
                await self._lease_task
            except (asyncio.CancelledError, FencedOffError):
                pass

    @property
    def is_fenced(self) -> bool:
        return self._fenced

    async def write_checkpoint(self, data: dict) -> None:
        await self.store.write_checkpoint(self.session.id, self.session.epoch, data)

    async def append_turn(self, turn: TranscriptTurn) -> None:
        await self.store.append_turn(self.session.id, turn)

    async def emit_usage(self, kind: str, quantity: float) -> None:
        await self.store.emit_usage_event(
            self.session.id, self.session.org_id, kind, quantity,
        )

    async def emit_ended(self, reason: str = "normal") -> None:
        await self.store.emit_session_event(
            "session.ended", self.session.id, reason=reason,
        )

    async def release(self) -> None:
        await self.store.release_lease(self.session.id)


# ── Job claim loop ─────────────────────────────────────────────────────────

async def _drain_one_priority(
    store: RedisSessionStore,
    worker_id: str,
    settings: Settings,
    priority: int,
    block_ms: int,
) -> tuple[str, int] | None:
    """Read from one priority stream, draining expired jobs until we claim a
    live one or the stream is empty."""
    stream = f"jobs:p{priority}"
    max_drain = 50  # safety cap: don't loop forever on a huge backlog

    for _ in range(max_drain):
        try:
            entries = await store._r.xreadgroup(
                "workers", worker_id, {stream: ">"}, count=1, block=block_ms,
            )
        except Exception:
            return None
        if not entries:
            return None  # stream empty or timed out

        for _, messages in entries:
            for msg_id, fields in messages:
                sid = fields["sid"]
                epoch = int(fields["epoch"])
                deadline = float(fields["deadline"])

                if time.time() > deadline:
                    logger.info(f"worker {worker_id}: job {sid} past deadline, acking")
                    await store._r.xack(stream, "workers", msg_id)
                    continue  # drain next message from this stream

                ok = await store.claim(sid, epoch, worker_id, settings.lease_ttl_secs)
                await store._r.xack(stream, "workers", msg_id)
                if ok:
                    return (sid, epoch)
                # Someone else claimed it — keep draining
    return None


async def claim_one_job(
    store: RedisSessionStore,
    worker_id: str,
    settings: Settings,
    *,
    timeout_secs: float = 30.0,
) -> tuple[str, int] | None:
    """Try to claim a job, retrying across all priorities until timeout.

    Drains expired jobs from each stream before moving on, and loops back
    to p0 so a fresh job that arrives while we were draining stale ones
    still gets picked up.
    """
    deadline = time.time() + timeout_secs

    while time.time() < deadline:
        remaining_ms = max(100, int((deadline - time.time()) * 1000))
        # Spread the block time across priorities: p0 gets the lion's share
        block_p0 = min(remaining_ms, 3000)

        for priority in (0, 1, 2):
            block = block_p0 if priority == 0 else 500
            result = await _drain_one_priority(store, worker_id, settings, priority, block)
            if result is not None:
                return result

    return None


# ── Load agent config ──────────────────────────────────────────────────────

async def load_agent_config(
    store: RedisSessionStore,
    session: Session,
    db_pool=None,
) -> AgentConfig:
    """Load the pinned agent config version. Redis cache -> Postgres fallback."""
    cache_key = f"agent:{session.org_id}:{session.agent_id}:v{session.agent_version}"
    cached = await store._r.get(cache_key)
    if cached:
        data = json.loads(cached)
        return AgentConfig(id=session.agent_id, version=session.agent_version, **data)

    if db_pool is None:
        raise RuntimeError(f"No cached config and no DB pool for {cache_key}")

    row = await db_pool.fetchrow(
        "SELECT config FROM agent_versions WHERE org_id = $1 AND agent_id = $2 AND version = $3",
        session.org_id,
        session.agent_id,
        session.agent_version,
    )
    if row is None:
        raise RuntimeError(f"Agent config not found: {cache_key}")

    data = json.loads(row["config"]) if isinstance(row["config"], str) else row["config"]
    # Cache for 1 hour
    await store._r.set(cache_key, json.dumps(data), ex=3600)
    return AgentConfig(id=session.agent_id, version=session.agent_version, **data)


# ── Worker main (one call) ─────────────────────────────────────────────────

async def run_one_call(
    store: RedisSessionStore,
    worker_id: str,
    settings: Settings,
    db_pool=None,
    embedder=None,
    kb=None,
    claim_timeout: float = 30.0,
) -> bool:
    """Claim and run one call. Returns True if a call was handled, False if no job."""
    result = await claim_one_job(store, worker_id, settings, timeout_secs=claim_timeout)
    if result is None:
        return False

    sid, epoch = result
    logger.info(f"worker {worker_id}: claimed session {sid} epoch={epoch}")

    session = await store.get(sid)
    if session is None:
        logger.error(f"worker {worker_id}: session {sid} vanished after claim")
        return True

    session.epoch = epoch  # pin the epoch we claimed with

    # Load config
    try:
        agent = await load_agent_config(store, session, db_pool)
    except Exception:
        logger.exception(f"worker {worker_id}: failed to load config for {sid}")
        await store.emit_session_event("session.ended", sid, reason="config_load_error")
        await store.release_lease(sid)
        return True

    # Load checkpoint if recovering
    checkpoint = None
    if session.status == SessionState.CONNECTING:
        # Check if this is a recovery (would have been RECOVERING -> QUEUED -> CONNECTING)
        checkpoint = await store.get_checkpoint(sid)
        if checkpoint:
            logger.info(f"worker {worker_id}: loaded checkpoint for {sid}")

    ctx = WorkerContext(
        session=session,
        agent=agent,
        store=store,
        settings=settings,
        worker_id=worker_id,
        checkpoint=checkpoint,
    )

    # Build transport: LiveKit when configured, otherwise direct WS server
    transport = None
    ws_publish_url = None
    if not settings.livekit_url:
        from app.transports.worker_ws import build_worker_ws_transport
        transport, port = build_worker_ws_transport(settings, sid)
        ws_publish_url = f"{settings.worker_public_scheme}://{settings.worker_public_host}:{port}"

    try:
        await ctx.start_lease_renewal()

        # Transition CONNECTING -> ACTIVE
        await store.transition(
            sid,
            expected_status=SessionState.CONNECTING,
            expected_epoch=epoch,
            new_status=SessionState.ACTIVE,
            extra_fields={"started_at": datetime.now(timezone.utc).isoformat()},
        )

        # Dynamically load and run the agent pipeline
        module_path, func_name = settings.agent_runner.rsplit(":", 1)
        module = importlib.import_module(module_path)
        run_agent = getattr(module, func_name)

        await run_agent(
            worker_ctx=ctx,
            agent=agent,
            session=session,
            settings=settings,
            embedder=embedder,
            transport=transport,
            kb=kb,
            ws_publish_url=ws_publish_url,
        )

        await ctx.emit_ended("normal")
        logger.info(f"worker {worker_id}: session {sid} completed normally")

    except FencedOffError:
        logger.warning(f"worker {worker_id}: fenced off from {sid}, exiting")
    except Exception as e:
        logger.exception(f"worker {worker_id}: session {sid} crashed")
        await store.emit_session_event(
            "worker.crashed", sid, epoch=str(epoch), error=str(e)[:200],
        )
    finally:
        await ctx.stop_lease_renewal()
        await ctx.release()

    return True


# ── Process entrypoint ─────────────────────────────────────────────────────

async def worker_main(worker_id: str | None = None) -> None:
    """Main loop for a worker process. Runs one call, then exits (recycled by supervisor)."""
    settings = get_settings()
    setup_logging(settings, f"worker-{worker_id or os.getpid()}")
    wid = worker_id or f"w-{os.getpid()}"

    redis = make_redis(settings.redis_url)
    store = RedisSessionStore(redis, session_ttl=settings.session_ttl_after_end_secs)

    # Postgres pool for agent config fallback (Redis cache miss)
    db_pool = None
    try:
        import asyncpg
        db_pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    except Exception as e:
        logger.warning(f"worker {wid}: no DB pool ({e}), relying on Redis cache only")

    # Ensure consumer groups exist
    for p in (0, 1, 2):
        await store.ensure_consumer_group(p)

    # Optional: pre-load embedder for speaker gate
    embedder = None
    if settings.speaker_gate_enabled:
        from app.audio.embedder import SpeakerEmbedder, ensure_model
        embedder = await asyncio.to_thread(
            lambda: SpeakerEmbedder(ensure_model(settings.models_dir, settings.speaker_model))
        )

    # Load Knowledge Base
    from pathlib import Path
    from app.kb.store import EmptyKnowledgeBase, load_product_catalog
    catalog_path = Path(settings.kb_default_catalog)
    if catalog_path.exists():
        kb = load_product_catalog(catalog_path)
        logger.info(f"worker {wid}: KB loaded ({kb.size} docs)")
    else:
        kb = EmptyKnowledgeBase()

    logger.info(f"worker {wid}: ready, waiting for job")

    # One call per process (§4.4: "Recycle per call")
    handled = await run_one_call(
        store, wid, settings,
        db_pool=db_pool, embedder=embedder, kb=kb,
        claim_timeout=settings.worker_claim_timeout_secs,
    )

    if not handled:
        logger.info(f"worker {wid}: no job available, exiting")

    if db_pool:
        await db_pool.close()
    await redis.aclose()


def worker_entry() -> None:
    """Synchronous entrypoint (called by supervisor via subprocess)."""
    asyncio.run(worker_main())
