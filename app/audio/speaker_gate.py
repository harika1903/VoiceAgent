"""Speaker gate: only the registered caller's voice reaches STT / VAD / interruption.

WHY THIS EXISTS
  Pipecat interrupts the agent whenever its VAD hears *any* speech. A TV, a
  coworker, or a second caller therefore cuts the agent off. Rather than tune
  thresholds (which can't tell voices apart), we put a gate *in front of* the
  VAD: audio that isn't the registered speaker is replaced by silence, so
  nothing downstream can react to it.

LIFECYCLE
  1. ENROLL   The first ~2.5 s of speech becomes the voiceprint (audio passes
              through untouched meanwhile). The match threshold is calibrated from
              that same speech, so a noisy mic gets a more lenient threshold.
  2. GATED    Gate is CLOSED (outputs zeros). Every 250 ms of speech we compare the
              last ~1 s against the voiceprint. Match -> OPEN, and we release the
              buffered start of the sentence so no words are lost. The gate closes
              again when the utterance ends, or if someone else takes over mid-speech.
              Utterances too short to score (e.g. "yes") are judged when they end.

TRADE-OFFS (worth knowing)
  * An utterance only reaches the agent ~0.6 s after it starts (time needed to
    be sure whose voice it is), so barge-in is slightly later than raw VAD.
  * Speaker verification is probabilistic. Similar voices, a very noisy mic, or
    two people talking at once can still slip through or be blocked.
  * Whoever speaks first after the greeting becomes "the user".

`SpeakerGateCore` is plain numpy (testable offline); `SpeakerGate` wraps it as a
Pipecat processor.
"""

import asyncio
from collections import deque
from dataclasses import dataclass

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

def make_vad():
    """A Silero VAD ready to use outside a pipeline.

    Pipecat's analyzer ignores the sample_rate constructor argument until
    set_sample_rate() is called (normally done by the pipeline's StartFrame), and
    on any error it logs and silently returns 0 - which would make the gate block
    everyone. So: set the rate explicitly, and prove it works on first use.
    """
    from pipecat.audio.vad.silero import SileroVADAnalyzer

    vad = SileroVADAnalyzer()
    vad.set_sample_rate(16000)
    return vad


def _confidence(vad, chunk: np.ndarray) -> float:
    # Pipecat returns a 1-element ndarray (or the int 0 after logging an error).
    return float(np.asarray(vad.voice_confidence(chunk.tobytes())).reshape(-1)[0])


CHUNK = 512  # samples per VAD step (Silero's frame size at 16 kHz = 32 ms)
CHUNK_SECS = CHUNK / 16000


@dataclass
class GateConfig:
    vad_threshold: float = 0.5
    window_secs: float = 1.0  # audio compared against the voiceprint
    hop_secs: float = 0.2  # how often we compare while someone is speaking
    min_speech_secs: float = 0.4  # speech needed inside a window to score it
    end_silence_secs: float = 0.5  # silence that ends an utterance
    onset_pad_chunks: int = 5  # also release this much audio *before* speech onset
    short_utterance_secs: float = 0.3  # shorter than this is ignored as noise

    enroll_secs: float = 2.5  # speech used to learn the voiceprint
    enroll_min_windows: int = 5
    threshold_ratio: float = 0.8  # match threshold = ratio * user's typical self-score
    threshold_floor: float = 0.25
    threshold_cap: float = 0.55
    # Closing uses a SHORTER window than opening, so a takeover is noticed fast
    # (a 1 s window would still be half the previous speaker). Shorter windows
    # score lower for the same person, hence the lower ratio.
    # A score only just over the threshold must repeat on two consecutive checks
    # before the gate opens; a clearly-matching one (+margin) opens at once. This
    # stops a lookalike voice from slipping through on one lucky window.
    strong_margin: float = 0.10
    # While the agent is SPEAKING a false accept means an unwanted interruption, so
    # the bar is higher then. While it is waiting for the user, the normal bar applies.
    speaking_boost: float = 1.2
    close_window_secs: float = 0.64
    close_min_speech_secs: float = 0.35
    close_ratio: float = 0.6  # close below ratio * threshold (hysteresis)
    close_after_hops: int = 2  # consecutive non-matching hops before closing
    # Speech older than this is never mixed into a comparison window.
    lookback_secs: float = 2.0
    # Utterances with < min_speech_secs of speech can't be verified reliably
    # (measured: user 0.29 vs strangers 0.03-0.25). While the agent is SPEAKING they
    # are blocked (so a cough/"yes" can't interrupt it). While the agent is WAITING,
    # nothing can be interrupted, so they're accepted at a lenient fraction of the
    # threshold.
    short_accept_ratio: float = 0.45


class SpeakerGateCore:
    def __init__(self, embedder, vad, config: GateConfig | None = None):
        self.cfg = config or GateConfig()
        self._embedder = embedder
        self._vad = vad  # anything with voice_confidence(int16 bytes) -> float

        c = self.cfg
        self._window_chunks = round(c.window_secs / CHUNK_SECS)
        self._hop_chunks = round(c.hop_secs / CHUNK_SECS)
        self._min_speech_chunks = round(c.min_speech_secs / CHUNK_SECS)
        self._end_chunks = round(c.end_silence_secs / CHUNK_SECS)
        self._short_chunks = round(c.short_utterance_secs / CHUNK_SECS)
        self._enroll_chunks = round(c.enroll_secs / CHUNK_SECS)
        self._close_window_chunks = round(c.close_window_secs / CHUNK_SECS)
        self._close_min_chunks = round(c.close_min_speech_secs / CHUNK_SECS)
        self._lookback_chunks = round(c.lookback_secs / CHUNK_SECS)

        self._carry = np.empty(0, np.int16)
        self._history: deque[tuple[np.ndarray, bool]] = deque(maxlen=200)  # ~6 s
        self._zeros = np.zeros(CHUNK, np.int16)
        self._t = 0.0  # stream time in seconds, for event logs

        # utterance state
        self._in_utt = False
        self._utt: list[np.ndarray] = []
        self._utt_flags: list[bool] = []
        self._silence_run = 0
        self._since_hop = 0
        self._utt_scored = False
        self._released = 0  # how many chunks of self._utt were already sent raw

        # gate state
        self.bot_speaking = False  # set by the Pipecat adapter
        self.open = False
        self._mismatch = 0
        self._confirm = 0  # consecutive borderline matches seen while closed

        # voiceprint
        self.profile: np.ndarray | None = None
        self.threshold = 0.0
        self.close_threshold = 0.0
        self._enroll_embs: list[np.ndarray] = []
        self._enroll_speech_chunks = 0

        self.events: list[tuple[float, str, float | None]] = []
        self.scores: list[tuple[float, float, bool]] = []  # (time, score, gate open) for tuning

    # ------------------------------------------------------------------ public

    @property
    def enrolled(self) -> bool:
        return self.profile is not None

    def feed(self, pcm: bytes) -> list[bytes]:
        """Push raw int16 mono audio; returns audio to forward downstream.

        Output is always whole 512-sample chunks, and usually the same length as
        the input. When the gate opens it is *longer* (a burst of buffered audio).
        """
        data = np.concatenate([self._carry, np.frombuffer(pcm, np.int16)])
        n = len(data) // CHUNK
        self._carry = data[n * CHUNK :]
        out: list[np.ndarray] = []
        for i in range(n):
            self._on_chunk(data[i * CHUNK : (i + 1) * CHUNK], out)
        return [o.tobytes() for o in out]

    # ----------------------------------------------------------------- internals

    def _event(self, kind: str, score: float | None = None) -> None:
        self.events.append((round(self._t, 2), kind, None if score is None else round(score, 3)))
        s = "" if score is None else f" score={score:.2f} (threshold {self.threshold:.2f})"
        logger.info(f"[gate] t={self._t:.1f}s {kind}{s}")

    def _on_chunk(self, c: np.ndarray, out: list[np.ndarray]) -> None:
        self._t += CHUNK_SECS
        speech = _confidence(self._vad, c) >= self.cfg.vad_threshold
        self._history.append((c, speech))

        if speech:
            self._silence_run = 0
            if not self._in_utt:
                self._start_utterance()
            if self.profile is None:
                self._enroll_speech_chunks += 1
        else:
            self._silence_run += 1

        if self._in_utt:
            self._utt.append(c)
            self._utt_flags.append(speech)
            self._since_hop += 1

        emitted = False
        if self._in_utt and self._since_hop >= self._hop_chunks:
            emitted = self._evaluate(out)

        if self._in_utt and self._silence_run >= self._end_chunks:
            if not emitted:
                if self.open or self.profile is None:
                    out.append(c)
                    emitted = True
                else:
                    emitted = self._judge_short_utterance(out)
            self._end_utterance()

        if not emitted:
            raw = self.open or self.profile is None
            out.append(c if raw else self._zeros)
            if raw and self._in_utt:
                self._released = len(self._utt)

    def _start_utterance(self) -> None:
        self._in_utt = True
        pad = list(self._history)[-(self.cfg.onset_pad_chunks + 1) : -1]
        self._utt = [p[0] for p in pad]
        self._utt_flags = [p[1] for p in pad]
        self._since_hop = 0
        self._utt_scored = False
        self._released = 0

    def _release_buffered(self, out: list[np.ndarray]) -> None:
        """Send audio we replaced with silence earlier (never audio already sent)."""
        out.extend(self._utt[self._released :])
        self._released = len(self._utt)

    def _end_utterance(self) -> None:
        self._in_utt = False
        self._utt, self._utt_flags = [], []
        self._released = 0
        self._since_hop = 0
        self.open = False  # re-arm: the next utterance must prove itself again
        self._mismatch = 0
        self._confirm = 0

    def _recent_speech(self, window_chunks: int, min_chunks: int) -> np.ndarray | None:
        """Latest speech-only audio (up to window_chunks), from the last few seconds
        only. None if there isn't at least min_chunks of it."""
        picked: list[np.ndarray] = []
        for chunk, is_speech in list(self._history)[-self._lookback_chunks :][::-1]:
            if is_speech:
                picked.append(chunk)
                if len(picked) >= window_chunks:
                    break
        if len(picked) < min_chunks:
            return None
        return np.concatenate(picked[::-1])

    def _evaluate(self, out: list[np.ndarray]) -> bool:
        """Compare the latest speech to the voiceprint. Returns True if it released audio."""
        self._since_hop = 0

        if self.profile is None:
            audio = self._recent_speech(self._window_chunks, self._min_speech_chunks)
            if audio is not None:
                self._enroll_step(self._embedder.embed(audio))
            return False

        if not self.open:
            audio = self._recent_speech(self._window_chunks, self._min_speech_chunks)
            if audio is None:
                return False
            self._utt_scored = True
            score = float(self.profile @ self._embedder.embed(audio))
            self.scores.append((self._t, score, False))
            bar = self.threshold * (self.cfg.speaking_boost if self.bot_speaking else 1.0)
            if score < bar:
                self._confirm = 0
                return False
            self._confirm += 1
            if score >= bar + self.cfg.strong_margin or self._confirm >= 2:
                self.open, self._mismatch, self._confirm = True, 0, 0
                self._event("open", score)
                self._release_buffered(out)  # the start of the sentence we had silenced
                return True
            return False

        # open: watch for someone else taking over
        audio = self._recent_speech(self._close_window_chunks, self._close_min_chunks)
        if audio is None:
            return False
        score = float(self.profile @ self._embedder.embed(audio))
        self.scores.append((self._t, score, True))
        if score < self.close_threshold:
            self._mismatch += 1
            if self._mismatch >= self.cfg.close_after_hops:
                self.open = False
                self._event("close (other speaker)", score)
        else:
            self._mismatch = 0
        return False

    def _judge_short_utterance(self, out: list[np.ndarray]) -> bool:
        """An utterance ended without ever being scored (too little speech, e.g. "yes")."""
        n_speech = sum(self._utt_flags)
        if self._utt_scored:
            self._event("blocked utterance")
            return False
        if n_speech < self._short_chunks:
            return False  # a click or breath, not worth logging
        if self.bot_speaking:
            self._event("blocked short utterance (agent speaking)")
            return False
        audio = np.concatenate([ch for ch, s in zip(self._utt, self._utt_flags) if s])
        score = float(self.profile @ self._embedder.embed(audio))
        if score >= self.threshold * self.cfg.short_accept_ratio:
            self._event("open (short utterance)", score)
            self._release_buffered(out)
            return True
        self._event("blocked short utterance", score)
        return False

    def _enroll_step(self, emb: np.ndarray) -> None:
        self._enroll_embs.append(emb)
        if (
            self._enroll_speech_chunks >= self._enroll_chunks
            and len(self._enroll_embs) >= self.cfg.enroll_min_windows
        ):
            self._finish_enrollment()

    def _finish_enrollment(self) -> None:
        E = np.stack(self._enroll_embs)
        centre = E.mean(0)
        centre /= np.linalg.norm(centre)
        sims = E @ centre
        # Drop windows that don't resemble the rest (e.g. a cough or someone else
        # chiming in during enrolment), then re-centre.
        keep = sims >= np.median(sims) - 0.15
        E = E[keep]
        total = E.sum(0)
        self.profile = total / np.linalg.norm(total)
        # "How similar is this user to their own voiceprint, on THIS mic?" Score each
        # window against windows that do NOT overlap it. (Consecutive windows share
        # 75% of their audio, so comparing neighbours gives a flattering ~0.75 that
        # real, unseen speech never reaches - that made the threshold too strict.)
        apart = round(self.cfg.window_secs / self.cfg.hop_secs)  # hops until no overlap
        loo = []
        for i, e in enumerate(E):
            far = [j for j in range(len(E)) if abs(j - i) >= apart]
            if far:
                ref = E[far].sum(0)
                loo.append(float(e @ (ref / np.linalg.norm(ref))))
        if not loo:  # too little speech to tell; fall back to a typical value
            loo = [0.5]
        typical = float(np.mean(loo))
        c = self.cfg
        self.threshold = float(np.clip(c.threshold_ratio * typical, c.threshold_floor, c.threshold_cap))
        self.close_threshold = self.threshold * c.close_ratio
        self.open = self._in_utt  # the speech we just learned from is the user
        logger.info(
            f"[gate] voiceprint registered from {len(E)}/{len(keep)} windows; "
            f"self-score≈{typical:.2f} -> match threshold {self.threshold:.2f}"
        )
        self._event("enrolled")


class SpeakerGate(FrameProcessor):
    """Pipecat adapter: runs the core on every inbound audio frame."""

    def __init__(self, core: SpeakerGateCore):
        super().__init__()
        self._core = core
        self._events_sent = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            # Embedding inference is CPU work (~30 ms); keep it off the event loop
            # so audio output and websockets stay responsive.
            chunks = await asyncio.get_running_loop().run_in_executor(
                None, self._core.feed, frame.audio
            )
            for chunk in chunks:
                await self.push_frame(
                    InputAudioRawFrame(
                        audio=chunk, sample_rate=frame.sample_rate, num_channels=frame.num_channels
                    ),
                    direction,
                )
            # Tell the client what the gate decided (shown in the web UI; handy when
            # debugging "why didn't it hear me?").
            for _t, kind, score in self._core.events[self._events_sent :]:
                await self.push_frame(
                    OutputTransportMessageUrgentFrame(
                        message={"type": "gate", "event": kind, "score": score}
                    )
                )
            self._events_sent = len(self._core.events)
        else:
            if isinstance(frame, BotStartedSpeakingFrame):
                self._core.bot_speaking = True
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._core.bot_speaking = False
            await self.push_frame(frame, direction)
