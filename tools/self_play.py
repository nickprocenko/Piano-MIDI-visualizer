"""Self-play for the fingering: finger every song, test the result against a human hand, adjust.

    .venv\\Scripts\\python tools\\self_play.py report [--songs 60]        finger songs, list what no hand could do
    .venv\\Scripts\\python tools\\self_play.py train  [--songs 60 --rounds 40]   nudge the fingering's costs to cut those
    .venv\\Scripts\\python tools\\self_play.py train --forever             keep going until Ctrl+C

Each round: finger a fixed sample of the library with midi_coach.fingering, run the physical
checks below on every hand, and score the whole sample by violations per 1000 notes. Training
perturbs one cost constant at a time and keeps the change only if the score improves. The
best set is saved to %USERPROFILE%\\MidiCoach\\self_play\\params.json and every round is
appended to log.jsonl. Nothing in the product reads params.json yet: look at the report, then
copy values into fingering.py (or call apply_saved()) once you trust them.

The checks (a left hand is mirrored first, as fingering.py does):
  double_finger   one finger holding two keys at once
  span            two fingers down together further apart / closer than Parncutt's "practical" limits
  order           fingers crossed while both are down (other than thumb vs. finger)
  finger_speed    the same finger on two different keys closer in time than it can travel
  hand_speed      the hand relocating faster than a human arm can (semitones per second)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from midi_coach import fingering as fg  # noqa: E402
from midi_coach import library  # noqa: E402

FINGER_GAP = 0.09      # s: least time for one finger to leave a key and strike another
HAND_RATE = 90.0       # semitones/s: fastest the whole hand relocates (about 1.2 m/s)
HAND_MIN_TRAVEL = 6    # semitones: shorter moves are a stretch, not a relocation
HOLD = 0.08            # s: a key down this long past the next start is held
TUNABLE = ["SAME_FINGER", "LEAP", "LEAP_STEP", "RELEASE", "RELEASE_PER_SEC", "RELEASE_MAX", "RELEASE_PEDAL",
           "THUMB_SIDE_FINGER", "THUMB_SIDE_PINKY"]


def state_dir() -> pathlib.Path:
    d = library.home() / "self_play"
    d.mkdir(parents=True, exist_ok=True)
    return d


def check_hand(notes: list[tuple[float, float, int, int]]) -> Counter:
    """notes: (start, end, pitch, finger) for one hand, pitch already mirrored for a left hand."""
    bad: Counter = Counter()
    notes = sorted(notes)
    for i, (s, e, p, f) in enumerate(notes):
        for s2, e2, p2, f2 in notes[i + 1:]:
            if s2 - s > 4.0:
                break
            if s2 >= e - HOLD:  # n2 starts after n1 is let go
                if s2 - s > 1.0:
                    break
                continue
            if p2 == p:
                continue
            if f == f2:
                bad["double_finger"] += 1
                continue
            (fa, pa), (fb, pb) = ((f, p), (f2, p2)) if f < f2 else ((f2, p2), (f, p))
            d = pb - pa
            lo, hi = fg.SPANS[(fa, fb)][0], fg.SPANS[(fa, fb)][5]
            if d > hi or d < lo:
                bad["span"] += 1
            elif d < 0 and fa != 1:
                bad["order"] += 1
    # one finger, or the whole hand, travelling between consecutive starts
    last: dict[int, tuple[float, int]] = {}
    prev = None
    for s, e, p, f in notes:
        if f in last and p != last[f][1] and 0 < s - last[f][0] < FINGER_GAP:
            bad["finger_speed"] += 1
        last[f] = (s, p)
        centre = p - fg.OFFSET[f]
        if prev and s - prev[0] > 0.01:
            travel = abs(centre - prev[1])
            if travel >= HAND_MIN_TRAVEL and travel / (s - prev[0]) > HAND_RATE:
                bad["hand_speed"] += 1
        if not prev or s - prev[0] > 0.01:
            prev = (s, centre)
    return bad


def hand_notes(score) -> dict[str, list[tuple[float, float, int, int]]]:
    fingers = fg.score_fingers(score)
    out: dict[str, list] = {"right": [], "left": []}
    for n in score.notes:
        got = fingers.get((round(n.start, 4), n.pitch))
        if got:
            hand, finger = got
            out[hand].append((n.start, n.end, fg.MIRROR - n.pitch if hand == "left" else n.pitch, finger))
    return out


def evaluate(scores) -> tuple[float, Counter, int, dict]:
    total, notes, per_song = Counter(), 0, {}
    for name, score in scores:
        c = Counter()
        n = 0
        for hand, seq in hand_notes(score).items():
            c += check_hand(seq)
            n += len(seq)
        per_song[name] = (sum(c.values()), n)
        total += c
        notes += n
    return 1000.0 * sum(total.values()) / max(notes, 1), total, notes, per_song


def sample(count: int, seed: int = 7):
    refs = library.scan_references()
    random.Random(seed).shuffle(refs)
    out = []
    for path in refs:
        if len(out) >= count:
            break
        try:
            score = library.get_score(str(path))
            if getattr(score, "playing", None) or len(score.notes) < 200:
                continue
            if len(fg.score_fingers(score)) >= 150:
                out.append((pathlib.Path(path).stem, score))
        except Exception:
            continue
    return out


def reset_caches() -> None:
    fg.pair_cost.cache_clear()
    fg._options.cache_clear()


def set_params(p: dict) -> None:
    for k, v in p.items():
        setattr(fg, k, v)
    reset_caches()


def apply_saved() -> bool:
    f = state_dir() / "params.json"
    if f.exists():
        set_params(json.loads(f.read_text())["params"])
        return True
    return False


def report(args) -> None:
    scores = sample(args.songs)
    score, total, notes, per_song = evaluate(scores)
    print(f"{len(scores)} songs, {notes} fingered notes: {score:.2f} violations per 1000 notes")
    for k, v in total.most_common():
        print(f"  {k:14s} {v}")
    print("worst songs:")
    for name, (v, n) in sorted(per_song.items(), key=lambda kv: -kv[1][0] / max(kv[1][1], 1))[:8]:
        print(f"  {1000 * v / max(n, 1):7.1f}/1000  {name}")


def train(args) -> None:
    scores = sample(args.songs)
    params = {k: getattr(fg, k) for k in TUNABLE}
    if args.resume and (state_dir() / "params.json").exists():
        params = json.loads((state_dir() / "params.json").read_text())["params"]
        set_params(params)
    best, _, notes, _ = evaluate(scores)
    print(f"start: {best:.2f} /1000 over {len(scores)} songs, {notes} notes")
    rng, rnd = random.Random(), 0
    log = (state_dir() / "log.jsonl").open("a")
    try:
        while args.forever or rnd < args.rounds:
            rnd += 1
            key = rng.choice(TUNABLE)
            trial = dict(params)
            trial[key] = round(params[key] * rng.choice([0.5, 0.7, 0.85, 1.2, 1.5, 2.0]), 3)
            set_params(trial)
            t = time.time()
            score, total, _, _ = evaluate(scores)
            kept = score < best - 1e-9
            if kept:
                best, params = score, trial
                (state_dir() / "params.json").write_text(json.dumps({"score": best, "params": params}, indent=1))
            else:
                set_params(params)
            log.write(json.dumps({"round": rnd, "key": key, "value": trial[key], "score": score, "kept": kept,
                                  "by_check": dict(total)}) + "\n")
            log.flush()
            print(f"round {rnd:3d} {key:16s} -> {trial[key]:<8} {score:6.2f} {'KEPT' if kept else '    '} ({time.time() - t:.0f}s)")
    except KeyboardInterrupt:
        pass
    print(f"best {best:.2f} /1000; saved to {state_dir() / 'params.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["report", "train"])
    ap.add_argument("--songs", type=int, default=60)
    ap.add_argument("--rounds", type=int, default=40)
    ap.add_argument("--forever", action="store_true")
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    (report if a.cmd == "report" else train)(a)
