"""midi-coach MCP server: record, analyze, compare and play back piano MIDI.

Run with:  python -m midi_coach   (stdio transport, for Claude Desktop)
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import os
import statistics
import sys
import time

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import analysis, lessons, library, live
from .display import DisplayHub
from .midi_io import Player, PortError, Recorder, RestProfile, build_events, list_ports
from .notes import note_name, notes_from_events, parse_bars, select_notes

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s midi-coach %(message)s")
log = logging.getLogger("midi-coach")

INSTRUCTIONS = """\
midi-coach lets you hear and coach the user's piano playing (Roland JUNO-DS).

Typical loop:
1. find_reference("moonlight") -> inspect_reference(path) to see parts, hands, bars.
2. start_recording(reference=..., hand=..., bars=...) then tell the user to play.
3. wait_for_recording() repeatedly until state is 'stopped'. With a reference it
   returns the comparison automatically. Recording auto-stops after silence, but
   waits through rests written in the reference.
4. Coach from the report: lead with the 2-3 most important issues (worst_bars,
   hesitations, wrong notes), cite bar numbers, and be encouraging and concrete.
5. play_comparison(bars=...) to let them hear their take vs the reference,
   play(reference, bars=..., hand="left", tempo_percent=70) for practice.
6. progress(reference) to show improvement across sessions.
Live sheet music: show_score opens a page (and the web visualizer's notation strip,
via its Coach link) with the reference. start_recording(mode='wait') holds the cursor
until the right notes are played (best for learning notes); mode='rehearsal' moves at
tempo_percent and grades notes as they pass (best for performance practice). After each
take the score shows a bar heat map; show_heatmap(take) redisplays any take's map.
Custom lessons: create_lesson writes an exercise (tinyNotation per hand, or MusicXML, or
an excerpt of a reference) and pushes it live into the visualizer's Learn Mode and the
coach page - no file loading. Check the returned bar-by-bar readout against what you
meant, then start_recording(reference=<lesson path>, mode=...) to grade it. Target
lessons at the user's weak spots (worst bars, hands, rhythms) and keep them short.
Timing numbers are relative to the user's own local tempo; playing slower than
the score is not an error. Velocity 1-127: ~40 soft, ~64 medium, ~95 loud.
"""

mcp = _Server("midi-coach", instructions=INSTRUCTIONS)
recorder = Recorder()
player = Player()
hub = DisplayHub()
_last_take: dict = {}
_live: dict = {"session": None}


def _err(exc: Exception) -> dict:
    return {"error": str(exc)}


def _selection(score, hand: str, bars: str | None, split_note: int, parts: list[int] | None = None):
    bar_range = parse_bars(bars)
    notes, info = select_notes(score, hand, parts=parts, bars=bar_range, split_note=split_note)
    return notes, info, bar_range


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_midi_ports() -> dict:
    """List MIDI input and output ports. Inputs are used for recording, outputs for playback."""
    try:
        ports = list_ports()
    except PortError as exc:
        return _err(exc)
    return {**ports, "note": "Ports are chosen by name substring; defaults come from MIDI_COACH_INPUT / MIDI_COACH_OUTPUT, else the JUNO."}


@mcp.tool()
async def find_reference(query: str = "", limit: int = 10) -> dict:
    """Search the reference library (config.json search_folders + MIDI_COACH_REFERENCE_DIRS) by fuzzy title.

    Empty query lists files alphabetically.
    """
    hits = await asyncio.to_thread(library.find_references, query, limit)
    return {"results": hits, "folders": [str(f) for f in library.reference_folders()]}


@mcp.tool()
async def inspect_reference(reference: str, split_note: int = 60) -> dict:
    """Describe a reference MIDI/MusicXML file: parts (track+channel), which hand each part is, bars, tempo, pedal, long rests."""
    try:
        score = await asyncio.to_thread(library.get_score, reference)
    except Exception as exc:
        return _err(exc)
    side = analysis.side_resolver(score, split_note)
    parts = []
    for p in score.parts:
        pnotes = [n for n in score.notes if n.part == p.index]
        if not pnotes:
            continue
        sides = [side(n) for n in pnotes]
        guess = max(set(sides), key=sides.count)
        parts.append({
            "index": p.index, "name": p.name, "track": p.track, "channel": p.channel + 1,
            "notes": p.note_count, "range": f"{note_name(p.low)}-{note_name(p.high)}",
            "hand": guess if sides.count(guess) / len(sides) > 0.8 else "mixed (split by pitch)",
        })
    profile = RestProfile.from_notes(score.notes)
    rests = sorted(
        ({"bar": score.position(score.notes[k].start)[0], "rest_sec": round(r, 2)} for k, r in enumerate(profile.rests) if r >= 1.0),
        key=lambda x: -x["rest_sec"],
    )[:5]
    sigs = sorted({f"{b.numerator}/{b.denominator}" for b in score.bars})
    bpms = [b for _, b in score.tempos]
    return {
        "path": score.path,
        "duration_sec": round(score.duration, 1),
        "bars": len(score.bars),
        "time_signatures": sigs,
        "tempo_bpm": {"start": bpms[0] if bpms else 120, "min": min(bpms, default=120), "max": max(bpms, default=120)},
        "notes": len(score.notes),
        "parts": parts,
        "has_pedal": bool(score.pedal),
        "has_dynamics": len(score.notes) > 2 and statistics.pstdev(n.velocity for n in score.notes) >= 4,
        "longest_rests": rests,
    }


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def _on_recording_finished(meta_base: dict, session: live.LiveSession | None = None):
    def finish(state) -> None:
        if session is not None:
            session.stop()
            meta_base["mode"] = session.mode
            meta_base["live"] = session.summary()
        if not state.events or state.note_ons == 0:
            _last_take.clear()
            _last_take.update({"id": None, "stop_reason": state.stop_reason})
            return
        notes, _ = notes_from_events(state.events)
        meta = library.save_take(state.events, {
            **meta_base,
            "port": state.port_name,
            "stop_reason": state.stop_reason,
            "notes": len(notes),
            "duration_sec": round(max(n.end for n in notes) - notes[0].start, 2),
        })
        _last_take.clear()
        _last_take.update(meta)
        log.info("saved take %s (%d notes, %s)", meta["id"], len(notes), state.stop_reason)
    return finish


@mcp.tool()
async def start_recording(
    reference: str | None = None,
    hand: str = "both",
    bars: str | None = None,
    silence_sec: float = 4.0,
    max_minutes: float = 10.0,
    input_port: str | None = None,
    split_note: int = 60,
    mode: str = "free",
    tempo_percent: float = 100.0,
    show_score: bool = True,
) -> dict:
    """Start recording the user's playing from the MIDI input.

    mode: 'free' (just record), 'wait' (cursor waits for the right notes, like Synthesia
      Melody Practice) or 'rehearsal' (cursor moves at tempo_percent once the first note
      is played; notes are graded hit/missed live, like Synthesia Song Recital).
      wait/rehearsal need a reference and end automatically at the end of the piece/bars.
    show_score: show the reference on the live sheet-music page (opens the browser if no
      display is connected).
    reference: optional reference title/path; enables rest-aware auto-stop and auto-compare.
    hand: 'both' | 'right' | 'left' - what the user is practicing.
    bars: e.g. '9-16' to practice a section.
    silence_sec: stop after this much silence (no keys held). With a reference the
      timeout is stretched to cover the longest written rest still ahead.
    Recording waits up to 2 minutes for the first note. Then call wait_for_recording.
    """
    mode = (mode or "free").lower()
    if mode not in ("free",) + live.MODES:
        return {"error": "mode must be 'free', 'wait' or 'rehearsal'."}
    if mode != "free" and not reference:
        return {"error": f"{mode} mode needs a reference to follow."}
    if recorder.active:
        return {"error": "A recording is already running. Call stop_recording first."}
    meta = {"reference": None, "hand": hand, "bars": bars, "split_note": split_note, "mode": mode}
    rests = None
    selection = None
    session = None
    display_url = None
    try:
        if reference:
            score = await asyncio.to_thread(library.get_score, reference)
            notes, selection, _ = _selection(score, hand, bars, split_note)
            if not notes:
                return {"error": f"No reference notes for hand={hand} bars={bars}."}
            rests = RestProfile.from_notes(notes)
            meta["reference"] = score.path
            if show_score:
                display_url = await asyncio.to_thread(_show, score, notes)
            if mode != "free":
                session = live.LiveSession(mode, score, notes, hub if show_score else None, tempo_percent)
                meta["tempo_percent"] = tempo_percent if mode == "rehearsal" else None
                silence_sec, rests = 300.0, None  # the session decides when the piece is over
            elif show_score:
                hub.status("Recording (free play) · Claude will analyze when you stop")
        recorder.on_finish = _on_recording_finished(meta, session)
        recorder.listener = session.on_message if session else None
        recorder.external_stop = session.should_stop if session else None
        port = await asyncio.to_thread(recorder.start, input_port, silence_sec, max_minutes * 60, 120.0, rests)
        if session:
            session.start()
        _live["session"] = session
    except Exception as exc:
        return _err(exc)
    _last_take.clear()
    longest = max(rests.rests, default=0.0) if rests else 0.0
    if mode == "wait":
        auto_stop = "when the last chord is played (or 5 minutes idle)"
    elif mode == "rehearsal":
        auto_stop = f"after the last note passes at {tempo_percent:g}% tempo (clock starts on the first note)"
    else:
        auto_stop = f"{silence_sec}s of silence" + (f", extended through written rests (longest {longest:.1f}s at score tempo)" if longest > silence_sec else "")
    return {
        "recording": True,
        "mode": mode,
        "port": port,
        "reference": meta["reference"],
        "selection": selection,
        "display": display_url,
        "auto_stop": auto_stop,
        "next": "Tell the user to start playing, then call wait_for_recording.",
    }


def _show(score, notes) -> str:
    """Load a score on the live display, opening the browser if nothing is watching."""
    url = hub.start()
    hub.load_score(score)
    hub.marks([], reset=True)
    hub.heat(None)
    if notes:
        hub.cursor(min(n.beat for n in notes))
    if hub.clients == 0 and not os.environ.get("MIDI_COACH_NO_BROWSER"):
        hub.open_browser()
    return url


def _push_heat(meta: dict, score, per_bar: list[dict] | None) -> list[dict] | None:
    if not hub.url:
        return None
    if meta.get("mode") in live.MODES and meta.get("live"):
        bars = live.heat_from_live(score, meta["live"])
    elif per_bar is not None:
        bars = live.heat_from_comparison(score, per_bar)
    else:
        return None
    hub.load_score(score)
    hub.cursor(bars[0]["start"] if bars else 0.0)
    hub.heat(bars)
    hub.status(f"Take {meta.get('id')} · bar heat map (green = clean, red = most problems)")
    return bars


def _summary(report: dict) -> dict:
    return {k: v for k, v in report.items() if not k.startswith("_")}


def _compare(take_meta: dict, reference: str | None, hand: str | None, bars: str | None, split_note: int | None, detail: str, save: bool) -> dict:
    reference = reference or take_meta.get("reference")
    if not reference:
        return {"error": "No reference given and the take has none attached."}
    hand = hand or take_meta.get("hand") or "both"
    bars = bars if bars is not None else take_meta.get("bars")
    split_note = split_note or take_meta.get("split_note") or 60
    score = library.get_score(reference)
    ref_notes, selection, bar_range = _selection(score, hand, bars, split_note)
    t_notes, t_pedal = library.take_notes(take_meta)
    started = time.perf_counter()
    report = analysis.compare(score, ref_notes, t_notes, t_pedal, bars_given=bar_range is not None, split_note=split_note, detail=detail)
    if "error" in report:
        return report
    report = {"take": take_meta["id"], "reference": score.path, "selection": selection, **report}
    if take_meta.get("mode") == "wait":
        # The cursor waited for the player, so timing and tempo say nothing here.
        skipped = {"note": "Wait mode take: the cursor waited for you, so timing/tempo aren't measured."}
        report["timing"], report["tempo"] = skipped, skipped
        report["scores"] = {"overall": report["scores"]["notes"], "notes": report["scores"]["notes"], "method": "wait mode: note accuracy only"}
    if take_meta.get("live"):
        report["live"] = take_meta["live"]
    try:
        _push_heat(take_meta, score, report["_per_bar"])
    except Exception as exc:  # display problems never fail an analysis
        log.warning("heat map push failed: %s", exc)
    if save:
        take_meta.setdefault("comparisons", []).append({
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reference": score.path,
            "hand": hand,
            "bars": report["scope"]["bars"],
            "scores": report["scores"],
            "notes": report["notes"],
            "tempo_bpm": report["tempo"].get("your_bpm"),
            "per_bar": [{k: b[k] for k in ("bar", "wrong", "missed", "extra", "timing_ms")} for b in report["_per_bar"]],
        })
        library.update_take(take_meta)
    log.info("compared %s in %.2fs", take_meta["id"], time.perf_counter() - started)
    return _summary(report)


@mcp.tool()
async def wait_for_recording(max_wait_sec: float = 45.0, auto_compare: bool = True) -> dict:
    """Wait (up to max_wait_sec) for the current recording to auto-stop.

    Returns live status while still recording - call again. When stopped, returns the
    saved take and, if a reference was attached and auto_compare is true, the comparison.
    """
    if recorder.status().get("state") == "idle":
        return {"error": "Not recording. Call start_recording first."}
    max_wait_sec = max(1.0, min(max_wait_sec, 55.0))
    done = await asyncio.to_thread(recorder.wait, max_wait_sec)
    status = recorder.status()
    if not done:
        session = _live["session"]
        progress = {k: v for k, v in session.summary().items() if k != "per_bar"} if session else None
        return {**status, "live": progress, "next": "Still going - call wait_for_recording again."}
    return await _finished_result(status, auto_compare)


async def _finished_result(status: dict, auto_compare: bool) -> dict:
    take_id = _last_take.get("id")
    if not take_id:
        return {**status, "take": None, "note": "Nothing was recorded."}
    out = {**status, "take": take_id, "file": _last_take.get("file"), "duration_sec": _last_take.get("duration_sec")}
    if not auto_compare:
        return out
    try:
        meta = library.get_take(take_id)
        if meta.get("reference"):
            out["comparison"] = await asyncio.to_thread(_compare, meta, None, None, None, None, "normal", True)
        else:
            notes, pedal = await asyncio.to_thread(library.take_notes, meta)
            out["analysis"] = analysis.analyze_take(notes, pedal, meta.get("split_note") or 60)
    except Exception as exc:
        out["analysis_error"] = str(exc)
    return out


@mcp.tool()
async def show_score(reference: str | None = None, hand: str = "both", bars: str | None = None, open_browser: bool = True, split_note: int = 60) -> dict:
    """Show a reference on the live sheet-music page (http://127.0.0.1:8765/) and in the
    web visualizer's notation strip when its Coach link is on. Defaults to the latest take's reference."""
    try:
        if not reference:
            reference = library.get_take("latest").get("reference")
            if not reference:
                return {"error": "No reference given and the latest take has none."}
        score = await asyncio.to_thread(library.get_score, reference)
        notes, selection, _ = _selection(score, hand, bars, split_note)
        url = hub.start()
        hub.load_score(score)
        hub.marks([], reset=True)
        hub.heat(None)
        if notes:
            hub.cursor(min(n.beat for n in notes))
        hub.status(f"{pathlib.Path(score.path).stem} · {selection.get('method')}" + (f" · bars {bars}" if bars else ""))
        if open_browser and hub.clients == 0 and not os.environ.get("MIDI_COACH_NO_BROWSER"):
            hub.open_browser()
    except Exception as exc:
        return _err(exc)
    return {"url": url, "reference": score.path, "viewers_connected": hub.clients}


def _publish_lesson(path: str, score, practice_mode: str, tempo_percent: float, autostart: bool) -> dict:
    side = analysis.side_resolver(score)
    hub.start()
    hub.load_score(score)
    hub.marks([], reset=True)
    hub.heat(None)
    hub.status(f"Lesson: {pathlib.Path(path).stem}")
    version = hub.lesson({
        "title": pathlib.Path(path).stem,
        "path": path,
        "xml": hub.xml_for(path),
        "events": lessons.learn_events(score, side),
        "learn_mode": "wait" if practice_mode == "wait" else "freeplay",
        "speed": max(0.1, tempo_percent / 100),
        "autostart": autostart,
    })
    if hub.clients == 0 and not os.environ.get("MIDI_COACH_NO_BROWSER"):
        hub.open_browser()
    return {"lesson_version": version, "viewers_connected": hub.clients}


@mcp.tool()
async def create_lesson(
    title: str,
    right: str | None = None,
    left: str | None = None,
    time_signature: str = "4/4",
    key: str = "C",
    tempo_bpm: float = 80,
    musicxml: str | None = None,
    from_reference: str | None = None,
    bars: str | None = None,
    hand: str = "both",
    send: bool = True,
    practice_mode: str = "wait",
    tempo_percent: float = 100,
    autostart: bool = True,
) -> dict:
    """Create a practice lesson and push it live to the visualizer's Learn Mode and the coach page.

    Three ways to write it:
    1. right / left: one music21 tinyNotation string per hand (written in the treble / bass clef):
       c d e f g a b = C4..B4; c' = C5, c'' = C6; C = C3, CC = C2. Sharps f#, flats b- (B flat).
       Durations after the pitch: 1 whole, 2 half, 4 quarter, 8 eighth, 16; dots c4.; a note
       without a number reuses the last duration. Rests r4. Ties c2~ c8. Chords chord{C2 E G}
       (duration on the first note). Triplets trip{c8 d e}. Example right hand:
       "g4 a b c' d'2 r4 d'8 c' b1"
    2. musicxml: a complete MusicXML document (for fingerings, dynamics, voices...).
    3. from_reference + bars (+ hand): excerpt of an existing piece, e.g. the user's worst bars.
    key: 'C', 'G', 'Bb', 'F#m', 'Am' (minor with m) or sharps count like -3.
    practice_mode: Learn Mode style in the visualizer - 'wait' or 'rehearsal' (free-play at
      tempo_percent). autostart: start Learn Mode immediately when it arrives.
    Returns the saved path (use it as `reference` for start_recording / compare_take) and a
    bar-by-bar readout - check it matches what you intended before telling the user.
    """
    try:
        if from_reference:
            bar_range = parse_bars(bars)
            if not bar_range:
                return {"error": "from_reference needs bars, e.g. '9-12'."}
            ref_path = str(library.resolve_reference(from_reference))
            path, score = await asyncio.to_thread(lessons.excerpt_lesson, ref_path, bar_range, hand, title)
        else:
            path, score = await asyncio.to_thread(lessons.build_lesson, title, right, left, time_signature, key, tempo_bpm, musicxml)
        if not score.notes:
            return {"error": "The lesson has no notes.", "path": path}
        side = analysis.side_resolver(score)
        out = {
            "path": path,
            "bars": len(score.bars),
            "notes": {"right": sum(1 for n in score.notes if side(n) == "right"), "left": sum(1 for n in score.notes if side(n) == "left")},
            "duration_sec_at_tempo": round(score.duration, 1),
            "readout": lessons.describe(score, side),
            "readout_format": "bar: RH note@beat ... | LH ...; chords joined with +",
        }
        if send:
            out["sent"] = await asyncio.to_thread(_publish_lesson, path, score, practice_mode, tempo_percent, autostart)
            out["display"] = hub.url
        out["next"] = f"start_recording(reference={path!r}, mode={practice_mode!r}) to grade the user on it."
        return out
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def send_lesson(lesson: str, practice_mode: str = "wait", tempo_percent: float = 100, autostart: bool = True) -> dict:
    """Push an existing lesson or reference file (title or path) live into the visualizer's Learn Mode."""
    try:
        score = await asyncio.to_thread(library.get_score, lesson)
        sent = await asyncio.to_thread(_publish_lesson, score.path, score, practice_mode, tempo_percent, autostart)
    except Exception as exc:
        return _err(exc)
    return {"path": score.path, "sent": sent, "display": hub.url}


@mcp.tool()
async def show_heatmap(take: str = "latest") -> dict:
    """Show a take's bar heat map on the live score (green = clean bar, red = most problems)."""
    try:
        meta = library.get_take(take)
        ref = meta.get("reference")
        if not ref:
            return {"error": "That take has no reference to draw on."}
        score = await asyncio.to_thread(library.get_score, ref)
        comps = [c for c in meta.get("comparisons", []) if c["reference"] == score.path]
        if not comps and not meta.get("live"):
            await asyncio.to_thread(_compare, meta, None, None, None, None, "normal", True)
            comps = [c for c in meta.get("comparisons", []) if c["reference"] == score.path]
        hub.start()
        bars = await asyncio.to_thread(_push_heat, meta, score, comps[-1]["per_bar"] if comps else None)
        if hub.clients == 0 and not os.environ.get("MIDI_COACH_NO_BROWSER"):
            hub.open_browser()
    except Exception as exc:
        return _err(exc)
    worst = sorted((b for b in bars or [] if b["value"] > 0), key=lambda b: -b["value"])[:8]
    return {"url": hub.url, "take": meta["id"], "bars_shown": len(bars or []), "hottest_bars": worst}


@mcp.tool()
async def stop_recording(auto_compare: bool = True) -> dict:
    """Stop the current recording now and save the take (then compare/analyze it)."""
    if recorder.status().get("state") == "idle":
        return {"error": "Not recording."}
    await asyncio.to_thread(recorder.stop)
    return await _finished_result(recorder.status(), auto_compare)


@mcp.tool()
async def status() -> dict:
    """Current recording and playback status."""
    session = _live["session"]
    return {
        "recording": recorder.status(),
        "live": session.summary() if session and recorder.active else None,
        "display": {"url": hub.url, "viewers_connected": hub.clients, "score": hub.score_path},
        "playback": player.status(),
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@mcp.tool()
async def analyze_take(take: str = "latest", split_note: int = 60) -> dict:
    """Analyze a take on its own (no reference): pulse/evenness, pauses, dynamics, hands, articulation, pedal.

    take: 'latest', a take id, or a path to any MIDI file.
    """
    try:
        meta = library.get_take(take)
        notes, pedal = await asyncio.to_thread(library.take_notes, meta)
    except Exception as exc:
        return _err(exc)
    return {"take": meta["id"], **analysis.analyze_take(notes, pedal, split_note)}


@mcp.tool()
async def compare_take(
    take: str = "latest",
    reference: str | None = None,
    hand: str | None = None,
    bars: str | None = None,
    split_note: int | None = None,
    detail: str = "normal",
) -> dict:
    """Compare a take to a reference: wrong/missed/extra notes, timing, tempo, dynamics, articulation, pedal.

    Defaults to the reference/hand/bars the take was recorded with. Without bars, the
    played section is detected automatically. detail='full' lists every bar and mistake.
    The result is saved to the take's history for progress().
    """
    try:
        meta = library.get_take(take)
        return await asyncio.to_thread(_compare, meta, reference, hand, bars, split_note, detail, True)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def list_takes(reference: str | None = None, limit: int = 20) -> dict:
    """List saved takes (newest last) with their latest comparison scores."""
    takes = library.list_takes()
    if reference:
        try:
            ref_path = str(library.resolve_reference(reference))
        except FileNotFoundError as exc:
            return _err(exc)
        takes = [t for t in takes if t.get("reference") == ref_path or any(c["reference"] == ref_path for c in t.get("comparisons", []))]
    rows = []
    for t in takes[-limit:]:
        last = t.get("comparisons", [])[-1] if t.get("comparisons") else None
        rows.append({
            "id": t["id"], "created": t.get("created"), "reference": pathlib.Path(t["reference"]).name if t.get("reference") else None,
            "hand": t.get("hand"), "bars": t.get("bars"), "notes": t.get("notes"), "duration_sec": t.get("duration_sec"),
            "scores": last["scores"] if last else None,
        })
    return {"takes": rows, "folder": str(library.home() / "takes")}


@mcp.tool()
async def progress(reference: str, hand: str | None = None) -> dict:
    """Show improvement over time for a reference: score trend, improved / persistent problem bars."""
    try:
        ref_path = str(library.resolve_reference(reference))
    except FileNotFoundError as exc:
        return _err(exc)
    history = []
    for t in library.list_takes():
        for c in t.get("comparisons", []):
            if c["reference"] == ref_path and (not hand or c["hand"] == hand):
                history.append({"take": t["id"], **c})
    if not history:
        return {"reference": ref_path, "note": "No comparisons recorded for this reference yet."}
    history.sort(key=lambda c: c["when"])
    bar_errors: dict[int, list[int]] = {}
    for c in history:
        for b in c["per_bar"]:
            bar_errors.setdefault(b["bar"], []).append(b["wrong"] + b["missed"] + b["extra"])
    improved, regressed, persistent = [], [], []
    for bar, errs in sorted(bar_errors.items()):
        if len(errs) >= 2:
            first, last = statistics.fmean(errs[: max(1, len(errs) // 2)]), errs[-1]
            if first - last >= 1:
                improved.append({"bar": bar, "errors_before": round(first, 1), "errors_now": last})
            elif last - first >= 1:
                regressed.append({"bar": bar, "errors_before": round(first, 1), "errors_now": last})
        if len(errs) >= 3 and sum(1 for e in errs if e) / len(errs) >= 0.6:
            persistent.append({"bar": bar, "takes_with_errors": sum(1 for e in errs if e), "of": len(errs)})
    return {
        "reference": ref_path,
        "sessions": [{"when": c["when"], "take": c["take"], "hand": c["hand"], "bars": c["bars"], "bpm": c["tempo_bpm"], **c["scores"]} for c in history[-20:]],
        "improved_bars": improved[:10],
        "regressed_bars": regressed[:10],
        "persistent_trouble_bars": sorted(persistent, key=lambda p: -p["takes_with_errors"])[:10],
    }


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------


def _is_take(source: str) -> bool:
    if source == "latest":
        return True
    return any(t["id"] == source for t in library.list_takes())


def _take_segment(meta: dict, bars: tuple[int, int] | None, reference: str | None, hand: str):
    notes, pedal = library.take_notes(meta)
    if not notes:
        raise ValueError("Take has no notes.")
    split = meta.get("split_note") or 60
    t0, t1, slope = notes[0].start, max(n.end for n in notes), 1.0
    if bars:
        ref = reference or meta.get("reference")
        if not ref:
            raise ValueError("Bars on a take need a reference to locate them.")
        score = library.get_score(ref)
        ref_notes, _ = select_notes(score, meta.get("hand") or "both", split_note=split)
        t0, t1, slope = analysis.take_range_for_bars(score, ref_notes, notes, bars)
        t0 = max(notes[0].start, t0 - 0.05)
    if hand == "right":
        notes = [n for n in notes if n.pitch >= split]
    elif hand == "left":
        notes = [n for n in notes if n.pitch < split]
    return notes, pedal, t0, t1, slope


@mcp.tool()
async def play(
    source: str,
    bars: str | None = None,
    hand: str = "both",
    tempo_percent: float = 100.0,
    loops: int = 1,
    output_port: str | None = None,
    channel: int = 1,
    split_note: int = 60,
) -> dict:
    """Play a reference or a take on the MIDI output (the JUNO by default). Returns immediately.

    source: reference title/path, 'latest', or a take id.
    bars: '9-16'; hand: 'both'|'right'|'left'; tempo_percent: 70 = slower practice speed;
    loops: repeat count (max 20). Notes are sent on `channel` (1-16) without program changes,
    so the keyboard's current sound is used.
    """
    try:
        bar_range = parse_bars(bars)
        speed = max(0.1, tempo_percent / 100)
        if _is_take(source):
            meta = library.get_take(source)
            notes, pedal, t0, t1, _ = await asyncio.to_thread(_take_segment, meta, bar_range, None, hand)
            label = f"take {meta['id']}"
        else:
            score = await asyncio.to_thread(library.get_score, source)
            notes, _, _ = _selection(score, hand, bars, split_note)
            if not notes:
                return {"error": "Nothing to play for that hand / bar range."}
            pedal = score.pedal
            t0, t1 = score.bar_range_times(*bar_range) if bar_range else (notes[0].start, max(n.end for n in notes))
            label = pathlib.Path(score.path).name
        events = build_events(notes, pedal, t0, t1, speed, channel - 1)
        loops = max(1, min(loops, 20))
        port = player.play([(f"{label} (loop {k + 1})", events) for k in range(loops)], output_port, gap_sec=0.8)
    except Exception as exc:
        return _err(exc)
    return {"playing": label, "port": port, "bars": bars, "hand": hand, "tempo_percent": tempo_percent, "loops": loops, "seconds": player.status().get("total_sec")}


@mcp.tool()
async def play_comparison(
    take: str = "latest",
    bars: str | None = None,
    reference: str | None = None,
    reference_tempo: str = "match",
    order: str = "take_first",
    output_port: str | None = None,
) -> dict:
    """Play the user's take for a passage, then the reference for the same bars (A/B listening).

    bars: defaults to the worst bar of the take's latest comparison (plus one bar each side).
    reference_tempo: 'match' plays the reference at the user's tempo, 'original' at score tempo.
    order: 'take_first' or 'reference_first'.
    """
    try:
        meta = library.get_take(take)
        ref = reference or meta.get("reference")
        if not ref:
            return {"error": "Take has no reference; pass reference=..."}
        score = await asyncio.to_thread(library.get_score, ref)
        bar_range = parse_bars(bars)
        if bar_range is None:
            comps = [c for c in meta.get("comparisons", []) if c["reference"] == score.path]
            if not comps:
                await asyncio.to_thread(_compare, meta, ref, None, None, None, "normal", True)
                comps = [c for c in meta.get("comparisons", []) if c["reference"] == score.path]
            if not comps:
                return {"error": "Could not compare the take to locate its worst bar; pass bars=..."}
            worst = max(comps[-1]["per_bar"], key=lambda b: 2 * (b["wrong"] + b["missed"]) + b["extra"], default=None)
            if not worst:
                return {"error": "No bars to compare."}
            bar_range = (max(1, worst["bar"] - 1), min(len(score.bars), worst["bar"] + 1))
        hand = meta.get("hand") or "both"
        notes, pedal, t0, t1, slope = await asyncio.to_thread(_take_segment, meta, bar_range, ref, "both")
        take_events = build_events(notes, pedal, t0, t1)
        ref_notes, _ = select_notes(score, hand, bars=bar_range, split_note=meta.get("split_note") or 60)
        r0, r1 = score.bar_range_times(*bar_range)
        speed = 1 / slope if reference_tempo == "match" else 1.0
        ref_events = build_events(ref_notes, score.pedal, r0, r1, speed)
        segments = [("your take", take_events), ("reference", ref_events)]
        if order == "reference_first":
            segments.reverse()
        port = player.play(segments, output_port, gap_sec=1.5)
    except Exception as exc:
        return _err(exc)
    return {
        "bars": f"{bar_range[0]}-{bar_range[1]}",
        "order": [s[0] for s in segments],
        "reference_tempo_percent": round(speed * 100),
        "port": port,
        "seconds": player.status().get("total_sec"),
    }


@mcp.tool()
async def stop_playback() -> dict:
    """Stop playback immediately (sends note-offs and releases the sustain pedal)."""
    player.stop()
    return player.status()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
