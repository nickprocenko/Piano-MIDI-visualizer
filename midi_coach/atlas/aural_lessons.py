"""Lessons for the Aural strand of the Atlas, built from generated examples (aural.py).

Each aural test is a requirement whose stages are its skills ('tap the pulse', 'two or
three time?', 'sing back a phrase'...) and, last, the test as the examiner gives it. A
skill stage has a short explanation and two graded items; the test stage one item of each
skill. Items are listen-and-answer quizzes, taps (along with the music, or echoing a
rhythm), sung echoes (pitch-detected on the page) or played-back echoes on the keyboard,
and singing from a short score. Examples are MIDI files the coach plays, never shown.

    python -m midi_coach.atlas.aural_lessons      write <content>/lessons for the aural stages
"""

from __future__ import annotations

import json
import random

from . import aural, content_dir, first_steps, load_atlas, load_syllabus

ITEMS_PER_SKILL = 2
METRES = {"metre-2-3": [2, 3], "metre-2-3-4": [2, 3, 4], "metre-2-3-4-68": [2, 3, 4, 6]}
METRE_NAMES = {2: "two time", 3: "three time", 4: "four time", 6: "6/8 time"}
SPANS = {"tonic-mediant": 2, "tonic-dominant": 4, "octave": 7}
CADENCE_SETS = {"cadence-perfect-imperfect": ["perfect", "imperfect"],
                "cadence-pii": ["perfect", "imperfect", "interrupted"],
                "cadence-piip": ["perfect", "imperfect", "interrupted", "plagal"]}
EXPLAIN = {
    "pulse": "Tap any key in time with the music, joining in as soon as you feel the beat.",
    "strong-beats": "Tap the beat, a little harder on the first beat of each bar.",
    "rhythm-echo": "Listen, then tap the rhythm of the tune straight back, in time.",
    "rhythm-clap-extract": "Listen to the extract, then tap its rhythm back.",
    "sing-echo": "Listen, then sing it back: any vowel, hum or whistle, at any octave.",
    "melody-memory": "Listen twice, then sing it or play it back on the keyboard.",
    "upper-part-memory": "Two parts play together: sing or play back the upper one.",
    "lower-part-memory": "Two parts play together: sing or play back the lower one.",
    "lowest-part-memory": "Three parts play together: sing or play back the lowest.",
    "sight-sing": "Sing the notes from the score in your own time, starting from the tonic you hear.",
    "sight-sing-accompanied": "Sing the melody from the score while the accompaniment plays.",
    "sight-sing-upper": "Sing the upper part from the score while the lower part plays.",
    "sight-sing-lower": "Sing the lower part from the score while the upper part plays.",
}


def _metre_item(rng, bpb_choices, sid, k, folder) -> dict:
    bpb = rng.choice(bpb_choices)
    notes = aural.accompanied_passage(rng, 3 if bpb == 6 else bpb, bars=4 if bpb != 2 else 6)
    f = _write(folder, f"{sid}-metre-{k}", notes, beats=3 if bpb == 6 else bpb, bpm=132 if bpb == 6 else aural.EXAMPLE_TEMPO)
    names = [METRE_NAMES[b] for b in bpb_choices]
    return {"id": f"metre-{k}", "type": "quiz", "file": f, "prompt": "Is it in " + ", ".join(names[:-1]) + " or " + names[-1] + "?",
            "options": names, "answer": names.index(METRE_NAMES[bpb]), "accept": [METRE_NAMES[bpb].split()[0]], "graded": True}


def _write(folder, name, notes, beats=4, bpm=aural.EXAMPLE_TEMPO) -> str:
    path = folder / f"{name}.mid"
    aural.write_midi(path, notes, bpm=bpm, beats_per_bar=beats)
    return f"aural/{path.name}"


def _seconds(beats: float, bpm: float = aural.EXAMPLE_TEMPO) -> float:
    return round(beats * 60 / bpm, 4)


def items_for(skill: str, test: dict, sid: str, rng: random.Random, folder, count: int) -> list[dict]:
    """`count` graded steps exercising one skill."""
    p = test.get("params", {})
    out = []
    for k in range(1, count + 1):
        name = f"{sid}-{skill}-{k}".replace(".", "_")
        if skill in ("pulse", "strong-beats"):
            bpb = rng.choice([2, 3, 4])
            notes = aural.accompanied_passage(rng, bpb, bars=6)
            f = _write(folder, name, notes, beats=bpb)
            beats = sorted({n[0] for n in notes if n[0] == int(n[0])})
            rule = {"metric": "taps", "min": 70}
            if skill == "strong-beats":
                rule["accent_min"] = 1.15
            out.append({"id": f"{skill}-{k}", "type": "tap", "file": f, "along": True, "ref": [_seconds(b) for b in beats],
                        "accent_every": bpb if skill == "strong-beats" else None, "graded": True, "pass": rule})
        elif skill in METRES:
            out.append(_metre_item(rng, METRES[skill], name, k, folder))
        elif skill in ("rhythm-echo", "rhythm-clap-extract"):
            notes = aural.rhythm_phrase(rng, rng.choice([3, 4]), bars=p.get("bars", 2))
            f = _write(folder, name, notes)
            out.append({"id": f"{skill}-{k}", "type": "tap", "file": f, "along": False,
                        "ref": [_seconds(n[0]) for n in notes], "graded": True, "pass": {"metric": "taps", "min": 65}})
        elif skill == "sing-echo":
            notes = aural.echo_phrase(rng, p.get("bars", 2), "Am" if p.get("mode") == "major-or-minor" and rng.random() < 0.4 else "C",
                                      SPANS.get(p.get("range", "tonic-mediant"), 2))
            f = _write(folder, name, notes)
            out.append({"id": f"{skill}-{k}", "type": "sing", "file": f, "ref": [n[2] for n in notes], "keyboard_ok": False,
                        "graded": True, "pass": {"metric": "pitch", "min": 75}})
        elif skill in ("melody-memory", "upper-part-memory", "lower-part-memory", "lowest-part-memory"):
            key = rng.choice(["C", "G", "F", "D", "Am", "Em"])
            tune = aural.echo_phrase(rng, 2, key, 7)
            notes, ref = tune, [n[2] for n in tune]
            if skill != "melody-memory":  # add a lower part (a third or sixth below, held a bit)
                lower = [(s, e, pt - rng.choice([3, 4, 8, 9]), v - 6) for s, e, pt, v in tune]
                third = [(s, e, pt - 12, v - 10) for s, e, pt, v in lower] if skill == "lowest-part-memory" else []
                notes = tune + lower + third
                ref = [n[2] for n in (tune if skill == "upper-part-memory" else third or lower)]
            f = _write(folder, name, aural.twice(notes, notes))
            out.append({"id": f"{skill}-{k}", "type": "sing", "file": f, "ref": ref, "keyboard_ok": True,
                        "graded": True, "pass": {"metric": "pitch", "min": 70}})
        elif skill.startswith("sight-sing"):
            from fractions import Fraction as F

            from ..transcribe import grand_staff

            key = rng.choice(p.get("keys") or ["C", "F", "G"])
            notes = aural.echo_phrase(rng, 2, key, 4 if skill == "sight-sing" else 7)[: p.get("notes", 8)]
            events = [("right", F(n[0]).limit_denominator(4), F(n[1]).limit_denominator(4) if n[1] - n[0] > 0.5 else F(n[0]).limit_denominator(4) + F(1, 2), n[2]) for n in notes]
            xml = grand_staff(events, "Sing from the score", "4/4")["xml"]
            (folder / f"{name}.musicxml").write_text(xml, encoding="utf-8")
            tonic = aural._degrees(key)[0]
            f = _write(folder, name + "-tonic", [(0, 1.5, tonic, 80)])
            out.append({"id": f"{skill}-{k}", "type": "sing", "file": f, "score": f"aural/{name}.musicxml",
                        "ref": [n[2] for n in notes], "keyboard_ok": False, "graded": True, "pass": {"metric": "pitch", "min": 70}})
        elif skill in ("pitch-change-place", "pitch-or-rhythm-change"):
            phrase = aural.echo_phrase(rng, p.get("bars", 2), "C", 4)
            kind = "pitch" if skill == "pitch-change-place" else rng.choice(["pitch", "rhythm"])
            second, ans = aural.changed(rng, phrase, kind)
            f = _write(folder, name, aural.twice(phrase, second))
            if skill == "pitch-change-place":
                q = {"prompt": "It's played twice; one note changes the second time. Near the beginning or near the end?",
                     "options": ["near the beginning", "near the end"], "answer": 0 if ans["where"] == "beginning" else 1,
                     "accept": [ans["where"]]}
            else:
                q = {"prompt": "It's played twice. What changed the second time: a note's pitch, or the rhythm?",
                     "options": ["the pitch", "the rhythm"], "answer": 0 if kind == "pitch" else 1, "accept": [kind]}
            out.append({"id": f"{skill}-{k}", "type": "quiz", "file": f, "graded": True, **q})
        elif skill in ("dynamics", "articulation", "tempo", "tonality"):
            notes, answer, options = aural.feature_passage(rng, skill)
            f = _write(folder, name, notes)
            prompt = {"dynamics": "Loud or quiet? Or getting louder or quieter?", "articulation": "Smooth or detached?",
                      "tempo": "Getting faster, getting slower, or staying the same?", "tonality": "Major or minor?"}[skill]
            out.append({"id": f"{skill}-{k}", "type": "quiz", "file": f, "prompt": prompt, "options": options,
                        "answer": options.index(answer), "accept": [answer.split(" (")[0]], "graded": True})
        elif skill in CADENCE_SETS:
            notes, kind, kinds, _ = aural.cadence(rng, CADENCE_SETS[skill], rng.choice(["C", "G", "F", "Am"]))
            f = _write(folder, name, aural.twice(notes, notes))
            out.append({"id": f"{skill}-{k}", "type": "quiz", "file": f, "prompt": "Which cadence ends the phrase?",
                        "options": kinds, "answer": kinds.index(kind), "accept": [kind], "graded": True})
        elif skill in ("cadence-chords-2", "cadence-chords-3"):
            kinds = ["perfect", "imperfect", "interrupted", "plagal"]
            notes, kind, _, (a, b) = aural.cadence(rng, kinds, rng.choice(["C", "G", "F"]))
            f = _write(folder, name, notes)
            options = [f"{aural.CHORD_NAMES[x].split()[0]}–{aural.CHORD_NAMES[y].split()[0]}" for x, y in aural.CADENCES.values()]
            answer = f"{aural.CHORD_NAMES[a].split()[0]}–{aural.CHORD_NAMES[b].split()[0]}"
            out.append({"id": f"{skill}-{k}", "type": "quiz", "file": f, "prompt": "Which two chords make the cadence?",
                        "options": options, "answer": options.index(answer), "accept": [answer.replace("–", " ")], "graded": True})
        elif skill in ("modulation-major", "modulation-minor"):
            notes, target, options = aural.modulation(rng, start_minor=skill.endswith("minor"))
            f = _write(folder, name, notes)
            out.append({"id": f"{skill}-{k}", "type": "quiz", "file": f, "prompt": "Where does it modulate to?",
                        "options": options, "answer": options.index(target), "accept": [target], "graded": True})
        elif skill == "character":
            choice = rng.choice(["lively", "gentle", "march-like", "dance-like"])
            feature = {"lively": "articulation", "gentle": "dynamics", "march-like": "tempo", "dance-like": "tonality"}[choice]
            notes, _, _ = aural.feature_passage(rng, feature)
            if choice == "lively":
                notes = [(s * 0.6, s * 0.6 + 0.12, pt, 96) for s, e, pt, v in notes]
            elif choice == "gentle":
                notes = [(s * 1.6, e * 1.6, pt, 40) for s, e, pt, v in notes]
            elif choice == "march-like":
                notes = aural.accompanied_passage(rng, 4, 4)
            else:
                notes = aural.accompanied_passage(rng, 3, 6)
            f = _write(folder, name, notes, beats=3 if choice == "dance-like" else 4)
            options = ["lively", "gentle", "march-like", "dance-like"]
            out.append({"id": f"{skill}-{k}", "type": "quiz", "file": f, "prompt": "Which word fits its character best?",
                        "options": options, "answer": options.index(choice), "accept": [choice.split("-")[0]], "graded": True})
        else:  # style and period, texture and structure, describing: facts to know (pieces bring the listening)
            out.append(_fact_quiz(skill, rng, k))
    return out


FACTS = {
    "style-period": [("Which period does Bach's music come from?", ["Baroque", "Classical", "Romantic", "20th century"], 0),
                     ("Mozart and Haydn wrote in which period?", ["Baroque", "Classical", "Romantic", "20th century"], 1),
                     ("Chopin and Schumann are composers of which period?", ["Baroque", "Classical", "Romantic", "20th century"], 2),
                     ("Ornaments, terraced dynamics and counterpoint are typical of…", ["Baroque", "Classical", "Romantic"], 0)],
    "texture-structure": [("A tune with chords underneath is…", ["melody and accompaniment", "counterpoint", "unison"], 0),
                          ("Two independent lines at once is…", ["counterpoint", "melody and accompaniment", "unison"], 0),
                          ("A section, a contrasting one, then the first again (ABA) is…", ["ternary form", "binary form", "rondo"], 0),
                          ("A refrain that keeps coming back between new sections (ABACA) is…", ["rondo", "binary form", "ternary form"], 0)],
}


def _fact_quiz(skill: str, rng: random.Random, k: int) -> dict:
    bank = FACTS.get(skill) or FACTS["texture-structure"] + FACTS["style-period"]
    prompt, options, answer = bank[(rng.randrange(len(bank)) + k) % len(bank)]
    return {"id": f"{skill}-{k}", "type": "quiz", "prompt": prompt, "options": options, "answer": answer,
            "accept": [options[answer]], "graded": True}


def write_lessons(seed: int = 1) -> int:
    atlas = load_atlas()
    syllabus = load_syllabus()
    tests = {(g["id"], t["id"]): t for g in syllabus["grades"] for t in g.get("aural", [])}
    folder = content_dir() / "lessons" / "aural"
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    for req in atlas["nodes"]:
        if req["level"] != "requirement" or req["kind"] != "aural" or req["tier"] in first_steps.OURS:  # those write their own
            continue
        test = tests.get((req["tier"], req["spec"]["id"]), req["spec"])
        for sid in req["stages"]:
            stage = atlas["by_id"][sid]
            rng = random.Random(f"{seed}:{sid}")
            key = stage["stage"]["key"]
            if key == "test":
                steps = [{"id": "read", "type": "read", "text": f"{test['title']}, as in the exam: one of each part."}]
                for skill in test["skills"]:
                    steps += items_for(skill, test, sid, rng, folder, 1)
            else:
                skill = next((s for s in test["skills"] if s.replace("-", "") == key.replace("-", "")), key)
                text = EXPLAIN.get(skill) or f"{stage['title']}: listen to each example, then answer."
                steps = [{"id": "read", "type": "read", "text": text}] + items_for(skill, test, sid, rng, folder, ITEMS_PER_SKILL)
            lesson = {"id": sid, "version": 1, "made": "atlas.aural_lessons", "checked": True, "requirement": req["id"], "steps": steps}
            (content_dir() / "lessons" / f"{sid}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
            count += 1
    return count


def main() -> None:
    print(f"{write_lessons()} aural lessons")


if __name__ == "__main__":
    main()
