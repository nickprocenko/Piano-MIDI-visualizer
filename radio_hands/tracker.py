"""What's on the radio and where the hands are in it: the app's one piece of state.

A station's title starts a song: it is looked up in the library (and on bitmidi.com when that's
on), its notes are prepared, and the radio is lined up with the file (chroma.align) until it
fits; from then on each few seconds' fit adds an anchor (stream second -> MIDI second) that the
page plays the hands from. Alongside, the chords are always being heard (chords.ChordTracker),
so a song that isn't in the library, or that won't line up, still gets hands playing its chords.

Everything the page needs goes out through `publish` as one JSON state, twice a second.
"""

from __future__ import annotations

import json
import logging
import queue
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from midi_coach import library

from . import chords as chordmod
from . import drums as drummod
from . import chroma, songs, stations
from .tuner import SR, Tuner

log = logging.getLogger("radio_hands.tracker")

TICK_SEC = 0.25
PUBLISH_SEC = 0.5
FIRST_WINDOW = 30.0     # seconds of radio compared with the whole file to find the song's place
FOLLOW_WINDOW = 15.0    # seconds compared around where it should be, once found
FOLLOW_SPREAD = 3.0     # ± seconds looked around the expected place
TRY_EVERY = (1.0, 2.0)  # seconds between fits: before the place is found, after
LOST_AFTER = 14.0       # seconds without a good fit before the place counts as lost
JUMP = 1.5              # a fit this far (MIDI s) from the anchors is a new place, not a nudge
NO_MATCH_AFTER = 45.0   # seconds of music without a fit before saying the file doesn't match
CHORDS_SINCE = 45.0     # seconds of past chords sent to the page
HOLD_SEC = 30.0         # the chord still sounding is drawn this much longer, until the next one comes


def settings_path():
    return library.home() / "radio_hands.json"


def load_settings() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"online": bool(data.get("online", True)), "charts": bool(data.get("charts", True))}


def save_settings(s: dict) -> None:
    try:
        settings_path().parent.mkdir(parents=True, exist_ok=True)
        settings_path().write_text(json.dumps(s, indent=1), encoding="utf-8")
    except OSError:
        pass


@dataclass
class Song:
    id: str
    title: str                # what the station (or the user) said
    started: float            # stream seconds when it was said
    seen_start: bool          # the title changed while listening, so `started` is near the song's start
    source: str = ""          # library | bitmidi | chosen
    status: str = "looking"   # looking | not_found | loading | listening | synced | no_match | lost | ended | error
    message: str = ""
    match: dict | None = None
    others: list = field(default_factory=list)
    prep: dict | None = None
    midi: np.ndarray | None = None
    vocab: list = field(default_factory=list)   # the file's chords, for naming what's heard
    anchors: list = field(default_factory=list)  # [stream s, MIDI s, rate]
    good_from: float | None = None
    good_until: float | None = None
    last_try: float = -1e9
    last_good: float | None = None
    fit: dict | None = None
    chart: dict | None = None

    def midi_at(self, t: float) -> float | None:
        if not self.anchors:
            return None
        if t <= self.anchors[0][0]:
            a = self.anchors[0]
            return a[1] + a[2] * (t - a[0])
        for a, b in zip(self.anchors, self.anchors[1:]):
            if a[0] <= t <= b[0]:
                return a[1] + (b[1] - a[1]) * (t - a[0]) / (b[0] - a[0] or 1)
        a = self.anchors[-1]
        return a[1] + a[2] * (t - a[0])

    def public(self) -> dict:
        return {"id": self.id, "title": self.title, "started": round(self.started, 3), "seen_start": self.seen_start,
                "source": self.source, "status": self.status, "message": self.message, "match": self.match,
                "others": self.others, "ready": self.prep is not None, "anchors": self.anchors[-60:],
                "good_from": self.good_from, "good_until": self.good_until, "fit": self.fit,
                "duration": self.prep["duration"] if self.prep else None,
                "hand_notes": self.prep["hand_notes"] if self.prep else None, "chart": self.chart}


class Tracker:
    def __init__(self, publish):
        self.publish_cb = publish
        self.lock = threading.RLock()
        self.lib = songs.Library()
        self.settings = load_settings()
        self.tuner: Tuner | None = None
        self.station: dict | None = None
        self.status = {"state": "off", "message": ""}
        self.audio: chroma.AudioChroma | None = None
        self.read_pos = 0
        self.chords = chordmod.ChordTracker()
        self.drums = drummod.DrumTracker(SR)
        self.song: Song | None = None
        self.previous: Song | None = None
        self.preps: dict[str, dict] = {}   # song id -> prepared notes, for GET /api/song
        self.history: deque = deque(maxlen=40)
        self.titles: queue.Queue = queue.Queue()
        self.charts: dict[str, dict | None] = {}
        self.chart_down = False
        self.last_publish = 0.0
        threading.Thread(target=self.lib.refresh, daemon=True, name="library-scan").start()
        threading.Thread(target=self._loop, daemon=True, name="tracker").start()

    # -- commands from the page ---------------------------------------------------------------

    def tune(self, station: dict) -> dict:
        url = (station or {}).get("url", "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("That isn't a stream link (it should start with http:// or https://).")
        with self.lock:
            self._stop_tuner()
            self.station = {k: station.get(k) for k in ("uuid", "name", "url", "favicon", "homepage", "country", "state", "codec", "bitrate")}
            self.station["name"] = self.station.get("name") or url
            self.audio = chroma.AudioChroma(SR)
            self.read_pos = 0
            self.chords = chordmod.ChordTracker()
            self.drums = drummod.DrumTracker(SR)
            self.song = self.previous = None
            self.history.clear()  # the page lists what's played on this station
            self.status = {"state": "connecting", "message": ""}
            tuner = Tuner(url, on_title=lambda t, text, s=None: None, on_status=lambda a, b: None)
            session = tuner.session
            tuner.on_title = lambda t, text: self.titles.put((session, t, text))
            tuner.on_status = lambda state, msg: self._tuner_status(session, state, msg)
            self.tuner = tuner.start()
        stations.clicked(station.get("uuid") or "")
        self._publish(force=True)
        return {"session": session}

    def stop(self) -> None:
        with self.lock:
            self._stop_tuner()
            self.station = None
            self.status = {"state": "off", "message": ""}
            self.song = self.previous = None
        self._publish(force=True)

    def choose(self, query: str | None = None, path: str | None = None) -> None:
        """The user says what's playing (typed), or picks another file for it."""
        with self.lock:
            if not self.tuner or not self.audio:
                raise ValueError("Tune in to a station first.")
            live = self.tuner.live
            if path:
                song = self.song
                if not song:
                    song = self._new_song(pathlib_name(path), live - 20, seen_start=False)
                song.match = {"path": path, "name": pathlib_name(path), "score": 1.0}
                song.source = "chosen"
                self._load(song, path)
                return
            if not (query or "").strip():
                raise ValueError("Type the song's name.")
            song = self._new_song(query.strip(), live - 20, seen_start=False, typed=True)
        self._lookup(song)

    def set_settings(self, **changes) -> dict:
        with self.lock:
            for k in ("online", "charts"):
                if k in changes and changes[k] is not None:
                    self.settings[k] = bool(changes[k])
            save_settings(self.settings)
        self._publish(force=True)
        return self.settings

    def prep(self, song_id: str) -> dict | None:
        p = self.preps.get(song_id)
        if not p:
            return None
        return {k: p[k] for k in ("path", "name", "notes", "bars", "timeline", "step", "duration", "drums")}

    # -- the tuner's reports ------------------------------------------------------------------

    def _stop_tuner(self) -> None:
        if self.tuner:
            self.tuner.stop()
            self.tuner = None

    def _tuner_status(self, session: str, state: str, message: str) -> None:
        with self.lock:
            if self.tuner and self.tuner.session == session:
                self.status = {"state": state, "message": message}

    # -- songs -------------------------------------------------------------------------------

    def _new_song(self, title: str, at: float, seen_start: bool, typed: bool = False) -> Song:
        with self.lock:
            if self.song and self.song.prep:
                self.previous = self.song
            song = Song(id=secrets.token_hex(4), title=title, started=at, seen_start=seen_start)
            if typed:
                song.source = "typed"
            self.song = song
            self.history.appendleft({"id": song.id, "title": title, "at": time.strftime("%H:%M"), "found": None, "status": "looking"})
            self.chords.use(None)
            # keep only the songs the page may still be playing
            keep = {s.id for s in (self.song, self.previous) if s}
            for k in [k for k in self.preps if k not in keep]:
                del self.preps[k]
            return song

    def _history(self, song: Song) -> None:
        for h in self.history:
            if h["id"] == song.id:
                h["status"] = song.status
                h["found"] = song.match["name"] if song.match else None

    def _lookup(self, song: Song) -> None:
        def work():
            try:
                match = self.lib.find(song.title)
                source = "library"
                if match is None and self.settings["online"]:
                    with self.lock:
                        song.message = "Not in your library. Looking on bitmidi.com…"
                    match = songs.find_online(song.title)
                    source = "bitmidi"
                    if match:
                        self.lib.refresh(force=True)
                with self.lock:
                    current = self.song is song
                    if match is None:
                        song.status = "not_found"
                        song.message = "Not in your library" + (" or on bitmidi.com." if self.settings["online"] else ".")
                    else:
                        song.match = {"path": match.path, "name": match.name, "score": match.score}
                        song.others = match.others
                        if song.source != "typed":
                            song.source = source
                        if not current:  # the station moved on while looking: list it, don't load it
                            song.status = "missed"
                    self._history(song)
                if not current:
                    return
                if match is None:
                    self._chart(song)
                    return
                self._load(song, match.path)
            except Exception as exc:  # noqa: BLE001 - a bad file or a network hiccup: say so
                log.exception("lookup failed")
                with self.lock:
                    song.status, song.message = "error", f"Couldn't open the song: {exc}"[:200]
                    self._history(song)

        threading.Thread(target=work, daemon=True, name="song-lookup").start()

    def _load(self, song: Song, path: str) -> None:
        def work():
            with self.lock:
                song.status, song.message = "loading", "Getting the hands ready…"
                song.anchors, song.good_from, song.good_until, song.last_good, song.fit = [], None, None, None, None
                song.last_try = -1e9
            try:
                prep = songs.prepare(path)
                midi = chroma.midi_chroma(prep["sounding"])
                vocab = _file_chords(path)
            except Exception as exc:  # noqa: BLE001
                log.exception("prepare failed")
                with self.lock:
                    song.status, song.message = "error", f"Couldn't read {pathlib_name(path)}: {exc}"[:200]
                    self._history(song)
                return
            with self.lock:
                if self.song is not song:
                    return
                song.prep, song.midi, song.vocab = prep, midi, vocab
                self.preps[song.id] = prep
                song.status = "listening"
                song.message = "Listening, to line the hands up with the radio…"
                if not prep["hand_notes"]:
                    song.message = "This file has no part for the hands; showing the chords."
                if vocab:
                    self.chords.use(vocab, "file")
                self._history(song)

        threading.Thread(target=work, daemon=True, name="song-load").start()

    def _chart(self, song: Song) -> None:
        """The song's chord chart (Ultimate Guitar, through the coach's client), to choose its
        chords from. Off, or down, the 24 triads are used."""
        if not self.settings["charts"] or self.chart_down:
            return
        title = song.title

        def work():
            if title in self.charts:
                chart = self.charts[title]
            else:
                chart = None
                try:
                    from midi_coach import web

                    for artist, name in songs.readings(title)[:3]:
                        if not artist:
                            continue
                        tabs = web.ug_search(f"{artist} {name}", ["chords"])
                        tabs = [t for t in tabs if songs._likeness(name, t.get("song", "")) >= 0.9
                                and songs._likeness(artist, t.get("artist", "")) >= 0.8]
                        if tabs:
                            best = max(tabs, key=lambda t: (t.get("votes") or 0) * (t.get("rating") or 0))
                            tab = web.ug_tab(best["tab_id"])
                            names = web.chart_chords(tab.get("content") or "")
                            if names:
                                chart = {"name": f"{best.get('artist')} - {best.get('song')}", "url": tab.get("url"), "chords": names}
                            break
                except Exception as exc:  # noqa: BLE001 - the chart site refused or is down
                    log.info("chart lookup failed: %s", exc)
                    self.chart_down = True
                    return
                self.charts[title] = chart
            with self.lock:
                if self.song is song and chart:
                    song.chart = chart
                    self.chords.use(chart["chords"], "chart")

        threading.Thread(target=work, daemon=True, name="chart").start()

    # -- lining up ---------------------------------------------------------------------------

    def _align(self, song: Song) -> None:
        audio = self.audio
        live = audio.time_of(audio.end)
        if live - song.last_try < TRY_EVERY[1 if song.anchors and song.status == "synced" else 0]:
            return
        song.last_try = live
        begin = song.started + (1.5 if song.seen_start else -600)
        dur = song.prep["duration"]
        if song.status == "synced" and song.anchors:
            a = max(begin, live - FOLLOW_WINDOW)
            frames, loud, t0 = audio.window(a, live)
            expected = song.midi_at(t0)
            rate = song.anchors[-1][2]
            fit = chroma.align(frames, loud, song.midi, near=(expected, FOLLOW_SPREAD),
                               rates=np.arange(rate - 0.03, rate + 0.0301, 0.005))
        else:
            a = max(begin, live - FIRST_WINDOW)
            frames, loud, t0 = audio.window(a, live)
            prior = None
            if song.seen_start:
                elapsed = t0 - song.started
                prior = (elapsed, 8 + 0.1 * elapsed)
            fit = chroma.align(frames, loud, song.midi, prior=prior)
        heard = float(loud.sum()) / chroma.FPS if len(loud) else 0.0
        if fit is None:
            if song.status == "listening":
                song.message = f"Listening, to line the hands up with the radio… ({heard:.0f} s)"
            return
        song.fit = {"score": round(fit.score, 3), "contrast": round(fit.contrast, 3), "margin": round(fit.margin, 3),
                    "rate": round(fit.rate, 3), "heard": round(heard, 1)}
        span = len(frames) / chroma.FPS
        if fit.sure:
            mid = t0 + span / 2
            m = fit.midi_time(span / 2)
            known = song.midi_at(mid)
            if known is not None and abs(known - m) > JUMP:
                song.anchors = [x for x in song.anchors if x[0] < t0]
            song.anchors = [x for x in song.anchors if x[0] < mid - 0.5] + [[round(mid, 3), round(m, 3), round(fit.rate, 4)]]
            if song.good_from is None:
                song.good_from = round(song.started if song.seen_start else t0, 3)
            song.good_until = round(t0 + span + 6.0, 3)
            song.last_good = live
            if song.status != "synced":
                song.status = "synced"
                self._history(song)
            song.message = f"In time with the radio ({fit.rate:.0%} of the file's speed)" if abs(fit.rate - 1) > 0.015 else "In time with the radio"
            if m > dur + 1.0:
                song.status, song.message = "ended", "The song's over."
        else:
            if song.status == "synced" and song.last_good is not None and live - song.last_good > LOST_AFTER:
                song.status, song.message = "lost", "Lost the place (talk-over, or a different edit?). Listening again…"
                self._history(song)
            elif song.status in ("listening", "no_match") and heard >= NO_MATCH_AFTER * 0.66 and live - song.started > NO_MATCH_AFTER:
                song.status = "no_match"
                song.message = "The radio doesn't match this file (another version or edit?). Showing the chords; still trying."

    # -- the loop ----------------------------------------------------------------------------

    def _loop(self) -> None:
        last_chords = 0.0
        while True:
            time.sleep(TICK_SEC)
            try:
                with self.lock:
                    tuner, audio, pos, drums = self.tuner, self.audio, self.read_pos, self.drums
                if not tuner or not audio:
                    self._publish()
                    continue
                while True:
                    try:
                        session, at, text = self.titles.get_nowait()
                    except queue.Empty:
                        break
                    if session != tuner.session:
                        continue
                    if songs.clean_title(text) and not (self.song and self.song.title == text):
                        song = self._new_song(text, at, seen_start=at > 3.0)
                        self._lookup(song)
                start, frames = tuner.ring.read(pos, SR * 10)
                if len(frames):
                    if start > pos:  # fell behind the ring: start the analysis afresh from here
                        audio = chroma.AudioChroma(SR, start_sample=start)
                        drums = drummod.DrumTracker(SR, start_sample=start)
                    mono = frames.astype(np.float32).mean(axis=1) / 32768.0
                    audio.add(mono)
                    drums.add(mono)
                    pos = start + len(frames)
                now = time.time()
                with self.lock:
                    if self.tuner is not tuner:  # tuned elsewhere during this tick: its audio was the old station's
                        continue
                    self.audio, self.read_pos, self.drums = audio, pos, drums
                    if now - last_chords >= 0.5:
                        self.chords.update(audio)
                        last_chords = now
                    song = self.song
                    if song and song.midi is not None and song.status not in ("ended", "error"):
                        self._align(song)
                self._publish()
            except Exception:  # noqa: BLE001 - keep the loop alive whatever one tick does
                log.exception("tracker tick failed")

    def state(self) -> dict:
        with self.lock:
            tuner = self.tuner
            live = tuner.live if tuner else 0.0
            since = max(0.0, live - CHORDS_SINCE)
            segs = self.chords.recent(since, hold=HOLD_SEC) if tuner else []
            return {
                "station": self.station,
                "tuner": {**self.status, "session": tuner.session if tuner else None, "live": round(live, 3),
                          "oldest": round(tuner.ring.oldest / SR, 3) if tuner else 0.0, "sr": SR,
                          "titles": tuner.metadata if tuner else False, "codec": tuner.codec if tuner else None,
                          "icy_name": tuner.name if tuner else None},
                "title": tuner.title if tuner else None,
                "song": self.song.public() if self.song else None,
                "previous": self.previous.public() if self.previous else None,
                "chords": {"source": self.chords.source, "names": self.chords.names if self.chords.source != "heard" else [],
                           "key": self.chords.key if tuner else "",
                           "segs": [[s["t0"], s["t1"], s["name"]] for s in segs],
                           "notes": chordmod.notes_for(segs), "bps": chordmod.BPS},
                "drums": {"hits": self.drums.recent(since)},
                "history": list(self.history)[:15],
                "settings": dict(self.settings),
                "library": len(self.lib.files),
            }

    def _publish(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last_publish < PUBLISH_SEC:
            return
        self.last_publish = now
        try:
            self.publish_cb(self.state())
        except Exception:  # noqa: BLE001
            log.exception("publish failed")


def pathlib_name(path: str) -> str:
    import pathlib

    return pathlib.Path(path).stem


def _file_chords(path: str) -> list[str]:
    """The chords a song file uses (coach's harmony.chords_by_bar), to name what's heard."""
    try:
        from midi_coach import harmony
        from midi_coach.notes import load_score

        score = load_score(path)
        drums = {p.index for p in score.parts if p.drums}
        notes = [n for n in score.notes if n.part not in drums]
        found = harmony.chords_by_bar(score, notes, per_bar=2)
        names = [c.get("chord") for c in found if c.get("chord")]
        common = [n for n, _ in sorted(((n, names.count(n)) for n in set(names)), key=lambda x: -x[1])]
        return [n for n in common if chordmod.parse(n)][:12]
    except Exception:  # noqa: BLE001 - the 24 triads will do
        return []
