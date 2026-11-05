"""Factories for the three AI services (STT, LLM, TTS).

PRODUCTION SEAM: this is the *only* file that knows which vendors we use.
Swapping Groq for Gemini/OpenAI, or Deepgram TTS for Cartesia/ElevenLabs, is an
edit here (Pipecat has a drop-in service class for each). Per-agent overrides
(voice, model) come from AgentConfig, so different agents can use different ones.
"""

from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.groq.llm import GroqLLMService

from app.agent.config import AgentConfig
from app.config import Settings


def build_services(agent: AgentConfig, settings: Settings):
    stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTService.Settings(model=settings.stt_model, language=agent.language),
    )
    llm = GroqLLMService(
        api_key=settings.groq_api_key,
        settings=GroqLLMService.Settings(
            model=agent.llm_model or settings.groq_model,
            reasoning_effort=settings.groq_reasoning_effort,
            # The agent's personality/rules live on the LLM service, not in the
            # chat history, so they can't be summarised away or edited by the user.
            system_instruction=agent.system_prompt,
        ),
    )
    tts = DeepgramTTSService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramTTSService.Settings(voice=agent.voice or settings.tts_voice),
    )
    return stt, llm, tts
