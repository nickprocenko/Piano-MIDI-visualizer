"""Grading one lesson step: did this pass meet the step's pass mark?

A play step's pass mark is {metric, min, tempo_min_pct?, max_wrong?}: metric is one of
the comparison's scores (notes, timing, overall; in Learn mode overall is notes), checked
against min; tempo_min_pct asks for at least that share of the score's tempo (Rehearse);
max_wrong limits the wrong keys pressed in a Learn pass. Sing and tap steps carry their own
score (aural.py) under the metric 'pitch' or 'taps'; a quiz is right or wrong.
"""

from __future__ import annotations

PLAY_METRICS = ("notes", "timing", "overall", "tempo_stability")
DEFAULT_PASS = {"metric": "notes", "min": 90}


def evaluate(step: dict, report: dict | None = None, live: dict | None = None, score: float | None = None) -> dict:
    """{passed, score, metric, detail}. report: the pass's comparison (analysis.compare via
    server._compare); live: LiveSession.summary(); score: a ready-made 0-100 score (sing, tap)."""
    rule = {**DEFAULT_PASS, **(step.get("pass") or {})}
    metric = rule["metric"]
    detail = []
    if score is None:
        scores = (report or {}).get("scores") or {}
        if metric not in scores:
            return {"passed": False, "score": None, "metric": metric, "detail": f"no {metric} score for this pass"}
        score = float(scores[metric])
    passed = score >= rule["min"]
    detail.append(f"{metric} {score:.0f} {'≥' if passed else '<'} {rule['min']}")
    pct = ((report or {}).get("tempo") or {}).get("percent_of_reference")
    if rule.get("tempo_min_pct") is not None:
        if pct is None or pct < rule["tempo_min_pct"]:
            passed = False
        detail.append(f"tempo {pct if pct is not None else '?'}% (need {rule['tempo_min_pct']}%)")
    if rule.get("max_wrong") is not None:
        wrong = (live or {}).get("wrong_presses")
        if wrong is None or wrong > rule["max_wrong"]:
            passed = False
        detail.append(f"{wrong if wrong is not None else '?'} wrong (at most {rule['max_wrong']})")
    return {"passed": bool(passed), "score": round(score, 1), "metric": metric, "detail": ", ".join(detail)}


def check_answer(step: dict, answer) -> bool:
    """A quiz answer: an option index, or text matched against the options and 'accept'."""
    import difflib
    import re

    if isinstance(answer, int) or (isinstance(answer, str) and answer.isdigit()):
        return int(answer) == step.get("answer")
    norm = lambda t: re.sub(r"[^a-z0-9#]+", " ", str(t).lower().replace("♯", "#").replace("♭", "b")).strip()  # noqa: E731
    said = norm(answer)
    right = [norm(step["options"][step["answer"]])] if step.get("options") else []
    right += [norm(a) for a in step.get("accept", [])]
    wrong = [norm(o) for k, o in enumerate(step.get("options", [])) if k != step.get("answer")]
    if said in right:
        return True
    words = f" {said} "
    named_right = any(f" {r} " in words for r in right if r)
    named_wrong = any(f" {w} " in words for w in wrong if w)
    if named_right != named_wrong:  # "it's the thumb": the answer said in a sentence
        return named_right
    best_right = max((difflib.SequenceMatcher(None, said, r).ratio() for r in right), default=0)
    best_wrong = max((difflib.SequenceMatcher(None, said, w).ratio() for w in wrong), default=0)
    return best_right >= 0.8 and best_right > best_wrong
