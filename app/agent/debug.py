"""Opt-in debugging taps. Enable with DEBUG_DIR=debug in .env.

A Pipecat pipeline is a chain of FrameProcessors; each receives frames and
passes them on. A "tap" is a processor that watches frames and forwards them
untouched - so we can look inside the pipeline without changing its behaviour.
"""

import wave
from pathlib import Path

from loguru import logger
from pipecat.frames.frames import (
    EndFrame,
    CancelFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class InboundAudioTap(FrameProcessor):
    """Saves exactly what the server receives from the caller to a WAV file.
    Placed right after transport.input(), i.e. before any AI touches it."""

    def __init__(self, path: Path, sample_rate: int):
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(str(path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)
        self._path = path

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            self._wav.writeframes(frame.audio)
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._wav.close()
            logger.info(f"[debug] caller audio saved to {self._path}")
        await self.push_frame(frame, direction)


class TranscriptTap(FrameProcessor):
    """Logs what STT actually returned (interim = still guessing, final = committed)."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            logger.info(f"[stt final]   {frame.text!r}")
        elif isinstance(frame, InterimTranscriptionFrame):
            logger.info(f"[stt interim] {frame.text!r}")
        await self.push_frame(frame, direction)
