"""Browser transport adapter.

THE IDEA: the agent pipeline only deals with Pipecat *frames* (audio in, audio
out, "user interrupted"). A transport adapter = a *serializer* that translates
between frames and whatever bytes the other side speaks. For telephony
providers, Pipecat already ships serializers (Twilio, Telnyx, Plivo, Exotel...),
so adding the phone later = pick a different serializer + different WS route.

Wire format for the browser (deliberately trivial, so you can read it):
  browser -> server : binary message = raw 16-bit little-endian mono PCM @ 16 kHz
  server -> browser : binary message = same format (the agent's voice)
                      text message   = JSON control, e.g. {"type":"clear"}
"""

import json

from fastapi import WebSocket
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from app.config import Settings


class BrowserPCMSerializer(FrameSerializer):
    def __init__(self, sample_rate: int):
        super().__init__()
        self._rate = sample_rate

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            # The user started talking over the agent. Tell the browser to drop
            # any audio it has queued, otherwise it keeps talking for seconds.
            return json.dumps({"type": "clear"})
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            # App-level notifications (e.g. speaker-gate decisions) -> JSON text message.
            # (Pipecat's own RTVI chatter is filtered out by should_ignore_frame.)
            return None if self.should_ignore_frame(frame) else json.dumps(frame.message)
        if isinstance(frame, OutputAudioRawFrame):
            # Pipeline output rate == self._rate (set via PipelineParams), so no
            # resampling is needed here.
            return frame.audio
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes) and data:
            return InputAudioRawFrame(audio=data, sample_rate=self._rate, num_channels=1)
        return None  # ignore text/control messages from the browser for now


def build_browser_transport(websocket: WebSocket, settings: Settings) -> FastAPIWebsocketTransport:
    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            serializer=BrowserPCMSerializer(settings.pipeline_sample_rate),
        ),
    )
