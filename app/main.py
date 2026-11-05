"""App wiring ("composition root").

TWO MODES:

1. Dev mode (default, no Redis/Postgres needed):
     uv run uvicorn app.main:app --reload
   Runs everything in one process: browser WS transport, in-memory sessions,
   in-memory agent repo. The browser connects to /ws/web.

2. Production mode (ENVIRONMENT=prod or Redis/Postgres configured):
     uv run uvicorn app.main:app
   Backend API with Postgres agents, Redis sessions, Dispatcher. Workers and
   Post-Call Processor run as separate processes (see app/worker/ and app/postcall/).

The decision is automatic: if redis_url and database_url are set AND the
services are reachable, production mode activates. Otherwise, dev mode.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config import get_settings
from app.observability import setup_logging

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


async def _try_production_setup(app: FastAPI, settings) -> bool:
    """Attempt to connect Redis + Postgres. Returns True if production mode is ready."""
    if settings.environment == "dev" and not settings.database_url:
        return False

    try:
        from app.db.pool import create_pool, migrate
        from app.infra.redis import make_redis
        from app.sessions.redis_store import RedisSessionStore
        from app.agent.repository import PostgresAgentRepository
        from app.dispatcher.dispatcher import SessionDispatcher

        # Test Redis connectivity
        redis = make_redis(settings.redis_url)
        await redis.ping()
        app.state.redis = redis

        # Postgres pool + migrations
        pool = await create_pool(settings.database_url)
        applied = await migrate(pool)
        if applied:
            logger.info(f"applied {len(applied)} migration(s): {applied}")
        app.state.db_pool = pool

        # Wire production components
        store = RedisSessionStore(redis, session_ttl=settings.session_ttl_after_end_secs)
        app.state.session_store = store
        app.state.agent_repo = PostgresAgentRepository(pool)
        app.state.dispatcher = SessionDispatcher(store, settings)

        # Ensure consumer groups
        for p in (0, 1, 2):
            await store.ensure_consumer_group(p)

        # Seed default org + agent if empty (first boot)
        await _seed_defaults(pool, settings)

        # Start dispatcher background tasks
        app.state._reaper_task = asyncio.create_task(app.state.dispatcher.reaper_loop())
        app.state._event_task = asyncio.create_task(
            app.state.dispatcher.consume_session_events()
        )

        return True

    except Exception as e:
        logger.warning(f"Production setup failed ({e}), falling back to dev mode")
        # Clean up partial setup
        if hasattr(app.state, "redis") and app.state.redis:
            await app.state.redis.aclose()
        if hasattr(app.state, "db_pool") and app.state.db_pool:
            await app.state.db_pool.close()
        return False


async def _seed_defaults(pool, settings) -> None:
    """Create a default org, API key, and agent on first boot."""
    import json
    from app.security import new_api_key, hash_api_key
    from app.agent.config import DEFAULT_AGENT_ID, DEFAULT_AGENT_SPEC

    existing = await pool.fetchval("SELECT id FROM orgs LIMIT 1")
    if existing:
        return

    raw_key = new_api_key()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO orgs (id, name) VALUES ('default', 'Default Org')"
            )
            await conn.execute(
                "INSERT INTO api_keys (org_id, key_hash, label) VALUES ('default', $1, 'bootstrap')",
                hash_api_key(raw_key),
            )
            await conn.execute(
                "INSERT INTO agents (org_id, id, current_version) VALUES ('default', $1, 1)",
                DEFAULT_AGENT_ID,
            )
            await conn.execute(
                "INSERT INTO agent_versions (org_id, agent_id, version, config) "
                "VALUES ('default', $1, 1, $2::jsonb)",
                DEFAULT_AGENT_ID,
                json.dumps(DEFAULT_AGENT_SPEC.model_dump()),
            )
    logger.info(f"seeded default org + agent. API key (save it!): {raw_key}")


class InMemoryAgentRepository:
    """Dev-mode shim: no org_id needed, wraps one-arg get/list."""

    def __init__(self):
        from app.agent.config import AgentConfig, DEFAULT_AGENT_SPEC, DEFAULT_AGENT_ID
        cfg = AgentConfig(id=DEFAULT_AGENT_ID, version=1, **DEFAULT_AGENT_SPEC.model_dump())
        self._agents = {cfg.id: cfg}

    async def get(self, agent_id: str) -> "AgentConfig | None":
        return self._agents.get(agent_id)

    async def list(self) -> list:
        return list(self._agents.values())


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings, "backend")
    app.state.settings = settings

    production = await _try_production_setup(app, settings)
    app.state.production = production

    if not production:
        # ── Dev mode: in-memory everything ─────────────────────────────
        from app.sessions.manager import InMemorySessionStore, SessionManager, log_summary_handler

        logger.info("starting in DEV mode (in-memory, no Redis/Postgres)")
        app.state.agents = InMemoryAgentRepository()
        app.state.sessions = SessionManager(InMemorySessionStore())
        app.state.sessions.post_call_handlers.append(log_summary_handler)
    else:
        logger.info("starting in PRODUCTION mode (Redis + Postgres)")

    # Speaker lock model (shared by both modes)
    app.state.embedder = None
    if settings.speaker_gate_enabled:
        from app.audio.embedder import SpeakerEmbedder, ensure_model

        def _load():
            return SpeakerEmbedder(ensure_model(settings.models_dir, settings.speaker_model))

        app.state.embedder = await asyncio.to_thread(_load)
        logger.info("speaker-lock model loaded")

    # Knowledge Base (shared by both modes)
    from app.kb.store import EmptyKnowledgeBase, load_product_catalog
    catalog_path = Path(settings.kb_default_catalog)
    if catalog_path.exists():
        app.state.kb = load_product_catalog(catalog_path)
        logger.info(f"knowledge base loaded: {app.state.kb.size} documents from {catalog_path}")
    else:
        app.state.kb = EmptyKnowledgeBase()
        logger.info("no knowledge base catalog found, KB disabled")

    if missing := settings.missing_keys():
        logger.warning(f"Missing {missing} - copy .env.example to .env and fill them in.")

    yield

    # ── Cleanup ────────────────────────────────────────────────────────
    if production:
        for task_name in ("_reaper_task", "_event_task"):
            task = getattr(app.state, task_name, None)
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if hasattr(app.state, "db_pool"):
            await app.state.db_pool.close()
        if hasattr(app.state, "redis"):
            await app.state.redis.aclose()


app = FastAPI(title="Voice Agent", lifespan=lifespan)


# ── Routes ─────────────────────────────────────────────────────────────────

# Always: legacy browser WS (dev mode) + health check
from app.api.ws import router as ws_router
app.include_router(ws_router)

# Production API routes (auth middleware rejects if Postgres isn't there)
from app.api.routes_agents import router as agents_router
from app.api.routes_calls import router as calls_router
from app.api.routes_kb import router as kb_router
from app.api.routes_settings import router as settings_router
app.include_router(agents_router)
app.include_router(calls_router)
app.include_router(kb_router)
app.include_router(settings_router)


@app.get("/healthz")
async def healthz():
    production = getattr(app.state, "production", False)
    return {"ok": True, "mode": "production" if production else "dev"}


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/production")
async def production_client():
    return FileResponse(WEB_DIR / "production.html")


# ── Dashboard SPA ─────────────────────────────────────────────────────────
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "dist"

if DASHBOARD_DIR.exists():
    @app.get("/dashboard/{rest_of_path:path}")
    async def dashboard_spa(rest_of_path: str):
        file = DASHBOARD_DIR / rest_of_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(DASHBOARD_DIR / "index.html")

    app.mount("/dashboard-assets", StaticFiles(directory=DASHBOARD_DIR / "assets"), name="dashboard-assets")

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# CORS for dashboard dev server (vite on :5173)
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
