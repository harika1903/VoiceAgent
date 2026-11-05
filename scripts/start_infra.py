"""Start Redis + Postgres for local production-mode testing.

Runs both as userland processes (no root/Docker needed):
  - Postgres via pgserver (bundled binary)
  - Redis via redislite (bundled binary)

Usage:
    uv run python scripts/start_infra.py          # start and block
    uv run python scripts/start_infra.py --bg      # start in background, print env
"""

import json
import os
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

# Ensure project root is on sys.path so `from app.db.pool import ...` works.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

PGDATA = Path.home() / ".local/share/voiceagent-pg"
REDIS_DIR = Path.home() / ".local/share/voiceagent-redis"
STATE_FILE = REDIS_DIR / "infra_state.json"


def start():
    PGDATA.mkdir(parents=True, exist_ok=True)
    REDIS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Postgres ───────────────────────────────────────────────────────
    import pgserver

    pg = pgserver.PostgresServer(PGDATA, cleanup_mode="stop")
    pg.ensure_pgdata_inited()
    pg.ensure_postgres_running()
    pg_uri = pg.get_uri()

    # Parse socket directory from pgserver's URI
    parsed = urllib.parse.urlparse(pg_uri)
    qs = urllib.parse.parse_qs(parsed.query)
    socket_dir = qs.get("host", [str(PGDATA)])[0]
    print(f"✅ Postgres running (socket: {socket_dir})")

    # Create voiceagent DB if needed
    pg_bin = Path(pgserver.__file__).parent / "pginstall" / "bin"
    subprocess.run(
        [str(pg_bin / "createdb"), "-h", socket_dir, "-U", "postgres", "voiceagent"],
        capture_output=True,
    )

    # Verify
    r = subprocess.run(
        [str(pg_bin / "psql"), "-h", socket_dir, "-U", "postgres", "-d", "voiceagent", "-c", "SELECT 1"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"❌ Postgres check failed: {r.stderr}")
        sys.exit(1)

    # asyncpg needs host= as a DSN parameter, not a query string
    # Format: postgresql://user@/dbname?host=/path/to/socket
    db_url = f"postgresql://postgres@/voiceagent?host={socket_dir}"
    print(f"✅ Database 'voiceagent' ready")

    # ── Redis ──────────────────────────────────────────────────────────
    import redislite

    redis_obj = redislite.Redis(str(REDIS_DIR / "voiceagent.rdb"))
    redis_obj.ping()
    redis_url = f"unix://{redis_obj.socket_file}?db=0"
    print(f"✅ Redis running (socket: {redis_obj.socket_file})")

    # ── Run migrations ─────────────────────────────────────────────────
    import asyncio
    import asyncpg

    async def migrate_db():
        pool = await asyncpg.create_pool(db_url)
        v = await pool.fetchval("SELECT version()")
        print(f"✅ asyncpg connected: {v[:50]}...")

        from app.db.pool import migrate
        applied = await migrate(pool)
        if applied:
            print(f"✅ Migrations applied: {applied}")
        else:
            print(f"✅ Migrations: up to date")

        tables = await pool.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        print(f"   Tables: {[t['tablename'] for t in tables]}")
        await pool.close()

    asyncio.run(migrate_db())

    # ── Test async Redis ───────────────────────────────────────────────
    import redis.asyncio as aioredis

    async def test_redis():
        r = aioredis.from_url(redis_url, decode_responses=True)
        await r.ping()
        print(f"✅ async Redis OK")
        await r.aclose()

    asyncio.run(test_redis())

    # ── Save state ─────────────────────────────────────────────────────
    state = {
        "database_url": db_url,
        "redis_url": redis_url,
        "pid": os.getpid(),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))

    # ── Auto-update .env ───────────────────────────────────────────────
    env_file = Path(_project_root) / ".env"
    if env_file.exists():
        lines = env_file.read_text().splitlines()
        new_lines = []
        for line in lines:
            if line.startswith("DATABASE_URL="):
                new_lines.append(f"DATABASE_URL={db_url}")
            elif line.startswith("REDIS_URL="):
                new_lines.append(f"REDIS_URL={redis_url}")
            else:
                new_lines.append(line)
        env_file.write_text("\n".join(new_lines) + "\n")
        print(f"✅ .env updated with current URLs")

    print(f"\n{'='*60}")
    print(f"  DATABASE_URL={db_url}")
    print(f"  REDIS_URL={redis_url}")
    print(f"{'='*60}")
    print(f"\nInfra running (pid {os.getpid()}). Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopping...")
        redis_obj.shutdown()
        pg.cleanup()
        STATE_FILE.unlink(missing_ok=True)
        print("Done.")


if __name__ == "__main__":
    start()
