"""Score notes.split_hands against piano parts whose hands are already known.

Ground truth is any piano written on two parts: MIDI files in reference/ whose piano is
on two tracks (named for each hand, or found to be a player's two hands), and two-staff
piano scores from music21's corpus (where the truth is the engraver's staff, not the
hand). Each case's two parts are merged into one, split again, and compared note by note.

Splitting at middle C is shown only as the floor to beat. split_by_reach is the search
split_hands falls back on; split_hands itself is scored when the hand model is installed
(midi_coach/hand_model.py). Cases whose hands are cut at one fixed key
throughout ("separable") are scored apart: a file split that way was probably split by
software at a key, and any splitter that does the easy thing gets them right.

    python tools/hand_split_bench.py --scan        # find the cases (once; cached)
    python tools/hand_split_bench.py               # score the splitters on every case
    python tools/hand_split_bench.py --against HEAD   # ...and split_hands as committed at HEAD
    python tools/hand_split_bench.py --worst 20 --only Joplin
"""

from __future__ import annotations

import argparse
import bisect
import importlib.util
import json
import multiprocessing
import os
import pathlib
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from midi_coach import notes as current  # noqa: E402

LIBRARY = REPO / "reference"
CASES = LIBRARY / "hand_split_cases.json"
CORPUS = REPO / ".venv" / "Lib" / "site-packages" / "music21" / "corpus"
# Two-staff piano scores in music21's corpus: (file, right-hand part, left-hand part).
CORPUS_CASES = [
    ("joplin/maple_leaf_rag.mxl", 0, 1),
    ("mozart/k545/movement1_exposition.mxl", 0, 1),
    ("cpebach/h186.mxl", 0, 1),
    ("schumann_clara/polonaise_op1n1.mxl", 0, 1),
    ("schumann_clara/polonaise_op1n2.mxl", 0, 1),
    ("schumann_clara/polonaise_op1n3.mxl", 0, 1),
    ("schumann_clara/polonaise_op1n4.mxl", 0, 1),
    ("schumann_clara/opus17/movement3.xml", 2, 3),
    ("schubert/Lindenbaum.xml", 1, 2),
    ("beach/prayer_of_a_tired_child.musicxml", 4, 5),
    ("liliuokalani/aloha_oe.mxl", 5, 6),
]
MIN_NOTES = 100  # a case with fewer notes in either hand says little


def find_case(path: str) -> dict | None:
    """The piano parts of one file that are already split by hand, if any."""
    try:
        score = current.load_score(path)
    except Exception:
        return None
    keys = [p for p in current.playable_parts(score) if current._is_keyboard(p)]
    doubled = current._doublings(score, keys)
    keys = [p for p in keys if p.index not in doubled]
    sides = {p.index: current._name_side(p.name) for p in keys}
    right = [i for i, s in sides.items() if s == "right"]
    left = [i for i, s in sides.items() if s == "left"]
    kind = "named"
    if not (right and left):
        if len(keys) < 2:
            return None
        main = max(keys, key=lambda p: p.note_count)
        partner = next((p for p in sorted(keys, key=lambda p: -p.note_count)
                        if p is not main and current._hand_pair(score, main, p)), None)
        if partner is None:
            return None
        hi, lo = sorted((main, partner), key=lambda p: -p.mean_pitch)
        right, left, kind = [hi.index], [lo.index], "paired"
    counts = [sum(score.parts[i].note_count for i in side) for side in (right, left)]
    if min(counts) < MIN_NOTES:
        return None
    return {"path": str(pathlib.Path(path).relative_to(REPO)), "right": right, "left": left, "kind": kind}


def scan(workers: int) -> None:
    files = sorted(str(p) for p in LIBRARY.rglob("*.mid"))
    print(f"scanning {len(files)} MIDI files...", flush=True)
    t = time.time()
    with multiprocessing.Pool(workers) as pool:
        found = [c for c in pool.imap_unordered(find_case, files, chunksize=8) if c]
    found.sort(key=lambda c: c["path"])
    for name, r, l in CORPUS_CASES:
        if (CORPUS / name).exists():
            found.append({"path": str((CORPUS / name).relative_to(REPO)), "right": [r], "left": [l], "kind": "engraved"})
    CASES.write_text(json.dumps(found, indent=1))
    kinds = {k: sum(c["kind"] == k for c in found) for k in ("named", "paired", "engraved")}
    print(f"{len(found)} cases in {time.time() - t:.0f}s {kinds} -> {CASES.relative_to(REPO)}")


def load_revision(rev: str):
    """notes.py as committed at a git revision, as its own module."""
    source = subprocess.run(["git", "show", f"{rev}:midi_coach/notes.py"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    name = f"notes_{rev.replace('/', '_').replace('~', '_').replace('^', '_')}"
    path = pathlib.Path(tempfile.gettempdir()) / f"hand_split_{name}_{os.getpid()}.py"  # one per worker: they load at once
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "midi_coach"  # its relative imports (from . import hand_model) use the working tree's
    sys.modules[name] = module  # dataclasses look their module up while it is being defined
    spec.loader.exec_module(module)
    return module


BASELINE = "middle C (floor)"
_SPLITTERS: dict = {}


def _init(against: str | None) -> None:
    from midi_coach import hand_model

    path = hand_model.model_path()
    if path and path.exists():  # one thread per session: the bench already runs one case per core
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        hand_model._sessions[str(path.resolve())] = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    _SPLITTERS.clear()
    _SPLITTERS[BASELINE] = lambda notes: {(round(n.start, 4), n.pitch): "right" if n.pitch >= 60 else "left" for n in notes}
    if against:
        _SPLITTERS[against] = load_revision(against).split_hands
    _SPLITTERS["split_by_reach"] = current.split_by_reach
    if hand_model.available():
        _SPLITTERS["split_hands (model)"] = current.split_hands


def evaluate(case: dict) -> dict | None:
    started = time.time()
    try:
        score = current.load_score(REPO / case["path"])
    except Exception:
        return None
    seconds = {"load": time.time() - started}
    truth: dict[tuple[float, int], str] = {}
    clash: set[tuple[float, int]] = set()
    for hand in ("right", "left"):
        for n in score.notes:
            if n.part in case[hand]:
                key = (round(n.start, 4), n.pitch)
                if truth.get(key, hand) != hand:
                    clash.add(key)  # the same key struck by both hands at once: no right answer
                truth[key] = hand
    notes = [n for n in score.notes if n.part in case["right"] + case["left"]]
    t = time.time()
    starts = [b.start for b in score.bars]
    bars = {(round(n.start, 4), n.pitch): bisect.bisect_right(starts, n.start + 1e-9) for n in notes}
    seconds["bars"] = time.time() - t
    lows = [p for (_, p), h in truth.items() if h == "left"]
    highs = [p for (_, p), h in truth.items() if h == "right"]
    out = {"path": case["path"], "kind": case["kind"], "separable": max(lows) < min(highs), "notes": 0, "bars": len(set(bars.values())), "scores": {}}
    for name, split in _SPLITTERS.items():
        t = time.time()
        sides = split(notes)
        seconds[name] = time.time() - t
        wrong = [k for k in truth if k not in clash and sides.get(k) != truth[k]]
        out["notes"] = len(truth) - len(clash)
        out["scores"][name] = {"wrong": len(wrong), "bad_bars": len({bars[k] for k in wrong})}
    out["seconds"] = seconds
    return out


def report(results: list[dict], worst: int) -> None:
    names = list(results[0]["scores"]) if results else []
    groups = [
        ("all", results),
        ("not separable", [r for r in results if not r["separable"]]),
        ("named tracks", [r for r in results if r["kind"] == "named" and not r["separable"]]),
        ("paired tracks", [r for r in results if r["kind"] == "paired" and not r["separable"]]),
        ("engraved scores", [r for r in results if r["kind"] == "engraved"]),
    ]
    print(f"\n{'':18}{'files':>6}{'notes':>9}   " + "".join(f"{n[:22]:>24}" for n in names))
    print(f"{'':39}" + "".join(f"{'notes  files  bars':>24}" for _ in names))
    for label, group in groups:
        if not group:
            continue
        total = sum(r["notes"] for r in group)
        cells = []
        for n in names:
            wrong = sum(r["scores"][n]["wrong"] for r in group)
            per_file = sum(1 - r["scores"][n]["wrong"] / max(1, r["notes"]) for r in group) / len(group)
            clean = 1 - sum(r["scores"][n]["bad_bars"] for r in group) / max(1, sum(r["bars"] for r in group))
            cells.append(f"{100 * (1 - wrong / max(1, total)):6.1f}%{100 * per_file:6.1f}%{100 * clean:6.1f}%")
        print(f"{label:18}{len(group):6}{total:9}   " + "".join(f"{c:>24}" for c in cells))
    print("\nnotes: share of notes in the right hand; files: the mean of each file's share; "
          f"bars: share of bars with no note in the wrong hand. '{BASELINE}' is not a method, only the floor to beat: "
          "every note from middle C up in the right hand.")
    if worst and names:
        key = names[-1]
        print(f"\nworst {worst} for {key} (not separable):")
        ranked = sorted((r for r in results if not r["separable"]), key=lambda r: -r["scores"][key]["wrong"] / max(1, r["notes"]))
        for r in ranked[:worst]:
            acc = " ".join(f"{100 * (1 - r['scores'][n]['wrong'] / max(1, r['notes'])):5.1f}" for n in names)
            print(f"  {acc}  {r['kind'][:5]}  {r['path'][-80:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scan", action="store_true", help="find the cases in reference/ (cached in reference/hand_split_cases.json)")
    ap.add_argument("--against", metavar="REV", help="also score split_hands as committed at this git revision")
    ap.add_argument("--only", help="only cases whose path contains this")
    ap.add_argument("--limit", type=int, help="only the first N cases")
    ap.add_argument("--worst", type=int, default=10, help="list the N files split worst")
    ap.add_argument("--workers", type=int, default=max(1, (multiprocessing.cpu_count() or 2) - 2))
    args = ap.parse_args()
    if args.scan or not CASES.exists():
        scan(args.workers)
    cases = json.loads(CASES.read_text())
    if args.only:
        cases = [c for c in cases if args.only.lower() in c["path"].lower()]
    cases = cases[: args.limit] if args.limit else cases
    t = time.time()
    results = []
    with multiprocessing.Pool(args.workers, initializer=_init, initargs=(args.against,)) as pool:
        for r in pool.imap_unordered(evaluate, cases):
            if r:
                results.append(r)
            if len(results) % 100 == 0:
                print(f"  {len(results)}/{len(cases)} in {time.time() - t:.0f}s", file=sys.stderr, flush=True)
    results.sort(key=lambda r: r["path"])
    print(f"scored {len(results)} cases in {time.time() - t:.0f}s")
    totals = {k: sum(r["seconds"].get(k, 0) for r in results) for k in results[0]["seconds"]} if results else {}
    print("time spent: " + ", ".join(f"{k} {v:.0f}s" for k, v in totals.items()))
    slow = max(results, key=lambda r: sum(r["seconds"].values()), default=None)
    if slow:
        print(f"slowest: {sum(slow['seconds'].values()):.0f}s {slow['path'][-70:]}")
    report(results, args.worst)


if __name__ == "__main__":
    main()
