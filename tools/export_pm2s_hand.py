"""Build the hand model midi_coach uses (midi_coach/hand_model.py): PM2S's hand-part network,
exported from its published PyTorch weights to ONNX so the coach runs it on onnxruntime.

PyTorch is needed only for this, once, and never by the coach: run it in a separate,
throwaway environment, not the repo's .venv.

    uv venv --python 3.12 %TEMP%\\pm2s-env
    uv pip install --python %TEMP%\\pm2s-env\\Scripts\\python.exe torch --index-url https://download.pytorch.org/whl/cpu
    uv pip install --python %TEMP%\\pm2s-env\\Scripts\\python.exe onnx onnxscript onnxruntime numpy
    git clone --depth 1 https://github.com/cheriell/PM2S.git %TEMP%\\PM2S
    curl -L -o %TEMP%\\RNNHandPartModel.pth "https://zenodo.org/records/10520196/files/RNNHandPartModel.pth?download=1"
    %TEMP%\\pm2s-env\\Scripts\\python.exe tools\\export_pm2s_hand.py %TEMP%\\PM2S %TEMP%\\RNNHandPartModel.pth

The model is written to %USERPROFILE%\\MidiCoach\\models\\pm2s_hand_part.onnx (or MIDI_COACH_HOME\\models,
or the path given with --out), about 41 MB. The export checks itself against PyTorch before
it's written. Then `.venv\\Scripts\\python -m midi_coach.hand_model` checks it from the coach's side.

PM2S: Liu, Kong, Morfi & Benetos, "Performance MIDI-to-score conversion by neural beat
tracking", ISMIR 2022 (https://github.com/cheriell/PM2S, MIT licence).
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import types

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("pm2s", type=pathlib.Path, help="a checkout of github.com/cheriell/PM2S")
ap.add_argument("weights", type=pathlib.Path, help="RNNHandPartModel.pth from PM2S's Zenodo record")
ap.add_argument("--out", type=pathlib.Path, help="where to write the .onnx (default: <MIDI_COACH_HOME>/models)")
args = ap.parse_args()
out = args.out or pathlib.Path(os.environ.get("MIDI_COACH_HOME") or pathlib.Path.home() / "MidiCoach") / "models" / "pm2s_hand_part.onnx"

import numpy as np  # noqa: E402
import torch  # noqa: E402

# Only the model classes: pm2s/__init__.py would import the whole toolbox (pandas, pretty_midi...).
package = types.ModuleType("pm2s")
package.__path__ = [str(args.pm2s / "pm2s")]
sys.modules["pm2s"] = package
from pm2s.models.hand_part import RNNHandPartModel  # noqa: E402


class Network(torch.nn.Module):
    """RNNHandPartModel.forward without its note encoding, which hand_model.py does in numpy."""

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, features):  # (windows, notes, 531) -> (windows, notes): left-hand probability
        x = self.model.convs(features)
        x = self.model.gru(x)
        return self.model.out(x).squeeze(-1)


def encode(seq: np.ndarray) -> np.ndarray:
    """(notes, 4) of pitch, onset, duration, velocity -> (notes, 531), as hand_model.py does it."""
    n = len(seq)
    features = np.zeros((n, 531), np.float32)
    features[np.arange(n), seq[:, 0].astype(int)] = 1
    gaps = np.clip(np.diff(seq[:, 1], prepend=seq[0, 1]), 0, 4)
    features[np.arange(n), 128 + np.round(gaps / 0.01).astype(int)] = 1
    features[:, 529] = seq[:, 2]
    features[:, 530] = seq[:, 3] / 127
    return features


model = RNNHandPartModel()
model.load_state_dict(torch.load(args.weights, map_location="cpu", weights_only=True))
model.eval()
network = Network(model).eval()

rng = np.random.default_rng(0)
seq = np.stack([rng.integers(30, 96, 300), np.cumsum(rng.uniform(0, 0.4, 300)), rng.uniform(0.05, 2, 300), rng.integers(30, 110, 300)], axis=1)
with torch.no_grad():
    reference = model(torch.tensor(seq).unsqueeze(0)).numpy()
    sample = torch.tensor(encode(seq)).unsqueeze(0)
    assert np.abs(network(sample).numpy() - reference).max() < 1e-5, "the numpy note encoding doesn't match PM2S's"

out.parent.mkdir(parents=True, exist_ok=True)
torch.onnx.export(network, (sample,), str(out), input_names=["features"], output_names=["left"],
                  dynamic_axes={"features": {0: "windows", 1: "notes"}, "left": {0: "windows", 1: "notes"}},
                  opset_version=17, dynamo=False)

import onnxruntime  # noqa: E402

session = onnxruntime.InferenceSession(str(out), providers=["CPUExecutionProvider"])
short = seq[:137]
with torch.no_grad():
    reference = model(torch.tensor(short).unsqueeze(0)).numpy()
error = np.abs(session.run(None, {"features": encode(short)[None]})[0] - reference).max()
if error > 1e-4:
    out.unlink()
    sys.exit(f"the ONNX model differs from PyTorch by {error}; not kept")
print(f"wrote {out} ({out.stat().st_size // 1024} KB); matches PyTorch to {error:.1e}")
