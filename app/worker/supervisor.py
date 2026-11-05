"""Agent Server Supervisor (architecture §4.4).

One supervisor per node (VM/container). Manages a pool of worker processes:
  - Warm pool: N idle processes with models pre-loaded, ready to claim a job
  - Recycle: each worker exits after its call; supervisor spawns a replacement
  - Health: detect child exit via proc.wait() (no polling), report capacity to Redis
  - Drain: on SIGTERM, stop spawning new workers and wait for live calls to finish
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
import uuid

from loguru import logger

from app.config import Settings, get_settings
from app.infra.redis import make_redis
from app.observability import setup_logging
from app.sessions.redis_store import RedisSessionStore


class WorkerProcess:
    """Tracks one child process."""

    __slots__ = ("pid", "proc", "worker_id", "started_at", "_wait_task", "_log_task")

    def __init__(self, proc: asyncio.subprocess.Process, worker_id: str):
        self.proc = proc
        self.pid = proc.pid
        self.worker_id = worker_id
        self.started_at = time.time()
        self._wait_task: asyncio.Task | None = None
        self._log_task: asyncio.Task | None = None


class Supervisor:
    def __init__(self, settings: Settings, node_id: str | None = None):
        self.settings = settings
        self.node_id = node_id or f"node-{uuid.uuid4().hex[:8]}"
        self._workers: dict[int, WorkerProcess] = {}  # pid -> WorkerProcess
        self._draining = False
        self._redis = None
        self._store: RedisSessionStore | None = None
        self._capacity_task: asyncio.Task | None = None
        self._child_exit = asyncio.Event()

    @property
    def total(self) -> int:
        return len(self._workers)

    @property
    def max_workers(self) -> int:
        return self.settings.worker_max_calls

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._redis = make_redis(self.settings.redis_url)
        self._store = RedisSessionStore(self._redis, session_ttl=self.settings.session_ttl_after_end_secs)

        for p in (0, 1, 2):
            await self._store.ensure_consumer_group(p)

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, self._initiate_drain)
        loop.add_signal_handler(signal.SIGINT, self._initiate_drain)

        self._capacity_task = asyncio.create_task(self._capacity_loop())

        await self._fill_pool()
        logger.info(
            f"supervisor {self.node_id}: started "
            f"(max={self.max_workers} warm={self.settings.worker_warm_pool})"
        )

    async def run_forever(self) -> None:
        """Main loop: wait for workers to exit and replace them."""
        await self.start()
        try:
            while not self._draining or self._workers:
                if not self._workers:
                    if self._draining:
                        break
                    await asyncio.sleep(0.5)
                    continue

                # Block until a child exits (or drain signal)
                self._child_exit.clear()
                await self._child_exit.wait()

                # Collect finished workers
                done_pids = [
                    pid for pid, wp in self._workers.items()
                    if wp.proc.returncode is not None
                ]
                for pid in done_pids:
                    wp = self._workers.pop(pid)
                    code = wp.proc.returncode
                    elapsed = time.time() - wp.started_at
                    if code == 0:
                        logger.info(
                            f"supervisor: worker {wp.worker_id} pid={pid} "
                            f"finished normally ({elapsed:.1f}s)"
                        )
                    else:
                        logger.warning(
                            f"supervisor: worker {wp.worker_id} pid={pid} "
                            f"exited code={code} ({elapsed:.1f}s)"
                        )

                if not self._draining:
                    await self._fill_pool()

        finally:
            if self._capacity_task:
                self._capacity_task.cancel()
            # Cancel any outstanding wait/log tasks
            for wp in self._workers.values():
                if wp._wait_task:
                    wp._wait_task.cancel()
                if wp._log_task:
                    wp._log_task.cancel()
            if self._redis:
                await self._redis.aclose()
            logger.info(f"supervisor {self.node_id}: shut down")

    # ── Pool management ────────────────────────────────────────────────────

    async def _fill_pool(self) -> None:
        target = self.max_workers
        while self.total < target and not self._draining:
            await self._spawn_worker()

    async def _spawn_worker(self) -> WorkerProcess:
        worker_id = f"{self.node_id}-{uuid.uuid4().hex[:6]}"
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.worker",
            "--worker-id",
            worker_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "WORKER_ID": worker_id},
        )
        wp = WorkerProcess(proc, worker_id)
        self._workers[proc.pid] = wp

        # Background task: wait for this child to exit, then signal main loop
        wp._wait_task = asyncio.create_task(self._wait_child(wp))
        # Background task: forward child stderr to supervisor log
        wp._log_task = asyncio.create_task(self._forward_logs(wp))

        logger.debug(f"supervisor: spawned worker pid={proc.pid} id={worker_id}")
        return wp

    async def _wait_child(self, wp: WorkerProcess) -> None:
        """Await a single child's exit and wake the main loop."""
        try:
            await wp.proc.wait()
        except asyncio.CancelledError:
            return
        self._child_exit.set()

    async def _forward_logs(self, wp: WorkerProcess) -> None:
        """Read worker stderr line by line and log it under the supervisor."""
        try:
            assert wp.proc.stderr is not None
            while True:
                line = await wp.proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.info(f"[worker {wp.worker_id}] {text}")
        except asyncio.CancelledError:
            return
        except Exception:
            pass

    # ── Drain (graceful shutdown) ──────────────────────────────────────────

    def _initiate_drain(self) -> None:
        if self._draining:
            return
        self._draining = True
        logger.info(f"supervisor {self.node_id}: draining (waiting for {self.total} workers)")
        self._child_exit.set()  # wake main loop so it sees the drain flag

    # ── Capacity reporting (§4.4) ──────────────────────────────────────────

    async def _capacity_loop(self) -> None:
        """Report node capacity to Redis every 5 seconds."""
        while True:
            try:
                await self._store.report_capacity(
                    self.node_id,
                    {
                        "total": self.max_workers,
                        "active": self.total,
                        "draining": int(self._draining),
                        "version": "1.0.0",
                    },
                    ttl=15,
                )
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("capacity report failed")
            await asyncio.sleep(5)


# ── Entrypoint ─────────────────────────────────────────────────────────────

async def supervisor_main() -> None:
    settings = get_settings()
    setup_logging(settings, "supervisor")
    supervisor = Supervisor(settings)
    await supervisor.run_forever()


def supervisor_entry() -> None:
    asyncio.run(supervisor_main())


if __name__ == "__main__":
    supervisor_entry()
