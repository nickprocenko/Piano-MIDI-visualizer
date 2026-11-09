"""midi-coach MCP server: record, analyze, compare and play back piano MIDI.

Run with:  python -m midi_coach   (stdio transport, for Claude Desktop)
"""

from __future__ import annotations

import asyncio
import base64
import json
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

from . import aids, analysis, autopilot, bugs, chat, deep, details, harmony, instruments, lessons, library, live, online, profiles, remarks, sheet, songfind, songwatch, stt, synced, tiles, tracks, transcribe, transcript, web
from .atlas import runtime as atlas_runtime
from .atlas import welcome as atlas_welcome
from .display import DisplayHub, sheet_problem
from .midi_io import MIC_PORT, Accompanist, Player, PortError, Recorder, RestProfile, build_events, list_ports, resolve_port
from .notes import ROLES, MIDI_SUFFIXES, MUSICXML_SUFFIXES, effective_roles, find_part, is_named, is_plain_piano, named_roles, note_name, notes_from_events, parse_bars, select_notes, split_hands, suggest_hands

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
an excerpt of a reference) and shows it on the coach page. Check the returned bar-by-bar
readout against what you meant. Target lessons at the user's weak spots (worst bars, hands, rhythms) and keep
them short.
The coach page has its own menu: input port, Listen / Learn (= wait) / Rehearse (= rehearsal),
hand, bars, tempo, loop, Start/Stop. Listen plays the piece on the MIDI output while the
cursor follows (nothing is played, graded or saved); play does the same without the cursor. Runs started there are the same single session as
start_recording: wait_for_recording returns each finished pass with its comparison, and
looping saves every pass as a take (use progress / list_takes to coach across passes).
After a Learn pass, give feedback on the notes and hesitations it reports.
The page's Record mode records over its metronome and writes what was played out as a
lesson; transcribe_take does the same for any take (e.g. free play), so the user can then
practice their own idea or improvisation.
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
recorder.on_keys = hub.keys  # the falling-notes view lights the keys you hold
_last_take: dict = {}
_live: dict = {"session": None, "watcher": None}
_seek_generation = 0


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
            "numbers (in reports, bars=..., heat maps) are only rough positions, the sheet music is a rough draft "
            "(the coach page's Auto clean can guess a steadier beat and redraw it) and there's no count-in. Learn "
            "mode works fine; refer to places by time or by the notes."} if score.played_live else {}),
        **({"auto_cleaned": True, "timing_note": "No steady beat in the file, so the user turned on Auto clean: bar "
            "numbers and the sheet follow a beat guessed from the playing. Check rhythms by ear."}
           if score.regrid and score.regrid.get("cleaned") else {}),
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
    named = [r for r in chosen if r not in ROLES and r.strip()]
    for role in list(ROLES) + named:
        for i in chosen.get(role) or []:
            if i not in valid:
                raise ValueError(f"Part {i} doesn't exist or has no notes. Parts: {sorted(valid)}")
            if i in roles:
                raise ValueError(f"Part {i} is listed for both {roles[i]} and {role}; use both=[{i}] to share it between the hands.")
            roles[i] = role if role in ROLES else role.strip().lower()
    if not any(r in ("right", "left", "both") or is_named(r) for r in roles.values()):
        raise ValueError("Give at least one part to the hands (right, left or both) or name the part you play, or clear=True.")
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
    named: dict[str, list[int]] | None = None,
    clear: bool = False,
) -> dict:
    """Save which parts of a reference the user plays (part indexes from inspect_reference).

    right / left: parts played by that hand; both: parts shared between the hands, split by
    pitch (e.g. a single piano track). pedals: a bass line played with the feet (graded when
    the user practices with hand='<hand>+pedals' or 'pedals'). vocals: the sung line, drawn
    above the piano and never graded. named: parts named for what the user plays them on,
    {"flute": [4]}: played on their own (hand='flute') with every other part as the backing.
    Parts not listed are left out of recording, comparison,
    playback and the score. The choice is remembered for this file. clear=True forgets it.
    """
    try:
        score = await asyncio.to_thread(library.get_score, reference)
        if clear:
            library.save_hands(score, {})
            return {"reference": score.path, "cleared": True, **_part_choice(score)}
        valid = {p.index for p in score.parts if p.note_count}
        hands = _save_parts(score, {"right": right, "left": left, "both": both, "pedals": pedals, "vocals": vocals, **(named or {})})
    except Exception as exc:
        return _err(exc)
    names = {p.index: f"{p.index} {p.name} ({p.instrument})" for p in score.parts}
    if hub.url and hub.score_path == score.path and not recorder.active:
        await asyncio.to_thread(_show, library.get_score(score.path), [])  # redraw the sheet for the new parts
    return {
        "reference": score.path,
        "saved": {h: [names[i] for i, v in sorted(hands.items()) if v == h] for h in dict.fromkeys([*ROLES, *hands.values()])},
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
        if state.stop_reason == "transport seek":
            _end_pass(state.stop_reason, None, None)
            return
        if not state.events or state.note_ons == 0:
            _last_take.clear()
            _last_take.update({"id": None, "stop_reason": state.stop_reason})
            _atlas.ungraded(meta_base.get("atlas"), "No notes heard, so nothing to grade. Check the keyboard is the input "
                                                    "(Settings), then press Start again.")
            _end_pass(state.stop_reason, None, None)
            return
        notes, _ = notes_from_events(state.events)
        try:
            meta = library.save_take(state.events, {
                **meta_base,
                "port": state.port_name,
                "stop_reason": state.stop_reason,
                "notes": len(notes),
                "duration_sec": round(max(n.end for n in notes) - notes[0].start, 2),
                **({"t0_perf": state.events[0][0]} if meta_base.get("atlas") else {}),  # the take's zero on the live clock (tap grading)
            })
        except Exception as exc:  # the pass still ends (and a loop goes on); only its take is lost
            log.warning("saving the take failed: %s", exc)
            hub.flash(f"Couldn't save that pass ({exc})")
            _end_pass(state.stop_reason, meta_base.get("live"), None)
            return
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
                _atlas.ungraded(meta["atlas"], f"Couldn't grade that pass ({exc}). Try it again.")
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
_aids = aids.Aids(push=hub.aids)  # Sheet ▸ Labels ▸ Coached: note names and counting on the bars you slip on


def _publish_practice(**changes) -> None:
    _practice.update(changes)
    hub.practice({**{k: v for k, v in _practice.items() if k != "stopping"}, "style": _coach.style, "talk": _coach.talk})


def _cmd_maestro(body: dict) -> dict:
    """The Maestro's style (friend / strict) and when it speaks in a run: read them, or set them
    with {"style": ...} and/or {"talk": {"greet": bool, "passes": "every"|"news"|"off", "sign_off": bool}}."""
    if body.get("style"):
        _coach.style = str(body["style"]).lower()
        _publish_practice()
    if isinstance(body.get("talk"), dict):
        _coach.set_talk(**body["talk"])
        _publish_practice()
    return {"style": _coach.style, "styles": list(remarks.STYLES), "talk": _coach.talk,
            "passes": list(remarks.PASS_TALK)}


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
    labels = None
    try:
        changes = _aids.end_pass(reason in FINISHED_REASONS, summary, report)
        if _coach.talk["passes"] != "off":
            labels = aids.remark(changes)
    except Exception as exc:
        log.warning("labels failed: %s", exc)
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
        lambda: labels,
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


def _npc_say(*lines, quiet: bool = True) -> None:
    """Speak the Maestro's lines (callables returning text or None). Never breaks practice.
    An example still playing stops so it isn't talked over, unless quiet=False (the line
    goes with something the Maestro was just asked to play)."""
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
        if quiet:
            _quiet()
        hub.say(text, speaker=remarks.NPC_NAME)


_said: list[str] = []  # the Maestro's latest lines, for the voice chat's context


def _talk_line() -> str:
    t = _coach.talk
    passes = {"every": "after every pass", "news": "after a pass when something is new", "off": "never after a pass"}
    return ("Your own remarks in a run: " + ("a greeting at Start, " if t["greet"] else "no greeting, ")
            + passes[t["passes"]] + (", a sign-off at the end." if t["sign_off"] else ", no sign-off."))


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
        settings = _practice["settings"]
        if settings and settings.get("start_bar") is not None:
            settings["start_bar"] = None
        _begin_pass(settings, _practice["pass"] + 1)
    except Exception as exc:
        hub.status(f"Could not start the next pass: {exc}")
        _publish_practice(running=False)


def _track_lanes(score, bars: str | None, *, mine: list | None = None, skip_part: str | None = None,
                 only: set[int] | None = None, listen: bool = False, voice_all: bool = False,
                 keyboard: bool = False) -> tuple[dict[str, list], dict[str, tuple[int, int | None]], dict[str, float]]:
    """Every track as its own lane for the Accompanist (tracks.py): {lane: notes} within `bars`,
    leaving out the notes the user plays (`mine`) and any track of `skip_part` (a named part),
    or keeping only the notes in `only` (ids). Returns the lanes, each lane's (channel, program)
    and its gain from the track's mix (Listen's mix with `listen`). Drums always sound on
    channel 10 and other instruments as themselves; piano tracks keep the output's own sound
    unless `voice_all` (a band). With a keyboard as the input, nothing is sent on channel 1,
    the one it plays on (a program change there would change its sound)."""
    bar_range = parse_bars(bars)
    t0, t1 = score.bar_range_times(*bar_range) if bar_range else (float("-inf"), float("inf"))
    skip = {id(n) for n in mine or []}
    entries = tracks.mix(score)
    used = {p.channel for p in score.parts}
    spare = [c for c in range(1, 16) if c != 9 and c not in used]
    lanes, voices, gains = {}, {}, {}
    for p in score.parts:
        if p.index not in entries or (skip_part and score.roles.get(p.index) == skip_part):
            continue
        notes = [n for n in score.notes if n.part == p.index and t0 - 1e-6 <= n.start < t1 - 1e-6
                 and id(n) not in skip and (only is None or id(n) in only)]
        if not notes:
            continue
        lane, mix = tracks.key(p.index), entries[p.index]
        lanes[lane] = notes
        gains[lane] = 0.0 if mix["listen_mute" if listen else "mute"] else mix["listen_vol" if listen else "vol"] / 100
        if voice_all or not p.is_piano:
            channel = 9 if p.drums else p.channel
            if keyboard and channel == 0:
                channel = spare.pop(0) if spare else 15
            voices[lane] = (channel, p.program)
    return lanes, voices, gains


SECTION_GAP_BARS = 8  # bars without a note of a part that split it into sections


def part_sections(score, role: str) -> list[tuple[int, int]]:
    """The stretches a named part plays, as (first bar, last bar): a gap of SECTION_GAP_BARS
    or more bars without its notes starts a new one."""
    bars = sorted({score.position(n.start)[0] for n in select_notes(score, role)[0]})
    out: list[tuple[int, int]] = []
    for b in bars:
        if out and b - out[-1][1] <= SECTION_GAP_BARS:
            out[-1] = (out[-1][0], b)
        else:
            out.append((b, b))
    return out


def _lead_in_start(score, first: int, pass_no: int) -> int | None:
    """The bar the backing starts from, before the user's first bar `first`: the file's lead-in
    setting (bars), on the first pass or every pass as set; None for no lead-in."""
    settings = library.song_settings(score.path)
    if not settings["lead_in"] or (pass_no > 1 and not settings["lead_in_every_pass"]):
        return None
    return max(1, first - settings["lead_in"]) if first > 1 else None


def _gains(gains) -> dict[str, float]:
    """The page's part faders, {role: 0..1} (0 is muted)."""
    out = {}
    for role, value in (gains or {}).items():
        try:
            out[str(role)] = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
    return out


def _start_input(port: str | None, *args) -> tuple[str, bool]:
    """Open the MIDI input; if the keyboard is busy (e.g. the visualizer has it), use 'Coach'.
    A flute, saxophone or voice profile listens on the microphone unless a port is named."""
    port = port or (MIC_PORT if instruments.uses_mic() else None)
    if port == MIC_PORT:
        return recorder.start(port, *args), False
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
    output_port: str | None = None,
    atlas: dict | None = None,
    start_bar: int | None = None,
    gains: dict[str, float] | None = None,
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
        _quiet()  # an example still playing would be heard as your playing (a flute's microphone)
        settings = {"reference": reference, "hand": hand, "bars": bars, "mode": mode, "tempo_percent": tempo_percent,
                    "input_port": input_port, "split_note": split_note, "silence_sec": silence_sec,
                    "max_minutes": max_minutes, "show_score": show_score, "loop": loop, "source": source,
                    "parts": parts, "count_in": count_in, "autopilot": autopilot,
                    "output_port": output_port, "atlas": atlas, "start_bar": start_bar, "gains": gains}
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
        voices, level = {}, {}
        if reference:
            score = library.get_score(reference)
            if hand == "both" and not parts and named_roles(score) and not score.hands:
                hand = settings["hand"] = meta["hand"] = library.default_part(score)
            score.playing = hand if is_named(hand) else None if score.hands else score.playing
            if is_named(hand) and not bars and start_bar is None:
                sections = part_sections(score, hand)
                if len(sections) == 1:
                    bars = settings["bars"] = meta["bars"] = f"{sections[0][0]}-{sections[0][1]}"
            if count_in and score.played_live:
                count_in = False  # no beat grid to click along with
                if show_score:
                    hub.flash("Recorded live: no steady beat, so no count-in")
            picked, selection, _ = _selection(score, hand, bars, split_note, parts)
            notes = _from_bar(score, picked, start_bar)
            if not notes:
                return {"error": f"No reference notes for hand={hand} bars={bars}."}
            rests = RestProfile.from_notes(notes)
            meta["reference"] = score.path
            if show_score:
                display_url = _show(score, notes)
            if mode != "free":
                labeled = not (atlas and atlas.get("exam"))  # a mock exam is played without labels
                if labeled:
                    _aids.begin_pass(score, {score.position(n.start)[0] for n in notes})
                elif show_score:
                    hub.aids([], off=True)
                bar_range = parse_bars(bars)
                first = bar_range[0] if bar_range else score.position(min(n.start for n in picked))[0]
                lead_bar = None if start_bar is not None else _lead_in_start(score, first, pass_no)
                last = (bar_range or (1, len(score.bars)))[1]
                band, voices, level = _track_lanes(score, f"{lead_bar}-{last}" if lead_bar else bars, mine=picked,
                                                   skip_part=hand if is_named(hand) else None, voice_all=bool(named_roles(score)),
                                                   keyboard=not instruments.uses_mic())
                level.update(_gains(gains))
                if lead_bar and not any(level.get(k, 1.0) > 0 for k in band):
                    lead_bar = None  # every backing track muted: nothing to lead in with
                    band = {k: [n for n in v if n.start >= score.bars[first - 1].start - 1e-6] for k, v in band.items()}
                lead_in = score.bars[lead_bar - 1].start if lead_bar else None
                if is_named(hand) and pass_no == 1:
                    played = library.song_settings(score.path)["played"]
                    library.save_song_settings(score.path, played={**played, hand: played.get(hand, 0) + 1})
                lanes = {role: _from_bar(score, part, start_bar) for role, part in band.items()}
                session = live.LiveSession(mode, score, notes, hub if show_score else None, tempo_percent, count_in=count_in,
                                           backing=lanes, on_slip=_aids.slip if labeled else None, lead_in=lead_in)
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
                session.accompanist.voices(voices)
                session.accompanist.gains.update(level)
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
            if session and mode == "wait":
                _coach.start(_coach_context(score, hand, mode, tempo_percent))  # Learn starts silently
            elif session:
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


def _from_bar(score, notes: list, start_bar: int | None) -> list:
    if start_bar is None:
        return notes
    bar = next((bar for bar in score.bars if bar.number == start_bar), None)
    if bar is None:
        return []
    return [note for note in notes if note.start >= bar.start - 1e-6]


def _listen_notes(score, roles: list[str], bars: str | None, split_note: int) -> list:
    picked = {id(n): n for part in _listen_lanes(score, roles, bars, split_note).values() for n in part}
    return sorted(picked.values(), key=lambda n: (n.start, n.pitch))


def _listen_lanes(score, roles: list[str], bars: str | None, split_note: int) -> dict[str, list]:
    """Listen's notes by role, each note in the first role that has it (so it sounds once)."""
    seen, lanes = set(), {}
    for role in dict.fromkeys(roles):
        if role in ROLES or is_named(role):
            lanes[role] = [n for n in _selection(score, role, bars, split_note)[0] if id(n) not in seen]
            seen.update(id(n) for n in lanes[role])
    return lanes


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
    start_bar: int | None = None,
    gains: dict[str, float] | None = None,
) -> dict:
    """Listen: the MIDI output plays the piece, every track at its Listen mix (tracks.py; `gains`,
    {lane: 0..1}, overrides it), or only the notes of `roles` when given (a lesson's Listen step:
    ['right']), and the cursor follows what sounds. Nothing is played, graded or saved."""
    if not _begin_lock.acquire(blocking=False):
        return {"error": "A practice run is already starting."}
    try:
        if _busy():
            return {"error": "A practice run is already going. Stop it first."}
        _quiet()
        score = library.get_score(reference)
        only = {id(n) for n in _listen_notes(score, roles, bars, split_note)} if roles else None
        band, voices, level = _track_lanes(score, bars, only=only, listen=True, voice_all=bool(named_roles(score)),
                                           keyboard=not instruments.uses_mic())
        level.update(_gains(gains))
        if band and all(level.get(k, 1.0) <= 0 for k in band):
            return {"error": "Every track is muted: unmute one to hear it."}
        lanes = {k: _from_bar(score, v, start_bar) for k, v in band.items()}  # a muted track is there to turn up mid-run
        notes = sorted((n for k, part in lanes.items() if level.get(k, 1.0) > 0 for n in part), key=lambda n: (n.start, n.pitch))
        if not notes:
            return {"error": "Nothing to hear there."}
        try:
            accompanist = Accompanist(output_port, pedal=True)
        except PortError as exc:
            return {"error": f"Listen plays the piece on your keyboard's MIDI output: {exc}"}
        accompanist.voices(voices)
        accompanist.gains.update(level)
        settings = {"reference": reference, "roles": roles, "bars": bars, "tempo_percent": tempo_percent, "loop": loop,
                    "output_port": output_port, "split_note": split_note, "source": source, "mode": live.LISTEN,
                    "start_bar": start_bar, "gains": gains}
        _show(score, notes)
        session = live.LiveSession(live.LISTEN, score, notes, hub, tempo_percent, backing=lanes,
                                   accompanist=accompanist, pedal=score.pedal)
        session.start()
        _live["session"] = session
        _practice["stopping"] = False
        _publish_practice(running=True, settings=settings, port=accompanist.port, source=source, **{"pass": pass_no})
        watcher = threading.Thread(target=_watch_listen, args=(session,), daemon=True)
        _live["watcher"] = watcher
        watcher.start()
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
    try:
        ports = list_ports()
    except PortError:  # no MIDI at all: a flute, sax or voice still has the microphone
        ports = {"inputs": [], "outputs": []}
    names, outputs = ports["inputs"], ports["outputs"]
    try:
        default = names[resolve_port(names, None, "MIDI_COACH_INPUT", "input")]
    except PortError:
        default = None
    names = names + [MIC_PORT]
    if instruments.uses_mic():
        default = MIC_PORT
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
    return {"lessons": listed, "categories": lessons.categories(listed), "standard": list(lessons.CATEGORIES),
            "current": hub.score_path}


def _cmd_open_file(body: dict) -> dict:
    """File → Open: a MIDI or MusicXML file from the computer, kept among the lessons and shown."""
    if _busy():
        return {"error": "Stop the current run before opening a file."}
    data = base64.b64decode(body.get("data") or "")
    if not data:
        return {"error": "That file is empty."}
    path = lessons.import_file(str(body.get("name") or "Opened file.mid"), data)
    try:
        return _cmd_load({"lesson": path})
    except Exception as exc:
        os.remove(path)
        return {"error": f"Couldn't read {pathlib.Path(path).name}: {exc}"}


def _cmd_save_as(body: dict) -> dict:
    """File → Save as: a copy of the sheet on the page, under a new name and category."""
    if not hub.score_path:
        return {"error": "There's no sheet to save yet."}
    title = (body.get("title") or "").strip()
    if not title:
        return {"error": "Give the copy a name."}
    path = lessons.copy_lesson(hub.score_path, (body.get("category") or "").strip() or lessons.UNSORTED, title)
    return {"path": path, "category": body.get("category") or lessons.UNSORTED}


SONG_SCAN_SEC = 300.0  # the reference library is scanned again after this long
_song_files: dict = {"at": -SONG_SCAN_SEC, "files": []}


def _songs_arrived(songs: list[dict]) -> None:
    """songwatch.py found new songs (a download, a file dropped into a song folder): the next
    search sees them, and the page says so."""
    _song_files["at"] = -SONG_SCAN_SEC
    hub.songs_added(songs)


def _cmd_rescan(_body: dict) -> dict:
    """File → Song folders → Rescan now: forget the cached list of songs."""
    _song_files["at"] = -SONG_SCAN_SEC
    return {"total": _cmd_songs({})["total"]}


def _cmd_songs(body: dict) -> dict:
    """Search the reference library (not the saved lessons) by title: every word of `query`
    in the file name. No query: the files practiced most recently."""
    songwatch.start(_songs_arrived)  # the page asks for songs as it opens: from then on, new ones are noticed
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


def _cmd_songs_online(body: dict) -> dict:
    """The Songs panel's "Search bitmidi.com": songs there whose names match `query`."""
    if not library.song_sources()["online"]:
        return {"error": "Online search is off. Turn it on in File → Song folders."}
    query = (body.get("query") or "").strip()
    return {"query": query, "songs": online.search(query) if query else []}


def _cmd_fetch_online(body: dict) -> dict:
    """Download a bitmidi.com song into the library and open it."""
    if _busy():
        return {"error": "Stop the current run before opening another song."}
    path = online.download(int(body.get("id") or 0))
    _song_files["at"] = -SONG_SCAN_SEC  # the next search sees the new file
    return _cmd_load({"lesson": path})


def _cmd_set_song_sources(body: dict) -> dict:
    """File → Song folders: save the folders searched for songs and the online switch."""
    sources = library.set_song_sources(body.get("folders"), body.get("online"), body.get("watch_downloads"))
    _song_files["at"] = -SONG_SCAN_SEC
    return sources


def _cmd_pick_folder(_body: dict) -> dict:
    """File → Song folders → Browse: Windows' own folder picker (the page can't see paths)."""
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:
        return {"error": "No folder picker here. Paste the folder's path instead."}
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        folder = filedialog.askdirectory(parent=root, title="Choose a folder of songs (MIDI or MusicXML)", mustexist=True)
    finally:
        root.destroy()
    return {"folder": os.path.normpath(folder) if folder else ""}


def _play_choices(score) -> list[str]:
    """What the user can pick to play on this file (the Playing menu's You play): the hands
    (with the pedals when a part is for the feet), then each named part."""
    roles = set(effective_roles(score).values())
    right, left = bool(roles & {"right", "both"}), bool(roles & {"left", "both"})
    hands = (["both"] if right and left else []) + (["right"] if right else []) + (["left"] if left else [])
    if "pedals" in roles:
        hands = hands + [f"{h}+pedals" for h in hands] + ["pedals"]
    return hands + named_roles(score)


def _play_choice(score) -> str:
    """What the user plays on this file unless told otherwise: the last pick, else the part
    the file opens on, else the first choice."""
    choices = _play_choices(score)
    saved = library.song_settings(score.path)["play"]
    if saved in choices:
        return saved
    if score.playing in choices:
        return score.playing
    return choices[0] if choices else "both"


def _cmd_parts(_body: dict) -> dict:
    """The current score's tracks for the Playing menu: each with its part and mix (tracks.py),
    what can be played (choices) and what is (play), and the song's lead-in."""
    if not hub.score_path or not os.path.isfile(hub.score_path):  # none yet, or its file was deleted since
        return {"path": None, "tracks": [], "choices": [], "play": None}
    score = library.get_score(hub.score_path)
    play = _play_choice(score)
    song = library.song_settings(score.path)
    return {"path": score.path, "confirmed": bool(score.roles), "tracks": tracks.describe(score, play),
            "choices": _play_choices(score), "play": play, "named": named_roles(score), "playing": score.playing,
            "song": {"lead_in": song["lead_in"], "lead_in_every_pass": song["lead_in_every_pass"]}}


def _cmd_song_settings(body: dict) -> dict:
    """The Playing / Playback menus' per-song settings: {"play": what you play ('both',
    'right+pedals', 'flute'...), "lead_in": bars, "lead_in_every_pass": bool} (any of them)."""
    if not hub.score_path:
        return {"error": "Pick a song or lesson first."}
    score = library.get_score(hub.score_path)
    play = body.get("play", body.get("playing"))
    if play is not None:
        if _busy():
            return {"error": "Stop the current run before changing what you play."}
        if play not in _play_choices(score):
            return {"error": f"Nothing called {play!r} to play in this piece."}
        library.save_song_settings(score.path, play=play)
        if is_named(play) or score.playing:
            score.playing = play if is_named(play) else None
            _show(score, [])  # redraw the sheet for that part
    changes = {k: body[k] for k in ("lead_in", "lead_in_every_pass") if k in body}
    if changes:
        library.save_song_settings(score.path, **changes)
    return _cmd_parts({})


def _cmd_practice_settings(body: dict) -> dict:
    """The Session's bars, tempo, loop and mode for a piece, {"path", "from", "to", "tempo",
    "loop", "mode"}, saved so the piece opens that way next time (library.practice_settings).
    The page names the piece, so a change saved just as another piece opens lands on the right one."""
    path = body.get("path") or hub.score_path
    if not path or not os.path.isfile(path):
        return {"error": "Pick a song or lesson first."}
    library.save_song_settings(path, practice={k: body[k] for k in ("from", "to", "tempo", "loop", "mode") if k in body})
    return {"path": path, "practice": library.practice_settings(path)}


def _live_gain(index: int, mix: dict) -> None:
    """A track's mix changed: a run going now hears it from its next note (Listen from the
    Listen mix), and an override it started with gives way."""
    session = _live.get("session")
    accompanist = session and session.accompanist
    lane = tracks.key(index)
    listen = bool(session) and session.mode == live.LISTEN
    gain = 0.0 if mix["listen_mute" if listen else "mute"] else mix["listen_vol" if listen else "vol"] / 100
    if accompanist and lane in session.lanes:
        accompanist.gains[lane] = gain
    settings = _practice.get("settings")
    if settings and lane in (settings.get("gains") or {}):
        settings["gains"][lane] = gain


def _cmd_track(body: dict) -> dict:
    """One track changed in the Playing menu: {"index": track, "part": a part or 'backing',
    "show", "mute", "vol", "listen_mute", "listen_vol"} (any of them). Saved for the file at
    once. The mix is heard live; the part and Show wait for the run to stop."""
    if not hub.score_path:
        return {"error": "Pick a song or lesson first."}
    try:
        index = int(body["index"])
    except (KeyError, TypeError, ValueError):
        return {"error": "Which track?"}
    score = library.get_score(hub.score_path)
    changes = {k: body[k] for k in tracks.MIX_KEYS if k in body}
    if ("part" in body or "show" in changes) and _busy():
        return {"error": "Stop the run to change that."}
    try:
        if "part" in body:
            tracks.set_part(score, index, str(body["part"]))
            if score.playing and score.playing not in named_roles(score):
                score.playing = None
        if changes:
            _live_gain(index, tracks.set_mix(score, index, **changes))
    except ValueError as exc:
        return {"error": str(exc)}
    if "part" in body or ("show" in changes and tracks.part_of(score, index) == tracks.BACKING and sheet.wanted(score)):
        _show(score, [])  # redraw the sheet: new parts, or a backing track's staff written in or out
        # (any other Show is the page's: it hides a staff that's there)
    return _cmd_parts({})


def _cmd_confirm_parts(_body: dict) -> dict:
    """The suggested parts are right: save them as the user's own."""
    if not hub.score_path:
        return {"error": "Pick a song or lesson first."}
    if _busy():
        return {"error": "Stop the current run before changing the parts."}
    tracks.confirm(library.get_score(hub.score_path))
    return _cmd_parts({})


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


def _cmd_cleanup(body: dict) -> dict:
    """Turn Auto clean on or off for the current score: {"on": bool}. For a MIDI file with no
    reliable beat, it redraws the sheet on a beat followed from the playing."""
    if _busy():
        return {"error": "Stop the current run before cleaning up the sheet."}
    if not hub.score_path:
        return {"error": "Pick a song or lesson first."}
    on = bool(body.get("on"))
    library.set_cleanup(hub.score_path, on)
    score = library.get_score(hub.score_path)
    if on and not (score.regrid and score.regrid.get("cleaned")):
        library.set_cleanup(hub.score_path, False)
        return {"error": "Auto clean couldn't find a steadier beat than the file's own, so the sheet stays as it was."}
    _show(score, [])
    return {"cleanup": "on" if on else "off"}


def _cmd_playable(body: dict) -> dict:
    """Turn Clean on or off for the current score: {"on": bool}. On, the parts the hands play
    are made playable (playable.py) and the sheet is redrawn and checked against the
    readability rules (engraving.py). Returns {"playable": "on" | "off", "summary", "check"}."""
    from . import engraving, playable

    if _busy():
        return {"error": "Stop the current run before cleaning the sheet."}
    if not hub.score_path:
        return {"error": "Pick a song or lesson first."}
    if pathlib.Path(hub.score_path).suffix.lower() not in MIDI_SUFFIXES:
        return {"error": "Clean works on MIDI files; this sheet is written out already."}
    on = bool(body.get("on"))
    library.set_playable(hub.score_path, on)
    score = library.get_score(hub.score_path)
    summary = score.clean["summary"] if score.clean else None
    if on and not score.clean["changes"]:
        library.set_playable(hub.score_path, False)  # nothing to change: stay on the file's own notes
        score = library.get_score(hub.score_path)
    _show(score, [])
    check = None
    if on:
        xml = hub.sheet_xml(score)
        found = engraving.lint(xml)["findings"] if xml else []
        bars = sorted({bar for _, _, bar, _ in found if bar})
        rules = sorted({rule.replace("-", " ") for rule, *_ in found})
        check = (f"Still hard to read in {playable._bars_text(bars)} ({', '.join(rules)})." if bars
                 else "Sheet check: nothing hard to read." if xml else None)
    return {"playable": "on" if score.clean else "off", "summary": summary, "check": check}


DETAILS_WAIT_SEC = 30 * 60  # finished details wait this long for a run to stop before the sheet is redrawn


def _cmd_details(body: dict) -> dict:
    """Add chord symbols, Roman numerals, lyrics and section names to the current sheet:
    what the file shows straight away, then the song looked up on the subscription
    (details.py, a few minutes). {"refresh": true} looks it up again."""
    if not hub.score_path:
        return {"error": "Pick a song or lesson first."}
    if not details.offered(hub.score_path):
        return {"error": "Chords and lyrics are for songs; this is an exercise."}
    score = library.get_score(hub.score_path)

    def finished(path: str) -> None:
        # Redraw once nothing is being played, so a run's marks aren't wiped mid-pass.
        deadline = time.time() + DETAILS_WAIT_SEC
        while _busy() and time.time() < deadline:
            time.sleep(2)
        if hub.score_path == path and not _busy():
            hub.load_score(library.get_score(path))
            hub.status(details.status(path).get("note") or "")

    out = details.start(score, refresh=bool(body.get("refresh")), done=finished)
    if not _busy():
        hub.load_score(score)  # the file's own chords and lyrics, and 'Looking up…'
    return out


def _cmd_synced(body: dict) -> dict:
    """Play along with a recording (synced.py): the current song's video and how it lines up.
    {"link": url} picks the video, {"search": query or ""} finds videos (the song's title if
    empty), {"taps": [video secs], "bar": n} saves downbeats tapped from bar n, {"nudge": video
    secs} puts the nearest bar line there, {"clear": true} forgets the taps, {"loop": {from, to,
    on}} sets the bars to repeat. Used by the coach page's video panel and the YouTube extension."""
    if not hub.score_path:
        return {"error": "Pick a song first."}
    score = library.get_score(hub.score_path)
    if "search" in body:
        query = str(body.get("search") or "").strip() or pathlib.Path(score.path).stem.replace("_", " ")
        try:
            return {"query": query, "results": web.youtube_search(query, 6)}
        except web.WebError as exc:
            return {"error": f"Couldn't search YouTube: {exc}"}
    entry = synced.load(score.path)
    bar = None
    if "link" in body:
        vid = synced.video_id(str(body.get("link") or ""))
        if not vid:
            return {"error": "That doesn't look like a YouTube link."}
        entry = synced.set_video(score.path, vid, body.get("title"))
    elif body.get("taps"):
        if not entry["video"]:
            return {"error": "Choose a video first."}
        entry = synced.save(score.path, synced.add_taps(score, entry, [float(t) for t in body["taps"]], int(body.get("bar") or 1)))
    elif body.get("nudge") is not None:
        entry, bar = synced.nudge(score, entry, float(body["nudge"]))
        entry = synced.save(score.path, entry)
    elif body.get("clear"):
        entry = synced.save(score.path, {**entry, "anchors": []})
    elif isinstance(body.get("loop"), dict):
        loop = body["loop"]
        entry = synced.save(score.path, synced.set_loop(score, entry, loop.get("from"), loop.get("to"), loop.get("on")))
    out = synced.view(score, entry)
    if bar:
        out["nudged"] = bar.number
    return out


def _cmd_youtube(body: dict) -> dict:
    """The YouTube tab: whether the extension is talking to the coach, where its folder is,
    the song open now with its video, and every song synced to a video. {"reveal": true}
    opens the extension's folder in Explorer, for Load unpacked."""
    folder = synced.EXTENSION_DIR
    if body.get("reveal"):
        if not hasattr(os, "startfile"):
            return {"error": f"Open this folder yourself: {folder}"}
        os.startfile(folder)
    song = None
    if hub.score_path:
        score = library.get_score(hub.score_path)
        view = synced.view(score, synced.load(score.path))
        song = {key: view[key] for key in ("path", "title", "video", "taps", "tapped", "bpm")}
    current = synced.key(hub.score_path) if hub.score_path else None
    videos = [{**entry, "current": synced.key(entry["path"]) == current} for entry in synced.saved()]
    return {"extension": synced.extension_status(hub.extension), "folder": str(folder), "song": song, "videos": videos}


def _cmd_synced_cursor(body: dict) -> dict:
    """The video's position as a beat: {beat, bps}. The cursor follows it on the coach page
    and the visualizer's strip (bps 0 parks it, when the video pauses)."""
    if _busy():
        return {"error": "Stop the practice run to follow the video."}
    hub.cursor(float(body.get("beat") or 0), max(0.0, float(body.get("bps") or 0)), live=True)
    return {}


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
            start_bar=int(body["start_bar"]) if body.get("start_bar") is not None else None,
            gains=_gains(body.get("gains")) or None,
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
        output_port=body.get("output") or None,
        start_bar=int(body["start_bar"]) if body.get("start_bar") is not None else None,
        gains=_gains(body.get("gains")) or None,
    )
    out.pop("rests", None)
    return out


def _cmd_mix(body: dict) -> dict:
    """Gains for the run going now, {"gains": {lane: 0..1}} (a lane is a track, tracks.key):
    heard from the next note and kept for its next pass, not saved (the Playing menu saves a
    track's mix through cmd/track)."""
    gains = _gains(body.get("gains"))
    session = _live.get("session")
    accompanist = session and session.accompanist
    if accompanist:
        accompanist.gains.update(gains)
    settings = _practice.get("settings")
    if settings is not None and gains:
        settings["gains"] = {**(settings.get("gains") or {}), **gains}
    return {"gains": gains, "live": bool(accompanist)}


def _restart_at_bar(settings: dict, pass_no: int, generation: int | None = None) -> None:
    _practice["stopping"] = _practice["restarting"] = True
    try:
        session = _live.get("session")
        if session and session.mode == live.LISTEN:
            if not session.stopped:
                session.stop()
            watcher = _live.get("watcher")
            if watcher and watcher is not threading.current_thread():
                watcher.join(timeout=3)
                if watcher.is_alive():
                    raise RuntimeError("The previous Listen session did not stop in time.")
        else:
            recorder.stop("transport seek")
            if not recorder.wait(5):
                raise RuntimeError("The previous practice session did not stop in time.")
    except Exception as exc:
        hub.status(f"Could not seek: {exc}")
        _publish_practice(running=False)
        _practice["stopping"] = False
        _practice["restarting"] = False
        return
    if generation is not None and generation != _seek_generation:
        return
    _practice["restarting"] = False
    try:
        out = _begin_pass(settings, pass_no)
    except Exception as exc:
        out = {"error": str(exc)}
    if generation is not None and generation != _seek_generation and _practice.get("settings") is settings:
        _practice["stopping"] = True
        if settings.get("mode") == live.LISTEN:
            session = _live.get("session")
            if session:
                session.stop()
        else:
            recorder.stop()
        return
    if "error" in out:
        hub.status(f"Could not seek: {out['error']}")
        _practice["stopping"] = False
        _publish_practice(running=False)


def _cmd_seek(body: dict) -> dict:
    global _seek_generation
    if not hub.score_path:
        return {"error": "Pick a lesson first."}
    try:
        bar_number = int(body.get("bar"))
    except (TypeError, ValueError):
        return {"error": "Choose a valid bar."}
    score = library.get_score(hub.score_path)
    if not any(bar.number == bar_number for bar in score.bars):
        return {"error": f"This lesson has no bar {bar_number}."}
    settings = _practice.get("settings") or {}
    bars = parse_bars(settings.get("bars")) if settings and _practice.get("running") else None  # a past run's bars don't hold
    if bars and not bars[0] <= bar_number <= bars[1]:
        return {"error": f"Choose a bar in the selected range ({bars[0]}-{bars[1]})."}
    if _practice.get("running"):
        if settings.get("mode") not in live.MODES + (live.LISTEN,):
            return {"error": "Bar seeking is available in Learn, Rehearse and Listen."}
        settings = dict(settings)
        settings["start_bar"] = bar_number
        _practice["settings"] = settings
        _seek_generation += 1
        _practice["stopping"] = True
        threading.Thread(target=_restart_at_bar, args=(settings, _practice.get("pass", 1), _seek_generation), daemon=True).start()
    else:
        bar = next(bar for bar in score.bars if bar.number == bar_number)
        beat = min((note.beat for note in score.notes if note.start >= bar.start - 1e-6), default=bar.start_beat)
        hub.cursor(beat)
    return {"bar": bar_number, "seeking": bool(_practice.get("running"))}


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
                    "pick Learn or Rehearse to practice it")
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
    global _seek_generation
    _seek_generation += 1
    _practice["stopping"] = True
    _practice["restarting"] = False
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
# Where the cursor was when the pianist pressed Talk: the "here" in "loop from here", which a
# moving cursor has left behind by the time the recording is sent and transcribed.
_talk: dict = {}


def _cmd_talk(_body: dict) -> dict:
    _talk.clear()
    _talk["beat"] = hub.cursor_beat()
    return {}


def _cursor_bar(score) -> int | None:
    beat = _talk["beat"] if "beat" in _talk else hub.cursor_beat()
    if beat is None or not score.bars:
        return None
    started = [bar.number for bar in score.bars if bar.start_beat <= beat + 1e-6]
    return started[-1] if started else score.bars[0].number


def _voice_context() -> str:
    """What Claude sees each turn: the lesson, the run, recent passes, history."""
    settings = _practice.get("settings") or {}
    roles = settings.get("roles") or []  # Listen keeps the part it plays as its roles
    hand = settings.get("hand") or (roles[0] if len(roles) == 1 else "both")
    lines = [time.strftime("Local time: %A %I:%M %p.").replace(" 0", " "), f"Teaching style: {_coach.style}.",
             _talk_line()]
    view = _page_view.get("view")
    if view in tiles.VIEWS:
        lines.append(f"The page is on {tiles.VIEW_NAMES[view]} ({view}); its panel tiles: {', '.join(tiles.layouts()[view]) or 'none'}.")
    elif view == "visualizer":
        lines.append("The page is on the Visualizer (full screen, the web piano visualizer with LEDs and video; "
                     "it has the keyboard, so practice runs start from the Session).")
    if instruments.uses_mic():
        lines.append(_instrument_line())
    about = atlas_welcome.about_line()
    if about:
        lines.append(about)
    if profiles.young():
        lines.append(f"Pupil: {profiles.active()['name']}, a young child just starting (young learner profile): "
                     "short, simple, warm words; no percentages or jargon.")
    if hub.score_path:
        score = library.get_score(hub.score_path)
        ctx = _coach_context(score, hand, settings.get("mode") or "wait", settings.get("tempo_percent") or 100)
        key = remarks.key_reminder(ctx["fifths"])
        lines.append(f"Lesson on screen: {ctx['title']}, {len(score.bars)} bars"
                     + (f", key signature {key[0]} ({key[1]})" if key else "") + ".")
        here = _cursor_bar(score)
        if here is not None:
            lines.append(f'Cursor at bar {here} ("here" / "this bar" when they spoke).')
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


def _voice_part(score, part: str, track: str = "") -> dict:
    """The Maestro's named part: {"part": role}, found and saved the first time it's asked for
    (by track name, then instrument, or the `track` the user picked), or {"ask": ...} with
    the tracks to choose from. On an instrument heard through the microphone, naming a part
    clears the hand choices (the parts they named become backing)."""
    role = part.strip().lower()
    if role in named_roles(score):
        return {"part": role}
    parts = [p for p in score.parts if p.note_count and not p.drums]
    if track:
        wanted = track.strip().lower()
        found = [p for p in parts if p.name.strip().lower() == wanted or str(p.index + 1) == wanted] \
            or [p for p in parts if wanted in p.name.lower()]
    else:
        found = find_part(score, role)
    if len(found) != 1:
        return {"ask": f"Which track is the {role} part?", "tracks": [p.name.strip() for p in (found or parts)]}
    return {"part": library.name_part(score, role, found[0].index, keep_hands=not instruments.uses_mic())}


def _readback(score, role: str, mode: str, bars: str | None, loop: bool) -> str:
    """One line saying what a named-part run was set up as, for the Maestro to say back."""
    settings = library.song_settings(score.path)
    lead = settings["lead_in"]
    words = [f"{role.capitalize()} part", f"bars {bars}" if bars else "the whole song",
             f"{lead}-bar lead-in" if lead else "no lead-in"]
    if loop:
        words.append("looping" + ("" if settings["lead_in_every_pass"] or not lead else ", lead-in on the first pass only"))
    if mode == "learn":
        words.append("the band waits for you")
    return ", ".join(words) + "."


def _voice_start(mode: str, hand: str = "both", bars: str = "", tempo_percent: int = 100, loop: bool = False,
                 part: str = "", track: str = "", lead_in_bars: int | None = None, lead_in_every_pass: bool | None = None) -> dict:
    """The Maestro's start_practice. Asked from another part of the app (the Roadmap, Home), it
    brings the Session up first, so the run is on screen; a Roadmap lesson runs where it is."""
    if not hub.score_path:
        return {"error": "No lesson is open in the Session. Ask which one, then switch_lesson to it."}
    if not _atlas.current:
        hub.page({"view": "session", "unguarded": True})  # they asked for this run: no "stop the last one?"
    if _busy():
        _cmd_stop({})
        deadline = time.time() + 3
        while _busy() and time.time() < deadline:
            time.sleep(0.05)
    last = _practice.get("settings") or {}
    score = None
    if part:
        score = library.get_score(hub.score_path)
        found = _voice_part(score, part, track)
        if "ask" in found:
            return found
        hand = found["part"]
        if lead_in_bars is not None:
            library.save_song_settings(score.path, lead_in=lead_in_bars)
        if lead_in_every_pass is not None:
            library.save_song_settings(score.path, lead_in_every_pass=lead_in_every_pass)
        sections = part_sections(score, hand)
        if not bars and len(sections) > 1:
            return {"ask": f"Which bars of the {hand} part?", "sections": [f"{a}-{b}" for a, b in sections]}
    out = _voice_start_run(mode, hand, bars, tempo_percent, loop, last)
    if score is not None and "error" not in out:
        out["readback"] = _readback(score, hand, mode, (out.get("selection") or {}).get("bars"), loop)
    return out


def _voice_start_run(mode: str, hand: str, bars: str, tempo_percent: int, loop: bool, last: dict) -> dict:
    return _cmd_start({"mode": mode, "hand": hand, "bars": bars or None, "tempo": tempo_percent, "loop": loop,
                       "port": last.get("input_port"), "count_in": last.get("count_in"), "autopilot": last.get("autopilot"),
                       "roles": [hand] if hand in ("right", "left") or is_named(hand) else last.get("roles"),
                       "output": last.get("output_port")})


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


_PAGE_RANGES = {"zoom_percent": (50, 200), "metronome_bpm": (20, 300), "tempo_percent": (30, 150)}


def _voice_page(**changes) -> dict:
    """The Maestro's page_control: the open coach page sets its own controls, as if clicked."""
    changes = {k: v for k, v in changes.items() if v is not None}
    for key, (low, high) in _PAGE_RANGES.items():
        if key in changes:
            changes[key] = max(low, min(high, int(changes[key])))
    if "bars" in changes:
        bars = str(changes["bars"]).strip()
        match = re.fullmatch(r"(\d+)\s*(?:[-–]\s*(\d+))?", bars)
        if bars and not match:
            return {"error": f"Bars should look like '5-8', not {bars!r}."}
        changes["bars"] = f"{match[1]}-{match[2] or match[1]}" if bars else ""
    if "menu" in changes and changes["menu"] not in chat.PAGE_MENUS:
        return {"error": f"I can't open {changes['menu']!r} yet. I can open: {', '.join(chat.PAGE_MENUS)}."}
    if changes.get("menu") == "see_in_song" and not (_atlas.current and _atlas.song_for(_atlas.current["node"])):
        return {"error": "That works from a Roadmap lesson on a song goal; none is open."}
    if not changes:
        return {"error": "Nothing to change."}
    if not hub.clients:
        return {"error": "No coach page is open."}
    hub.page(changes)
    return {"done": changes}


def _voice_backing_volume(part: str, volume_percent: int) -> dict:
    """The Maestro's set_backing_volume: one track you aren't playing, by its name or instrument,
    turned up, down or off (0 mutes it), for the run going now and saved for the song (Listen's
    mix while Listen runs)."""
    if not hub.score_path:
        return {"error": "No lesson on screen."}
    settings = _practice.get("settings") or {}
    score = library.get_score(hub.score_path)
    play = settings.get("hand") if _busy() and settings.get("hand") else _play_choice(score)
    rows = [r for r in tracks.describe(score, play) if _listening() or not r["yours"]]
    wanted = part.strip().lower().rstrip("s")
    found = [r for r in rows if wanted in r["name"].lower()] or [r for r in rows if wanted in r["instrument"].lower()]
    if len(found) != 1:
        return {"error": f"Which part? The backing is: {', '.join(r['name'] for r in rows)}."}
    volume = max(0, min(100, int(volume_percent)))
    prefix = "listen_" if _listening() else ""
    changes = {f"{prefix}mute": True} if volume == 0 else {f"{prefix}mute": False, f"{prefix}vol": volume}
    _live_gain(found[0]["index"], tracks.set_mix(score, found[0]["index"], **changes))
    return {"part": found[0]["name"], "volume_percent": volume}


def _voice_start_exam(grade: str) -> dict:
    out = _atlas.cmd_exam_start({"tier": grade})
    state = out.get("exam") or {}
    return {"exam": state.get("title"), "first_task": (state.get("task") or {}).get("title")}


_bug_log_lines = bugs.LogRing()
log.addHandler(_bug_log_lines)
_page_errors = bugs.PageErrors()
_bugs = bugs.BugLog(bugs.ScreenRing(active=lambda: hub.clients > 0), logs=_bug_log_lines, page=_page_errors)


def _cmd_page_error(body: dict) -> dict:
    """An uncaught error on the coach page: kept for the next bug report."""
    _page_errors.add(str(body.get("message") or ""), str(body.get("where") or ""), str(body.get("stack") or ""))
    return {"ok": True}


def _report_state() -> dict:
    """Where the page is, saved with a bug report for the check step's Go there."""
    try:
        settings = _practice.get("settings") or {}
        state = {"score": hub.score_path, "view": _page_view.get("view")}
        if hub.score_path:
            state["bar"] = _cursor_bar(library.get_score(hub.score_path))
        if settings:
            state.update(mode=bugs.PAGE_MODES.get(settings.get("mode")), hand=settings.get("hand"),
                         bars=settings.get("bars") or "", tempo_percent=settings.get("tempo_percent"),
                         loop=bool(settings.get("loop")))
        return {k: v for k, v in state.items() if v is not None}
    except Exception as exc:  # a report must never fail for this
        log.info("report state: %s", exc)
        return {}


def _voice_bug(description: str, add_to_last: bool = False, kind: str = "bug", important: bool = False) -> dict:
    if add_to_last:
        return _bugs.add(description, kind=kind)
    return _bugs.report(description, _voice_context(), kind=kind, state=_report_state(), important=important)


def _cmd_report(body: dict) -> dict:
    """The page's F9: a bug report or a request typed instead of said, saved the same way."""
    text = str(body.get("text") or "").strip()
    kind = "request" if body.get("kind") == "request" else "bug"
    if not text:
        return {"error": "Say what's wrong (or what you'd like) first."}
    out = _voice_bug(text, kind=kind, important=bool(body.get("important")))
    bugs.conversation_log(f"(typed, F9) {'Idea' if kind == 'request' else 'Bug'}: {text}", f"saved {out.get('saved')}")
    return {**out, "kind": kind}


def _find_piece(place: dict) -> str | None:
    """The file a report was made on: its saved path, else the file whose name is the title shown
    in the report (lessons, files with saved parts, the song folders), else the closest song."""
    score = place.get("score")
    if score and os.path.isfile(score):
        return score
    title = place.get("title")
    if not title:
        return None
    want = re.sub(r"[^a-z0-9]+", "", title.lower())
    candidates = [row["path"] for row in _cmd_lessons({}).get("lessons", [])]
    candidates += list(library._load_choices()) + [str(p) for p in library.scan_references()]
    for path in candidates:
        if re.sub(r"[^a-z0-9]+", "", pathlib.Path(path).stem.lower()) == want and os.path.isfile(path):
            return path
    try:
        return str(library.resolve_reference(title))
    except FileNotFoundError:
        return None


def _cmd_goto_report(body: dict) -> dict:
    """The check step's Go there: open the piece a report was made on. The page then sets its
    controls (view, mode, bars, tempo, loop) and the cursor's bar from what this returns."""
    place = bugs.place(str(body.get("id") or ""))
    if "error" in place:
        return place
    if _busy():
        return {"error": "Stop the run first."}
    path = _find_piece(place)
    loaded = False
    if path and path != hub.score_path:
        out = _cmd_load({"lesson": path})
        if "error" in out:
            return out
        loaded = True
    elif not path and place.get("title"):
        return {"error": f"Couldn't find “{place['title']}” any more."}
    page = {k: place[k] for k in ("view", "mode", "bars", "tempo_percent", "loop") if place.get(k) not in (None, "")}
    return {"path": path, "loaded": loaded, "page": page, "bar": place.get("bar")}


def _cmd_checks(body: dict) -> dict:
    """Fixes waiting for the user to try (the page's 👀 button); with screenshots when it opens.
    Also the ❓ questions waiting for an answer: how many, and (full) each one with its choices."""
    asks = bugs.questions()
    return {**bugs.to_check(with_shots=bool(body.get("full"))), "asks": len(asks),
            **({"questions": asks} if body.get("full") else {})}


def _cmd_check(body: dict) -> dict:
    """The user tried a fix: it works (→ fixed) or it's still wrong (→ open, with what they said)."""
    out = bugs.verify(str(body.get("id") or ""), bool(body.get("works")), str(body.get("note") or ""))
    return out if "error" in out else {**out, **bugs.to_check(), "asks": len(bugs.questions())}


def _cmd_answer(body: dict) -> dict:
    """The user picked an answer to a ❓ question (or wrote their own): the item joins its batch."""
    out = bugs.answer(str(body.get("id") or ""), str(body.get("choice") or ""))
    return out if "error" in out else {**out, **bugs.to_check(), "asks": len(bugs.questions())}


def _cmd_try_fix(body: dict) -> dict:
    """Try it: put a worker's fix into the user's code before they say whether it works."""
    return bugs.try_fix(str(body.get("id") or ""))


RESTART_NOTE = "restart.json"  # the piece on the page when Restart was pressed, for the fresh copy
_code_cache: dict = {"at": 0.0, "times": {}}


def _cmd_code_status(_body: dict) -> dict:
    """For the page's update bar: when this coach started, when its code and the page's files last
    changed (launch.code_times), and whether Restart can bring it back by itself."""
    from . import launch

    now = time.time()
    if now - _code_cache["at"] > 5:
        _code_cache.update(at=now, times=launch.code_times())
    return {"started": hub.started, **_code_cache["times"], "busy": _busy(),
            "restartable": bool(os.environ.get("MIDI_COACH_RESTARTABLE"))}


def _cmd_restart(_body: dict) -> dict:
    """The page's Restart: this practice copy exits and the launcher starts it again on the new
    code, with the same piece. Claude Desktop's midi-coach can't restart itself."""
    from . import launch

    if not os.environ.get("MIDI_COACH_RESTARTABLE"):
        return {"error": "This coach can't restart itself: quit Claude Desktop (File > Exit) and open it again."}
    if _busy():
        return {"error": "Stop the run first, then restart."}
    try:
        (library.home() / RESTART_NOTE).write_text(json.dumps({"score": hub.score_path, "at": time.time()}), encoding="utf-8")
    except OSError as exc:
        log.info("restart note: %s", exc)

    def go() -> None:
        time.sleep(0.5)  # let the page have its answer
        _practice["stopping"] = True
        recorder.stop()
        hub.shutdown()
        os._exit(launch.RESTART_EXIT)

    threading.Thread(target=go, name="restart", daemon=True).start()
    return {"restarting": True}


def restarted_score() -> str | None:
    """The piece that was on the page when Restart was pressed (once, and only just after)."""
    note = library.home() / RESTART_NOTE
    try:
        saved = json.loads(note.read_text(encoding="utf-8"))
        note.unlink()
    except (OSError, ValueError):
        return None
    score = saved.get("score")
    return score if score and time.time() - float(saved.get("at") or 0) < 120 and pathlib.Path(score).exists() else None


ASKING_SEC = 10 * 60  # how long after reading a question "answer two" still means it
_asking: dict = {}     # the ❓ question the Maestro read out last: {id, at, skipped}


def _asking_now() -> dict | None:
    return _asking if _asking.get("id") and time.time() - _asking["at"] < ASKING_SEC else None


def _voice_questions(what: str, value: str, asked: dict | None) -> str:
    """"Any questions?" reads the first ❓ question; "answer two" / "my answer is …" answers the one
    just read and goes on to the next; "skip" goes on without answering."""
    skipped = set(asked.get("skipped", ())) if asked else set()
    lead = ""
    if what == "answer" and asked:
        out = bugs.answer(asked["id"], value, "told the Maestro")
        if "error" in out:
            _asking.clear()
            return out["error"]
        lead = f"Got it: {out['answer']}. That one's back in the queue. "
    elif what == "skip" and asked:
        skipped.add(asked["id"])
    waiting = bugs.questions()
    left = [q for q in waiting if q["id"] not in skipped]
    if not left:
        _asking.clear()
        if lead:
            return lead + ("That's all my questions." if not waiting else "I'll ask the skipped ones another time.")
        return "No questions right now." if not waiting else "That's all for now: I'll ask the rest another time."
    q = left[0]
    _asking.update(id=q["id"], at=time.time(), skipped=sorted(skipped))
    hub.line("Maestro", "❓ " + q["question"] + "  " + "  ".join(f"{i}. {c}" for i, c in enumerate(q["choices"], 1)), "remark")
    return lead + bugs.spoken_question(q, waiting.index(q) + 1, len(waiting))


def _voice_request(description: str, add_to_last: bool = False, important: bool = False) -> dict:
    return _voice_bug(description, add_to_last, kind="request", important=important)


def _voice_open_song(name: str, artist: str = "") -> dict:
    """The Maestro's open_song (songfind.py): the library, then Downloads, then bitmidi.com; else a
    MuseScore link goes in the Maestro panel for the pianist to fetch it."""
    if _busy():
        return {"error": "Stop the current run before opening another song."}
    found = songfind.find(name, artist)
    if found.get("path"):
        _song_files["at"] = -SONG_SCAN_SEC  # a file copied or downloaded just now
        out = _cmd_load({"lesson": found["path"]})
        hub.page({"view": "session"})
        return {**out, "title": pathlib.Path(found["path"]).stem, "where": found["where"],
                **({"note": "From bitmidi.com: someone's upload, its name is only what they called it."}
                   if found["where"] == "bitmidi" else {})}
    if found.get("ask"):
        return {"ask_which": found["ask"]}
    if found.get("link"):
        hub.line("Maestro", f"Couldn't find “{name}” here. Get it on MuseScore, save it to Downloads, then ask again:",
                 "remark", link=found["link"])
        return {"not_found": True, "link_sent_to_panel": True, "searched": "library, Downloads"
                + (", bitmidi.com" if library.song_sources()["online"] else ""), "online": found.get("tried_online")}
    return found


def _voice_today_remove(what: str) -> dict:
    out = _atlas.cmd_today_remove({"what": what})
    if "error" not in out:
        hub.page({"today": True})  # the page fetches the plan again
    return {**{k: out[k] for k in ("error", "removed_now") if k in out},
            "left_in_plan": [f"{p['label']}: {p['title']}" for p in out.get("parts", [])]}


def _voice_tiles(view: str, add=(), remove=(), reset: bool = False) -> dict:
    out = tiles.change(view, add or (), remove or (), reset)
    if "error" not in out:
        hub.page({"tiles": out})
    return out


_voice = chat.VoiceChat(
    actions={
        "start_practice": _voice_start,
        "set_backing_volume": _voice_backing_volume,
        "stop_practice": lambda: _cmd_stop({}),
        "play_passage": _voice_play,
        "progress": _voice_progress,
        "switch_lesson": lambda name: _cmd_load({"lesson": name}),
        "create_lesson": _voice_create,
        "hand_off": _voice_hand_off,
        "remember": deep.remember,
        "page_control": _voice_page,
        "set_style": lambda style: _cmd_maestro({"style": style}),
        "set_talk": lambda **talk: _cmd_maestro({"talk": talk}),
        "set_goal": _voice_set_goal,
        "next_stop": _voice_next_stop,
        "start_exam": _voice_start_exam,
        "atlas_summary": _atlas_summary,
        "report_bug": _voice_bug,
        "request_feature": _voice_request,
        "set_tiles": _voice_tiles,
        "open_song": _voice_open_song,
        "remove_from_today": _voice_today_remove,
    },
    context=_voice_context,
    instrument=profiles.instrument,
    young=profiles.young,
)


def _voice_reply(heard: str) -> dict:
    """Answer what was said; the reply is spoken and shown by the Maestro on every open page.
    Both go in today's conversation log, and in the Maestro panel's transcript, under a line
    when the Maestro starts a fresh conversation (it no longer remembers what's above it)."""
    if (heard or "").strip() and _voice.start_fresh_if_due():
        hub.line("Maestro", "New conversation: the Maestro doesn't remember what's above this line.", "divider")
    hub.line("You", heard, "you")
    with transcript.answering():
        out = _answer(heard)
    if out.get("error"):
        hub.line("Maestro", out["error"], "error")
    bugs.conversation_log(heard, out.get("reply", ""), out.get("actions") or (), out.get("error", ""))
    return out


def _answer(heard: str) -> dict:
    # "That's enough" / "stop talking": the Maestro finishes its sentence and stops, on every
    # page. Never a practice command (a run keeps going), and no API call.
    if chat.heard_hush(heard):
        hub.page({"hush": True})
        hub.line("Maestro", "Okay, I'll stop there.")
        return {"heard": heard, "reply": "", "hushed": True, "actions": ["hush"], "cost": 0.0}
    # "No" / "undo" right after an autopilot change reverses it here, at once and for free.
    if _autopilot.can_undo and _UNDO_RE.match(re.sub(r"[^a-z' ]+", "", (heard or "").lower()).strip()):
        text = _undo_autopilot()
        if text:
            _npc_say(lambda: text)
            return {"heard": heard, "reply": text, "actions": ["undo"], "cost": 0.0}
    # "Any questions?": the backlog's ❓ questions, read out and answered here, with no API call.
    asked = _asking_now()
    said = bugs.heard_answer(heard, asking=asked is not None)
    if said:
        text = _voice_questions(*said, asked)
        _npc_say(lambda: text)
        return {"heard": heard, "reply": text, "actions": ["backlog_question"], "cost": 0.0}
    # "Bug: ..." / "Idea: ..." / "another screenshot" are saved here too, with no API call.
    command = bugs.heard_command(heard)
    if command:
        kind, rest = command
        out = _voice_bug(rest, add_to_last=kind == "more", kind="request" if kind == "request" else "bug",
                         important=bugs.said_important(heard)[0])
        n = out.get("screenshots", 0)
        noted = ({"more": "Added", "report": "Bug noted", "request": "Request noted"}[kind]
                 if kind == "more" or not bugs.said_important(heard)[0]
                 else {"report": "Important bug noted", "request": "Important request noted"}[kind])
        text = noted + (f", with {n} screenshot{'s' if n != 1 else ''}." if n else ".")
        _npc_say(lambda: text)
        return {"heard": heard, "reply": text, "actions": ["request_feature" if kind == "request" else "report_bug"], "cost": 0.0}
    try:
        out = _voice.ask(heard)
    except chat.Unavailable as exc:
        return {"error": str(exc), "heard": heard}
    except Exception as exc:  # network, bad key, rate limit...
        log.warning("voice chat failed: %s", exc)
        return {"error": f"The Maestro couldn't answer: {exc}", "heard": heard}
    if out.get("reply"):
        _npc_say(lambda: out["reply"], quiet="play_passage" not in (out.get("actions") or ()))
    return {"heard": heard, **out}


def _voice_audio(audio: bytes) -> dict:
    try:
        heard = stt.transcribe(audio)
        if not heard:
            return {"error": "I didn't catch that. Hold the button while you speak.", "heard": ""}
        return _voice_reply(heard)
    except stt.Unavailable as exc:
        return {"error": str(exc)}
    finally:
        _talk.clear()  # a typed message later means the cursor as it is then


_page_view: dict = {}  # the part of the app the page is on (it says so on every change)


def _cmd_view(body: dict) -> dict:
    view = body.get("view")
    _page_view["view"] = {"lesson": "progress"}.get(view, view)
    return {}


def _cmd_tiles(_body: dict) -> dict:
    return {"layouts": tiles.layouts(), "tiles": tiles.TILES, "defaults": tiles.DEFAULTS}


def _cmd_tiles_set(body: dict) -> dict:
    """The panel's edit mode: one view's tiles, in order. Every open page follows."""
    out = tiles.save(body.get("view", ""), list(body.get("tiles") or []))
    if "error" not in out:
        hub.page({"tiles": out})
    return out


def _cmd_transcript(_body: dict) -> dict:
    """Today's lines for the Maestro panel, when a page opens."""
    return {"lines": transcript.today()}


def _cmd_voice_status(_body: dict) -> dict:
    status = _voice.status()
    if status["available"]:
        stt.warm_up()
    _bugs.ring.start()  # a page is open: keep the last few seconds of screen for bug reports
    threading.Thread(target=bugs.write_backlog, name="backlog", daemon=True).start()  # fixes made while closed
    status["deep_available"], status["deep_reason"] = _deep.available()
    return status


def _instrument_line() -> str:
    """The Maestro's context line for an instrument heard through the microphone."""
    inst = instruments.get()
    if inst["id"] == "sax":
        return "Instrument: alto saxophone, heard through the microphone (pitch only); notes are named in written pitch."
    if inst["id"] == "voice":
        return f"Instrument: voice ({profiles.active()['voice']} voice), heard through the microphone (pitch only)."
    if inst.get("strings"):
        return (f"Instrument: {inst['name'].lower()}, heard through the microphone (pitch only, one note at a time); notes "
                "are named in written pitch, an octave above how it sounds.")
    return f"Instrument: {inst['name'].lower()}, heard through the microphone (pitch only)."


def _profile_view() -> dict:
    data = profiles.load()
    return {"active": data["active"], "profiles": data["profiles"], "busy": _busy(), "instrument": instruments.page_config()}


def _switched_profile() -> dict:
    """Forget what belonged to the last profile: its last take, Maestro memory and Atlas run."""
    _last_take.clear()
    _song_files["at"] = -SONG_SCAN_SEC
    _coach._loaded = False
    _coach._recent = {}
    _coach.reset()
    _atlas.reset()
    _voice.messages = []  # the next profile may play another instrument
    return _profile_view()


def _profile_change(action, *args) -> dict:
    if _busy():
        raise ValueError("Stop the run first, then change profile.")
    action(*args)
    return _switched_profile()


def _young_start() -> None:
    """A young learner's profile, now active: the Maestro's friend style, and (piano, no goal yet)
    a first goal on the Atlas's First steps."""
    if not profiles.young():
        return
    _coach.style = "friend"
    if profiles.instrument() == "piano":
        from .atlas import first_steps

        first_steps.start_goal()


def _cmd_profile_new(body: dict) -> dict:
    young = bool(body.get("young"))
    out = _profile_change(lambda name: profiles.create(name, instrument=body.get("instrument") or "piano", young=young,
                                                       voice=body.get("voice") or "high"),
                          body.get("name", ""))
    _young_start()
    return out


def _cmd_profile_young(body: dict) -> dict:
    """Make a profile a young learner's, or not. The active one starts on First steps if it has no goal."""
    profiles.set_young(body.get("id", ""), bool(body.get("young")))
    if body.get("id") == profiles.load()["active"]:
        _young_start()
    return _profile_view()


def _cmd_profile_instrument(body: dict) -> dict:
    """Play another instrument (Home's switcher): its own Roadmap, input and Maestro."""
    pid = body.get("id") or profiles.load()["active"]
    out = _profile_change(profiles.set_instrument, pid, body.get("instrument", ""))
    if pid == profiles.load()["active"]:
        _young_start()
    return out


def _cmd_profile_voice(body: dict) -> dict:
    """A singer's high or low voice: the vocal Roadmap in that octave (progress is shared)."""
    return _profile_change(profiles.set_voice, body.get("id") or profiles.load()["active"], body.get("voice", ""))


def _cmd_profile_select(body: dict) -> dict:
    return _profile_change(profiles.select, body.get("id", ""))


def _cmd_profile_rename(body: dict) -> dict:
    profiles.rename(body.get("id", ""), body.get("name", ""))
    return _profile_view()


def _cmd_profile_delete(body: dict) -> dict:
    return _profile_change(profiles.delete, body.get("id", ""))


def _cmd_mic_note(body: dict) -> dict:
    """A note the coach page heard on the microphone: {on: pitch} or {off: pitch}, with
    velocity and ago_ms (how long before posting the note began)."""
    at = time.perf_counter() - max(0.0, min(1.0, float(body.get("ago_ms") or 0) / 1000))
    if body.get("on") is not None:
        message = [0x90, int(body["on"]) & 0x7F, max(1, min(127, int(body.get("velocity") or 80)))]
    elif body.get("off") is not None:
        message = [0x80, int(body["off"]) & 0x7F, 0]
    else:
        return {"error": "Give on or off."}
    return {"listening": recorder.feed(message, at)}


PAGE_COMMANDS = {"ports": _cmd_ports, "mic_note": _cmd_mic_note, "lessons": _cmd_lessons, "songs": _cmd_songs, "parts": _cmd_parts,
                 "songs_online": _cmd_songs_online, "fetch_online": _cmd_fetch_online,
                 "song_sources": lambda _body: library.song_sources(), "set_song_sources": _cmd_set_song_sources,
                 "pick_folder": _cmd_pick_folder, "rescan": _cmd_rescan,
                 "profiles": lambda _body: _profile_view(), "profile_new": _cmd_profile_new,
                 "profile_select": _cmd_profile_select, "profile_rename": _cmd_profile_rename,
                 "profile_delete": _cmd_profile_delete, "profile_instrument": _cmd_profile_instrument,
                 "profile_voice": _cmd_profile_voice,
                 "profile_young": _cmd_profile_young,
                 "set_parts": _cmd_set_parts, "song_settings": _cmd_song_settings, "practice_settings": _cmd_practice_settings, "track": _cmd_track, "confirm_parts": _cmd_confirm_parts, "cleanup": _cmd_cleanup, "playable": _cmd_playable, "details": _cmd_details,
                 "load": _cmd_load, "open_file": _cmd_open_file, "save_as": _cmd_save_as, "start": _cmd_start, "stop": _cmd_stop,
                 "seek": _cmd_seek, "mix": _cmd_mix, "synced": _cmd_synced, "synced_cursor": _cmd_synced_cursor,
                 "youtube": _cmd_youtube,
                 "record": _cmd_record, "maestro": _cmd_maestro, "stop_playback": lambda _body: _quiet(),
                 "voice_status": _cmd_voice_status, "talk": _cmd_talk, "page_error": _cmd_page_error,
                 "checks": _cmd_checks, "check": _cmd_check, "try_fix": _cmd_try_fix, "code_status": _cmd_code_status, "restart": _cmd_restart, "goto_report": _cmd_goto_report, "report": _cmd_report, "chat": lambda body: _voice_reply(body.get("text", "")),
                 "transcript": _cmd_transcript, "view": _cmd_view, "tiles": _cmd_tiles, "tiles_set": _cmd_tiles_set}
def _atlas_show(path: str) -> dict:
    """A lesson's music on the sheet. Opening a lesson means leaving whatever was running
    (a Freeplay Listen or Learn run): stop it, as Stop would, so the lesson can load."""
    if _busy():
        watcher = _live.get("watcher") if _listening() else None
        _cmd_stop({})
        if watcher and watcher is not threading.current_thread():
            watcher.join(timeout=3)
        elif recorder.active:
            recorder.wait(5)
    out = _cmd_load({"lesson": path})
    if "error" in out:
        raise RuntimeError(out["error"])
    return out


PAGE_COMMANDS["answer"] = _cmd_answer  # the 👀 box's ❓ questions (bugs.answer)


def _atlas_listen(path: str, hand: str = "both", bars: str | None = None, tempo_percent: float = 100.0) -> dict:
    """A lesson's Listen step as a Listen run: the cursor follows and Stop ends it. A profile on
    the microphone (flute, sax, voice) hears it from the page instead (it may have no MIDI output)."""
    if instruments.uses_mic():
        return asyncio.run(play(path, hand=hand, bars=bars, tempo_percent=tempo_percent))
    base = (hand or "both").partition("+")[0]
    return _begin_listen(path, roles=[base] if base in ("right", "left") else None, bars=bars,
                         tempo_percent=tempo_percent, source="page")


# The Atlas (midi_coach/atlas): its page commands, and grading the steps practised on it.
_atlas = atlas_runtime.AtlasCoach(
    hub,
    show=_atlas_show,
    begin=lambda path, **kw: _begin(path, source="page", **kw),
    play=lambda path, **kw: asyncio.run(play(path, **kw)),
    listen=_atlas_listen,
    compare=lambda meta: _compare(meta, None, None, None, None, "normal", True),
    say=lambda text: hub.say(text, speaker="Examiner"),
)
PAGE_COMMANDS.update(_atlas.page_commands())
hub.commands.update(PAGE_COMMANDS)
hub.voice_handler = _voice_audio
hub.extension_hook = synced.note_extension  # the YouTube tab knows it's installed after a restart
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
    In wait/rehearsal, every track the user isn't playing sounds on the MIDI output as its mix
      says (the coach page's Playing menu: mute / volume per track): in time in rehearsal, the
      stretch up to the next chord each time one is played in wait mode.
    silence_sec: stop after this much silence (no keys held). With a reference the
      timeout is stretched to cover the longest written rest still ahead.
    If the keyboard's port is busy, the 'Coach' loopMIDI port is used instead.
    Recording waits up to 2 minutes for the first note. Then call wait_for_recording.
    """
    try:
        started = await asyncio.to_thread(
            _begin, reference, hand, bars, mode, tempo_percent, input_port, split_note,
            silence_sec, max_minutes, show_score, loop and (mode or "").lower() != "free",
            parts=parts,
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


def _wait_mode_note_grade(live: dict, expected_notes: int) -> dict:
    """Grade a wait-mode pass from the notes accepted by the live cursor."""
    counts = {key: live.get(key) for key in ("hits", "missed", "wrong_presses", "notes_total")}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("wait-mode live summary has invalid note counts")
    hits = counts["hits"]
    missed = counts["missed"]
    wrong = counts["wrong_presses"]
    total = counts["notes_total"]
    if total != expected_notes or hits + missed > total:
        raise ValueError("wait-mode live summary does not match the selected reference notes")

    missed = max(missed, total - hits)
    recall = hits / total if total else 0.0
    precision = hits / (hits + wrong) if hits + wrong else 0.0
    score = 2 * precision * recall / (precision + recall) * 100 if precision + recall else 0.0
    return {
        "scores": {
            "overall": round(score),
            "notes": round(score),
            "method": "wait mode: live note accuracy (hits, missed notes and wrong presses)",
        },
        "notes": {
            "correct": hits,
            "wrong": 0,
            "missed": missed,
            "extra": wrong,
            "accuracy_pct": round(100 * recall, 1),
            "precision_pct": round(100 * precision, 1),
        },
    }


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
    wait_grade = None
    if take_meta.get("mode") == "wait" and take_meta.get("live") is not None:
        wait_grade = _wait_mode_note_grade(take_meta["live"], len(ref_notes))
    started = time.perf_counter()
    report = analysis.compare(score, ref_notes, t_notes, t_pedal, bars_given=bar_range is not None, split_note=split_note, detail=detail)
    if "error" in report:
        if wait_grade is None:
            return report
        first_bar = score.position(min(n.start for n in ref_notes))[0] if ref_notes else 1
        last_bar = score.position(max(n.start for n in ref_notes))[0] if ref_notes else first_bar
        scope_bars = f"{bar_range[0]}-{bar_range[1]}" if bar_range else f"{first_bar}-{last_bar}"
        report = {
            "scope": {
                "bars": scope_bars,
                "auto_detected": bar_range is None,
                "reference_notes": len(ref_notes),
                "take_notes": len(t_notes),
            },
            "_per_bar": [],
        }
    report = {"take": take_meta["id"], "reference": score.path, "selection": selection, **report}
    if take_meta.get("mode") == "wait":
        # The cursor waited for the player, so timing and tempo say nothing here.
        skipped = {"note": "Wait mode take: the cursor waited for you, so timing/tempo aren't measured."}
        report["timing"], report["tempo"] = skipped, skipped
        if wait_grade is not None:
            report.update(wait_grade)
        else:
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


def _publish_lesson(path: str, score) -> dict:
    hub.start()
    hub.load_score(score)
    hub.marks([], reset=True)
    hub.heat(None)
    hub.status(f"Lesson: {pathlib.Path(path).stem} · pick Listen, Learn or Rehearse and press Start")
    if score.notes:
        hub.cursor(min(n.beat for n in score.notes))
    if hub.clients == 0 and not os.environ.get("MIDI_COACH_NO_BROWSER"):
        hub.open_browser()
    return {"viewers_connected": hub.clients}


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
            line = instruments.uses_mic() and right and not left  # one line, named for the instrument
            path, score = await asyncio.to_thread(lessons.build_lesson, title, right, left, time_signature, key, tempo_bpm, musicxml,
                                                  category or lessons.AI_EXERCISES, part_name=instruments.get()["part"] if line else None,
                                                  **(instruments.score_look() if line else {}))
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
            out["sent"] = await asyncio.to_thread(_publish_lesson, path, score)
            out["display"] = hub.url
        out["next"] = (
            "The user can start Learn/Rehearse from the page; call wait_for_recording (or "
            f"compare_take('latest')) to coach them. Or start_recording(reference={path!r}, mode='wait')."
        )
        return out
    except Exception as exc:
        return _err(exc)


@mcp.tool()
async def send_lesson(lesson: str) -> dict:
    """Show an existing lesson or reference file (title or path) on the coach page."""
    if recorder.active:
        return {"error": "A practice run is going; stop_recording first."}
    try:
        score = await asyncio.to_thread(library.get_score, lesson)
        sent = await asyncio.to_thread(_publish_lesson, score.path, score)
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
async def make_playlist(name: str, songs: list[str], artist: str | None = None, replace: bool = False) -> dict:
    """Make a playlist: a category on the coach page whose pieces are in a set order (an album,
    a set list), stepped through with ◀ ▶ beside the title. Every keyboard part of every song
    (piano, organ, synths) becomes its own entry, in song order: a copy of the song's file
    with that part chosen for the hands, the band playing the rest. songs: titles in order,
    each found in the reference library (the version with the most keyboard notes), or
    "Title=path" to pick the file. artist narrows the search. replace rebuilds an existing
    playlist. Report the version used per song, the parts, and any song left 'missing'."""
    from . import playlist

    if recorder.active:
        return {"error": "A practice run is going; stop_recording first."}
    try:
        return await asyncio.to_thread(playlist.build_playlist, name, songs, artist, replace)
    except Exception as exc:
        return _err(exc)


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
    Roadmap and the first grade not passed becomes the active goal, its weakest items first.
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
    """Where the pianist stands on the Roadmap (the ABRSM-style skill tree): each grade's
    requirements known, mock exam bests, the active goal and its next stop."""
    return await asyncio.to_thread(_atlas_summary)


@mcp.tool()
async def atlas_node(node_id: str) -> dict:
    """One node of the Roadmap (grade, strand, family, requirement or stage) with its state, its
    stages and, for a stage, its lesson. Ids look like 'g3.technique.scales-ht.scale-...'; find
    them with atlas_overview, list_goals or the page's search."""
    out = await asyncio.to_thread(_atlas.cmd_node, {"id": node_id})
    return out


@mcp.tool()
async def open_node(node_id: str) -> dict:
    """Open a stage's lesson in the coach page's step panel (or show a cluster in the Roadmap)."""
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
    """Plan a goal on the Roadmap with Claude Code on the pianist's subscription, in the
    background (a minute or two; a song longer, as its facts are researched first: Hooktheory
    TheoryTab, then other sources, cross-checked against the file). song: a reference file for
    a song goal. Check list_goals for the result. To plan it yourself instead, use save_goal."""
    return await asyncio.to_thread(_atlas.cmd_goal_plan, {"text": goal, "song": song, "artist": artist, "research": research})


@mcp.tool()
async def save_goal(title: str, kind: str, targets: list[str], reasons: list[str], bridges: list[dict] | None = None,
                    order_hints: list[str] | None = None, song: str | None = None, text: str | None = None) -> dict:
    """Save a goal you planned yourself and make it active. targets: Roadmap node ids (requirements,
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
    """Recompute the Roadmap progress from the takes and the event log (after editing them by hand)."""
    return await asyncio.to_thread(_atlas.cmd_progress_rebuild, {})


@mcp.tool()
async def say(text: str, interrupt: bool = False) -> dict:
    """Speak to the user through the coach page (http://127.0.0.1:8765/) with the browser's
    voice, so they hear feedback with their hands on the keys. Keep it to a sentence or two of
    plain words (say "bar 3", not "b.3"). After each Learn/Rehearse pass the page already speaks
    a short strict-teacher remark (verdict, the bar or note that went wrong, one instruction), so
    add what it can't: the bigger picture, musical advice, what to practice next. Don't repeat it.
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
    The lesson can then be practiced like any other (start_recording(reference=path)).
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
    """Play a reference or a take on the MIDI output (the JUNO by default; for a flute, sax or
    voice profile, the coach page). Returns immediately.

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
        port, seconds = _sound([(f"{label} (loop {k + 1})", events) for k in range(loops)], output_port, gap_sec=0.8)
    except Exception as exc:
        return _err(exc)
    return {"playing": label, "port": port, "bars": bars, "hand": hand, "tempo_percent": tempo_percent, "loops": loops, "seconds": seconds}


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
        port, seconds = _sound(segments, output_port, gap_sec=1.5)
    except Exception as exc:
        return _err(exc)
    return {
        "bars": f"{bar_range[0]}-{bar_range[1]}",
        "order": [s[0] for s in segments],
        "reference_tempo_percent": round(speed * 100),
        "port": port,
        "seconds": seconds,
    }


PAGE_SOUND = "the coach page"


def _sound(segments: list, output_port: str | None, gap_sec: float) -> tuple[str, float]:
    """Play labelled event lists (Player.play's) and return (where, seconds). A profile on the
    microphone hears them from the coach page instead of the MIDI output, unless a port is
    named: no keyboard needed, and the page's microphone knows the sound is its own, so it
    isn't taken for the instrument. With no page open, the MIDI output plays them. The page
    takes a transposing instrument's written pitches down to how they sound."""
    if output_port is None and instruments.uses_mic() and hub.clients:
        player.stop()
        notes, offset = [], 0.0
        for _, events in segments:
            held = {}
            for t, msg in events:
                kind, key = msg[0] & 0xF0, (msg[0] & 0x0F, msg[1])
                if kind == 0x90 and msg[2] > 0:
                    held[key] = (t, msg[2])
                elif kind in (0x80, 0x90) and key in held:
                    on, velocity = held.pop(key)
                    notes.append([round(offset + on, 3), round(t - on, 3), msg[1], velocity])
            offset += (events[-1][0] if events else 0.0) + gap_sec
        hub.sound(notes)
        return PAGE_SOUND, round(max(0.0, offset - gap_sec), 1)
    port = player.play(segments, output_port, gap_sec=gap_sec)
    return port, player.status().get("total_sec")


def _quiet() -> dict:
    """Stop an example playing (on the MIDI output or the page). A run's own notes go on."""
    player.stop()
    hub.sound(None)
    return player.status()


@mcp.tool()
async def stop_playback() -> dict:
    """Stop playback immediately (sends note-offs and releases the sustain pedal)."""
    return _quiet()


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
