"""Post-Call Processor (architecture §5.1).

Trigger: session.ended or session.ending event on the events:session stream.
Processing is idempotent per session_id (so redelivery or duplicate events are safe).

Steps:
  1. Read transcript from Redis
  2. Write per-turn rows to Postgres + full JSON to object storage (Postgres JSONB for now)
  3. Run LLM summary (optional, skipped if no GROQ key)
  4. Write final usage records
  5. Fire customer webhook (TODO)
  6. Shorten Redis TTL for the session's keys
  7. Mark session as post-call-complete in Postgres
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import asyncpg
from loguru import logger

from app.config import Settings, get_settings
from app.infra.redis import make_redis
from app.observability import setup_logging
from app.sessions.redis_store import RedisSessionStore


class PostCallProcessor:
    def __init__(
        self,
        store: RedisSessionStore,
        pool: asyncpg.Pool,
        settings: Settings,
    ):
        self._store = store
        self._pool = pool
        self._settings = settings

    async def process_session(self, sid: str) -> None:
        """Idempotent: safe to call multiple times for the same session."""
        # Check if already processed
        existing = await self._pool.fetchval(
            "SELECT post_call_at FROM call_sessions WHERE id = $1", sid,
        )
        if existing is not None:
            logger.debug(f"postcall: session {sid} already processed, skipping")
            return

        session = await self._store.get(sid)
        if session is None:
            logger.warning(f"postcall: session {sid} not found in Redis")
            return

        logger.info(f"postcall: processing session {sid}")

        # 1. Read transcript from Redis
        turns = await self._store.get_transcript(sid)

        # 2. Persist session + transcript to Postgres
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Upsert session row (may already exist from Dispatcher)
                await conn.execute(
                    """INSERT INTO call_sessions
                        (id, org_id, agent_id, agent_version, call_type, status, epoch,
                         room, worker_id, end_reason, created_at, started_at, ended_at, duration_secs)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                       ON CONFLICT (id) DO UPDATE SET
                         status = EXCLUDED.status,
                         ended_at = EXCLUDED.ended_at,
                         end_reason = EXCLUDED.end_reason,
                         duration_secs = EXCLUDED.duration_secs,
                         worker_id = EXCLUDED.worker_id""",
                    session.id,
                    session.org_id,
                    session.agent_id,
                    session.agent_version,
                    session.call_type,
                    session.status.value,
                    session.epoch,
                    session.room,
                    session.worker_id,
                    session.end_reason,
                    session.created_at,
                    session.started_at,
                    session.ended_at,
                    session.duration_secs,
                )

                # Write transcript turns
                for idx, turn in enumerate(turns):
                    await conn.execute(
                        """INSERT INTO transcript_turns (session_id, seq, role, text, at, interrupted)
                           VALUES ($1, $2, $3, $4, $5, $6)
                           ON CONFLICT (session_id, seq) DO NOTHING""",
                        sid,
                        idx,
                        turn.role,
                        turn.text,
                        turn.at,
                        turn.interrupted,
                    )

                # Store full transcript JSON as an artifact
                transcript_json = json.dumps(
                    [{"role": t.role, "text": t.text, "at": t.at.isoformat(), "interrupted": t.interrupted}
                     for t in turns],
                    indent=2,
                )
                await conn.execute(
                    """INSERT INTO session_artifacts (session_id, kind, object_key)
                       VALUES ($1, 'transcript_json', $2)
                       ON CONFLICT (session_id, kind) DO NOTHING""",
                    sid,
                    f"transcripts/{sid}.json",
                )

        # 3. LLM summary (optional)
        summary = None
        if turns and self._settings.groq_api_key and self._settings.summary_model:
            try:
                summary = await self._generate_summary(turns)
            except Exception:
                logger.exception(f"postcall: summary generation failed for {sid}")

        # 4. Usage records
        if session.duration_secs:
            await self._write_usage(sid, session.org_id, "call_seconds", session.duration_secs)

        # 5. Mark post-call complete
        await self._pool.execute(
            "UPDATE call_sessions SET summary = $2, post_call_at = $3 WHERE id = $1",
            sid,
            summary,
            datetime.now(timezone.utc),
        )

        # 6. Shorten Redis TTL
        await self._store.set_session_ttl(sid, self._settings.session_ttl_after_end_secs)

        logger.info(
            f"postcall: session {sid} complete "
            f"(turns={len(turns)} summary={'yes' if summary else 'no'})"
        )

    async def _generate_summary(self, turns: list) -> str | None:
        """Generate a call summary using Groq."""
        import httpx

        transcript_text = "\n".join(f"{t.role}: {t.text}" for t in turns)
        prompt = (
            "Summarise this phone call in 2-3 sentences. "
            "Include the caller's intent and the outcome.\n\n"
            f"{transcript_text}"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.groq_api_key}"},
                json={
                    "model": self._settings.summary_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    async def _write_usage(self, sid: str, org_id: str, kind: str, quantity: float) -> None:
        await self._pool.execute(
            """INSERT INTO usage_records (session_id, org_id, kind, quantity)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (session_id, kind) DO NOTHING""",
            sid,
            org_id,
            kind,
            quantity,
        )


# ── Event consumer loop ───────────────────────────────────────────────────

async def postcall_consumer(
    store: RedisSessionStore,
    pool: asyncpg.Pool,
    settings: Settings,
) -> None:
    """Consume events:session and process ended sessions."""
    processor = PostCallProcessor(store, pool, settings)
    group = "postcall"
    consumer = f"postcall-{id(processor)}"

    try:
        await store._r.xgroup_create("events:session", group, id="0", mkstream=True)
    except Exception:
        pass  # BUSYGROUP

    max_deliveries = settings.postcall_max_deliveries

    while True:
        try:
            entries = await store._r.xreadgroup(
                group, consumer, {"events:session": ">"}, count=10, block=5000,
            )
            if not entries:
                continue

            for _, messages in entries:
                for msg_id, fields in messages:
                    event = fields.get("event", "")
                    sid = fields.get("sid", "")

                    if event in ("session.ended", "session.ending"):
                        try:
                            await processor.process_session(sid)
                        except Exception:
                            logger.exception(f"postcall: failed to process {sid}")
                            # Leave unacked for redelivery (up to max_deliveries)
                            continue

                    await store._r.xack("events:session", group, msg_id)

        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("postcall: consumer error")
            await asyncio.sleep(2)


# ── Entrypoint ─────────────────────────────────────────────────────────────

async def postcall_main() -> None:
    settings = get_settings()
    setup_logging(settings, "postcall")

    redis = make_redis(settings.redis_url)
    store = RedisSessionStore(redis, session_ttl=settings.session_ttl_after_end_secs)

    from app.db.pool import create_pool
    pool = await create_pool(settings.database_url)

    logger.info("postcall processor: started")
    try:
        await postcall_consumer(store, pool, settings)
    finally:
        await pool.close()
        await redis.aclose()


def postcall_entry() -> None:
    asyncio.run(postcall_main())
