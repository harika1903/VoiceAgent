"""Postgres-backed AgentRepository (agents + immutable agent_versions)."""

import json

import asyncpg

from app.agent.config import AgentConfig, AgentExists, AgentSpec


def _to_config(agent_id: str, version: int, config: str | dict) -> AgentConfig:
    data = json.loads(config) if isinstance(config, str) else config
    return AgentConfig(id=agent_id, version=version, **data)


class PostgresAgentRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def get(self, org_id: str, agent_id: str) -> AgentConfig | None:
        """Live (not soft-deleted) agent: what new sessions may start from."""
        row = await self._pool.fetchrow(
            """SELECT a.id, a.current_version, v.config FROM agents a
               JOIN agent_versions v ON v.org_id = a.org_id AND v.agent_id = a.id
                                    AND v.version = a.current_version
               WHERE a.org_id = $1 AND a.id = $2 AND a.deleted_at IS NULL""",
            org_id,
            agent_id,
        )
        return _to_config(row["id"], row["current_version"], row["config"]) if row else None

    async def list(self, org_id: str) -> list[AgentConfig]:
        rows = await self._pool.fetch(
            """SELECT a.id, a.current_version, v.config FROM agents a
               JOIN agent_versions v ON v.org_id = a.org_id AND v.agent_id = a.id
                                    AND v.version = a.current_version
               WHERE a.org_id = $1 AND a.deleted_at IS NULL ORDER BY a.id""",
            org_id,
        )
        return [_to_config(r["id"], r["current_version"], r["config"]) for r in rows]

    async def create(self, org_id: str, agent_id: str, spec: AgentSpec) -> AgentConfig:
        cfg = AgentConfig(id=agent_id, version=1, **spec.model_dump())  # validates the id
        try:
            async with self._pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "INSERT INTO agents (org_id, id, current_version) VALUES ($1, $2, 1)",
                    org_id,
                    agent_id,
                )
                await conn.execute(
                    "INSERT INTO agent_versions (org_id, agent_id, version, config) "
                    "VALUES ($1, $2, 1, $3::jsonb)",
                    org_id,
                    agent_id,
                    json.dumps(spec.model_dump()),
                )
        except asyncpg.UniqueViolationError as e:
            raise AgentExists(agent_id) from e
        return cfg

    async def update(self, org_id: str, agent_id: str, spec: AgentSpec) -> AgentConfig | None:
        async with self._pool.acquire() as conn, conn.transaction():
            # FOR UPDATE serialises concurrent edits so versions never collide.
            row = await conn.fetchrow(
                "SELECT current_version FROM agents WHERE org_id = $1 AND id = $2 "
                "AND deleted_at IS NULL FOR UPDATE",
                org_id,
                agent_id,
            )
            if row is None:
                return None
            version = row["current_version"] + 1
            await conn.execute(
                "INSERT INTO agent_versions (org_id, agent_id, version, config) "
                "VALUES ($1, $2, $3, $4::jsonb)",
                org_id,
                agent_id,
                version,
                json.dumps(spec.model_dump()),
            )
            await conn.execute(
                "UPDATE agents SET current_version = $3, updated_at = now() "
                "WHERE org_id = $1 AND id = $2",
                org_id,
                agent_id,
                version,
            )
        return AgentConfig(id=agent_id, version=version, **spec.model_dump())

    async def delete(self, org_id: str, agent_id: str) -> bool:
        """Soft delete: blocks new sessions; live calls finish on their pinned version."""
        res = await self._pool.execute(
            "UPDATE agents SET deleted_at = now() WHERE org_id = $1 AND id = $2 AND deleted_at IS NULL",
            org_id,
            agent_id,
        )
        return res.endswith(" 1")
