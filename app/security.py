"""API keys and the media-WebSocket token.

API keys: random, shown once, stored only as a SHA-256 hash (a DB leak must not leak
usable keys). SHA-256 (not bcrypt) is fine because keys are 256-bit random, not
human passwords, and we need a fast lookup on every request.

WS token: the browser talks to a worker directly, so the worker must verify the caller
was authorised by the control plane. The token is `base64(payload).hmac` binding one
session id to an expiry; the worker only needs the shared secret (no DB, no Redis).
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

API_KEY_PREFIX = "va_"


def new_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: str, body: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def make_ws_token(secret: str, session_id: str, ttl_secs: int, now: float | None = None) -> str:
    payload = {"sid": session_id, "exp": int((now if now is not None else time.time()) + ttl_secs)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(secret, body)}"


def verify_ws_token(
    secret: str, token: str, session_id: str, now: float | None = None
) -> bool:
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(secret, body)):
            return False
        payload = json.loads(_unb64(body))
        return payload["sid"] == session_id and payload["exp"] >= (
            now if now is not None else time.time()
        )
    except Exception:
        return False
