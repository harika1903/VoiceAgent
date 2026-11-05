#!/usr/bin/env bash
# Start all 3 production processes: API, Supervisor, PostCall.
# Ctrl+C sends SIGTERM to all children for graceful shutdown.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colours for log prefixes ──────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

API_PREFIX="${GREEN}[api]${NC}      "
SUP_PREFIX="${BLUE}[supervisor]${NC}"
POST_PREFIX="${YELLOW}[postcall]${NC} "

PIDS=()

cleanup() {
    echo ""
    echo -e "${RED}Shutting down...${NC}"
    for pid in "${PIDS[@]}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    # Wait for children (up to 15s)
    for pid in "${PIDS[@]}"; do
        timeout 15 tail --pid="$pid" -f /dev/null 2>/dev/null || true
    done
    echo -e "${RED}All processes stopped.${NC}"
}
trap cleanup EXIT INT TERM

# ── Prefixed log forwarder ────────────────────────────────────────────────
prefix_output() {
    local prefix="$1"
    while IFS= read -r line; do
        echo -e "${prefix} ${line}"
    done
}

# ── Infrastructure checks ────────────────────────────────────────────────
echo -e "${GREEN}Checking infrastructure...${NC}"

python -c "
from app.infra.redis import make_redis
from app.config import get_settings
import asyncio
async def check():
    s = get_settings()
    r = make_redis(s.redis_url)
    await r.ping()
    await r.aclose()
    print(f'  Redis: ok ({s.redis_url})')
asyncio.run(check())
" 2>&1 || { echo "Redis not reachable. Start it first."; exit 1; }

python -c "
import asyncpg, asyncio
from app.config import get_settings
async def check():
    s = get_settings()
    conn = await asyncpg.connect(s.database_url)
    await conn.close()
    print(f'  Postgres: ok ({s.database_url})')
asyncio.run(check())
" 2>&1 || { echo "Postgres not reachable. Start it first."; exit 1; }

echo ""

# ── Start API server ─────────────────────────────────────────────────────
echo -e "${GREEN}Starting API server...${NC}"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1 | prefix_output "$API_PREFIX" &
PIDS+=($!)

# Give the API a moment to boot and run migrations
sleep 3

# ── Start Supervisor ──────────────────────────────────────────────────────
echo -e "${BLUE}Starting Supervisor...${NC}"
python -m app.worker.supervisor 2>&1 | prefix_output "$SUP_PREFIX" &
PIDS+=($!)

# ── Start Post-Call Processor ─────────────────────────────────────────────
echo -e "${YELLOW}Starting Post-Call Processor...${NC}"
python -m app.postcall 2>&1 | prefix_output "$POST_PREFIX" &
PIDS+=($!)

sleep 2

# ── Health check ──────────────────────────────────────────────────────────
echo ""
if curl -sf http://localhost:8000/healthz > /dev/null 2>&1; then
    MODE=$(curl -sf http://localhost:8000/healthz | python -c "import sys,json; print(json.load(sys.stdin)['mode'])")
    echo -e "${GREEN}Health check passed (mode: ${MODE})${NC}"
else
    echo -e "${RED}Health check failed — API may still be starting${NC}"
fi

echo ""
echo -e "${GREEN}All processes running. Ctrl+C to stop.${NC}"
echo -e "  API:        http://localhost:8000"
echo -e "  Production: http://localhost:8000/production"
echo -e "  Dev:        http://localhost:8000/"
echo ""

# Wait for any child to exit
wait -n "${PIDS[@]}" 2>/dev/null || true
echo -e "${RED}A process exited unexpectedly.${NC}"
