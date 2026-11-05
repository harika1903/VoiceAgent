# Voice Agent Platform v1.0

Production-ready voice AI agent platform (Pipecat + LiveKit) handling web calls,
PSTN inbound/outbound, campaigns, and call transfers.

## Architecture Overview

```
Clients (Web/Mobile, Operator Console, Admin UI, PSTN)
    │
    ▼
┌─────────────────────────── Control Plane ──────────────────────────────┐
│  Backend API        Session Dispatcher       Campaign Scheduler       │
│  (auth, agents,     (lifecycle, admission,   (slot-based pacing,      │
│   CRUD, credits)     rooms, recovery)         retries, windows)       │
│                                                                       │
│  Post-Call Processor (transcript, summary, usage reconciliation)      │
└───────────────────────────────┬───────────────────────────────────────┘
                                │  Redis (jobs, sessions, leases, events)
                                ▼
┌─────────────────────── Agent Server Fleet ────────────────────────────┐
│  Supervisor per node (warm pool, health, drain)                       │
│  Agent Workers 1..N  (1 call per process, Pipecat pipeline)          │
└───────────────────────────────┬───────────────────────────────────────┘
                                ▼
        AI Providers (STT, LLM, TTS) + LiveKit (SFU, SIP, Egress)
                                +
        Durable Storage (Postgres + Object Storage)
```

## Quick Start (Dev Mode — no Redis/Postgres needed)

```bash
cp .env.example .env      # add DEEPGRAM_API_KEY and GROQ_API_KEY (both free tiers)
uv sync
uv run uvicorn app.main:app --reload
# open http://localhost:8000, use headphones, click "Start call"
```

Dev mode runs everything in one process: browser WebSocket transport, in-memory
sessions, in-memory agent repo. No infrastructure required.

## Production Mode

Requires Redis and Postgres. Install them:
```bash
sudo apt install redis-server postgresql
sudo -u postgres createdb voiceagent
```

Set in `.env`:
```
ENVIRONMENT=prod
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=postgresql://postgres@localhost:5432/voiceagent
WS_TOKEN_SECRET=<random-64-char-string>
LIVEKIT_URL=wss://your-livekit.example.com
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
```

Start the services (each is a separate process):
```bash
# 1. Backend API + Dispatcher (runs migrations on first boot, seeds default org/agent)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. Agent Server (supervisor + warm pool of worker processes)
uv run va-supervisor

# 3. Post-Call Processor (transcript persistence, LLM summary, usage)
uv run va-postcall
```

On first boot, the Backend seeds a default org and prints an API key to the logs.
Save it — it's shown only once.

## API

All endpoints require `Authorization: Bearer va_<key>`.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/v1/agents` | List agents |
| `GET`  | `/v1/agents/{id}` | Get agent |
| `POST` | `/v1/agents/{id}` | Create agent (body: AgentSpec) |
| `PUT`  | `/v1/agents/{id}` | Update agent (bumps version) |
| `DELETE`| `/v1/agents/{id}` | Soft-delete (blocks new calls, live calls finish) |
| `POST` | `/v1/calls/web` | Start web call (returns room + LiveKit token) |
| `POST` | `/v1/calls/{id}/end` | End a call |
| `GET`  | `/v1/calls/{id}` | Get session state |
| `GET`  | `/healthz` | Health check (shows dev/production mode) |

## Project Layout

```
app/
├── main.py                    Composition root (dev + production wiring)
├── config.py                  Infrastructure settings (env vars)
├── security.py                API key hashing, WS token HMAC
├── observability.py           Structured logging setup
├── infra/redis.py             Redis connection factory
├── db/
│   ├── pool.py                Postgres pool + forward-only migrator
│   └── migrations/001_init.sql Schema: orgs, keys, agents, sessions, usage
├── agent/
│   ├── config.py              AgentConfig + AgentSpec + Protocol
│   ├── repository.py          PostgresAgentRepository (versioned CRUD)
│   ├── providers.py           STT/LLM/TTS factories (vendor seam)
│   ├── pipeline.py            Pipecat pipeline (production + legacy)
│   └── debug.py               Audio/transcript taps
├── sessions/
│   ├── models.py              Session state machine (11 states)
│   ├── redis_store.py         Redis store (Lua CAS, leases, checkpoints)
│   └── manager.py             Worker helpers + dev-mode in-memory store
├── dispatcher/dispatcher.py   Session Dispatcher (admission, lifecycle, reaper)
├── api/
│   ├── auth.py                API key auth middleware
│   ├── deps.py                FastAPI dependency factories
│   ├── routes_agents.py       Agent CRUD endpoints
│   ├── routes_calls.py        Call start/stop/history endpoints
│   └── ws.py                  Legacy browser WebSocket (dev mode)
├── worker/
│   ├── worker.py              Agent Worker (claim, pipeline, lease, checkpoint)
│   ├── supervisor.py          Supervisor (warm pool, health, drain)
│   └── __main__.py            Worker process entrypoint
├── postcall/processor.py      Post-Call Processor (persist, summary, usage)
├── transports/
│   ├── browser.py             Browser PCM-over-WebSocket (dev mode)
│   └── livekit.py             LiveKit transport (production)
└── audio/
    ├── embedder.py            Speaker voiceprint embedding (ONNX)
    └── speaker_gate.py        Speaker lock (ignore non-caller voices)
tests/                         40 tests (security, state machine, config, Redis)
web/index.html                 Browser client (dev mode)
```

## Key Design Decisions

1. **Dispatcher owns all state transitions** — CAS on `(status, epoch)` via Lua
   scripts in Redis. Two replicas can never both act on the same session.

2. **Workers never write to Postgres** — Transcripts and usage go to Redis. The
   Post-Call Processor persists them. A crashed worker can't corrupt the DB.

3. **Epoch-fenced leases** — A crashed worker can't keep talking. Its lease
   expires, the reaper bumps the epoch, and a new worker resumes from checkpoint.

4. **One call per process, recycled after each call** — No state bleeding between
   tenants, no slow memory leaks.

5. **Immutable agent versions** — Each edit creates a new version. Sessions pin
   the version they started with. Editing an agent never affects live calls.

6. **Priority job streams** — p0 (inbound + recovery), p1 (outbound), p2
   (campaigns). A ringing caller can't be starved by campaigns.

## Speaker Lock

The first ~2.5s of speech registers the caller's voiceprint (NeMo TitaNet-small,
ONNX, CPU). Everything that doesn't match is replaced with silence *before* STT
and VAD. Per-agent: `AgentConfig.speaker_lock`. Globally: `SPEAKER_GATE_ENABLED`.

## Testing

```bash
uv run pytest tests/ -v
```

Redis tests use `redislite` (embedded Redis binary, no server needed).
