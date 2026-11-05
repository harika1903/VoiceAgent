"""Settings routes: API keys, org profile, usage summary.

GET    /v1/keys          — list API keys (hash masked)
POST   /v1/keys          — create a new API key (raw shown once)
DELETE /v1/keys/{id}     — revoke an API key
GET    /v1/org           — get org profile
PUT    /v1/org           — update org profile
GET    /v1/usage/summary — aggregate usage stats
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.auth import AuthContext, get_auth
from app.api.deps import get_db_pool
from app.security import hash_api_key, new_api_key

router = APIRouter(tags=["settings"])


# ── API Keys ──────────────────────────────────────────────────────────────

class ApiKeyItem(BaseModel):
    id: int
    label: str
    prefix: str
    created_at: datetime
    revoked_at: datetime | None


class ApiKeyCreateRequest(BaseModel):
    label: str = Field("", max_length=120)


class ApiKeyCreateResponse(BaseModel):
    id: int
    label: str
    raw_key: str
    created_at: datetime


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyItem]


@router.get("/v1/keys", response_model=ApiKeyListResponse)
async def list_keys(
    auth: AuthContext = Depends(get_auth),
    pool=Depends(get_db_pool),
):
    rows = await pool.fetch(
        """SELECT id, label, key_hash, created_at, revoked_at
           FROM api_keys WHERE org_id = $1 ORDER BY created_at DESC""",
        auth.org_id,
    )
    keys = []
    for r in rows:
        keys.append(ApiKeyItem(
            id=r["id"],
            label=r["label"],
            prefix="va_" + r["key_hash"][:8] + "...",
            created_at=r["created_at"],
            revoked_at=r["revoked_at"],
        ))
    return ApiKeyListResponse(keys=keys)


@router.post("/v1/keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: ApiKeyCreateRequest,
    auth: AuthContext = Depends(get_auth),
    pool=Depends(get_db_pool),
):
    raw = new_api_key()
    hashed = hash_api_key(raw)
    row = await pool.fetchrow(
        """INSERT INTO api_keys (org_id, key_hash, label)
           VALUES ($1, $2, $3) RETURNING id, created_at""",
        auth.org_id,
        hashed,
        body.label,
    )
    return ApiKeyCreateResponse(
        id=row["id"],
        label=body.label,
        raw_key=raw,
        created_at=row["created_at"],
    )


@router.delete("/v1/keys/{key_id}", status_code=status.HTTP_200_OK)
async def revoke_key(
    key_id: int,
    auth: AuthContext = Depends(get_auth),
    pool=Depends(get_db_pool),
):
    if key_id == auth.key_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot revoke the key you are currently using",
        )
    result = await pool.execute(
        """UPDATE api_keys SET revoked_at = $3
           WHERE id = $1 AND org_id = $2 AND revoked_at IS NULL""",
        key_id,
        auth.org_id,
        datetime.now(timezone.utc),
    )
    if result == "UPDATE 0":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found or already revoked")
    return {"ok": True}


# ── Org Profile ───────────────────────────────────────────────────────────

class OrgResponse(BaseModel):
    id: str
    name: str
    max_concurrent_calls: int | None
    created_at: datetime


class OrgUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


@router.get("/v1/org", response_model=OrgResponse)
async def get_org(
    auth: AuthContext = Depends(get_auth),
    pool=Depends(get_db_pool),
):
    row = await pool.fetchrow(
        "SELECT id, name, max_concurrent_calls, created_at FROM orgs WHERE id = $1",
        auth.org_id,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Org not found")
    return OrgResponse(**dict(row))


@router.put("/v1/org", response_model=OrgResponse)
async def update_org(
    body: OrgUpdateRequest,
    auth: AuthContext = Depends(get_auth),
    pool=Depends(get_db_pool),
):
    row = await pool.fetchrow(
        """UPDATE orgs SET name = $2 WHERE id = $1
           RETURNING id, name, max_concurrent_calls, created_at""",
        auth.org_id,
        body.name,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Org not found")
    return OrgResponse(**dict(row))


# ── Usage Summary ─────────────────────────────────────────────────────────

class UsageKindSummary(BaseModel):
    kind: str
    total: float
    count: int


class UsageSummaryResponse(BaseModel):
    total_calls: int
    total_duration_secs: float
    avg_duration_secs: float
    by_kind: list[UsageKindSummary]


@router.get("/v1/usage/summary", response_model=UsageSummaryResponse)
async def usage_summary(
    auth: AuthContext = Depends(get_auth),
    pool=Depends(get_db_pool),
    days: int = Query(30, ge=1, le=365),
):
    since = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    from datetime import timedelta
    since = since - timedelta(days=days)

    call_stats = await pool.fetchrow(
        """SELECT COUNT(*) as total_calls,
                  COALESCE(SUM(duration_secs), 0) as total_duration,
                  COALESCE(AVG(duration_secs), 0) as avg_duration
           FROM call_sessions
           WHERE org_id = $1 AND created_at >= $2""",
        auth.org_id,
        since,
    )

    usage_rows = await pool.fetch(
        """SELECT kind, SUM(quantity) as total, COUNT(*) as count
           FROM usage_records
           WHERE org_id = $1 AND created_at >= $2
           GROUP BY kind""",
        auth.org_id,
        since,
    )

    return UsageSummaryResponse(
        total_calls=call_stats["total_calls"],
        total_duration_secs=float(call_stats["total_duration"]),
        avg_duration_secs=float(call_stats["avg_duration"]),
        by_kind=[
            UsageKindSummary(kind=r["kind"], total=float(r["total"]), count=r["count"])
            for r in usage_rows
        ],
    )
