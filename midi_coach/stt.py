"""Speech to text for talking to the Maestro, with Whisper running locally (faster-whisper).

The model (base.en, ~145 MB) downloads to %USERPROFILE%\\MidiCoach\\whisper on first use.
Audio comes from the coach page's microphone recording (webm/opus or wav; PyAV decodes it).
"""

from __future__ import annotations

import io
import threading

from .library import home

MODEL = "base.en"
# Words Whisper should expect, so "Rehearse" and "F sharp" come out right.
HINT = ("Piano practice with the Maestro: Listen, Learn mode, Rehearse, bars five to eight, tempo, loop, "
        "left hand, right hand, hands together, F sharp, B flat, D major scale, arpeggio, metronome.")
FLUTE_HINT = ("Maestro, flute practice: Listen, Learn mode, Rehearse, bars five to eight, tempo, loop, long tones, "
              "tonguing, slurred, F sharp, B flat, G major scale, E minor, arpeggio, a twelfth, metronome, Roadmap, write me.")

_lock = threading.Lock()
_model = None


class Unavailable(RuntimeError):
    pass


def _load():
    global _model
    if _model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise Unavailable("faster-whisper is not installed (pip install faster-whisper)") from exc
        _model = WhisperModel(MODEL, device="cpu", compute_type="int8", download_root=str(home() / "whisper"))
    return _model


def warm_up() -> None:
    def run() -> None:
        try:
            with _lock:
                _load()
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


def decode(audio: bytes):
    """Any container PyAV reads (webm/opus, ogg, wav) -> 16 kHz mono float32 samples.
    Done here rather than in faster-whisper, whose decoder passes options newer PyAV dropped."""
    import av
    import numpy as np

    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = []
    with av.open(io.BytesIO(audio), mode="r") as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):
        chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def _hint() -> str:
    from . import profiles

    return FLUTE_HINT if profiles.instrument() == "flute" else HINT


def transcribe(audio: bytes) -> str:
    if not audio:
        return ""
    samples = decode(audio)
    if samples.size < 16000 * 0.3:  # under a third of a second: nothing said
        return ""
    with _lock:
        segments, _ = _load().transcribe(samples, language="en", beam_size=1, vad_filter=True, initial_prompt=_hint())
        return " ".join(s.text.strip() for s in segments).strip()
