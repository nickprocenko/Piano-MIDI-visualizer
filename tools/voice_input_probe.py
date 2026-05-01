"""Quick CLI probe for microphone capture and speech recognition.

Usage examples:
  python tools/voice_input_probe.py --seconds 6
  python tools/voice_input_probe.py --device 26 --backend google --save-wav probe.wav
  python tools/voice_input_probe.py --list-devices
"""

from __future__ import annotations

import argparse
import array
import json
import math
import pathlib
import statistics
import wave

import pyaudio


def _load_selected_device() -> int:
    cfg_path = pathlib.Path(__file__).resolve().parents[1] / "config.json"
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        return int(((data.get("audio_settings") or {}).get("selected_input_device", -1)))
    except Exception:
        return -1


def _list_input_devices(pa: pyaudio.PyAudio) -> None:
    print("Input devices:")
    for idx in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(idx)
        max_in = int(info.get("maxInputChannels", 0) or 0)
        if max_in <= 0:
            continue
        name = str(info.get("name", "Unknown"))
        host = int(info.get("hostApi", -1))
        rate = int(float(info.get("defaultSampleRate", 0) or 0))
        print(f"  [{idx}] {name} | hostApi={host} | defaultRate={rate} | maxIn={max_in}")


def _capture_audio(
    pa: pyaudio.PyAudio,
    device_index: int | None,
    seconds: float,
    chunk_frames: int = 1024,
) -> tuple[bytes, int, int, int, list[int], list[float]]:
    if device_index is not None and device_index >= 0:
        info = pa.get_device_info_by_index(device_index)
    else:
        info = pa.get_default_input_device_info()

    idx = int(info.get("index", -1))
    sample_rate = int(float(info.get("defaultSampleRate", 16_000) or 16_000))
    channels = max(1, min(int(info.get("maxInputChannels", 1) or 1), 2))

    print(f"\nCapturing [{idx}] {info.get('name')} @ {sample_rate}Hz {channels}ch for {seconds:.1f}s")

    stream = pa.open(
        format=pyaudio.paInt16,
        channels=channels,
        rate=sample_rate,
        input=True,
        input_device_index=idx,
        frames_per_buffer=chunk_frames,
    )

    loops = max(1, int(sample_rate / chunk_frames * seconds))
    chunks: list[bytes] = []
    peaks: list[int] = []
    rms_values: list[float] = []
    try:
        for _ in range(loops):
            raw = stream.read(chunk_frames, exception_on_overflow=False)
            chunks.append(raw)

            samples = array.array("h")
            samples.frombytes(raw)
            if not samples:
                peaks.append(0)
                rms_values.append(0.0)
                continue

            peak = max(abs(v) for v in samples)
            mean_sq = sum(v * v for v in samples) / len(samples)
            rms = math.sqrt(mean_sq)
            peaks.append(peak)
            rms_values.append(rms)
    finally:
        stream.stop_stream()
        stream.close()

    return b"".join(chunks), sample_rate, channels, idx, peaks, rms_values


def _recognize_google(raw: bytes, sample_rate: int) -> str | None:
    try:
        import speech_recognition as sr
    except Exception as exc:
        return f"Google backend unavailable: {exc}"

    recognizer = sr.Recognizer()
    audio = sr.AudioData(raw, sample_rate, 2)
    try:
        return recognizer.recognize_google(audio).strip()
    except sr.UnknownValueError:
        return None
    except Exception as exc:
        return f"Google error: {exc}"


def _recognize_vosk(raw: bytes, sample_rate: int, model_path: str) -> str | None:
    try:
        from vosk import KaldiRecognizer, Model, SetLogLevel
    except Exception as exc:
        return f"Vosk backend unavailable: {exc}"

    candidates: list[pathlib.Path] = []
    if model_path:
        candidates.append(pathlib.Path(model_path))

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    candidates.extend(
        [
            repo_root / "models" / "vosk-model-small-en-us-0.15",
            repo_root / "models" / "vosk-model-en-us-0.22",
            repo_root / "vosk-model-small-en-us-0.15",
            repo_root / "vosk-model-en-us-0.22",
        ]
    )

    model_dir: pathlib.Path | None = None
    for p in candidates:
        try:
            r = p.expanduser().resolve()
        except Exception:
            r = p
        if r.exists() and r.is_dir():
            model_dir = r
            break

    if model_dir is None:
        return "Vosk model not found"

    try:
        SetLogLevel(-1)
        model = Model(str(model_dir))
        recognizer = KaldiRecognizer(model, float(sample_rate))
        recognizer.SetWords(False)
        recognizer.AcceptWaveform(raw)
        result = json.loads(recognizer.FinalResult())
        text = str(result.get("text", "")).strip()
        return text or None
    except Exception as exc:
        return f"Vosk error: {exc}"


def _save_wav(path: pathlib.Path, raw: bytes, sample_rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe microphone input and STT output")
    parser.add_argument("--device", type=int, default=None, help="PyAudio input device index")
    parser.add_argument("--seconds", type=float, default=5.0, help="Capture duration")
    parser.add_argument(
        "--backend",
        choices=["google", "vosk", "both"],
        default="both",
        help="Which recognizer backend to test",
    )
    parser.add_argument("--vosk-model", default="", help="Path to Vosk model directory")
    parser.add_argument("--save-wav", default="", help="Optional WAV output path")
    parser.add_argument("--list-devices", action="store_true", help="List input devices and exit")
    args = parser.parse_args()

    pa = pyaudio.PyAudio()
    try:
        configured = _load_selected_device()
        print(f"Configured selected_input_device: {configured}")

        if args.list_devices:
            _list_input_devices(pa)
            return 0

        target_device = args.device if args.device is not None else (configured if configured >= 0 else None)
        raw, sample_rate, channels, used_idx, peaks, rms_values = _capture_audio(pa, target_device, args.seconds)

        peak_max = max(peaks) if peaks else 0
        peak_avg = statistics.fmean(peaks) if peaks else 0.0
        rms_avg = statistics.fmean(rms_values) if rms_values else 0.0
        active_chunks = sum(1 for v in rms_values if v > 200.0)
        active_pct = (100.0 * active_chunks / len(rms_values)) if rms_values else 0.0

        print(f"Used device index: {used_idx}")
        print(f"Signal stats: peak_max={peak_max:.1f} peak_avg={peak_avg:.1f} rms_avg={rms_avg:.1f} active_chunks={active_pct:.1f}%")

        if args.save_wav:
            out = pathlib.Path(args.save_wav).expanduser().resolve()
            _save_wav(out, raw, sample_rate, channels)
            print(f"Saved capture: {out}")

        if args.backend in ("google", "both"):
            google_text = _recognize_google(raw, sample_rate)
            print(f"Google STT: {google_text!r}")

        if args.backend in ("vosk", "both"):
            vosk_text = _recognize_vosk(raw, sample_rate, args.vosk_model)
            print(f"Vosk STT: {vosk_text!r}")

        return 0
    finally:
        pa.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
