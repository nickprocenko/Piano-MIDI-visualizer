"""midi-coach MCP server: record, analyze, compare and play back piano MIDI.

Run with:  python -m midi_coach   (stdio transport, for Claude Desktop)
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import os
import re
import statistics
import sys
import threading
import time

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import analysis, autopilot, chat, deep, harmony, lessons, library, live, profiles, remarks, stt, transcribe, web
from .atlas import runtime as atlas_runtime
from .display import DisplayHub, sheet_problem
from .midi_io import Accompanist, Player, PortError, Recorder, RestProfile, build_events, list_ports, resolve_port
from .notes import ROLES, MUSICXML_SUFFIXES, effective_roles, is_plain_piano, note_name, notes_from_events, parse_bars, select_notes, split_hands, suggest_hands

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s midi-coach %(message)s")
log = logging.getLogger("midi-coach")

INSTRUCTIONS = """\
midi-coach lets you hear and coach the user's piano playing (Roland JUNO-DS).

Typical loop:
1. find_reference("moonlight") -> inspect_reference(path) to see parts, hands, bars.
   Band arrangements (files downloaded from MIDI sites): inspect_reference names each
   part's instrument. When it returns ask_user, show the user the parts and your
   suggestion (e.g. melody in the right hand, bass line in the left), ask which to
   play, then set_parts(...) saves the choice; every tool uses it from then on.
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
an excerpt of a reference) and shows it on the coach page (to_visualizer=True also pushes
it into the visualizer's Learn Mode). Check the returned bar-by-bar readout against what
you meant. Target lessons at the user's weak spots (worst bars, hands, rhythms) and keep
them short.
The coach page has its own menu: input port, Listen / Learn (= wait) / Rehearse (= rehearsal),
hand, bars, tempo, loop, Start/Stop. Listen plays the piece on the MIDI output while the
cursor follows (nothing is played, graded or saved); play does the same without the cursor. Runs started there are the same single session as
start_recording: wait_for_recording returns each finished pass with its comparison, and
looping saves every pass as a take (use progress / list_takes to coach across passes).
After a Learn pass, give feedback on the notes and hesitations it reports.
The page's Record mode records over its metronome and writes what was played out as a
lesson; transcribe_take does the same for any take (e.g. free play), so the user can then
practise their own idea or improvisation.
Cross-reference: search_chord_charts / get_chord_chart pull Ultimate Guitar charts (key, capo,
progression); chords_in_score names each bar's chord from the reference's notes, and
get_chord_chart(reference=...) suggests the transpose that lines a chart up with the score.
search_youtube finds recordings and tutorials. Charts are fan-made: when chart and score
disagree, trust the score and say so.
The Maestro (the page's voice chat) passes big questions to Claude Code on the user's
subscription; when that can't run they wait in maestro_inbox - check it when the user asks
about the Maestro's inbox or a question they asked at the keyboard. pianist_notes is the
Maestro's notebook on the user (goals, pieces, weak spots); read it before a long lesson and
add to it with remember.
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
    """Describe a reference MIDI/MusicXML file: parts (track+channel) with their instrument and
    hand, bars, tempo, pedal, long rests. part_choice is the user's saved choice of parts per
    hand, or a suggestion; when ask_user is true, confirm it with the user, then set_parts."""
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
        if score.roles:
            hand = _ROLE_NAMES.get(score.roles.get(p.index), "not played")
        elif p.drums:
            hand = "not played (drums)"
        else:
            sides = [side(n) for n in pnotes]
            guess = max(set(sides), key=sides.count)
            hand = guess if sides.count(guess) / len(sides) > 0.8 else "mixed (split by register)"
        parts.append({
            "index": p.index, "name": p.name, "instrument": p.instrument, "track": p.track, "channel": p.channel + 1,
            "notes": p.note_count, "range": f"{note_name(p.low)}-{note_name(p.high)}", "hand": hand,
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
        **_part_choice(score),
        **({"played_live": True, "timing_note": "Recorded live: the file's bar lines don't follow the music, so bar "
            "numbers (in reports, bars=..., heat maps) are only rough positions and there's no sheet music or "
            "count-in. Learn mode works fine; refer to places by time or by the notes."} if score.played_live else {}),
        **({"sheet_note": sheet_problem(score)} if sheet_problem(score) and not score.played_live else {}),
    }


_ROLE_NAMES = {"right": "right", "left": "left", "both": "both (split by register)",
               "pedals": "pedals (played with the feet)", "vocals": "vocals (shown and heard, not played)"}


def _part_choice(score) -> dict:
    if score.roles:
        chosen = {r: [i for i, v in sorted(score.roles.items()) if v == r] for r in ROLES}
        return {"part_choice": {"confirmed": True, **chosen}, "ask_user": False}
    # A plain piano file (one or two piano parts, nothing else) needs no questions; for any
    # other file the suggestion is used (sheet music, grading) until the user confirms.
    suggested = suggest_hands(score)
    for role in ("pedals", "vocals"):
        suggested[role] = [i for i, r in sorted(effective_roles(score).items()) if r == role]
    return {"part_choice": {"confirmed": False, "suggested": suggested}, "ask_user": not is_plain_piano(score)}


def _save_parts(score, chosen: dict[str, list[int] | None]) -> dict[int, str]:
    """Check and save a part -> role choice given as {role: [part indexes]}; returns it."""
    roles: dict[int, str] = {}
    valid = {p.index for p in score.parts if p.note_count}
    for role in ROLES:
        for i in chosen.get(role) or []:
            if i not in valid:
                raise ValueError(f"Part {i} doesn't exist or has no notes. Parts: {sorted(valid)}")
            if i in roles:
                raise ValueError(f"Part {i} is listed for both {roles[i]} and {role}; use both=[{i}] to share it between the hands.")
            roles[i] = role
    if not any(r in ("right", "left", "both") for r in roles.values()):
        raise ValueError("Give at least one part to the hands (right, left or both), or clear=True.")
    library.save_hands(score, roles)
    return roles


@mcp.tool()
async def set_parts(
    reference: str,
    right: list[int] | None = None,
    left: list[int] | None = None,
    both: list[int] | None = None,
    pedals: list[int] | None = None,
    vocals: list[int] | None = None,
    clear: bool = False,
) -> dict:
    """Save which parts of a reference the user plays (part indexes from inspect_reference).

    right / left: parts played by that hand; both: parts shared between the hands, split by
    pitch (e.g. a single piano track). pedals: a bass line played with the feet (graded when
    the user practises with hand='<hand>+pedals' or 'pedals'). vocals: the sung line, drawn
    above the piano and never graded. Parts not listed are left out of recording, comparison,
    playback and the score. The choice is remembered for this file. clear=True forgets it.
    """
    try:
        score = await asyncio.to_thread(library.get_score, reference)
        if clear:
            library.save_hands(score, {})
            return {"reference": score.path, "cleared": True, **_part_choice(score)}
        valid = {p.index for p in score.parts if p.note_count}
        hands = _save_parts(score, {"right": right, "left": left, "both": both, "pedals": pedals, "vocals": vocals})
    except Exception as exc:
        return _err(exc)
    names = {p.index: f"{p.index} {p.name} ({p.instrument})" for p in score.parts}
    if hub.url and hub.score_path == score.path and not recorder.active:
        await asyncio.to_thread(_show, library.get_score(score.path), [])  # redraw the sheet for the new parts
    return {
        "reference": score.path,
        "saved": {h: [names[i] for i, v in sorted(hands.items()) if v == h] for h in ROLES},
        "left_out": [names[i] for i in sorted(valid - set(hands))],
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
            _end_pass(state.stop_reason, None, None)
            return
        notes, _ = notes_from_events(state.events)
        meta = library.save_take(state.events, {
            **meta_base,
            "port": state.port_name,
            "stop_reason": state.stop_reason,
            "notes": len(notes),
            "duration_sec": round(max(n.end for n in notes) - notes[0].start, 2),
            **({"t0_perf": state.events[0][0]} if meta_base.get("atlas") else {}),  # the take's zero on the live clock (tap grading)
        })
        _last_take.clear()
        _last_take.update(meta)
        log.info("saved take %s (%d notes, %s)", meta["id"], len(notes), state.stop_reason)
        report = None
        if session is not None:
            # Grade every live pass right away: the page shows its score and heat map and
            # progress() sees each loop pass, whether or not Claude is watching.
            try:
                report = _compare(meta, None, None, None, None, "normal", True)
                _last_take["comparison"] = report
            except Exception as exc:
                log.warning("pass comparison failed: %s", exc)
        if meta.get("atlas"):
            try:
                _atlas.on_pass(meta, report, meta_base.get("live"), state.stop_reason)
            except Exception as exc:
                log.warning("atlas grading failed: %s", exc)
        _end_pass(state.stop_reason, meta_base.get("live"), report)
    return finish


# ---------------------------------------------------------------------------
# Practice runs: one shared session, started by Claude or the coach page's menu
# ---------------------------------------------------------------------------

PAGE_MODES = {"learn": "wait", "rehearse": "rehearsal"}  # and "listen", which records nothing
FINISHED_REASONS = ("finished the piece", "reached the end")
_practice: dict = {"running": False, "settings": None, "port": None, "pass": 0, "last": None, "source": None, "stopping": False}
_begin_lock = threading.Lock()
# Spoken teacher remark after each pass; remembers the run's earlier passes, and keeps its
# style and recent wording in maestro.json between sessions.
_coach = remarks.Coach(memory=lambda: library.profile_home() / "maestro.json")
_autopilot = autopilot.Autopilot()  # "Maestro decides": changes the next loop pass like a teacher would


def _publish_practice(**changes) -> None:
    _practice.update(changes)
    hub.practice({**{k: v for k, v in _practice.items() if k != "stopping"}, "style": _coach.style})


def _cmd_maestro(body: dict) -> dict:
    """The Maestro's style (warm / strict): read it, or set it with {"style": ...}."""
    if body.get("style"):
        _coach.style = str(body["style"]).lower()
        _publish_practice()
    return {"style": _coach.style, "styles": list(remarks.STYLES)}


def _pass_line(summary: dict | None, report: dict | None) -> str | None:
    if not summary:
        return None
    wait = summary["mode"] == "wait"
    parts = [f"{summary['hits']}/{summary['notes_total']} notes"]
    if not wait:
        parts.append(f"{summary['missed']} missed")
    parts.append(f"{summary['wrong_presses']} wrong")
    per_bar = summary.get("per_bar") or {}
    if wait:
        slow = max(per_bar.items(), key=lambda kv: kv[1]["wait_sec"], default=None)
        if slow and slow[1]["wait_sec"] > 0 and len(per_bar) > 1:
            parts.append(f"bar {slow[0]} slowest")
    else:
        worst = max(per_bar.items(), key=lambda kv: kv[1]["wrong"] + kv[1]["missed"], default=None)
        if worst and worst[1]["wrong"] + worst[1]["missed"]:
            parts.append(f"bar {worst[0]} hardest")
    if report and isinstance(report.get("scores"), dict) and report["scores"].get("overall") is not None:
        parts.append(f"score {report['scores']['overall']}")
    label = "Learn" if wait else f"Rehearse {summary['tempo_percent']}%"
    return f"Pass {_practice['pass']} · {label}: " + ", ".join(parts)


def _end_pass(reason: str | None, summary: dict | None, report: dict | None) -> None:
    line = _pass_line(summary, report)
    if line:
        hub.status(line)
    settings = _practice.get("settings") or {}
    again = bool(settings.get("loop")) and reason in FINISHED_REASONS and not _practice["stopping"]
    remark = None
    if reason in FINISHED_REASONS:  # a pass you stopped halfway isn't graded
        try:
            remark = _coach.remark(summary, report)
            if again and settings.get("autopilot"):
                change = _autopilot_step(settings)
                if change:  # how it went, then what changes; the change replaces the advice
                    remark = " ".join(filter(None, [_coach.last_lead, change]))
        except Exception as exc:
            log.warning("Maestro remark failed: %s", exc)
    _npc_say(
        lambda: remark,
        # The run's sign-off follows the last pass (not a pass restarted by undo).
        lambda: None if again or _practice.get("restarting") else _coach.wrap_up(),
    )
    _publish_practice(running=again, last=line or _practice["last"])
    if again:
        threading.Timer(1.5, _next_pass).start()


def _autopilot_step(settings: dict) -> str | None:
    """Let the autopilot change the next pass's settings; returns what the Maestro says about it."""
    last_bar = len(library.get_score(settings["reference"]).bars)
    out = _autopilot.decide(_coach.history, settings, last_bar)
    if not out:
        return None
    changes, said = out
    settings.update(changes)
    return said


_UNDO_RE = re.compile(r"^(no|nope|no thanks|undo|undo that|stop that|cancel that|go back|put it back)$")
_HAND_NAMES = {"both": "both hands", "right": "the right hand", "left": "the left hand"}


def _undo_autopilot() -> str | None:
    """Put back what the autopilot last changed; a pass already running restarts with it."""
    before = _autopilot.undo(len(_coach.history))
    if before is None:
        return None
    settings = _practice.get("settings") or {}
    settings.update(before)
    what = []
    if "mode" in before:
        what.append(_MODE_NAMES.get(before["mode"], before["mode"]))
    if "hand" in before:
        what.append(_HAND_NAMES.get(before["hand"] or "both", before["hand"]))
    if "bars" in before:
        what.append(autopilot._bars_text(before["bars"], len(library.get_score(settings["reference"]).bars)))
    if "tempo_percent" in before and "mode" not in before:
        what.append(f"{round(float(before['tempo_percent']))} percent")
    if recorder.active:
        threading.Thread(target=_restart_pass, daemon=True).start()
    else:
        _publish_practice()
    return "Okay, back to " + " and ".join(what) + "."


def _restart_pass() -> None:
    _practice["stopping"] = _practice["restarting"] = True
    try:
        recorder.stop()
        deadline = time.time() + 3
        while recorder.active and time.time() < deadline:
            time.sleep(0.05)
    finally:
        _practice["restarting"] = False
    try:
        out = _begin_pass(_practice["settings"], max(1, _practice["pass"]))
    except Exception as exc:
        out = {"error": str(exc)}
    if "error" in out:
        hub.status(f"Could not restart the pass: {out['error']}")
        _publish_practice(running=False)


def _npc_say(*lines) -> None:
    """Speak the Maestro's lines (callables returning text or None). Never breaks practice."""
    said = []
    for make in lines:
        try:
            text = make()
        except Exception as exc:
            log.warning("Maestro line failed: %s", exc)
            text = None
        if text:
            said.append(text)
    if said:
        text = " ".join(said)
        _said.append(text)
        del _said[:-3]
        hub.say(text, speaker=remarks.NPC_NAME)


_said: list[str] = []  # the Maestro's latest lines, for the voice chat's context


_TITLE_RE = re.compile(r"<(?:movement-title|work-title)>([^<]+)<")
_FIFTHS_RE = re.compile(r"<fifths>\s*(-?\d+)\s*</fifths>")


def _coach_context(score, hand: str, mode: str, tempo_percent: float) -> dict:
    """What the Maestro knows when you press Start: the piece, its key, your history on it."""
    path = pathlib.Path(score.path)
    title, fifths = None, None
    if path.suffix.lower() in MUSICXML_SUFFIXES - {".mxl"}:
        head = path.read_text(encoding="utf-8", errors="replace")[:20000]
        m = _TITLE_RE.search(head)
        title = m.group(1).strip() if m else None
        m = _FIFTHS_RE.search(head)
        fifths = int(m.group(1)) if m else None
    if not title or title.lower() in ("music21 fragment", "untitled"):
        title = re.sub(r"[-_]+", " ", path.stem).strip().capitalize()
    best, takes, last = None, 0, None
    for t in library.list_takes():
        for c in t.get("comparisons", []):
            if c.get("reference") != score.path or (c.get("hand") or "both") != (hand or "both"):
                continue
            takes += 1
            s = (c.get("scores") or {}).get("overall")
            if s is not None:
                best = s if best is None else max(best, s)
            if c.get("when") and (last is None or c["when"] > last):
                last = c["when"]
    days = None
    if last:
        try:
            days = (time.time() - time.mktime(time.strptime(last, "%Y-%m-%d %H:%M:%S"))) // 86400
        except ValueError:
            pass
    return {"title": title, "mode": mode, "tempo_percent": tempo_percent, "fifths": fifths,
            "best_before": best, "takes_before": takes, "days_away": int(days) if days is not None else None}


def _begin_pass(settings: dict, pass_no: int) -> dict:
    return (_begin_listen if settings.get("mode") == live.LISTEN else _begin)(**settings, pass_no=pass_no)


def _next_pass() -> None:
    if _practice["stopping"] or _busy():
        return
    try:
        _begin_pass(_practice["settings"], _practice["pass"] + 1)
    except Exception as exc:
        hub.status(f"Could not start the next pass: {exc}")
        _publish_practice(running=False)


def _backing_notes(score, hand: str, backing: list[str] | None, bars: str | None, split_note: int) -> list:
    """The notes to sound on the MIDI output during a run: the roles in `backing` ('right',
    'left', 'pedals', 'vocals') that the user isn't playing (`hand`, e.g. 'right+pedals')."""
    base, _, extra = (hand or "both").partition("+")
    played = {"both": {"right", "left"}, "right": {"right"}, "left": {"left"}}.get(base, set()) | {base, extra}
    out = []
    for role in dict.fromkeys(backing or []):
        if role in ("right", "left", "pedals", "vocals") and role not in played:
            out += _selection(score, role, bars, split_note)[0]
    return out


def _start_input(port: str | None, *args) -> tuple[str, bool]:
    """Open the MIDI input; if the keyboard is busy (e.g. the visualizer has it), use 'Coach'."""
    try:
        return recorder.start(port, *args), False
    except PortError:
        if "coach" in (port or os.environ.get("MIDI_COACH_INPUT") or "").lower():
            raise
        try:
            return recorder.start("Coach", *args), True
        except PortError:
            pass
        raise


def _begin(
    reference: str | None,
    hand: str = "both",
    bars: str | None = None,
    mode: str = "free",
    tempo_percent: float = 100.0,
    input_port: str | None = None,
    split_note: int = 60,
    silence_sec: float = 4.0,
    max_minutes: float = 10.0,
    show_score: bool = True,
    loop: bool = False,
    source: str = "claude",
    pass_no: int = 1,
    parts: list[int] | None = None,
    count_in: bool = False,
    autopilot: bool = False,
    backing: list[str] | None = None,
    output_port: str | None = None,
    atlas: dict | None = None,
) -> dict:
    mode = (mode or "free").lower()
    autopilot = autopilot and not atlas  # an Atlas step keeps its own settings
    mode = PAGE_MODES.get(mode, mode)
    if mode not in ("free",) + live.MODES:
        return {"error": "mode must be 'free', 'wait' or 'rehearsal'."}
    if mode != "free" and not reference:
        return {"error": f"{mode} mode needs a reference to follow."}
    if not _begin_lock.acquire(blocking=False):
        return {"error": "A practice run is already starting."}
    try:
        if _busy():
            return {"error": "A practice run is already going. Stop it first."}
        settings = {"reference": reference, "hand": hand, "bars": bars, "mode": mode, "tempo_percent": tempo_percent,
                    "input_port": input_port, "split_note": split_note, "silence_sec": silence_sec,
                    "max_minutes": max_minutes, "show_score": show_score, "loop": loop, "source": source,
                    "parts": parts, "count_in": count_in, "autopilot": autopilot, "backing": backing,
                    "output_port": output_port, "atlas": atlas}
        meta = {"reference": None, "hand": hand, "bars": bars, "split_note": split_note, "mode": mode, "source": source,
                "parts": parts}
        if atlas:
            meta["atlas"] = dict(atlas)  # the step this run belongs to; its verdict is added per pass
        if loop:
            meta["pass"] = pass_no
        rests = None
        selection = None
        session = None
        display_url = None
        score = None
        if reference:
            score = library.get_score(reference)
            if count_in and score.played_live:
                count_in = False  # no beat grid to click along with
                if show_score:
                    hub.flash("Recorded live: no steady beat, so no count-in")
            notes, selection, _ = _selection(score, hand, bars, split_note, parts)
            if not notes:
                return {"error": f"No reference notes for hand={hand} bars={bars}."}
            rests = RestProfile.from_notes(notes)
            meta["reference"] = score.path
            if show_score:
                display_url = _show(score, notes)
            if mode != "free":
                session = live.LiveSession(mode, score, notes, hub if show_score else None, tempo_percent, count_in=count_in,
                                           backing=_backing_notes(score, hand, backing, bars, split_note))
                meta["tempo_percent"] = tempo_percent if mode == "rehearsal" else None
                silence_sec, rests = 300.0, None  # the session decides when the piece is over
            elif show_score:
                hub.status("Recording (free play) · Claude will analyze when you stop")
        recorder.on_finish = _on_recording_finished(meta, session)
        recorder.listener = session.on_message if session else None
        recorder.external_stop = session.should_stop if session else None
        port, fell_back = _start_input(input_port, silence_sec, max_minutes * 60, 120.0, rests)
        if session and session.backing:
            try:
                session.accompanist = Accompanist(output_port)
            except PortError as exc:
                hub.flash("No accompaniment: MIDI output unavailable")
                log.warning("accompaniment off: %s", exc)
        if session:
            session.start()
        _live["session"] = session
        _last_take.clear()
        _practice["stopping"] = False
        _publish_practice(running=True, settings=settings, port=port, source=source, **{"pass": pass_no})
        if pass_no == 1:
            _autopilot.start(settings)
            if session:
                _npc_say(lambda: _coach.start(_coach_context(score, hand, mode, tempo_percent)))
            else:
                _coach.reset()
        if fell_back:
            hub.flash(f"Keyboard busy - listening on {port}")
        return {"mode": mode, "port": port, "port_fallback": fell_back, "reference": meta["reference"],
                "selection": selection, "display": display_url, "rests": rests}
    finally:
        _begin_lock.release()


def _listening() -> bool:
    session = _live["session"]
    return bool(session and session.mode == live.LISTEN and not session.stopped)


def _busy() -> bool:
    """A run is going: a recorded one (Learn, Rehearse, Record, free play) or Listen."""
    return recorder.active or _listening()


def _listen_notes(score, roles: list[str], bars: str | None, split_note: int) -> list:
    picked = {}
    for role in dict.fromkeys(roles):
        if role in ("right", "left", "pedals", "vocals"):
            picked.update((id(n), n) for n in _selection(score, role, bars, split_note)[0])
    return sorted(picked.values(), key=lambda n: (n.start, n.pitch))


def _begin_listen(
    reference: str,
    roles: list[str] | None = None,
    bars: str | None = None,
    tempo_percent: float = 100.0,
    loop: bool = False,
    output_port: str | None = None,
    split_note: int = 60,
    source: str = "page",
    mode: str = live.LISTEN,
    pass_no: int = 1,
) -> dict:
    """Listen: the MIDI output plays the piece (the roles in `roles`, default both hands and
    any pedal part) and the cursor follows. Nothing is played, graded or saved."""
    if not _begin_lock.acquire(blocking=False):
        return {"error": "A practice run is already starting."}
    try:
        if _busy():
            return {"error": "A practice run is already going. Stop it first."}
        score = library.get_score(reference)
        if not roles:
            roles = ["right", "left"] + (["pedals"] if "pedals" in effective_roles(score).values() else [])
        notes = _listen_notes(score, roles, bars, split_note)
        if not notes:
            return {"error": "Nothing to hear there: show at least one part."}
        try:
            accompanist = Accompanist(output_port, pedal=True)
        except PortError as exc:
            return {"error": f"Listen plays the piece on your keyboard's MIDI output: {exc}"}
        settings = {"reference": reference, "roles": roles, "bars": bars, "tempo_percent": tempo_percent, "loop": loop,
                    "output_port": output_port, "split_note": split_note, "source": source, "mode": live.LISTEN}
        _show(score, notes)
        session = live.LiveSession(live.LISTEN, score, notes, hub, tempo_percent, backing=notes,
                                   accompanist=accompanist, pedal=score.pedal)
        session.start()
        _live["session"] = session
        _practice["stopping"] = False
        _publish_practice(running=True, settings=settings, port=accompanist.port, source=source, **{"pass": pass_no})
        threading.Thread(target=_watch_listen, args=(session,), daemon=True).start()
        return {"mode": live.LISTEN, "output": accompanist.port, "reference": score.path, "bars": bars}
    finally:
        _begin_lock.release()


def _watch_listen(session) -> None:
    """End a Listen pass when it reaches the end or is stopped; with Loop, start the next."""
    while not session.done_reason and not session.stopped:
        time.sleep(0.1)
    finished = session.done_reason in FINISHED_REASONS
    session.stop()
    again = bool((_practice.get("settings") or {}).get("loop")) and finished and not _practice["stopping"]
    if finished and not again:
        hub.status(f"{pathlib.Path(session.score.path).stem} · that's the end · pick Learn to play it yourself")
    _publish_practice(running=again)
    if again:
        threading.Timer(1.5, _next_pass).start()


def _cmd_ports(_body: dict) -> dict:
    ports = list_ports()
    names, outputs = ports["inputs"], ports["outputs"]
    try:
        default = names[resolve_port(names, None, "MIDI_COACH_INPUT", "input")]
    except PortError:
        default = None
    try:
        default_output = outputs[resolve_port(outputs, None, "MIDI_COACH_OUTPUT", "output")]
    except PortError:
        default_output = None
    return {"inputs": names, "default": default, "outputs": outputs, "default_output": default_output}


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _history() -> dict[str, dict]:
    """Practice history per file, from the saved takes: {path key: {runs, last, best, latest}};
    best / latest are the overall score (0-100) of graded runs."""
    out: dict[str, dict] = {}
    for t in library.list_takes():  # oldest first
        if not t.get("reference"):
            continue
        h = out.setdefault(_path_key(t["reference"]), {"runs": 0, "last": None, "best": None, "latest": None})
        h["runs"] += 1
        h["last"] = t.get("created") or h["last"]
        overall = next((c["scores"].get("overall") for c in reversed(t.get("comparisons") or []) if c.get("scores")), None)
        if overall is not None:
            h["latest"] = overall
            h["best"] = max(h["best"] or 0, overall)
    return out


def _cmd_lessons(_body: dict) -> dict:
    """Every saved lesson file with its kind ('lesson': exercises; 'song': the rest) and history."""
    listed = lessons.list_lessons()
    history = _history()
    for item in listed:
        item["kind"] = "lesson" if item["category"] in lessons.LESSON_CATEGORIES else "song"
        item["history"] = history.get(_path_key(item["path"]))
    return {"lessons": listed, "categories": lessons.categories(listed), "current": hub.score_path}


SONG_SCAN_SEC = 300.0  # the reference library is scanned again after this long
_song_files: dict = {"at": -SONG_SCAN_SEC, "files": []}


def _cmd_songs(body: dict) -> dict:
    """Search the reference library (not the saved lessons) by title: every word of `query`
    in the file name. No query: the files practised most recently."""
    now = time.monotonic()
    if now - _song_files["at"] > SONG_SCAN_SEC:
        root = _path_key(str(lessons.lessons_dir())) + os.sep
        files = [f for f in library.scan_references() if not _path_key(str(f)).startswith(root)]
        _song_files.update(at=now, files=[(f, library._norm(f.stem)) for f in files])
    files = _song_files["files"]
    history = _history()
    limit = min(int(body.get("limit") or 60), 300)
    words = library._norm(body.get("query") or "").split()
    if words:
        hits = [f for f, name in files if all(w in name for w in words)]
    else:
        recent = sorted((h["last"] or "", key) for key, h in history.items())
        practised = {key for _, key in recent}
        by_key = {_path_key(str(f)): f for f, _ in files if _path_key(str(f)) in practised}
        hits = [by_key[key] for _, key in reversed(recent) if key in by_key]
    return {
        "songs": [{"title": f.stem, "path": str(f), "folder": f.parent.name, "history": history.get(_path_key(str(f)))}
                  for f in hits[:limit]],
        "matches": len(hits), "total": len(files), "current": hub.score_path,
    }


def _cmd_parts(_body: dict) -> dict:
    """The current score's parts with their roles, and which roles it has (the page's Parts menu)."""
    if not hub.score_path:
        return {"path": None, "parts": [], "roles": []}
    score = library.get_score(hub.score_path)
    roles = effective_roles(score)
    parts = [{"index": p.index, "name": p.name, "instrument": p.instrument, "notes": p.note_count,
              "range": f"{note_name(p.low)}-{note_name(p.high)}", "role": roles.get(p.index, "off")}
             for p in score.parts if p.note_count]
    present = set(roles.values())
    return {"path": score.path, "confirmed": bool(score.roles), "parts": parts,
            "roles": ["right", "left"] + [r for r in ("pedals", "vocals") if r in present]}


def _cmd_set_parts(body: dict) -> dict:
    """Save the current score's part roles: {"roles": {"<part index>": role or "off"}}."""
    if _busy():
        return {"error": "Stop the current run before changing the parts."}
    if not hub.score_path:
        return {"error": "Pick a song or lesson first."}
    score = library.get_score(hub.score_path)
    chosen: dict[str, list[int]] = {}
    for index, role in (body.get("roles") or {}).items():
        if role != "off":
            chosen.setdefault(role, []).append(int(index))
    _save_parts(score, chosen)
    _show(library.get_score(score.path), [])  # redraw the sheet for the new parts
    return _cmd_parts({})


def _cmd_load(body: dict) -> dict:
    if _busy():
        return {"error": "Stop the current run before switching lessons."}
    score = library.get_score(body["lesson"])
    _show(score, score.notes)
    tag = lessons.made_from(lessons.source_note(score.path))
    hub.status(f"{pathlib.Path(score.path).stem}{f' ({tag})' if tag else ''} · pick Listen, Learn or Rehearse and press Start")
    return {"path": score.path, "bars": len(score.bars)}


def _cmd_start(body: dict) -> dict:
    if not hub.score_path:
        return {"error": "Pick a lesson first."}
    bars = parse_bars(body.get("bars"))
    if bars:  # the page sends an open-ended range ("5-9999") when only From is set
        last = library.get_score(hub.score_path).bars[-1].number
        if bars[0] > last:
            return {"error": f"This lesson has {last} bars."}
        bars = (bars[0], min(bars[1], last))
    if (body.get("mode") or "").lower() == live.LISTEN:
        return _begin_listen(
            hub.score_path,
            roles=[str(r) for r in body.get("roles") or []] or None,
            bars=f"{bars[0]}-{bars[1]}" if bars else None,
            tempo_percent=float(body.get("tempo") or 100),
            loop=bool(body.get("loop")),
            output_port=body.get("output") or None,
        )
    out = _begin(
        hub.score_path,
        hand=body.get("hand") or "both",
        bars=f"{bars[0]}-{bars[1]}" if bars else None,
        mode=body.get("mode") or "learn",
        tempo_percent=float(body.get("tempo") or 100),
        input_port=body.get("port") or None,
        loop=bool(body.get("loop")),
        source="page",
        count_in=bool(body.get("count_in")),
        autopilot=bool(body.get("autopilot")) and bool(body.get("loop")),
        backing=[str(r) for r in body.get("backing") or []] or None,
        output_port=body.get("output") or None,
    )
    out.pop("rests", None)
    return out


# ---------------------------------------------------------------------------
# Record mode: play over the metronome, get your playing back as sheet music
# ---------------------------------------------------------------------------

RECORD_SILENCE_SEC = 10.0
_record_box: dict = {}  # the running recording's downbeat (perf_counter seconds) and title


def _cmd_record(body: dict) -> dict:
    bpm = min(300.0, max(20.0, float(body.get("bpm") or 80)))
    beats = min(16, max(1, int(body.get("beats") or 4)))
    if not _begin_lock.acquire(blocking=False):
        return {"error": "A practice run is already starting."}
    try:
        if _busy():
            return {"error": "A practice run is already going. Stop it first."}
        beat_sec = 60.0 / bpm
        count_in_beats = beats * (2 if beats * beat_sec < live.MIN_COUNT_IN_SEC else 1)
        meta = {"reference": None, "hand": "both", "mode": "record", "bpm": bpm, "beats_per_bar": beats,
                "split_note": 60, "source": "page"}
        recorder.on_finish = _on_record_finished(meta)
        recorder.listener = None
        recorder.external_stop = None
        port, fell_back = _start_input(body.get("port") or None, RECORD_SILENCE_SEC, 30 * 60, 120.0, None)
        lead = 0.05  # time for the event to reach the page
        _record_box.clear()
        _record_box.update(downbeat=time.perf_counter() + lead + count_in_beats * beat_sec, title=transcribe.default_title())
        hub.metronome({"start_in": lead, "bpm": bpm, "beats": beats, "count_in_beats": count_in_beats})
        _live["session"] = None
        _last_take.clear()
        _practice["stopping"] = False
        _publish_practice(running=True, settings={"mode": "record", "bpm": bpm, "beats": beats, "input_port": body.get("port") or None,
                                                  "source": "page"}, port=port, source="page", **{"pass": 1})
        hub.status(f"Record {round(bpm)} BPM · count-in… then play · press Stop when you're done")
        threading.Timer(lead + count_in_beats * beat_sec, lambda: recorder.active and hub.status(
            f"Recording at {round(bpm)} BPM · press Stop when you're done ({RECORD_SILENCE_SEC:.0f}s of silence also stops)")).start()
        if fell_back:
            hub.flash(f"Keyboard busy - listening on {port}")
        return {"mode": "record", "port": port, "port_fallback": fell_back, "bpm": bpm, "count_in_beats": count_in_beats}
    finally:
        _begin_lock.release()


def _on_record_finished(meta_base: dict):
    def finish(state) -> None:
        hub.metronome(None)
        if not state.events or state.note_ons == 0:
            _last_take.clear()
            _last_take.update({"id": None, "stop_reason": state.stop_reason})
            hub.status("Nothing was recorded.")
            _publish_practice(running=False)
            return
        notes, _ = notes_from_events(state.events)
        downbeat = _record_box.get("downbeat", notes[0].start)
        meta = library.save_take(state.events, {
            **meta_base,
            "port": state.port_name,
            "stop_reason": state.stop_reason,
            "notes": len(notes),
            "duration_sec": round(max(n.end for n in notes) - notes[0].start, 2),
            "downbeat_sec": round(downbeat - state.events[0][0], 4),  # in the take file's time
        })
        _last_take.clear()
        _last_take.update(meta)
        try:
            out = _transcribe_to_lesson(notes, meta_base["bpm"], meta_base["beats_per_bar"], downbeat, _record_box.get("title"))
            line = (f"Recorded {out['bars']} bar{'s' if out['bars'] != 1 else ''} in {out['key']} → “{out['title']}” · "
                    "pick Learn or Rehearse to practise it")
            _last_take["transcription"] = out["path"]
        except Exception as exc:
            log.warning("transcription failed: %s", exc)
            line = f"Saved take {meta['id']}, but couldn't write it out: {exc}"
        hub.status(line)
        _publish_practice(running=False, last=line)
    return finish


def _transcribe_to_lesson(notes, bpm: float, beats_per_bar: int, downbeat: float | None, title: str | None,
                          split_note: int = 60, triplets: str = "auto") -> dict:
    title = title or transcribe.default_title()
    out = transcribe.transcribe(notes, bpm, beats_per_bar, downbeat, split_note, title, triplets)
    folder = lessons.lessons_dir(lessons.RECORDINGS)
    stem = lessons._slug(title)
    path = folder / f"{stem}.musicxml"
    n = 2
    while path.exists():
        path = folder / f"{stem}-{n}.musicxml"
        n += 1
    path.write_text(out["xml"], encoding="utf-8")
    score = library.get_score(str(path))
    _show(score, score.notes)
    return {"path": str(path), "title": title, "bars": out["bars"], "key": out["key"], "notes": out["notes"],
            "dropped_before_downbeat": out["dropped"]}


def _cmd_stop(_body: dict) -> dict:
    _practice["stopping"] = True
    if recorder.active:
        recorder.stop()
    elif _listening():
        _live["session"].stop()  # its watcher publishes the end
    else:
        _publish_practice(running=False)
    return {"stopped": True, "take": _last_take.get("id")}


# ---------------------------------------------------------------------------
# Voice chat: talk to the Maestro from the coach page (optional, Claude API)
# ---------------------------------------------------------------------------

_MODE_NAMES = {"listen": "Listen", "wait": "Learn", "rehearsal": "Rehearse", "free": "free play", "record": "Record"}


def _voice_context() -> str:
    """What Claude sees each turn: the lesson, the run, recent passes, history."""
    settings = _practice.get("settings") or {}
    hand = settings.get("hand") or "both"
    lines = [time.strftime("Local time: %A %I:%M %p.").replace(" 0", " "), f"Teaching style: {_coach.style}."]
    if hub.score_path:
        score = library.get_score(hub.score_path)
        ctx = _coach_context(score, hand, settings.get("mode") or "wait", settings.get("tempo_percent") or 100)
        key = remarks.key_reminder(ctx["fifths"])
        lines.append(f"Lesson on screen: {ctx['title']}, {len(score.bars)} bars"
                     + (f", key signature {key[0]} ({key[1]})" if key else "") + ".")
        if ctx["best_before"] is not None:
            away = f", last played {ctx['days_away']} days ago" if ctx["days_away"] else ""
            lines.append(f"History ({hand} hand{'s' if hand == 'both' else ''}): best score {ctx['best_before']} "
                         f"over {ctx['takes_before']} graded takes{away}.")
        else:
            lines.append(f"History ({hand}): no graded takes yet.")
    else:
        lines.append("No lesson on screen.")
    if settings:
        run = (f"{_MODE_NAMES.get(settings.get('mode'), settings.get('mode'))} mode, hand {hand}, "
               f"bars {settings.get('bars') or 'all'}, tempo {settings.get('tempo_percent')}%, "
               f"loop {'on' if settings.get('loop') else 'off'}"
               + (", the autopilot changes the practice between passes" if settings.get("autopilot") else ""))
        lines.append(f"Run going now ({run}), pass {_practice.get('pass')}." if _practice.get("running")
                     else f"No run going. Last run: {run}.")
    else:
        lines.append("No run going.")
    if _coach.history:
        passes = []
        for i, h in enumerate(_coach.history[-6:], max(1, len(_coach.history) - 5)):
            bits = [h["grade"], f"{h['errors']} mistakes"]
            if h["score"] is not None:
                bits.append(f"score {h['score']}")
            if h["hot_bar"]:
                bits.append(f"worst bar {h['hot_bar']}")
            passes.append(f"pass {i}: " + ", ".join(bits))
        lines.append("This run: " + "; ".join(passes) + ".")
    if _practice.get("last"):
        lines.append(f"Latest pass line on screen: {_practice['last']}.")
    if _said:
        lines.append(f'You (the Maestro) last said: "{_said[-1]}"')
    if _deep.busy:
        lines.append("The senior teacher is still working on the last question you handed off.")
    lines += _atlas.context_lines()
    notes = deep.read_notes(1500)
    if notes:
        lines.append(f"Your notebook on the pianist:\n{notes}")
    return "\n".join(lines)


def _voice_start(mode: str, hand: str = "both", bars: str = "", tempo_percent: int = 100, loop: bool = False) -> dict:
    if _busy():
        _cmd_stop({})
        deadline = time.time() + 3
        while _busy() and time.time() < deadline:
            time.sleep(0.05)
    last = _practice.get("settings") or {}
    return _cmd_start({"mode": mode, "hand": hand, "bars": bars or None, "tempo": tempo_percent, "loop": loop,
                       "port": last.get("input_port"), "count_in": last.get("count_in"), "autopilot": last.get("autopilot"),
                       "roles": [hand] if hand in ("right", "left") else last.get("roles"), "output": last.get("output_port")})


def _voice_play(bars: str = "", hand: str = "both", tempo_percent: int = 100) -> dict:
    if not hub.score_path:
        return {"error": "No lesson on screen."}
    return asyncio.run(play(hub.score_path, bars=bars or None, hand=hand, tempo_percent=tempo_percent))


def _voice_progress() -> dict:
    if not hub.score_path:
        return {"error": "No lesson on screen."}
    out = asyncio.run(progress(hub.score_path))
    keep = ("error", "note", "sessions", "improved_bars", "regressed_bars", "persistent_trouble_bars")
    out = {k: v for k, v in out.items() if k in keep}
    if out.get("sessions"):
        out["sessions"] = [{k: s.get(k) for k in ("when", "hand", "bars", "overall", "notes", "timing")} for s in out["sessions"][-8:]]
    return out


def _voice_create(title: str, right: str = "", left: str = "", time_signature: str = "4/4", key: str = "C", tempo_bpm: int = 80) -> dict:
    out = asyncio.run(create_lesson(title=title, right=right or None, left=left or None, time_signature=time_signature,
                                    key=key, tempo_bpm=tempo_bpm))
    return out


_deep = deep.DeepTeacher(deep.Endpoint(mcp), speak=lambda text: _npc_say(lambda: text))


def _voice_hand_off(question: str) -> dict:
    context = _voice_context()
    if hub.score_path:
        context += f"\nLesson file (the reference for the tools): {hub.score_path}"
    out = _deep.ask(question, context)
    if out.get("handed_off"):
        hub.flash("The Maestro is thinking it over…")
    return out


def _atlas_summary() -> dict:
    """Each grade's progress and mock exam best, the active goal and its next stop."""
    tree, states = _atlas.tree(), _atlas.states()
    grades = []
    for t in tree["tiers"]:
        st, ex = states.get(t["id"]) or {}, states.get(f"{t['id']}.exam") or {}
        grades.append({"grade": t["title"], "known": st.get("done", 0), "of": st.get("total", 0),
                       **({"exam_best": ex["best"]} if ex.get("best") else {})})
    goals = _atlas.goal_state()
    return {"grades": grades, "goal": (goals["goal"] or {}).get("title"), "next_stop": _atlas.next_stop(),
            "planning": goals["planning"]}


def _voice_set_goal(goal: str, song: str = "", artist: str = "") -> dict:
    out = _atlas.cmd_goal_plan({"text": goal, "song": song or None, "artist": artist or None})
    return out if "error" in out else {"planning": True, "note": "The plan arrives in a minute or two; it will be announced."}


def _voice_next_stop() -> dict:
    nxt = _atlas.cmd_path_next({})
    if "error" not in nxt:
        _atlas.publish(open=nxt["stage"])  # the page opens it in the step panel
    return nxt


def _voice_start_exam(grade: str) -> dict:
    out = _atlas.cmd_exam_start({"tier": grade})
    state = out.get("exam") or {}
    return {"exam": state.get("title"), "first_task": (state.get("task") or {}).get("title")}


_voice = chat.VoiceChat(
    actions={
        "start_practice": _voice_start,
        "stop_practice": lambda: _cmd_stop({}),
        "play_passage": _voice_play,
        "progress": _voice_progress,
        "switch_lesson": lambda name: _cmd_load({"lesson": name}),
        "create_lesson": _voice_create,
        "hand_off": _voice_hand_off,
        "remember": deep.remember,
        "set_style": lambda style: _cmd_maestro({"style": style}),
        "set_goal": _voice_set_goal,
        "next_stop": _voice_next_stop,
        "start_exam": _voice_start_exam,
        "atlas_summary": _atlas_summary,
    },
    context=_voice_context,
)


def _voice_reply(heard: str) -> dict:
    """Answer what was said; the reply is spoken and shown by the Maestro on every open page."""
    # "No" / "undo" right after an autopilot change reverses it here, at once and for free.
    if _autopilot.can_undo and _UNDO_RE.match(re.sub(r"[^a-z' ]+", "", (heard or "").lower()).strip()):
        text = _undo_autopilot()
        if text:
            _npc_say(lambda: text)
            return {"heard": heard, "reply": text, "actions": ["undo"], "cost": 0.0}
    try:
        out = _voice.ask(heard)
    except chat.Unavailable as exc:
        return {"error": str(exc), "heard": heard}
    except Exception as exc:  # network, bad key, rate limit...
        log.warning("voice chat failed: %s", exc)
        return {"error": f"The Maestro couldn't answer: {exc}", "heard": heard}
    if out.get("reply"):
        _npc_say(lambda: out["reply"])
    return {"heard": heard, **out}


def _voice_audio(audio: bytes) -> dict:
    try:
        heard = stt.transcribe(audio)
    except stt.Unavailable as exc:
        return {"error": str(exc)}
    if not heard:
        return {"error": "I didn't catch that. Hold the button while you speak.", "heard": ""}
    return _voice_reply(heard)


def _cmd_voice_status(_body: dict) -> dict:
    status = _voice.status()
    if status["available"]:
        stt.warm_up()
    status["deep_available"], status["deep_reason"] = _deep.available()
    return status


def _profile_view() -> dict:
    data = profiles.load()
    return {"active": data["active"], "profiles": data["profiles"], "busy": _busy()}


def _switched_profile() -> dict:
    """Forget what belonged to the last profile: its last take, Maestro memory and Atlas run."""
    _last_take.clear()
    _song_files["at"] = -SONG_SCAN_SEC
    _coach._loaded = False
    _coach._recent = {}
    _coach.reset()
    _atlas.reset()
    return _profile_view()


def _profile_change(action, *args) -> dict:
    if _busy():
        raise ValueError("Stop the run first, then change profile.")
    action(*args)
    return _switched_profile()


def _cmd_profile_new(body: dict) -> dict:
    return _profile_change(profiles.create, body.get("name", ""))


def _cmd_profile_select(body: dict) -> dict:
    return _profile_change(profiles.select, body.get("id", ""))


def _cmd_profile_rename(body: dict) -> dict:
    profiles.rename(body.get("id", ""), body.get("name", ""))
    return _profile_view()


def _cmd_profile_delete(body: dict) -> dict:
    return _profile_change(profiles.delete, body.get("id", ""))


PAGE_COMMANDS = {"ports": _cmd_ports, "lessons": _cmd_lessons, "songs": _cmd_songs, "parts": _cmd_parts,
                 "profiles": lambda _body: _profile_view(), "profile_new": _cmd_profile_new,
                 "profile_select": _cmd_profile_select, "profile_rename": _cmd_profile_rename,
                 "profile_delete": _cmd_profile_delete,
                 "set_parts": _cmd_set_parts, "load": _cmd_load, "start": _cmd_start, "stop": _cmd_stop,
                 "record": _cmd_record, "maestro": _cmd_maestro,
                 "voice_status": _cmd_voice_status, "chat": lambda body: _voice_reply(body.get("text", ""))}
# The Atlas (midi_coach/atlas): its page commands, and grading the steps practised on it.
_atlas = atlas_runtime.AtlasCoach(
    hub,
    show=lambda path: _cmd_load({"lesson": path}),
    begin=lambda path, **kw: _begin(path, source="page", **kw),
    play=lambda path, **kw: asyncio.run(play(path, **kw)),
    compare=lambda meta: _compare(meta, None, None, None, None, "normal", True),
    say=lambda text: hub.say(text, speaker="Examiner"),
)
PAGE_COMMANDS.update(_atlas.page_commands())
hub.commands.update(PAGE_COMMANDS)
hub.voice_handler = _voice_audio
hub.transcribe_handler = lambda audio: {"heard": stt.transcribe(audio)}  # quiz answers said aloud: Whisper only, no API


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
    parts: list[int] | None = None,
    loop: bool = False,
    backing: list[str] | None = None,
) -> dict:
    """Start recording the user's playing from the MIDI input.

    mode: 'free' (just record), 'wait' (cursor waits for the right notes, like Synthesia
      Melody Practice; 'Learn' on the coach page) or 'rehearsal' (cursor moves at
      tempo_percent once the first note is played; notes are graded hit/missed live, like
      Synthesia Song Recital; 'Rehearse' on the page).
      wait/rehearsal need a reference and end automatically at the end of the piece/bars.
    show_score: show the reference on the live sheet-music page (opens the browser if no
      display is connected).
    reference: optional reference title/path; enables rest-aware auto-stop and auto-compare.
    hand: 'both' | 'right' | 'left' - what the user is practicing; add '+pedals' (or just
      'pedals') to include the part played with the feet (set_parts pedals=...).
    bars: e.g. '9-16' to practice a section.
    parts: part indexes to practice for this take only (overrides hand and the saved choice).
    loop: wait/rehearsal only - restart after each completed pass, saving each pass as its own take.
    backing: wait/rehearsal only - roles the user isn't playing to sound on the MIDI output
      along with them ('right', 'left', 'pedals', 'vocals'): in time in rehearsal, the stretch
      up to the next chord each time one is played in wait mode.
    silence_sec: stop after this much silence (no keys held). With a reference the
      timeout is stretched to cover the longest written rest still ahead.
    If the keyboard's port is busy, the 'Coach' loopMIDI port is used instead.
    Recording waits up to 2 minutes for the first note. Then call wait_for_recording.
    """
    try:
        started = await asyncio.to_thread(
            _begin, reference, hand, bars, mode, tempo_percent, input_port, split_note,
            silence_sec, max_minutes, show_score, loop and (mode or "").lower() != "free",
            parts=parts, backing=backing,
        )
    except Exception as exc:
        return _err(exc)
    if "error" in started:
        return started
    mode, port, rests = started["mode"], started["port"], started["rests"]
    selection, display_url = started["selection"], started["display"]
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
        "port": port + (" (keyboard port was busy)" if started["port_fallback"] else ""),
        "reference": started["reference"],
        "selection": selection,
        "display": display_url,
        "auto_stop": auto_stop + ("; then the next pass starts (loop on)" if loop and mode != "free" else ""),
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
    parts = take_meta.get("parts") if score.path == take_meta.get("reference") else None
    ref_notes, selection, bar_range = _selection(score, hand, bars, split_note, parts)
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
        return {"error": "Not recording. Call start_recording, or ask the user to press Start on the coach page."}
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
    if _last_take.get("comparison"):  # live passes are graded as they finish
        out["comparison"] = _last_take["comparison"]
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
async def show_score(reference: str | None = None, hand: str = "both", bars: str | None = None, open_browser: bool = True, split_note: int = 60, parts: list[int] | None = None) -> dict:
    """Show a reference on the live sheet-music page (http://127.0.0.1:8765/) and in the
    web visualizer's notation strip when its Coach link is on. Defaults to the latest take's reference."""
    try:
        if not reference:
            reference = library.get_take("latest").get("reference")
            if not reference:
                return {"error": "No reference given and the latest take has none."}
        score = await asyncio.to_thread(library.get_score, reference)
        notes, selection, _ = _selection(score, hand, bars, split_note, parts)
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


def _publish_lesson(path: str, score, practice_mode: str, tempo_percent: float, autostart: bool, to_visualizer: bool) -> dict:
    hub.start()
    hub.load_score(score)
    hub.marks([], reset=True)
    hub.heat(None)
    hub.status(f"Lesson: {pathlib.Path(path).stem} · pick Listen, Learn or Rehearse and press Start")
    if score.notes:
        hub.cursor(min(n.beat for n in score.notes))
    version = None
    if to_visualizer:
        version = _push_to_visualizer(path, score, practice_mode, tempo_percent, autostart)
    if hub.clients == 0 and not os.environ.get("MIDI_COACH_NO_BROWSER"):
        hub.open_browser()
    return {"lesson_version": version, "viewers_connected": hub.clients}


def _push_to_visualizer(path: str, score, practice_mode: str, tempo_percent: float, autostart: bool) -> int:
    side = analysis.side_resolver(score)
    return hub.lesson({
        "title": pathlib.Path(path).stem,
        "path": path,
        # No sheet for a live recording or a huge file: Learn Mode's falling notes still work.
        "xml": hub.sheet_xml(score),
        "events": lessons.learn_events(score, side),
        "learn_mode": "wait" if practice_mode == "wait" else "freeplay",
        "speed": max(0.1, tempo_percent / 100),
        "autostart": autostart,
    })


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
    to_visualizer: bool = False,
    category: str | None = None,
) -> dict:
    """Create a practice lesson and show it on the coach sheet-music page, where the user
    picks the input, Learn (wait) or Rehearse mode, hand, bars, tempo and loop, and starts.

    Three ways to write it:
    1. right / left: one music21 tinyNotation string per hand (written in the treble / bass clef):
       c d e f g a b = C4..B4; c' = C5, c'' = C6; C = C3, CC = C2. Sharps f#, flats b- (B flat);
       the accidental goes after octave marks: c'# (C#5), not c#'.
       Durations after the pitch: 1 whole, 2 half, 4 quarter, 8 eighth, 16; dots c4.; a note
       without a number reuses the last duration. Rests r4. Ties c2~ c8. Chords chord{C2 E G}
       (duration on the first note). Triplets trip{c8 d e}. Example right hand:
       "g4 a b c' d'2 r4 d'8 c' b1"
    2. musicxml: a complete MusicXML document (for fingerings, dynamics, voices...).
    3. from_reference + bars (+ hand): excerpt of an existing piece, e.g. the user's worst bars.
    key: 'C', 'G', 'Bb', 'F#m', 'Am' (minor with m) or sharps count like -3.
    to_visualizer: also push it into the web visualizer's Learn Mode. practice_mode ('wait' or
      'rehearsal' at tempo_percent) and autostart only apply to that visualizer push.
    category: the group in the page's Songs / Lessons panel (a folder). Default: 'AI exercises' for a lesson you
      compose (right/left or musicxml), 'Exercises' for an excerpt of a real piece. Others:
      'Needs review', 'Solo piano', 'Vocals & accompaniment', 'Recordings', or a new name.
      organize_lesson moves one later.
    Returns the saved path (use it as `reference` for start_recording / compare_take) and a
    bar-by-bar readout - check it matches what you intended before telling the user.
    """
    try:
        if from_reference:
            bar_range = parse_bars(bars)
            if not bar_range:
                return {"error": "from_reference needs bars, e.g. '9-12'."}
            ref_path = str(library.resolve_reference(from_reference))
            path, score = await asyncio.to_thread(lessons.excerpt_lesson, ref_path, bar_range, hand, title, category or lessons.EXERCISES)
        else:
            path, score = await asyncio.to_thread(lessons.build_lesson, title, right, left, time_signature, key, tempo_bpm, musicxml,
                                                  category or lessons.AI_EXERCISES)
        if not score.notes:
            return {"error": "The lesson has no notes.", "path": path}
        side = analysis.side_resolver(score)
        out = {
            "path": path,
            "bars": len(score.bars),
            "notes": {"right": sum(1 for n in score.notes if side(n) == "right"), "left": sum(1 for n in score.notes if side(n) == "left")},
            "duration_sec_at_tempo": round(score.duration, 1),
            "readout": lessons.describe(score, side, None if from_reference or musicxml else lessons.key_spelling(key)),
            "readout_format": "bar: RH note@beat ... | LH ...; chords joined with +",
        }
        if send and recorder.active:
            out["sent"] = {"error": "Not shown: a practice run is going. send_lesson after it ends."}
        elif send:
            out["sent"] = await asyncio.to_thread(_publish_lesson, path, score, practice_mode, tempo_percent, autostart, to_visualizer)
            out["display"] = hub.url
        out["next"] = (
            "The user can start Learn/Rehearse from the page; call wait_for_recording (or "
            f"compare_take('latest')) to coach them. Or start_recording(reference={path!r}, mode='wait')."
        )
        return out
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def send_lesson(lesson: str, practice_mode: str = "wait", tempo_percent: float = 100, autostart: bool = True, to_visualizer: bool = False) -> dict:
    """Show an existing lesson or reference file (title or path) on the coach page (and, with
    to_visualizer, in the visualizer's Learn Mode)."""
    if recorder.active:
        return {"error": "A practice run is going; stop_recording first."}
    try:
        score = await asyncio.to_thread(library.get_score, lesson)
        sent = await asyncio.to_thread(_publish_lesson, score.path, score, practice_mode, tempo_percent, autostart, to_visualizer)
    except Exception as exc:
        return _err(exc)
    return {"path": score.path, "sent": sent, "display": hub.url}


@mcp.tool()
async def make_song_lesson(reference: str, title: str | None = None, melody_part: int | None = None,
                           category: str = "Needs review", show: bool = True) -> dict:
    """Make a song lesson from a band file: its vocal line (with the MIDI file's karaoke
    lyrics, if any) over the piano part the user plays, with time and key signature changes.
    Saved in 'Needs review' (until the user has checked it against the music) with a note on
    where it came from. melody_part: the tune's part index from inspect_reference, when the
    one found from the part names is wrong (check 'vocal' in the result: a sound effect or
    the highest strings is a guess). Report 'check' - the notes read back must equal the
    source's - and that it needs review."""
    from . import songs

    if recorder.active:
        return {"error": "A practice run is going; stop_recording first."}
    try:
        out = await asyncio.to_thread(songs.song_lesson, reference, title, melody_part, category)
        if show:
            score = await asyncio.to_thread(library.get_score, out["path"])
            await asyncio.to_thread(_publish_lesson, out["path"], score, "wait", 100, False, False)
    except Exception as exc:
        return _err(exc)
    return out


@mcp.tool()
async def organize_lesson(lesson: str, category: str, title: str | None = None) -> dict:
    """Move a lesson - or a piece from the reference library - into a category of the page's panel, so
    it is listed under that heading on the coach page. category: 'Solo piano', 'Vocals &
    accompaniment', 'Exercises', 'Recordings' or a new name (a new folder). title renames it.
    Takes and the saved part choice follow the file, so progress history is kept."""
    if recorder.active:
        return {"error": "A practice run is going; stop_recording first."}
    try:
        old = str(library.resolve_reference(lesson))
        new = await asyncio.to_thread(lessons.move_lesson, old, category, title)
    except Exception as exc:
        return _err(exc)
    library._score_cache.pop(old, None)
    if hub.score_path and pathlib.Path(hub.score_path).resolve() == pathlib.Path(old).resolve():
        await asyncio.to_thread(_show, library.get_score(new), [])  # it's on screen: follow it
    listed = lessons.list_lessons()
    return {"path": new, "category": next((x["category"] for x in listed if x["path"] == new), category),
            "menu": {c: [x["title"] for x in listed if x["category"] == c] for c in lessons.categories(listed)}}


@mcp.tool()
async def start_exam(grade: str, fresh: bool = False) -> dict:
    """Start (or resume) a mock exam on the coach page, shaped like a graded piano exam and
    marked out of 150 by the coach (not an exam board): three pieces, scales and arpeggios,
    sight-reading and aural tests. grade: 'initial' or 'g1'..'g8'. An unfinished exam of that
    grade is picked up where it stopped unless fresh=True. The pianist then works through it on
    the page (each task: Begin, play, and the examiner moves on)."""
    hub.start()
    if hub.clients == 0 and not os.environ.get("MIDI_COACH_NO_BROWSER"):
        hub.open_browser()
    try:
        return await asyncio.to_thread(_atlas.cmd_exam_start, {"tier": grade, "fresh": fresh})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def exam_report(exam_id: str | None = None, grade: str | None = None) -> dict:
    """The marks and written report of a finished mock exam (the latest, or of one grade or
    id), plus the exam in progress if there is one. Marks per piece (/30, from pitch, time,
    tone, shape and performance), scales (/21), sight-reading (/21) and aural (/18); pass 100,
    merit 120, distinction 130."""
    out = await asyncio.to_thread(_atlas.cmd_exam_report, {"id": exam_id, "tier": grade})
    out["in_progress"] = (await asyncio.to_thread(_atlas.cmd_exam_state, {}))["exam"]
    return out


@mcp.tool()
async def start_placement(grade: str | None = None, resume: bool = False) -> dict:
    """Find the pianist's level with full mock exams on the coach page, starting at the grade
    they think they're at ('initial', 'g1'..'g8'): each pass climbs a grade until one isn't
    passed; if the first isn't, it steps down until one is. Grades passed are credited in the
    Atlas and the first grade not passed becomes the active goal, its weakest items first.
    resume=True continues a placement under way instead. With no grade and no resume, returns
    where placement stands."""
    hub.start()
    if hub.clients == 0 and not os.environ.get("MIDI_COACH_NO_BROWSER"):
        hub.open_browser()
    try:
        if resume:
            return await asyncio.to_thread(_atlas.cmd_placement_continue, {})
        if grade:
            return await asyncio.to_thread(_atlas.cmd_placement_start, {"tier": grade})
        return await asyncio.to_thread(_atlas.cmd_placement_state, {})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def atlas_overview() -> dict:
    """Where the pianist stands on the Atlas (the ABRSM-style skill tree): each grade's
    requirements known, mock exam bests, the active goal and its next stop."""
    return await asyncio.to_thread(_atlas_summary)


@mcp.tool()
async def atlas_node(node_id: str) -> dict:
    """One node of the Atlas (grade, strand, family, requirement or stage) with its state, its
    stages and, for a stage, its lesson. Ids look like 'g3.technique.scales-ht.scale-...'; find
    them with atlas_overview, list_goals or the page's search."""
    out = await asyncio.to_thread(_atlas.cmd_node, {"id": node_id})
    return out


@mcp.tool()
async def open_node(node_id: str) -> dict:
    """Open a stage's lesson in the coach page's step panel (or show a cluster in the Atlas)."""
    hub.start()
    _atlas.publish(open=node_id)
    return {"opened": node_id}


@mcp.tool()
async def list_goals() -> dict:
    """The pianist's goals, the active one's Path (families in order, each requirement with its
    stages and levels), the planner's status and its reasons and sources."""
    return await asyncio.to_thread(_atlas.goal_state)


@mcp.tool()
async def plan_goal(goal: str, song: str | None = None, artist: str | None = None, research: bool = True) -> dict:
    """Plan a goal on the Atlas with Claude Code on the pianist's subscription, in the
    background (a minute or two; a song longer, as its facts are researched first: Hooktheory
    TheoryTab, then other sources, cross-checked against the file). song: a reference file for
    a song goal. Check list_goals for the result. To plan it yourself instead, use save_goal."""
    return await asyncio.to_thread(_atlas.cmd_goal_plan, {"text": goal, "song": song, "artist": artist, "research": research})


@mcp.tool()
async def save_goal(title: str, kind: str, targets: list[str], reasons: list[str], bridges: list[dict] | None = None,
                    order_hints: list[str] | None = None, song: str | None = None, text: str | None = None) -> dict:
    """Save a goal you planned yourself and make it active. targets: Atlas node ids (requirements,
    families or exams like 'g3.exam'); bridges: at most 5 {title, brief, after: [ids], before: [ids]}
    for skills the tree lacks (their lessons are written in the background); order_hints: targets
    to bring forward; song: a reference file, which becomes the capstone. Checked like the planner's."""
    from .atlas import load_atlas, planner, store as atlas_store, temporary

    plan = {"title": title, "kind": kind, "targets": targets, "bridges": bridges or [], "order_hints": order_hints or [],
            "reasons": reasons}
    base = load_atlas()
    errors = planner.validate(plan, base)
    if errors:
        return {"error": " ".join(errors)}
    score, path = None, None
    if song:
        path = library.resolve_reference(song)
        score = library.get_score(str(path))
    goal = await asyncio.to_thread(planner.build_goal, plan, text or title, base, atlas_store.progress(temporary.merged(base)),
                                   path, score, None, {"by": "Claude Desktop"})
    _atlas.write_bridges()
    _atlas.publish_goals()
    return goal


@mcp.tool()
async def piece_grade(reference: str, bars: str | None = None) -> dict:
    """Estimate a piece's grade (Initial = 0 .. Grade 8) from its measured features: the playing
    from the notes alone, and its length; with the features that pushed it most. bars '5-12'
    grades a passage. A prior, not a verdict: the coach's model is right within a grade about
    half the time."""
    from .atlas import difficulty

    try:
        path = library.resolve_reference(reference)
        span = tuple(int(x) for x in bars.split("-")) if bars else None
        feats = await asyncio.to_thread(difficulty.features, path, span)
        return {"reference": str(path), **difficulty.estimate(feats), "features": feats}
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def rebuild_progress() -> dict:
    """Recompute the Atlas progress from the takes and the event log (after editing them by hand)."""
    return await asyncio.to_thread(_atlas.cmd_progress_rebuild, {})


@mcp.tool()
async def say(text: str, interrupt: bool = False) -> dict:
    """Speak to the user through the coach page (http://127.0.0.1:8765/) with the browser's
    voice, so they hear feedback with their hands on the keys. Keep it to a sentence or two of
    plain words (say "bar 3", not "b.3"). After each Learn/Rehearse pass the page already speaks
    a short strict-teacher remark (verdict, the bar or note that went wrong, one instruction), so
    add what it can't: the bigger picture, musical advice, what to practise next. Don't repeat it.
    interrupt: cut off whatever is still being spoken.
    The user can mute it with the page's Voice switch."""
    text = " ".join(text.split())[:600]
    if not text:
        return {"error": "Nothing to say."}
    url = hub.start()
    if _deep.busy:  # a question the Maestro handed off: the answer is in the Maestro's voice
        _deep.spoken += 1
        _said.append(text)
        del _said[:-3]
        listeners = hub.say(text, interrupt, speaker=remarks.NPC_NAME)
    else:
        listeners = hub.say(text, interrupt)
    if listeners:
        return {"spoken": True, "pages": listeners}
    if not os.environ.get("MIDI_COACH_NO_BROWSER"):
        hub.open_browser()
    return {"spoken": False, "note": f"No coach page was open, so nothing was heard. Opened {url}; ask the user to click the page once (browsers only let a page speak after a click), then say it again."}


@mcp.tool()
async def pianist_notes() -> dict:
    """The Maestro's notebook on the user: goals, pieces they're learning, weak spots, how they
    like to be taught, where the last lesson left off. Read it before a long lesson."""
    return {"notes": deep.read_notes() or "(empty)"}


@mcp.tool()
async def remember(note: str) -> dict:
    """Add one lasting fact about the user to the Maestro's notebook (one short line). The page's
    voice chat reads it too. Not for things that only matter today."""
    return deep.remember(note)


@mcp.tool()
async def maestro_inbox(clear: bool = True) -> dict:
    """Questions the user asked the Maestro at the keyboard that Claude Code couldn't answer
    (not installed, signed out, usage limit), each with the practice context at the time.
    Answer them here; clear=True empties the inbox once read."""
    items = deep.take_inbox(clear)
    return {"questions": items} if items else {"questions": [], "note": "The inbox is empty."}


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
    _practice["stopping"] = True  # also ends a looping run
    await asyncio.to_thread(recorder.stop)
    return await _finished_result(recorder.status(), auto_compare)


@mcp.tool()
async def transcribe_take(
    take: str = "latest",
    bpm: float | None = None,
    beats_per_bar: int | None = None,
    title: str | None = None,
    split_note: int = 60,
    triplets: str = "auto",
) -> dict:
    """Write a take out as sheet music (a two-staff lesson shown on the coach page).

    Takes from the coach page's Record mode carry their metronome tempo and downbeat, so
    they need nothing else. For other takes give bpm if you know it; otherwise it is
    estimated (often off by a factor of two - check the result with the user) and the
    first note is taken as beat 1. triplets: 'auto' | 'never' | 'always'.
    The lesson can then be practised like any other (start_recording(reference=path)).
    """
    try:
        meta = await asyncio.to_thread(library.get_take, take)
        notes, _ = await asyncio.to_thread(library.take_notes, meta)
        if not notes:
            return {"error": "That take has no notes."}
        estimated = False
        downbeat = None
        if bpm is None and meta.get("bpm"):
            bpm = meta["bpm"]
            downbeat = meta.get("downbeat_sec")
        elif bpm is None:
            bpm = transcribe.estimate_bpm(notes)
            estimated = True
        beats = beats_per_bar or meta.get("beats_per_bar") or 4
        out = await asyncio.to_thread(_transcribe_to_lesson, notes, float(bpm), int(beats), downbeat,
                                      title or f"Take {meta['id']}", split_note, triplets)
    except Exception as exc:
        return _err(exc)
    return {**out, "take": meta["id"], "bpm": round(float(bpm), 1), "bpm_estimated": estimated, "beats_per_bar": beats}


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
    return {"takes": rows, "folder": str(library.profile_home() / "takes")}


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


def _take_parts(meta: dict, score) -> list[int] | None:
    """Parts a take was recorded against, if it was against this score."""
    return meta.get("parts") if score.path == meta.get("reference") else None


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
        ref_notes, _ = select_notes(score, meta.get("hand") or "both", parts=_take_parts(meta, score), split_note=split)
        t0, t1, slope = analysis.take_range_for_bars(score, ref_notes, notes, bars)
        t0 = max(notes[0].start, t0 - 0.05)
    if hand in ("right", "left"):
        sides = split_hands(notes, split)
        notes = [n for n in notes if sides[(round(n.start, 4), n.pitch)] == hand]
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
    parts: list[int] | None = None,
) -> dict:
    """Play a reference or a take on the MIDI output (the JUNO by default). Returns immediately.

    source: reference title/path, 'latest', or a take id.
    bars: '9-16'; hand: 'both'|'right'|'left'; tempo_percent: 70 = slower practice speed;
    loops: repeat count (max 20). Notes are sent on `channel` (1-16) without program changes,
    so the keyboard's current sound is used. parts: play only these part indexes of a
    reference (e.g. just the bass line); otherwise the saved part choice, without drums.
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
            notes, _, _ = _selection(score, hand, bars, split_note, parts)
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
        ref_notes, _ = select_notes(score, hand, parts=_take_parts(meta, score), bars=bar_range, split_note=meta.get("split_note") or 60)
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


# ---------------------------------------------------------------------------
# Cross-reference: chord charts, YouTube, the score's own harmony
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_chord_charts(query: str, types: list[str] | None = None, limit: int = 10) -> dict:
    """Search Ultimate Guitar by song/artist. types: chords (default), tabs, bass, ukulele,
    drums, guitar pro; [] searches all. Results are sorted by votes × rating; open one with get_chord_chart."""
    try:
        tabs = await asyncio.to_thread(web.ug_search, query, types)
    except Exception as exc:
        return _err(exc)
    tabs.sort(key=lambda t: -((t["votes"] or 0) * (t["rating"] or 0)))
    return {"query": query, "results": tabs[:limit], "sheet_music": web.sheet_music_links(query)}


@mcp.tool()
async def get_chord_chart(tab_id: int, transpose: int = 0, include_text: bool = True, reference: str | None = None, bars: str | None = None) -> dict:
    """Open an Ultimate Guitar chart: key, capo, chords, progression per section and the
    chord-over-lyrics text. transpose shifts every chord (semitones). With a reference, the
    score's own chords per bar (chords_in_score) are compared to suggest the transpose that
    lines the chart up with the score; chords are as written, so a capo raises the sounding key."""
    try:
        tab = await asyncio.to_thread(web.ug_tab, tab_id)
    except Exception as exc:
        return _err(exc)
    content = tab.pop("content")
    out = {
        **tab,
        "transpose": transpose,
        "chords": web.chart_chords(content, transpose),
        "progression": web.chart_progression(content, transpose),
    }
    if tab["capo"]:
        out["sounding_chords"] = web.chart_chords(content, transpose + tab["capo"])
    if include_text:
        out["text"] = web.chart_text(content, transpose)
    if reference:
        harm = await chords_in_score(reference, bars=bars)
        if "error" in harm:
            out["score_comparison"] = harm
        else:
            out["score_comparison"] = {
                "reference": harm["reference"],
                "score_key": harm["key"],
                "score_chords": harm["distinct"],
                # Values for `transpose` that make the written chart match the score.
                "best_transpose": harmony.best_transpose(
                    [c for sec in web.chart_progression(content) for c in sec["chords"]],
                    [c["chord"] for c in harm["chords"]],
                ),
            }
    return out


@mcp.tool()
async def chords_in_score(reference: str, bars: str | None = None, hand: str = "both", per_bar: int = 1, split_note: int = 60) -> dict:
    """Name the chord in each bar of a reference (or lesson) from its notes, plus an estimated
    key. per_bar=2 or 4 splits each bar into halves or beats (for faster harmonic rhythm, e.g. hymns). 'fit' is how much of
    the sounding notes the chord explains; low fit means melody/passing notes dominate."""
    try:
        score = await asyncio.to_thread(library.get_score, reference)
        notes, selection, bar_range = _selection(score, hand, bars, split_note)
    except Exception as exc:
        return _err(exc)
    key = harmony.estimate_key(notes)
    chords = harmony.chords_by_bar(score, notes, bar_range, max(1, min(per_bar, 4)), key)
    return {
        "reference": score.path,
        "selection": selection,
        "key": key,
        "distinct": list(dict.fromkeys(c["chord"] for c in chords if c["chord"] != "N.C.")),
        "chords": chords,
    }


@mcp.tool()
async def search_youtube(query: str, limit: int = 5) -> dict:
    """Find YouTube videos (recordings, performances, tutorials) for a piece, to hear how it goes
    or compare interpretations. Add words like 'piano tutorial' or 'slow' to the query."""
    try:
        videos = await asyncio.to_thread(web.youtube_search, query, max(1, min(limit, 20)))
    except Exception as exc:
        return _err(exc)
    return {"query": query, "videos": videos}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
