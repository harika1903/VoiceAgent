"""Postgres pool factory + tiny forward-only migrator."""

import hashlib
from pathlib import Path

import asyncpg
from loguru import logger

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_ID = 7_450_001  # arbitrary constant: "only one process migrates at a time"


async def create_pool(url: str, *, min_size: int = 1, max_size: int = 10) -> asyncpg.Pool:
    return await asyncpg.create_pool(url, min_size=min_size, max_size=max_size, command_timeout=30)


async def migrate(pool: asyncpg.Pool) -> list[str]:
    """Apply unapplied *.sql files in name order. Returns the versions applied.

    Safe to run from several replicas at once (advisory lock), and refuses to continue
    if an already-applied file was edited (history must be immutable; add a new file).
    """
    applied: list[str] = []
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_ID)
        try:
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                       version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                       applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            done = {r["version"]: r["checksum"] for r in await conn.fetch("SELECT * FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                sql = path.read_text()
                checksum = hashlib.sha256(sql.encode()).hexdigest()
                if path.stem in done:
                    if done[path.stem] != checksum:
                        raise RuntimeError(f"migration {path.name} was modified after being applied")
                    continue
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                        path.stem,
                        checksum,
                    )
                applied.append(path.stem)
                logger.info(f"applied migration {path.stem}")
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_ID)
    return applied
