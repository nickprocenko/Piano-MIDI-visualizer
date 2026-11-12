"""Tune in to an internet radio station: decode it into a buffer the page plays from and the
aligner listens to, and notice the song titles it sends along with the audio.

Most stations are Icecast/SHOUTcast streams (MP3 or AAC) that send 'StreamTitle' every few
kilobytes when asked (the ICY protocol); those are read here and the title is cut out of the
audio. HLS stations (CBC, some others) are handed to PyAV whole. Either way the audio becomes
44.1 kHz stereo 16-bit in a ring buffer about seven minutes long; a sample's index in it (from
the moment of tuning in) is the clock everything else uses: stream seconds = index / SR.
"""

from __future__ import annotations

import io
import logging
import re
import secrets
import threading
import time
import urllib.request
from typing import Callable

import av
import numpy as np

log = logging.getLogger("radio_hands.tuner")

SR = 44100
CHANNELS = 2
RING_SEC = 420
USER_AGENT = "RadioHands/0.1 (personal piano practice)"
TIMEOUT_SEC = 15
FORMATS = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/aac": "aac", "audio/aacp": "aac",
           "audio/x-aac": "aac", "audio/ogg": "ogg", "application/ogg": "ogg", "audio/opus": "ogg"}
PLAYLISTS = ("audio/x-mpegurl", "audio/mpegurl", "application/vnd.apple.mpegurl", "application/x-mpegurl",
             "audio/x-scpls", "application/pls+xml", "text/html", "text/plain", "video/x-ms-asf", "audio/x-ms-wax")


class Ring:
    """The decoded audio: int16 stereo, written by the tuner, read by the page and the aligner."""

    def __init__(self, seconds: int = RING_SEC):
        self.cap = SR * seconds
        self.buf = np.zeros((self.cap, CHANNELS), np.int16)
        self.total = 0  # samples written since tuning in
        self.cond = threading.Condition()
        self.closed = False

    def write(self, frames: np.ndarray) -> None:
        frames = frames[-self.cap:]
        n = len(frames)
        with self.cond:
            i = self.total % self.cap
            first = min(n, self.cap - i)
            self.buf[i:i + first] = frames[:first]
            if first < n:
                self.buf[:n - first] = frames[first:]
            self.total += n
            self.cond.notify_all()

    @property
    def oldest(self) -> int:
        return max(0, self.total - self.cap)

    def read(self, start: int, most: int, wait: float = 0.0) -> tuple[int, np.ndarray]:
        """(where the samples start, up to `most` samples from `start`), waiting up to `wait`
        seconds for some to arrive. Samples already overwritten are skipped."""
        with self.cond:
            if wait and start >= self.total and not self.closed:
                self.cond.wait(wait)
            start = max(start, self.oldest)
            end = min(self.total, start + most)
            if end <= start:
                return start, np.zeros((0, CHANNELS), np.int16)
            a, b = start % self.cap, end % self.cap
            if a < b:
                out = self.buf[a:b].copy()
            else:
                out = np.concatenate([self.buf[a:], self.buf[:b]])
            return start, out

    def close(self) -> None:
        with self.cond:
            self.closed = True
            self.cond.notify_all()


class IcyReader(io.RawIOBase):
    """The audio of an ICY stream with the metadata blocks cut out; titles go to on_title."""

    def __init__(self, response, metaint: int, on_title: Callable[[str], None]):
        self.r = response
        self.metaint = metaint
        self.left = metaint  # audio bytes before the next metadata block
        self.on_title = on_title

    def readable(self) -> bool:
        return True

    def _read_exact(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = self.r.read(n - len(out))
            if not chunk:
                raise EOFError("the station stopped sending")
            out += chunk
        return out

    def readinto(self, b) -> int:
        if self.metaint and self.left == 0:
            size = self._read_exact(1)[0] * 16
            if size:
                text = self._read_exact(size).rstrip(b"\0").decode("utf-8", "replace")
                m = re.search(r"StreamTitle='(.*?)';", text, re.S)
                if m:
                    self.on_title(m.group(1))
            self.left = self.metaint
        want = len(b) if not self.metaint else min(len(b), self.left)
        data = self.r.read(want)
        if not data:
            return 0
        b[:len(data)] = data
        if self.metaint:
            self.left -= len(data)
        return len(data)


def _playlist_urls(text: str) -> list[str]:
    return re.findall(r"(https?://[^\s\"'<>]+)", text)


class Tuner:
    """One station, playing until stop(). Titles and status changes are reported through the
    callbacks as (stream seconds, text)."""

    def __init__(self, url: str, on_title: Callable[[float, str], None], on_status: Callable[[str, str], None]):
        self.url = url
        self.session = secrets.token_hex(4)
        self.ring = Ring()
        self.on_title = on_title
        self.on_status = on_status
        self.stopping = False
        self.title: str | None = None
        self.name: str | None = None   # the station's own name (icy-name)
        self.codec: str | None = None
        self.metadata = False          # the station sends titles
        self._response = None
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"tuner-{self.session}")

    def start(self) -> "Tuner":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.stopping = True
        try:
            if self._response is not None:
                self._response.close()
        except Exception:  # noqa: BLE001 - closing a stream another thread reads may complain
            pass
        self.ring.close()

    @property
    def live(self) -> float:
        """Stream seconds decoded so far (the live edge)."""
        return self.ring.total / SR

    def _title(self, text: str) -> None:
        self.metadata = True
        text = text.strip()
        if text != self.title:
            self.title = text
            self.on_title(self.live, text)

    def _run(self) -> None:
        delay = 1.0
        while not self.stopping:
            started = time.time()
            try:
                self.on_status("connecting", "")
                self._play(self.url, depth=0)
                if not self.stopping:
                    raise EOFError("the station stopped sending")
            except Exception as exc:  # noqa: BLE001 - any failure: say so, wait, try again
                if self.stopping:
                    break
                log.info("tuner %s: %s", self.url, exc)
                self.on_status("retrying", _plain(exc))
                if time.time() - started > 30:
                    delay = 1.0
                time.sleep(delay)
                delay = min(30.0, delay * 2)
        self.on_status("stopped", "")

    def _play(self, url: str, depth: int) -> None:
        if url.lower().split("?")[0].endswith(".m3u8"):
            return self._decode(av.open(url, timeout=TIMEOUT_SEC))
        req = urllib.request.Request(url, headers={"Icy-MetaData": "1", "User-Agent": USER_AGENT})
        res = urllib.request.urlopen(req, timeout=TIMEOUT_SEC)
        self._response = res
        kind = (res.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        self.name = res.headers.get("icy-name") or self.name
        if kind in PLAYLISTS or (not kind.startswith("audio") and kind not in FORMATS):
            text = res.read(65536).decode("utf-8", "replace")
            res.close()
            if "#EXT-X-" in text:  # an HLS playlist without the .m3u8 name
                return self._decode(av.open(url, timeout=TIMEOUT_SEC))
            urls = _playlist_urls(text)
            if not urls or depth > 2:
                raise ValueError("this link isn't an audio stream")
            return self._play(urls[0], depth + 1)
        metaint = int(res.headers.get("icy-metaint") or 0)
        reader = io.BufferedReader(IcyReader(res, metaint, self._title), buffer_size=16384)
        self._decode(av.open(reader, format=FORMATS.get(kind)))

    def _decode(self, container) -> None:
        try:
            stream = container.streams.audio[0]
            self.codec = stream.codec_context.name
            resampler = av.AudioResampler(format="s16", layout="stereo", rate=SR)
            self.on_status("playing", "")
            for frame in container.decode(stream):
                if self.stopping:
                    return
                for out in resampler.resample(frame):
                    self.ring.write(out.to_ndarray().reshape(-1, CHANNELS))
                if container.metadata.get("StreamTitle"):  # HLS / ffmpeg's own ICY reading
                    self._title(container.metadata["StreamTitle"])
        finally:
            container.close()


def _plain(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    if "timed out" in text.lower():
        return "The station isn't answering."
    if "404" in text or "Not Found" in text:
        return "The station's link doesn't work any more."
    if "stopped sending" in text:
        return "The station stopped sending. Trying again."
    return text[:160]
