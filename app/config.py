"""Process-level configuration, read from environment / .env.

Only *infrastructure* settings live here (API keys, hosts). Per-agent behaviour
(prompt, voice, language) lives in AgentConfig, because in production the admin
UI edits that at runtime and it must not require a redeploy.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deepgram_api_key: str = ""
    groq_api_key: str = ""

    # Defaults used when an AgentConfig doesn't override them.
    # Groq retires models often (llama-3.3-70b-versatile already vanished), so this
    # is config, not code. List what your key can use: GET api.groq.com/openai/v1/models
    groq_model: str = "openai/gpt-oss-120b"
    # How much hidden "thinking" before answering. "low" keeps latency ~0.4s; gpt-oss
    # takes low/medium/high (Qwen takes none/default). Why not Qwen: Pipecat's
    # "didn't catch that" recovery sends a `developer`-role message, which Qwen's chat
    # template rejects (HTTP 400); gpt-oss accepts it.
    groq_reasoning_effort: str = "low"
    stt_model: str = "nova-3"
    tts_voice: str = "aura-2-thalia-en"

    log_level: str = "INFO"
    # "json" = one JSON object per line (what log aggregators want); "text" = human readable.
    log_format: str = "text"

    # ---- shared infrastructure (every service reads these) ----
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql://postgres@localhost:5432/voiceagent"

    # ---- security ----
    # HMAC key for the short-lived token that lets a browser open the worker's media
    # WebSocket. MUST be overridden outside dev (validated by require_production_safe()).
    ws_token_secret: str = "dev-only-change-me"
    ws_token_ttl_secs: int = 60
    environment: str = "dev"  # dev | prod

    # ---- session / dispatcher ----
    # A call's lease must be renewed within this window or the reaper declares the
    # worker dead. Heartbeat runs at a third of it.
    lease_ttl_secs: int = 15
    # How long POST /v1/calls/web waits for a worker to take the job.
    start_timeout_secs: float = 10.0
    # Browser must connect to its worker within this long or the call is released.
    client_connect_timeout_secs: float = 30.0
    # Default per-tenant concurrent-call cap (a tenant row can override it).
    default_max_concurrent_calls: int = 10
    # Finished sessions stay in Redis this long after the Post-Call Processor is done.
    session_ttl_after_end_secs: int = 3600

    # ---- agent worker fleet ----
    worker_max_calls: int = 4  # processes per node (1 call per process)
    worker_warm_pool: int = 1  # idle, model-loaded processes kept ready
    worker_public_host: str = "localhost"  # host the BROWSER uses to reach workers
    worker_public_scheme: str = "ws"  # use "wss" behind TLS termination
    worker_port_start: int = 9100
    worker_claim_timeout_secs: float = 30.0  # how long a worker waits for a job before exiting
    worker_drain_timeout_secs: float = 600.0
    # Dotted path "module:function" of the coroutine that runs one call. A seam
    # (and what lets tests run the whole fleet without paid AI providers).
    agent_runner: str = "app.agent.pipeline:run_agent"

    # ---- post-call ----
    # Summary is skipped when empty/no GROQ key. Uses the same Groq account.
    summary_model: str = "openai/gpt-oss-20b"
    postcall_max_deliveries: int = 5

    # ---- LiveKit (production media transport) ----
    livekit_url: str = ""          # e.g. wss://my-livekit.example.com
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Speaker lock: only the voice that is registered at the start of a call can
    # reach STT / interrupt the agent. Per-agent switch: AgentConfig.speaker_lock.
    speaker_gate_enabled: bool = True
    speaker_model: str = "nemo_en_titanet_small.onnx"
    # Tuning knobs. If the agent ignores YOU: lower the ratio (e.g. 0.65). If other
    # voices still get through: raise it (e.g. 0.9) or raise the speaking boost.
    speaker_threshold_ratio: float = 0.8
    speaker_speaking_boost: float = 1.2
    models_dir: str = "models"

    # Knowledge Base: default catalog loaded at startup. Per-agent kb_file overrides.
    kb_default_catalog: str = "data/catalog.json"

    # When set (e.g. DEBUG_DIR=debug), each call saves the caller's audio as a WAV
    # there and logs raw STT output. Leave empty in production (privacy + disk).
    debug_dir: str = ""

    # Browser transport audio format (16 kHz mono 16-bit PCM). Telephony adapters
    # will use their own (8 kHz) but the pipeline core is resampled by Pipecat.
    pipeline_sample_rate: int = 16000

    def require_production_safe(self) -> None:
        """Refuse to boot prod with dev defaults (a known secret = forgeable tokens)."""
        if self.environment == "prod" and self.ws_token_secret == "dev-only-change-me":
            raise RuntimeError("WS_TOKEN_SECRET must be set when ENVIRONMENT=prod")

    def missing_keys(self) -> list[str]:
        missing = []
        if not self.deepgram_api_key:
            missing.append("DEEPGRAM_API_KEY")
        if not self.groq_api_key:
            missing.append("GROQ_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
