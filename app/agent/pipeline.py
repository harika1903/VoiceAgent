"""The agent pipeline: one call = one Pipecat pipeline.

    mic audio -> STT -> [user aggregator + VAD] -> LLM -> TTS -> speaker audio
                                 ^                              |
                                 +---- [assistant aggregator] <-+

Transport-agnostic: it receives an already-built transport, so the same code
serves browser, LiveKit, Twilio, etc. In production each call runs this inside
an Agent Worker process; the Session Dispatcher decides *which* worker gets it.

Two entry points:
  - run_agent_legacy() : old single-process dev mode (browser WS transport)
  - run_agent()        : production mode (called by worker with WorkerContext)
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)

from app.agent.config import AgentConfig
from app.agent.debug import InboundAudioTap, TranscriptTap
from app.agent.providers import build_services
from app.audio.speaker_gate import GateConfig, SpeakerGate, SpeakerGateCore, make_vad
from app.config import Settings
from app.kb.store import EmptyKnowledgeBase, KnowledgeBase
from app.sessions.models import Session, TranscriptTurn


def _build_pipeline_components(
    transport,
    agent: AgentConfig,
    session: Session,
    settings: Settings,
    embedder=None,
):
    """Build the pipeline pieces shared by both entry points."""
    stt, llm, tts = build_services(agent, settings)

    context = LLMContext()
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )
    user_agg, assistant_agg = aggregators.user(), aggregators.assistant()

    debug_in, debug_gated, debug_stt = [], [], []
    if settings.debug_dir:
        wav = Path(settings.debug_dir) / f"{session.id}.wav"
        debug_in = [InboundAudioTap(wav, settings.pipeline_sample_rate)]
        debug_stt = [TranscriptTap()]

    gate = []
    if embedder is not None and agent.speaker_lock:
        gate = [SpeakerGate(SpeakerGateCore(
            embedder,
            make_vad(),
            GateConfig(
                threshold_ratio=settings.speaker_threshold_ratio,
                speaking_boost=settings.speaker_speaking_boost,
            ),
        ))]
        if settings.debug_dir:
            debug_gated = [
                InboundAudioTap(
                    Path(settings.debug_dir) / f"{session.id}_gated.wav",
                    settings.pipeline_sample_rate,
                )
            ]

    pipeline = Pipeline(
        [
            transport.input(),
            *debug_in,
            *gate,
            *debug_gated,
            stt,
            *debug_stt,
            user_agg,
            llm,
            tts,
            transport.output(),
            assistant_agg,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=settings.pipeline_sample_rate,
            audio_out_sample_rate=settings.pipeline_sample_rate,
            enable_metrics=True,
        ),
    )

    return context, user_agg, assistant_agg, task


# ── Production entry point (called by Worker) ─────────────────────────────

async def run_agent(
    *,
    worker_ctx,
    agent: AgentConfig,
    session: Session,
    settings: Settings,
    embedder=None,
    transport=None,
    kb: KnowledgeBase | None = None,
    ws_publish_url: str | None = None,
) -> None:
    """Production path: the Worker provides a WorkerContext for checkpoints, lease
    renewal, and transcript streaming to Redis."""
    if transport is None:
        # Build LiveKit transport from session.room
        from app.transports.livekit import build_livekit_transport
        transport = build_livekit_transport(session, settings, worker_ctx.worker_id)

    if kb is None:
        kb = EmptyKnowledgeBase()

    context, user_agg, assistant_agg, task = _build_pipeline_components(
        transport, agent, session, settings, embedder,
    )

    turn_count = 0

    # Restore checkpoint if recovering
    if worker_ctx.checkpoint:
        messages = worker_ctx.checkpoint.get("messages", [])
        for msg in messages:
            context.add_message(msg)
        turn_count = worker_ctx.checkpoint.get("turn_count", 0)
        logger.info(f"session {session.id}: restored {len(messages)} messages from checkpoint")

    # ── Transcript capture -> Redis ────────────────────────────────────
    @user_agg.event_handler("on_user_turn_stopped")
    async def _user_turn(_agg, _strategy, message):
        nonlocal turn_count
        if message.content:
            turn_count += 1
            turn = TranscriptTurn(role="user", text=message.content)
            await worker_ctx.append_turn(turn)

            # KB context injection: search and add relevant products
            _inject_kb_context(kb, context, message.content, agent.kb_top_k)

            # Checkpoint after every user turn
            await worker_ctx.write_checkpoint({
                "messages": [m for m in context.messages],
                "turn_count": turn_count,
            })

    @assistant_agg.event_handler("on_assistant_turn_stopped")
    async def _assistant_turn(_agg, message):
        nonlocal turn_count
        if message.content:
            turn_count += 1
            turn = TranscriptTurn(
                role="assistant",
                text=message.content,
                interrupted=message.interrupted,
            )
            await worker_ctx.append_turn(turn)
            # Checkpoint after every assistant turn
            await worker_ctx.write_checkpoint({
                "messages": [m for m in context.messages],
                "turn_count": turn_count,
            })

    # ── Lifecycle ──────────────────────────────────────────────────────
    @transport.event_handler("on_client_connected")
    async def _connected(_transport, _client):
        if not worker_ctx.checkpoint:
            # Fresh call: agent speaks first
            context.add_message({"role": "user", "content": agent.greeting_instruction})
            await task.queue_frames([LLMRunFrame()])
        else:
            # Recovery: apologise and resume
            context.add_message({
                "role": "user",
                "content": "You were briefly disconnected. Apologise briefly for the interruption and continue the conversation from where you left off.",
            })
            await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _disconnected(_transport, _client):
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.add_workers(task)

    # Publish the WS URL only AFTER the transport server is actually listening
    if ws_publish_url:
        from app.sessions.redis_store import _sk
        await worker_ctx.store._r.hset(_sk(session.id), "worker_ws_url", ws_publish_url)
        logger.info(f"worker {worker_ctx.worker_id}: published WS URL {ws_publish_url}")

    await runner.run()


# ── Legacy single-process dev mode (browser WS, no Redis) ─────────────────

def _inject_kb_context(
    kb: KnowledgeBase, context: LLMContext, query: str, top_k: int,
) -> None:
    """Search the KB and inject matching products as a developer message."""
    if kb.size == 0:
        return
    results = kb.search(query, top_k=top_k)
    if not results:
        return
    lines = [doc.format_for_llm() for doc in results]
    context.add_message({
        "role": "developer",
        "content": f"[Relevant products from our catalog]\n" + "\n".join(f"- {l}" for l in lines),
    })


async def run_agent_legacy(
    *,
    transport,
    agent: AgentConfig,
    session: Session,
    sessions,  # SessionManager
    settings: Settings,
    embedder=None,
    kb: KnowledgeBase | None = None,
) -> None:
    """Old path: single-process, in-memory sessions, browser WebSocket.
    Kept for `uv run uvicorn app.main:app` local development."""

    if kb is None:
        kb = EmptyKnowledgeBase()

    context, user_agg, assistant_agg, task = _build_pipeline_components(
        transport, agent, session, settings, embedder,
    )

    @user_agg.event_handler("on_user_turn_stopped")
    async def _user_turn(_agg, _strategy, message):
        if message.content:
            await sessions.add_turn(session, TranscriptTurn(role="user", text=message.content))
            _inject_kb_context(kb, context, message.content, agent.kb_top_k)

    @assistant_agg.event_handler("on_assistant_turn_stopped")
    async def _assistant_turn(_agg, message):
        if message.content:
            await sessions.add_turn(
                session,
                TranscriptTurn(role="assistant", text=message.content, interrupted=message.interrupted),
            )

    @transport.event_handler("on_client_connected")
    async def _connected(_transport, _client):
        await sessions.mark_active(session)
        context.add_message({"role": "user", "content": agent.greeting_instruction})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def _disconnected(_transport, _client):
        await task.cancel()

    try:
        runner = PipelineRunner(handle_sigint=False)
        await runner.add_workers(task)
        await runner.run()
        await sessions.end(session, reason="client_disconnected")
    except Exception as e:
        logger.exception(f"session {session.id} crashed")
        await sessions.end(session, reason=f"error: {e}", failed=True)
