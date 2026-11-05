"""LiveKit transport adapter (architecture §3 + §8).

In production, audio flows through LiveKit's SFU rooms instead of raw WebSocket.
This gives us:
  - WebRTC (adaptive bitrate, jitter buffer, network resilience)
  - SIP gateway for PSTN calls (inbound and outbound)
  - Egress for audio-only recording
  - Room-based transfer (caller stays in room, participants move in/out)

The worker joins the room as `agent-{session_id}-e{epoch}` using a server-minted
token. The caller (web or PSTN) is already in the room by the time the worker starts.
"""

from __future__ import annotations

from loguru import logger

from app.config import Settings
from app.sessions.models import Session

try:
    from livekit.api import AccessToken, VideoGrants
    from pipecat.transports.livekit.transport import (
        LiveKitParams,
        LiveKitTransport,
    )
    _HAS_LIVEKIT = True
except ImportError:
    _HAS_LIVEKIT = False


def build_livekit_transport(
    session: Session,
    settings: Settings,
    worker_id: str,
) -> "LiveKitTransport":
    """Build a LiveKit transport for the worker to join the session's room.

    The worker identity encodes both the session id and epoch so that the
    Dispatcher can remove a stale agent participant on recovery (§9).
    """
    if not _HAS_LIVEKIT:
        raise RuntimeError(
            "LiveKit transport requires livekit-api and pipecat-ai[livekit]. "
            "Install with: uv add 'pipecat-ai[livekit]' livekit-api"
        )

    lk_url = settings.livekit_url
    lk_api_key = settings.livekit_api_key
    lk_api_secret = settings.livekit_api_secret
    room = session.room

    if not all([lk_url, lk_api_key, lk_api_secret, room]):
        raise RuntimeError(
            "LiveKit transport requires LIVEKIT_URL, LIVEKIT_API_KEY, "
            "LIVEKIT_API_SECRET and a room name on the session"
        )

    identity = f"agent-{session.id}-e{session.epoch}"

    # Mint a server-side token for the agent
    token = AccessToken(lk_api_key, lk_api_secret)
    token.identity = identity
    token.add_grants(VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
    ))
    token.ttl = 3600  # 1 hour (well beyond any call)
    jwt_token = token.to_jwt()

    transport = LiveKitTransport(
        url=lk_url,
        token=jwt_token,
        room_name=room,
        params=LiveKitParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=settings.pipeline_sample_rate,
            audio_out_sample_rate=settings.pipeline_sample_rate,
        ),
    )

    logger.info(
        f"livekit transport: room={room} identity={identity} url={lk_url}"
    )
    return transport


def mint_client_token(
    settings: Settings,
    room: str,
    identity: str,
    ttl: int = 300,
) -> str:
    """Mint a short-lived token for a web caller to join their room."""
    if not _HAS_LIVEKIT:
        return ""
    token = AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
    token.identity = identity
    token.add_grants(VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
    ))
    token.ttl = ttl
    return token.to_jwt()
