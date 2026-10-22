"""Natural-sounding speech for the coach page, with Kokoro running locally.

    .venv\\Scripts\\python -m midi_coach.tts                 download the model (~340 MB, once), say a test line
    .venv\\Scripts\\python -m midi_coach.tts "Hello" af_heart  say something with a given voice

The model is kept in %USERPROFILE%\\MidiCoach\\kokoro. Without it, or without the
kokoro-onnx package, the coach page falls back to the browser's Windows voices.
"""

from __future__ import annotations

import io
import pathlib
import sys
import threading
import urllib.request
import wave
from collections import OrderedDict

from .library import home

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"
DEFAULT_VOICE = "af_heart"
MAX_CHARS = 600

# Kokoro voice ids: first letter = accent (a American, b British), second = f / m.
_ACCENTS = {"a": ("US", "en-us"), "b": ("UK", "en-gb")}

_lock = threading.Lock()
_engine = None
_cache: OrderedDict[tuple, bytes] = OrderedDict()


class Unavailable(RuntimeError):
    """Kokoro isn't installed or its model hasn't been downloaded."""


def model_dir() -> pathlib.Path:
    return home() / "kokoro"


def _load():
    global _engine
    if _engine is None:
        model, voices = model_dir() / MODEL_FILE, model_dir() / VOICES_FILE
        if not (model.exists() and voices.exists()):
            raise Unavailable(f"Kokoro model not found in {model_dir()}; run: python -m midi_coach.tts")
        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise Unavailable("kokoro-onnx is not installed (pip install kokoro-onnx)") from exc
        _engine = Kokoro(str(model), str(voices))
    return _engine


def voices() -> list[dict]:
    """English voices as [{id, label}], best first; [] when Kokoro isn't set up."""
    try:
        with _lock:
            ids = _load().get_voices()
    except Unavailable:
        return []
    out = []
    for vid in sorted(ids, key=lambda v: (v != DEFAULT_VOICE, v)):
        accent = _ACCENTS.get(vid[:1])
        if not accent or "_" not in vid:
            continue
        gender = "female" if vid[1:2] == "f" else "male"
        out.append({"id": vid, "label": f"{vid.split('_', 1)[1].title()} ({accent[0]} {gender})"})
    return out


def warm_up() -> None:
    """Run one short synthesis in the background; the first one is several times slower."""
    def run() -> None:
        try:
            speak_wav("Ready.")
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


def speak_wav(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> bytes:
    """Synthesize text to a 16-bit mono WAV. Recent phrases are cached."""
    text = " ".join(text.split())[:MAX_CHARS]
    if not text:
        raise ValueError("Nothing to say.")
    speed = min(2.0, max(0.5, speed))
    key = (text, voice, round(speed, 2))
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        engine = _load()
        if voice not in engine.get_voices():
            voice = DEFAULT_VOICE
        lang = _ACCENTS.get(voice[:1], _ACCENTS["a"])[1]
        samples, rate = engine.create(text, voice=voice, speed=speed, lang=lang)
        wav = _to_wav(samples, rate)
        _cache[key] = wav
        if len(_cache) > 64:
            _cache.popitem(last=False)
        return wav


def _to_wav(samples, rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def download() -> None:
    model_dir().mkdir(parents=True, exist_ok=True)
    for name in (VOICES_FILE, MODEL_FILE):
        dest = model_dir() / name
        if dest.exists():
            print(f"  {name}: already downloaded")
            continue
        print(f"  downloading {name} ...", flush=True)
        part = dest.with_suffix(dest.suffix + ".part")
        urllib.request.urlretrieve(RELEASE + name, part)
        part.replace(dest)
    print(f"  model ready in {model_dir()}")


def main(argv: list[str]) -> None:
    if not argv:
        download()
    text = argv[0] if argv else "Hi! I'm your piano coach. Nice work on that last pass."
    voice = argv[1] if len(argv) > 1 else DEFAULT_VOICE
    out = model_dir() / "test.wav"
    out.write_bytes(speak_wav(text, voice))
    print(f"  wrote {out}")
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(str(out), winsound.SND_FILENAME)


if __name__ == "__main__":
    main(sys.argv[1:])
