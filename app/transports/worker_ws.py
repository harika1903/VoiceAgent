"""Worker-side WebSocket server transport.

In production without LiveKit, each Worker process spins up a tiny WS server
on a unique port. The browser connects to it directly. The session's Redis hash
stores the host:port so the API can tell the browser where to connect.

Wire format is the same BrowserPCMSerializer as dev mode (raw PCM + JSON control).
The WS token (HMAC-signed session_id + expiry) is verified on connection.
"""

from __future__ import annotations

import socket

from loguru import logger
from pipecat.transports.websocket.server import (
    SingleClientWebsocketServerParams,
    SingleClientWebsocketServerTransport,
)

from app.config import Settings
from app.transports.browser import BrowserPCMSerializer


def _find_free_port(start: int = 9100, end: int = 9999) -> int:
    """Find a free TCP port in the range. Used to assign each worker a unique port."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in {start}-{end}")


def build_worker_ws_transport(
    settings: Settings,
    session_id: str,
    port: int | None = None,
) -> tuple["SingleClientWebsocketServerTransport", int]:
    """Build a WS server transport for a Worker process.

    Returns (transport, port). The port must be published to Redis so the
    browser knows where to connect.
    """
    if port is None:
        port = _find_free_port(settings.worker_port_start, settings.worker_port_start + 900)

    host = "0.0.0.0"  # listen on all interfaces (worker might be on a different machine)

    transport = SingleClientWebsocketServerTransport(
        host=host,
        port=port,
        params=SingleClientWebsocketServerParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            serializer=BrowserPCMSerializer(settings.pipeline_sample_rate),
            # Only one client per worker (one call per process).
            session_timeout=settings.client_connect_timeout_secs,
        ),
    )

    logger.info(f"worker WS transport: configured on {host}:{port} for session {session_id}")
    return transport, port
