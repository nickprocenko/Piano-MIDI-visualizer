"""The runner's own test check of each fix (fixtests.py), its history, and sending a fix back once."""

import subprocess
from types import SimpleNamespace

from midi_coach import bugs, fixes, fixtests, history, runner
from midi_coach.tests.test_fixgit import home, log_of, repo, report, worker_fixes  # noqa: F401  (fixtures)

QUIET = "....F.\nFAILED midi_coach/tests/test_a.py::test_one - assert 1 == 2\n"


def fake_pytest(results):
    """Stands in for running the suite: `results` maps the checked-out page.html to pytest's output."""
    def run(args, cwd, **kw):
        page = (cwd / "page.html").read_text(encoding="utf-8")
        return SimpleNamespace(stdout=results["fix" if "top" in page else "base"], stderr="", returncode=1)
    return run


def test_pytest_output_is_read():
    out = fixtests.parse("..F\nFAILED midi_coach/tests/test_a.py::test_one - boom\nERROR midi_coach/tests/test_b.py::test_two\n"
                         "1 failed, 540 passed, 1 error in 200.1s")
    assert out["passed"] == 540 and out["failed"] == ["midi_coach/tests/test_a.py::test_one", "midi_coach/tests/test_b.py::test_two"]
    assert not fixtests.parse("ImportError: no module")["ran"]


def test_a_fix_is_tested_against_your_own_code(home, repo, monkeypatch):  # noqa: F811
    item = report()
    worker_fixes(monkeypatch, repo, item)
    run = fake_pytest({
        "base": QUIET + "1 failed, 10 passed in 1s",
        "fix": QUIET + "FAILED midi_coach/tests/test_b.py::test_new - nope\n2 failed, 9 passed in 1s"})
    out = fixtests.check(item, runner=run)
    assert out["new"] == ["midi_coach/tests/test_b.py::test_new"]
    assert out["already"] == ["midi_coach/tests/test_a.py::test_one"]
    fix_md = (home / "requests" / "check" / item / "fix.md").read_text(encoding="utf-8")
    assert "Tests: 9 passed · new failures: midi_coach/tests/test_b.py::test_new · already failing: midi_coach/tests/test_a.py::test_one" in fix_md
    assert bugs.items("check")[0]["fix"] == "Video button moved to the top bar."  # the Tests line isn't "what changed"
    row = {r["id"]: r for r in fixes.board()["items"]}[item]
    assert row["tests"]["state"] == "fail" and row["tests"]["new"] == ["midi_coach/tests/test_b.py::test_new"]
    assert [e["event"] for e in row["history"]] == ["built", "tested"]
    assert log_of(repo)[0] == "start"  # testing never touches your branch
    assert fixtests.baseline(runner=lambda *a, **k: 1 / 0)["failed"] == ["midi_coach/tests/test_a.py::test_one"]  # cached


def test_a_fix_that_breaks_tests_goes_back_once(home, repo, monkeypatch):  # noqa: F811
    item = report()
    worker_fixes(monkeypatch, repo, item)
    monkeypatch.setenv("MIDI_COACH_FIX_TESTS", "on")
    bad = {"id": item, "new": ["midi_coach/tests/test_b.py::test_new"], "line": "9 passed · new failures: …"}
    r = runner.Runner(launch=lambda *a, **k: {"result": "done"}, tester=lambda _id: bad)
    r._finish("worker-1", {"kind": "build", "ids": [item]}, {"result": "done"})
    assert bugs.find(item)[1] == "open"  # sent back
    assert "The runner's test check, not Nick" in (home / "requests" / "open" / item / "report.md").read_text(encoding="utf-8")
    assert [e["event"] for e in history.of(item)][-2:] == ["still_wrong", "sent_back"]

    worker_fixes(monkeypatch, repo, item, text="<button>Video</button> <!-- top again -->\n")
    r._finish("worker-1", {"kind": "build", "ids": [item]}, {"result": "done"})
    assert bugs.find(item)[1] == "check"  # the second time it stays, and the Workshop warns


def test_passing_fixes_stay_ready(home, repo, monkeypatch):  # noqa: F811
    item = report()
    worker_fixes(monkeypatch, repo, item)
    monkeypatch.setenv("MIDI_COACH_FIX_TESTS", "on")
    r = runner.Runner(launch=lambda *a, **k: {}, tester=lambda _id: {"new": [], "line": "10 passed · new failures: none"})
    r._finish("worker-1", {"kind": "build", "ids": [item]}, {"result": "done"})
    assert bugs.find(item)[1] == "check"
