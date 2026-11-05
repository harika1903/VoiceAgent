"""Speaker embedding: turn ~1 second of speech into a 192-number "voiceprint".

Two recordings of the SAME person give vectors that point in nearly the same
direction (cosine similarity high); different people point in different
directions. That is all speaker verification is. The model is NeMo TitaNet-small
(40 MB, ONNX, ~27 ms per second of audio on one CPU thread), run through
sherpa-onnx so we don't need PyTorch.
"""

import threading
import urllib.request
from pathlib import Path

import numpy as np
from loguru import logger

MODEL_URL = (
    # (sic) "recongition" is how the upstream release tag is actually spelled.
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{name}"
)


def ensure_model(models_dir: str, name: str) -> Path:
    path = Path(models_dir) / name
    if path.exists() and path.stat().st_size > 1_000_000:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"downloading speaker model {name} (one-time, ~40 MB)...")
    tmp = path.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL.format(name=name), tmp)
    tmp.rename(path)
    return path


class SpeakerEmbedder:
    def __init__(self, model_path: Path, sample_rate: int = 16000):
        import sherpa_onnx  # imported lazily: only needed when the gate is enabled

        self._sr = sample_rate
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(model_path), num_threads=1, provider="cpu"
            )
        )
        # One extractor is shared by every call in the process; guard it because
        # we can't assume the native object is safe for concurrent use.
        self._lock = threading.Lock()

    def embed(self, pcm16: np.ndarray) -> np.ndarray:
        """int16 mono samples -> unit-length embedding."""
        audio = pcm16.astype(np.float32) / 32768.0
        with self._lock:
            stream = self._extractor.create_stream()
            stream.accept_waveform(sample_rate=self._sr, waveform=audio)
            stream.input_finished()
            vec = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        return vec / (np.linalg.norm(vec) + 1e-9)
