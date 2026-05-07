"""Push-to-talk voice controller for theme selection in Voice Play mode.

Hold SPACE to record, release to stop.  The captured audio is sent to
speech-to-text and the transcript is returned via an on_transcript callback.

Dependencies (install once):
    pip install vosk SpeechRecognition pyaudio
"""

from __future__ import annotations

import json
import pathlib
import threading
import time


class VoiceState:
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    MATCHED = "matched"
    NO_MATCH = "no_match"


class VoiceController:
    """Records audio on push-to-talk keypress and returns STT transcripts.

    Parameters
    ----------
    on_transcript:
        Called from a background thread with the lower-cased STT string, or
        ``None`` when recognition failed / nothing was heard.
    """

    _RESULT_DISPLAY_SECS: float = 3.0
    _MAX_RECORD_SECS: int = 6
    _SAMPLE_RATE: int = 16_000
    _CHUNK_FRAMES: int = 1_024

    def __init__(
        self,
        on_transcript,
        input_device_index: int = -1,
        stt_backend: str = "vosk",
        vosk_model_path: str = "",
        allow_google_fallback: bool = True,
        max_record_secs: float = 6.0,
        result_display_secs: float = 3.0,
    ) -> None:
        self._on_transcript = on_transcript
        self._input_device_index = int(input_device_index)
        self._stt_backend = str(stt_backend).strip().lower() or "vosk"
        self._vosk_model_path = str(vosk_model_path).strip()
        self._allow_google_fallback = bool(allow_google_fallback)
        self._max_record_secs = max(0.3, float(max_record_secs))
        self._result_display_secs = max(0.15, float(result_display_secs))
        self._vosk_model = None
        self._state = VoiceState.IDLE
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_text: str = ""
        self._last_hardware_error: str = ""
        self._result_at: float = 0.0
        self._active_sample_rate: int = self._SAMPLE_RATE

    # ------------------------------------------------------------------
    # Public interface (called from the pygame main thread)
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def last_hardware_error(self) -> str:
        return self._last_hardware_error

    def start_recording(self) -> bool:
        """Begin recording.  Returns False if already busy."""
        with self._lock:
            if self._state != VoiceState.IDLE:
                return False
            self._state = VoiceState.RECORDING
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        return True

    def stop_recording(self) -> None:
        """Signal the recording thread to stop capturing and start processing."""
        with self._lock:
            if self._state == VoiceState.RECORDING:
                self._stop_event.set()

    def tick(self) -> None:
        """Call once per frame; resets MATCHED/NO_MATCH after display timeout."""
        with self._lock:
            if self._state in (VoiceState.MATCHED, VoiceState.NO_MATCH):
                if time.monotonic() - self._result_at > self._result_display_secs:
                    self._state = VoiceState.IDLE

    def stop(self) -> None:
        """Shut down cleanly when leaving Voice Play mode."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Worker (runs on a daemon thread)
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        try:
            frames = self._record_frames()
            self._last_hardware_error = ""
        except Exception as exc:
            self._last_hardware_error = str(exc).strip() or "mic unavailable"
            self._finish(VoiceState.NO_MATCH, "")
            return

        if not frames:
            self._finish(VoiceState.NO_MATCH, "")
            return

        with self._lock:
            if self._state == VoiceState.RECORDING:
                self._state = VoiceState.PROCESSING

        text = self._transcribe(frames)
        if text:
            self._finish(VoiceState.MATCHED, text)
            self._on_transcript(text)
        else:
            self._finish(VoiceState.NO_MATCH, "")
            self._on_transcript(None)

    def _record_frames(self) -> list[bytes]:
        import pyaudio  # noqa: PLC0415

        pa = pyaudio.PyAudio()
        stream, sample_rate, channels, device_index = self._open_input_stream_with_fallback(pa)
        self._active_sample_rate = sample_rate
        frames: list[bytes] = []
        max_chunks = int(sample_rate / self._CHUNK_FRAMES * self._max_record_secs)
        try:
            for _ in range(max_chunks):
                if self._stop_event.is_set():
                    break
                frames.append(stream.read(self._CHUNK_FRAMES, exception_on_overflow=False))
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
        return frames

    def _transcribe(self, frames: list[bytes]) -> str | None:
        backend = self._stt_backend
        if backend == "google":
            return self._transcribe_google(frames)

        text = self._transcribe_vosk(frames)
        if text:
            return text

        if self._allow_google_fallback:
            return self._transcribe_google(frames)
        return None

    def _transcribe_google(self, frames: list[bytes]) -> str | None:
        import speech_recognition as sr  # noqa: PLC0415

        raw = b"".join(frames)
        audio = sr.AudioData(raw, self._active_sample_rate, 2)  # 2 bytes = paInt16
        try:
            return sr.Recognizer().recognize_google(audio).lower()
        except sr.UnknownValueError:
            return None
        except Exception:
            return None

    def _transcribe_vosk(self, frames: list[bytes]) -> str | None:
        model = self._get_vosk_model()
        if model is None:
            return None

        try:
            from vosk import KaldiRecognizer  # noqa: PLC0415
        except Exception:
            return None

        recognizer = KaldiRecognizer(model, float(self._active_sample_rate))
        recognizer.SetWords(False)
        for chunk in frames:
            recognizer.AcceptWaveform(chunk)

        try:
            result = json.loads(recognizer.FinalResult())
        except Exception:
            return None
        text = str(result.get("text", "")).strip().lower()
        return text or None

    def _resolve_vosk_model_dir(self) -> pathlib.Path | None:
        candidates: list[pathlib.Path] = []
        if self._vosk_model_path:
            candidates.append(pathlib.Path(self._vosk_model_path))

        root = pathlib.Path(__file__).resolve().parent.parent
        candidates.extend(
            [
                root / "models" / "vosk-model-small-en-us-0.15",
                root / "models" / "vosk-model-en-us-0.22",
                root / "vosk-model-small-en-us-0.15",
                root / "vosk-model-en-us-0.22",
            ]
        )

        for path in candidates:
            try:
                resolved = path.expanduser().resolve()
            except Exception:
                resolved = path
            if resolved.exists() and resolved.is_dir():
                return resolved
        return None

    def _get_vosk_model(self):
        if self._vosk_model is not None:
            return self._vosk_model

        model_dir = self._resolve_vosk_model_dir()
        if model_dir is None:
            return None

        try:
            from vosk import Model, SetLogLevel  # noqa: PLC0415

            SetLogLevel(-1)
            self._vosk_model = Model(str(model_dir))
            return self._vosk_model
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_input_config(self, pa: object) -> tuple[int, int, int | None]:
        sample_rate = self._SAMPLE_RATE
        channels = 1
        device_index: int | None = self._input_device_index if self._input_device_index >= 0 else None

        try:
            if device_index is not None:
                info = pa.get_device_info_by_index(device_index)
            else:
                info = pa.get_default_input_device_info()
                resolved_idx = int(info.get("index", -1))
                device_index = resolved_idx if resolved_idx >= 0 else None
            sample_rate = int(float(info.get("defaultSampleRate", sample_rate)))
            channels = max(1, min(int(info.get("maxInputChannels", 1) or 1), 2))
        except Exception:
            sample_rate = self._SAMPLE_RATE
            channels = 1

        return sample_rate, channels, device_index

    def _build_candidate_input_indices(self, pa: object, preferred_index: int | None) -> list[int]:
        host_priority = {
            "windows wasapi": 0,
            "windows wdm-ks": 1,
            "windows directsound": 2,
            "mme": 3,
        }
        virtual_markers = (
            "voicemeeter",
            "cable",
            "vb-audio",
            "stereo mix",
            "mapper",
            "virtual",
        )

        def _tokens(name: str) -> set[str]:
            cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in name)
            words = {w for w in cleaned.split() if len(w) >= 4}
            return words - {"input", "output", "audio", "device", "point", "windows"}

        def _name_penalty(name: str) -> int:
            n = name.lower()
            if any(k in n for k in ("microphone", "mic", "array")):
                return 0
            if "input" in n:
                return 1
            if any(k in n for k in virtual_markers):
                return 4
            return 2

        preferred_name = ""
        preferred_tokens: set[str] = set()
        preferred_is_virtual = False
        if preferred_index is not None:
            try:
                pinfo = pa.get_device_info_by_index(preferred_index)
                preferred_name = str(pinfo.get("name", "")).strip().lower()
                preferred_tokens = _tokens(preferred_name)
                preferred_is_virtual = any(m in preferred_name for m in virtual_markers)
            except Exception:
                preferred_name = ""
                preferred_tokens = set()
                preferred_is_virtual = False

        host_names: dict[int, str] = {}
        try:
            for host_idx in range(pa.get_host_api_count()):
                try:
                    host_names[host_idx] = str(pa.get_host_api_info_by_index(host_idx).get("name", ""))
                except Exception:
                    host_names[host_idx] = ""
        except Exception:
            pass

        candidates: list[tuple[int, int]] = []
        try:
            for idx in range(int(pa.get_device_count())):
                try:
                    info = pa.get_device_info_by_index(idx)
                except Exception:
                    continue
                max_in = int(info.get("maxInputChannels", 0) or 0)
                if max_in <= 0:
                    continue

                host_idx = int(info.get("hostApi", -1))
                host_name = host_names.get(host_idx, "").strip().lower()
                host_score = host_priority.get(host_name, 5)
                name = str(info.get("name", "")).strip().lower()
                tokens = _tokens(name)
                overlap = len(tokens & preferred_tokens) if preferred_tokens else 0
                pref_bonus = -1000 if preferred_index is not None and idx == preferred_index else 0
                name_family_bonus = -220 if overlap > 0 else 0
                if preferred_name and (name in preferred_name or preferred_name in name):
                    name_family_bonus -= 120
                virtual_penalty = 0
                if any(m in name for m in virtual_markers) and not preferred_is_virtual:
                    virtual_penalty = 300
                penalty = _name_penalty(str(info.get("name", "")))
                score = (host_score * 10) + penalty + pref_bonus + name_family_bonus + virtual_penalty
                candidates.append((score, idx))
        except Exception:
            pass

        candidates.sort(key=lambda item: item[0])
        ordered: list[int] = [idx for _score, idx in candidates]
        if preferred_index is not None and preferred_index not in ordered:
            ordered.insert(0, preferred_index)
        return ordered[:20]

    def _open_input_stream_with_fallback(self, pa: object) -> tuple[object, int, int, int | None]:
        try:
            import pyaudio  # noqa: PLC0415
        except Exception as exc:
            raise RuntimeError("PyAudio missing") from exc

        default_rate, _default_channels, preferred_index = self._resolve_input_config(pa)
        candidate_indices = self._build_candidate_input_indices(pa, preferred_index)
        last_error = ""

        for candidate_index in candidate_indices:
            try:
                info = pa.get_device_info_by_index(candidate_index)
                resolved_index = int(info.get("index", -1))
                if resolved_index < 0:
                    continue
                max_in = int(info.get("maxInputChannels", 0) or 0)
                if max_in <= 0:
                    continue

                channel_candidates = [1]
                if max_in >= 2:
                    channel_candidates.append(2)

                rate_candidates: list[int] = []
                for rate in (int(float(info.get("defaultSampleRate", default_rate))), default_rate, 48_000, 44_100, 16_000):
                    if rate > 0 and rate not in rate_candidates:
                        rate_candidates.append(rate)

                for channels in channel_candidates:
                    for rate in rate_candidates:
                        try:
                            stream = pa.open(
                                format=pyaudio.paInt16,
                                channels=channels,
                                rate=rate,
                                input=True,
                                input_device_index=resolved_index,
                                frames_per_buffer=self._CHUNK_FRAMES,
                            )
                            return stream, rate, channels, resolved_index
                        except Exception as exc:
                            last_error = str(exc).strip() or "cannot open input format"
            except Exception as exc:
                last_error = str(exc).strip() or "cannot inspect selected input device"

        raise RuntimeError(last_error or "device busy or unavailable")

    def _finish(self, new_state: str, text: str) -> None:
        self.last_text = text
        self._result_at = time.monotonic()
        with self._lock:
            self._state = new_state
