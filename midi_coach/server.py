"""midi-coach MCP server: record, analyze, compare and play back piano MIDI.

Run with:  python -m midi_coach   (stdio transport, for Claude Desktop)
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import statistics
import sys
import time

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import analysis, library
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
Timing numbers are relative to the user's own local tempo; playing slower than
the score is not an error. Velocity 1-127: ~40 soft, ~64 medium, ~95 loud.
"""

mcp = _Server("midi-coach", instructions=INSTRUCTIONS)
recorder = Recorder()
player = Player()
_last_take: dict = {}


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


def _on_recording_finished(meta_base: dict):
    def finish(state) -> None:
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
) -> dict:
    """Start recording the user's playing from the MIDI input.

    reference: optional reference title/path; enables rest-aware auto-stop and auto-compare.
    hand: 'both' | 'right' | 'left' - what the user is practicing.
    bars: e.g. '9-16' to practice a section.
    silence_sec: stop after this much silence (no keys held). With a reference the
      timeout is stretched to cover the longest written rest still ahead.
    Recording waits up to 2 minutes for the first note. Then call wait_for_recording.
    """
    meta = {"reference": None, "hand": hand, "bars": bars, "split_note": split_note}
    rests = None
    selection = None
    try:
        if reference:
            score = await asyncio.to_thread(library.get_score, reference)
            notes, selection, _ = _selection(score, hand, bars, split_note)
            if not notes:
                return {"error": f"No reference notes for hand={hand} bars={bars}."}
            rests = RestProfile.from_notes(notes)
            meta["reference"] = score.path
        recorder.on_finish = _on_recording_finished(meta)
        port = await asyncio.to_thread(recorder.start, input_port, silence_sec, max_minutes * 60, 120.0, rests)
    except Exception as exc:
        return _err(exc)
    _last_take.clear()
    longest = max(rests.rests, default=0.0) if rests else 0.0
    return {
        "recording": True,
        "port": port,
        "reference": meta["reference"],
        "selection": selection,
        "auto_stop": f"{silence_sec}s of silence" + (f", extended through written rests (longest {longest:.1f}s at score tempo)" if longest > silence_sec else ""),
        "next": "Tell the user to start playing, then call wait_for_recording.",
    }


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
    if save:
        take_meta.setdefault("comparisons", []).append({
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reference": score.path,
            "hand": hand,
            "bars": report["scope"]["bars"],
            "scores": report["scores"],
            "notes": report["notes"],
            "tempo_bpm": report["tempo"]["your_bpm"],
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
        return {**status, "next": "Still going - call wait_for_recording again."}
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
async def stop_recording(auto_compare: bool = True) -> dict:
    """Stop the current recording now and save the take (then compare/analyze it)."""
    if recorder.status().get("state") == "idle":
        return {"error": "Not recording."}
    await asyncio.to_thread(recorder.stop)
    return await _finished_result(recorder.status(), auto_compare)


@mcp.tool()
async def status() -> dict:
    """Current recording and playback status."""
    return {"recording": recorder.status(), "playback": player.status()}


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
