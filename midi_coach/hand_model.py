"""Which hand plays each note, from a trained model: PM2S's hand-part network (Liu, Kong,
Morfi & Benetos, ISMIR 2022; MIT licence), run with onnxruntime.

    .venv\\Scripts\\python -m midi_coach.hand_model           check the model is installed and working

The model is kept in %USERPROFILE%\\MidiCoach\\models\\pm2s_hand_part.onnx (or the file named
by MIDI_COACH_HAND_MODEL; set it to "off" to not use one). It is built once from PM2S's
published weights with tools/export_pm2s_hand.py, which needs PyTorch in a separate,
throwaway environment - the coach itself only needs onnxruntime. Without the model,
notes.split_hands splits by its search alone.

The model's chances steer that search (notes.split_by_reach) rather than decide on their own:
the model knows nothing of how far a hand reaches. Together they put about 93% of the
reference library's two-track piano notes in the right hand, with seven bars in ten clean,
against 90% and one in two for the search alone (tools/hand_split_bench.py).
"""

from __future__ import annotations

import os
import pathlib
import sys
import threading

from .library import home

MODEL_FILE = "pm2s_hand_part.onnx"
NAME = "pm2s"  # goes into cache keys, so sheets split another way are rebuilt
PITCHES, GAPS = 128, 401  # one-hot pitch; onset gap since the previous note, 10 ms steps up to 4 s
FEATURES = PITCHES + GAPS + 2  # + duration (s) + velocity / 127
WINDOW = 500  # notes per pass: the length the model was trained on
MARGIN = 50  # notes at each end of a window are read from the window that has them in the middle
BATCH = 16  # windows per run

_lock = threading.Lock()
_sessions: dict[str, object] = {}


def model_path() -> pathlib.Path | None:
    """The model file to use, or None when it's switched off."""
    chosen = os.environ.get("MIDI_COACH_HAND_MODEL", "").strip()
    if chosen.lower() in ("off", "none", "0", "false"):
        return None
    return pathlib.Path(chosen) if chosen else home() / "models" / MODEL_FILE


def _session():
    path = model_path()
    if path is None or not path.exists():
        return None
    key = str(path.resolve())
    with _lock:
        if key not in _sessions:
            try:
                import onnxruntime as ort
            except ImportError:
                return None
            _sessions[key] = ort.InferenceSession(key, providers=["CPUExecutionProvider"])
        return _sessions[key]


def available() -> bool:
    return _session() is not None


def splitter() -> str:
    """'pm2s' when the model will be used, else 'reach' (notes.split_by_reach)."""
    return NAME if available() else "reach"


def predict(notes) -> dict[tuple[float, int], str] | None:
    """{(start rounded to 4 places, pitch): 'right' | 'left'} for the notes, the model's guess
    alone, or None when the model or onnxruntime isn't there."""
    left = left_odds(notes)
    return None if left is None else {k: "left" if p > 0.5 else "right" for k, p in left.items()}


def left_odds(notes) -> dict[tuple[float, int], float] | None:
    """{(start rounded to 4 places, pitch): chance the left hand plays it} for the notes, or
    None when the model or onnxruntime isn't there. Long pieces go through in overlapping
    windows of the length the model was trained on, batched, so a 30,000-note piece takes
    seconds."""
    session = _session()
    if session is None:
        return None
    if not notes:
        return {}
    import numpy as np

    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))  # the model's training order
    count = len(ordered)
    starts = np.array([n.start for n in ordered])
    features = np.zeros((count, FEATURES), np.float32)
    rows = np.arange(count)
    features[rows, [n.pitch for n in ordered]] = 1
    gaps = np.clip(np.diff(starts, prepend=starts[0]), 0, 4)
    features[rows, PITCHES + np.round(gaps / 0.01).astype(int)] = 1
    features[:, PITCHES + GAPS] = [n.end - n.start for n in ordered]
    features[:, PITCHES + GAPS + 1] = [n.velocity / 127 for n in ordered]

    # Windows of WINDOW notes, each one's middle kept: [first, keep_from, keep_to).
    step = WINDOW - 2 * MARGIN
    windows = []
    first = 0
    while True:
        last = min(first + WINDOW, count)
        first = max(0, last - WINDOW)
        windows.append((first, 0 if first == 0 else first + MARGIN, count if last == count else last - MARGIN))
        if last == count:
            break
        first += step
    left = np.zeros(count, np.float32)
    for b in range(0, len(windows), BATCH):
        group = windows[b:b + BATCH]
        size = min(WINDOW, count)
        batch = np.stack([features[f:f + size] for f, _, _ in group])
        out = session.run(None, {"features": batch})[0]
        for (f, keep_from, keep_to), probs in zip(group, out):
            left[keep_from:keep_to] = probs[keep_from - f:keep_to - f]
    # The model's 1 is the second track of its training files, the left hand (its own
    # docstring says the opposite; its training code labels each note by track number).
    return {(round(n.start, 4), n.pitch): float(p) for n, p in zip(ordered, left)}


if __name__ == "__main__":
    from .notes import Note

    path = model_path()
    if not available():
        sys.exit(f"No hand model at {path}. Build it with tools/export_pm2s_hand.py (see its docstring).")
    tune = [Note(76 + i % 5, i * 0.25, i * 0.25 + 0.2, 80) for i in range(16)]
    bass = [Note(40 + i % 3 * 5, i * 1.0, i * 1.0 + 0.9, 70) for i in range(4)]
    sides = predict(tune + bass)
    right = sum(sides[(round(n.start, 4), n.pitch)] == "right" for n in tune)
    left = sum(sides[(round(n.start, 4), n.pitch)] == "left" for n in bass)
    print(f"{path}: tune {right}/{len(tune)} right hand, bass {left}/{len(bass)} left hand")
