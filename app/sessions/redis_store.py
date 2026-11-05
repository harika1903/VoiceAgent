"""Redis session store (architecture §7.2 key layout + §7.3 implementation notes).

Key layout (all keys use {sid} hash tag for cluster-slot affinity):
    sess:{sid}              Hash: status, epoch, org_id, agent_id, agent_version,
                            room, call_type, worker_id, created_at, started_at, ...
    sess:{sid}:transcript   Stream of turns (id = auto, fields = role, text, at, interrupted)
    sess:{sid}:ckpt         String: JSON blob of LLM context + flow state + tool log
    sess:{sid}:ctl          Stream: commands TO the worker (wrap_up, hold, resume, ...)
    leases                  ZSET: member=sid, score=expiry_unix_ts
    org:{org_id}:active     String (Lua-guarded counter)
    events:session          Stream consumed by Dispatcher + Post-Call
    events:usage            Stream consumed by Metering
    jobs:p0 / jobs:p1 / jobs:p2   Streams, consumer group "workers"
    node:{node_id}          Hash with TTL (capacity reporting)

Every state transition is a compare-and-set on (status, epoch) inside a Lua script,
so two Dispatcher replicas can never both act on the same session.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis
from loguru import logger

from app.sessions.models import ALLOWED, Session, SessionState, TranscriptTurn

# ── Lua: atomic compare-and-set transition ──────────────────────────────────
# KEYS[1] = sess:{sid}   ARGV[1] = expected_status  ARGV[2] = expected_epoch
# ARGV[3] = new_status   ARGV[4..N] = extra HSET field/value pairs
# Returns 1 on success, 0 on mismatch (stale epoch or wrong status).
_LUA_CAS_TRANSITION = """
local cur_status = redis.call('HGET', KEYS[1], 'status')
local cur_epoch  = redis.call('HGET', KEYS[1], 'epoch')
if cur_status ~= ARGV[1] or cur_epoch ~= ARGV[2] then
    return 0
end
redis.call('HSET', KEYS[1], 'status', ARGV[3])
for i = 4, #ARGV, 2 do
    redis.call('HSET', KEYS[1], ARGV[i], ARGV[i+1])
end
return 1
"""

# ── Lua: worker claim (§4.5 "Claim with fencing") ──────────────────────────
# KEYS[1] = sess:{sid}   KEYS[2] = leases (ZSET)
# ARGV[1] = expected_epoch  ARGV[2] = worker_id  ARGV[3] = lease_expiry_ts
# Returns 1 on success, 0 if session is gone or epoch doesn't match QUEUED/RECOVERING.
_LUA_CLAIM = """
local status = redis.call('HGET', KEYS[1], 'status')
local epoch  = redis.call('HGET', KEYS[1], 'epoch')
if epoch ~= ARGV[1] then return 0 end
if status ~= 'queued' and status ~= 'recovering' then return 0 end
redis.call('HSET', KEYS[1], 'status', 'connecting', 'worker_id', ARGV[2])
redis.call('ZADD', KEYS[2], ARGV[3], KEYS[1])
return 1
"""

# ── Lua: lease renewal (epoch-guarded) ──────────────────────────────────────
# KEYS[1] = sess:{sid}   KEYS[2] = leases
# ARGV[1] = expected_epoch  ARGV[2] = worker_id  ARGV[3] = new_expiry_ts
# Returns 1 on success, 0 if fenced off (worker must exit immediately).
_LUA_RENEW_LEASE = """
local epoch  = redis.call('HGET', KEYS[1], 'epoch')
local worker = redis.call('HGET', KEYS[1], 'worker_id')
if epoch ~= ARGV[1] or worker ~= ARGV[2] then return 0 end
redis.call('ZADD', KEYS[2], ARGV[3], KEYS[1])
return 1
"""

# ── Lua: org concurrency increment (admission) ─────────────────────────────
# KEYS[1] = org:{org_id}:active  ARGV[1] = limit
# Returns new count on success, -1 if at capacity.
_LUA_ORG_INCR = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
local lim = tonumber(ARGV[1])
if cur >= lim then return -1 end
return redis.call('INCR', KEYS[1])
"""

# Keys
def _sk(sid: str) -> str:
    """Session hash key. Uses {sid} hash tag for cluster slot affinity."""
    return f"sess:{{{sid}}}"


def _tk(sid: str) -> str:
    return f"sess:{{{sid}}}:transcript"


def _ck(sid: str) -> str:
    return f"sess:{{{sid}}}:ckpt"


def _ctlk(sid: str) -> str:
    return f"sess:{{{sid}}}:ctl"


LEASES_KEY = "leases"


def _org_active(org_id: str) -> str:
    return f"org:{org_id}:active"


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def _from_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


class RedisSessionStore:
    """Owns all session reads/writes in Redis. Used by the Dispatcher and read by Workers."""

    def __init__(self, redis: aioredis.Redis, *, session_ttl: int = 3600):
        self._r = redis
        self._ttl = session_ttl
        # Script objects (loaded lazily on first call)
        self._cas: aioredis.client.Script | None = None
        self._claim: aioredis.client.Script | None = None
        self._renew: aioredis.client.Script | None = None
        self._org_incr: aioredis.client.Script | None = None

    async def _ensure_scripts(self) -> None:
        if self._cas is not None:
            return
        self._cas = self._r.register_script(_LUA_CAS_TRANSITION)
        self._claim = self._r.register_script(_LUA_CLAIM)
        self._renew = self._r.register_script(_LUA_RENEW_LEASE)
        self._org_incr = self._r.register_script(_LUA_ORG_INCR)

    # ── Create ──────────────────────────────────────────────────────────────

    async def create(self, session: Session) -> None:
        """Write the initial session hash. Called by the Dispatcher only."""
        key = _sk(session.id)
        mapping = {
            "status": session.status.value,
            "epoch": str(session.epoch),
            "org_id": session.org_id,
            "agent_id": session.agent_id,
            "agent_version": str(session.agent_version),
            "call_type": session.call_type,
            "room": session.room or "",
            "worker_id": "",
            "created_at": _ts(session.created_at),
            "started_at": "",
            "ended_at": "",
            "end_reason": "",
            "worker_ws_url": "",
        }
        await self._r.hset(key, mapping=mapping)
        logger.info(f"session {session.id} created in Redis (org={session.org_id})")

    # ── Read ────────────────────────────────────────────────────────────────

    async def get(self, sid: str) -> Session | None:
        data = await self._r.hgetall(_sk(sid))
        if not data:
            return None
        return Session(
            id=sid,
            org_id=data["org_id"],
            agent_id=data["agent_id"],
            agent_version=int(data["agent_version"]),
            call_type=data["call_type"],
            status=SessionState(data["status"]),
            epoch=int(data["epoch"]),
            room=data.get("room") or None,
            worker_id=data.get("worker_id") or None,
            created_at=_from_ts(data.get("created_at")) or _now_utc(),
            started_at=_from_ts(data.get("started_at")),
            ended_at=_from_ts(data.get("ended_at")),
            end_reason=data.get("end_reason") or None,
            worker_ws_url=data.get("worker_ws_url") or None,
        )

    # ── Atomic CAS transition (Dispatcher only) ────────────────────────────

    async def transition(
        self,
        sid: str,
        *,
        expected_status: SessionState,
        expected_epoch: int,
        new_status: SessionState,
        extra_fields: dict[str, str] | None = None,
    ) -> bool:
        """Compare-and-set transition. Returns False on stale epoch / wrong status."""
        if new_status not in ALLOWED[expected_status]:
            logger.warning(f"session {sid}: illegal transition {expected_status} -> {new_status}")
            return False
        await self._ensure_scripts()
        extras: list[str] = []
        for k, v in (extra_fields or {}).items():
            extras.extend([k, v])
        result = await self._cas(
            keys=[_sk(sid)],
            args=[expected_status.value, str(expected_epoch), new_status.value, *extras],
        )
        if result == 1:
            logger.info(f"session {sid}: {expected_status} -> {new_status} (epoch={expected_epoch})")
            return True
        logger.warning(f"session {sid}: CAS failed {expected_status}(e{expected_epoch}) -> {new_status}")
        return False

    # ── Worker claim (§4.5) ────────────────────────────────────────────────

    async def claim(self, sid: str, epoch: int, worker_id: str, lease_ttl: int) -> bool:
        await self._ensure_scripts()
        expiry = time.time() + lease_ttl
        result = await self._claim(
            keys=[_sk(sid), LEASES_KEY],
            args=[str(epoch), worker_id, str(expiry)],
        )
        if result == 1:
            logger.info(f"session {sid}: claimed by {worker_id} (epoch={epoch})")
            return True
        logger.warning(f"session {sid}: claim failed for {worker_id} (epoch={epoch})")
        return False

    # ── Lease renewal ──────────────────────────────────────────────────────

    async def renew_lease(self, sid: str, epoch: int, worker_id: str, lease_ttl: int) -> bool:
        await self._ensure_scripts()
        expiry = time.time() + lease_ttl
        result = await self._renew(
            keys=[_sk(sid), LEASES_KEY],
            args=[str(epoch), worker_id, str(expiry)],
        )
        return result == 1

    async def release_lease(self, sid: str) -> None:
        await self._r.zrem(LEASES_KEY, _sk(sid))

    # ── Org concurrency (admission) ────────────────────────────────────────

    async def org_increment(self, org_id: str, limit: int) -> bool:
        await self._ensure_scripts()
        result = await self._org_incr(
            keys=[_org_active(org_id)],
            args=[str(limit)],
        )
        return result != -1

    async def org_decrement(self, org_id: str) -> None:
        key = _org_active(org_id)
        await self._r.decr(key)
        # Floor at zero (a bug or race shouldn't make it negative).
        val = await self._r.get(key)
        if val is not None and int(val) < 0:
            await self._r.set(key, "0")

    # ── Transcript ─────────────────────────────────────────────────────────

    async def append_turn(self, sid: str, turn: TranscriptTurn) -> None:
        await self._r.xadd(
            _tk(sid),
            {
                "role": turn.role,
                "text": turn.text,
                "at": _ts(turn.at),
                "interrupted": "1" if turn.interrupted else "0",
            },
        )

    async def get_transcript(self, sid: str) -> list[TranscriptTurn]:
        entries = await self._r.xrange(_tk(sid))
        turns = []
        for seq_idx, (_, fields) in enumerate(entries):
            turns.append(
                TranscriptTurn(
                    role=fields["role"],
                    text=fields["text"],
                    at=_from_ts(fields["at"]) or _now_utc(),
                    interrupted=fields.get("interrupted") == "1",
                    seq=seq_idx,
                )
            )
        return turns

    # ── Checkpoint (worker writes, recovery reads) ─────────────────────────

    async def write_checkpoint(self, sid: str, epoch: int, data: dict) -> None:
        """Epoch-guarded: only writes if the session's epoch still matches."""
        key = _sk(sid)
        cur_epoch = await self._r.hget(key, "epoch")
        if cur_epoch != str(epoch):
            return  # fenced off
        await self._r.set(_ck(sid), json.dumps(data), ex=self._ttl * 2)

    async def get_checkpoint(self, sid: str) -> dict | None:
        raw = await self._r.get(_ck(sid))
        return json.loads(raw) if raw else None

    # ── Control stream (Dispatcher -> Worker) ──────────────────────────────

    async def send_control(self, sid: str, command: str, payload: dict | None = None) -> None:
        fields = {"cmd": command}
        if payload:
            fields["payload"] = json.dumps(payload)
        await self._r.xadd(_ctlk(sid), fields)

    async def read_control(self, sid: str, last_id: str = "0-0") -> list[tuple[str, dict]]:
        entries = await self._r.xread({_ctlk(sid): last_id}, count=10, block=0)
        if not entries:
            return []
        results = []
        for _, messages in entries:
            for msg_id, fields in messages:
                cmd = fields["cmd"]
                payload = json.loads(fields["payload"]) if "payload" in fields else {}
                results.append((msg_id, {"cmd": cmd, **payload}))
        return results

    # ── Event streams (workers publish, Dispatcher/PostCall consume) ───────

    async def emit_session_event(self, event: str, sid: str, **data: str) -> None:
        await self._r.xadd(
            "events:session",
            {"event": event, "sid": sid, **data},
            maxlen=100_000,
        )

    async def emit_usage_event(self, sid: str, org_id: str, kind: str, quantity: float) -> None:
        await self._r.xadd(
            "events:usage",
            {"sid": sid, "org_id": org_id, "kind": kind, "quantity": str(quantity)},
            maxlen=100_000,
        )

    # ── Job streams ────────────────────────────────────────────────────────

    async def enqueue_job(self, sid: str, epoch: int, deadline: float, priority: int = 0) -> str:
        stream = f"jobs:p{priority}"
        msg_id = await self._r.xadd(
            stream,
            {"sid": sid, "epoch": str(epoch), "deadline": str(deadline)},
        )
        return msg_id

    async def ensure_consumer_group(self, priority: int = 0) -> None:
        stream = f"jobs:p{priority}"
        try:
            await self._r.xgroup_create(stream, "workers", id="0", mkstream=True)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    # ── Expired leases (recovery reaper) ───────────────────────────────────

    async def get_expired_leases(self, now: float | None = None) -> list[str]:
        """Returns session keys whose lease has expired (sorted set score < now)."""
        ts = now or time.time()
        members = await self._r.zrangebyscore(LEASES_KEY, "-inf", str(ts))
        # members are sess:{sid} keys; extract sid
        sids = []
        for m in members:
            # m is like "sess:{abc123}" -> extract abc123
            if m.startswith("sess:{") and m.endswith("}"):
                sids.append(m[6:-1])
        return sids

    # ── Cleanup (after post-call) ──────────────────────────────────────────

    async def set_session_ttl(self, sid: str, ttl: int) -> None:
        """Shorten TTL on all session keys after post-call is done."""
        for key in [_sk(sid), _tk(sid), _ck(sid), _ctlk(sid)]:
            await self._r.expire(key, ttl)

    # ── Node capacity ──────────────────────────────────────────────────────

    async def report_capacity(self, node_id: str, data: dict, ttl: int = 15) -> None:
        key = f"node:{node_id}"
        await self._r.hset(key, mapping={k: str(v) for k, v in data.items()})
        await self._r.expire(key, ttl)

    async def get_fleet_capacity(self) -> list[dict]:
        """Read all node capacity hashes (for admission control / autoscaler)."""
        keys = []
        async for key in self._r.scan_iter("node:*", count=100):
            keys.append(key)
        nodes = []
        for key in keys:
            data = await self._r.hgetall(key)
            if data:
                data["node_id"] = key.split(":", 1)[1]
                nodes.append(data)
        return nodes


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
