"""Redis connection factory (the only place that builds a Redis client)."""

import redis.asyncio as aioredis


def make_redis(url: str) -> aioredis.Redis:
    # decode_responses: we only store text/JSON; bytes would leak into every caller.
    # health_check_interval: detect half-dead connections (LB / NAT idle drops).
    # socket_timeout: redis-py's default (5s) is the same as the longest XREADGROUP
    # BLOCK used anywhere (postcall's 5000ms), which races the client's own read
    # timeout against the server's block duration. Give it headroom above every
    # BLOCK value in the codebase so a normal "no new events" return never looks
    # like a timeout.
    kwargs: dict = {"decode_responses": True, "health_check_interval": 15, "socket_timeout": 15}
    # socket_keepalive is TCP-only; skip it for Unix sockets.
    if not url.startswith("unix://"):
        kwargs["socket_keepalive"] = True
    return aioredis.from_url(url, **kwargs)
