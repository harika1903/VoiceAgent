"""API key authentication middleware (architecture §4.1).

Every request carries an API key in the Authorization header:
    Authorization: Bearer va_<random>

The key is hashed (SHA-256) and looked up in the api_keys table. A match
gives us the org_id for the request. Revoked keys are rejected.

Why SHA-256 and not bcrypt: keys are 256-bit random (not human passwords),
so brute-force is infeasible and we need a fast lookup on every request.
"""

from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
from fastapi import Depends, HTTPException, Request, status

from app.security import hash_api_key


class AuthContext:
    """Injected into route handlers via Depends(get_auth)."""

    __slots__ = ("org_id", "key_id")

    def __init__(self, org_id: str, key_id: int):
        self.org_id = org_id
        self.key_id = key_id


async def get_auth(request: Request) -> AuthContext:
    """FastAPI dependency: extract and verify the API key."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Authorization: Bearer <key>")

    raw_key = auth[7:].strip()
    if not raw_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Empty API key")

    pool: asyncpg.Pool = request.app.state.db_pool
    key_hash = hash_api_key(raw_key)

    row = await pool.fetchrow(
        "SELECT id, org_id, revoked_at FROM api_keys WHERE key_hash = $1",
        key_hash,
    )
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    if row["revoked_at"] is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key revoked")

    return AuthContext(org_id=row["org_id"], key_id=row["id"])


async def get_auth_optional(request: Request) -> AuthContext | None:
    """For endpoints that work with or without auth (e.g. dev mode)."""
    auth = request.headers.get("authorization", "")
    if not auth:
        return None
    return await get_auth(request)
