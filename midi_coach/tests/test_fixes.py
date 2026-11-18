"""The fix board Agent Quest's Workshop shows (fixes.py), and the Hub commands that serve it."""

import json
import subprocess
import urllib.request

import pytest

from midi_coach import bugs, display, fixes, fixgit
from midi_coach.tests.test_fixgit import home, log_of, repo, report, worker_fixes  # noqa: F401  (fixtures)


def test_the_board_puts_each_item_in_its_column(home, repo, monkeypatch):  # noqa: F811
    queued, asked, building, ready = report("tiles"), report("which colour?"), report("metronome"), report("video")
    bugs.triage(queued, "top bar & layout", "S", files=["page.html"])
    bugs.triage(asked, "top bar & layout", "S", needs="question", question="Which colour?", choices=["Blue", "Gold"])
    bugs.claim(building, "worker-2")
    worker_fixes(monkeypatch, repo, ready)
    out = fixes.board()
    by_id = {r["id"]: r for r in out["items"]}
    assert by_id[queued]["column"] == "queued" and by_id[queued]["area"] == "top bar & layout"
    assert by_id[asked]["column"] == "question" and by_id[asked]["choices"] == ["Blue", "Gold"]
    assert by_id[building]["column"] == "building" and by_id[building]["worker"] == "worker-2"
    assert by_id[ready]["column"] == "ready" and by_id[ready]["files"] == ["page.html"]
    assert by_id[ready]["fixed"] == "Video button moved to the top bar."
    assert out["counts"]["ready"] == 1 and out["columns"][0] == "question"
    assert [r["column"] for r in out["items"]] == sorted((r["column"] for r in out["items"]), key=fixes.COLUMNS.index)


def test_works_adds_the_fix_and_says_the_page_needs_a_reload(home, repo, monkeypatch):  # noqa: F811
    item = report()
    worker_fixes(monkeypatch, repo, item)
    out = fixes.works(item)
    assert out["merged"] and out["restart"] is False
    assert log_of(repo)[0].startswith("Request: Video button moved")
    done = {r["id"]: r for r in fixes.board()["items"]}[item]
    assert done["column"] == "done" and done["outcome"] == "works"


def test_save_first_commits_your_edits_then_adds_the_fix(home, repo, monkeypatch):  # noqa: F811
    lines = [f"<p>{n}</p>\n" for n in range(12)]
    (repo / "page.html").write_text("<button>Video</button>\n" + "".join(lines), encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "longer page"], cwd=repo, check=True)
    item = report()
    worker_fixes(monkeypatch, repo, item, text="<button>Video</button> <!-- top -->\n" + "".join(lines))
    mine = "<button>Video</button>\n" + "".join(lines[:-1]) + "<p>11 mine</p>\n"
    (repo / "page.html").write_text(mine, encoding="utf-8")  # your own edit, far down the same file

    held = fixes.works(item)
    assert held["wait"] == ["page.html"] and held["can_save_first"] is True
    assert log_of(repo)[0] == "longer page"

    out = fixes.works(item, save_first=True)
    assert out["saved"]["files"] == ["page.html"] and out["merged"]
    assert log_of(repo)[:2] == ["Request: Video button moved to the top bar.",
                                "Work in progress (saved before adding: Video button moved to the top bar.)"]
    text = (repo / "page.html").read_text(encoding="utf-8")
    assert "<!-- top -->" in text and "11 mine" in text  # both kept
    assert not fixgit.dirty_files()


def test_still_wrong_drops_it_and_closes_its_test_copy(home, repo, monkeypatch):  # noqa: F811
    item = report()
    worker_fixes(monkeypatch, repo, item)
    closed = []
    monkeypatch.setattr(fixes.preview, "current", lambda: {"id": item})
    monkeypatch.setattr(fixes.preview, "close", lambda: closed.append(item) or {"closed": item})
    out = fixes.still_wrong(item, "still in the corner")
    assert out["undone"] is True and closed == [item] and log_of(repo)[0] == "start"
    row = {r["id"]: r for r in fixes.board()["items"]}[item]
    assert row["column"] == "queued" and row["reopened"]


def test_answering_a_question_puts_it_in_the_queue(home, repo):  # noqa: F811
    item = report("which colour?")
    bugs.triage(item, "top bar & layout", "S", needs="question", question="Which colour?", choices=["Blue", "Gold"])
    fixes.answer(item, "2")
    row = {r["id"]: r for r in fixes.board()["items"]}[item]
    assert row["column"] == "queued" and row["needs"] == "build"
    assert "in Agent Quest" in (home / "requests" / "open" / item / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("origin, allowed", [(None, True), ("http://localhost:4445", True),
                                             ("http://127.0.0.1:8765", True), ("https://example.com", False),
                                             ("http://localhost.evil.com", False)])
def test_only_this_pc_may_use_the_fix_commands(origin, allowed):
    assert display._local_origin(origin) is allowed


def test_the_hub_refuses_fix_commands_from_a_website(monkeypatch):
    hub = display.DisplayHub()
    monkeypatch.setenv("MIDI_COACH_DISPLAY_PORT", "8790")
    hub.commands["fixes"] = lambda body: {"items": []}
    hub.local_only.add("fixes")
    url = hub.start()
    try:
        def post(origin):
            headers = {"Content-Type": "application/json", **({"Origin": origin} if origin else {})}
            req = urllib.request.Request(url + "cmd/fixes", data=b"{}", headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=5) as res:
                    return res.status, json.loads(res.read())
            except urllib.error.HTTPError as err:
                return err.code, json.loads(err.read())
        assert post(None) == (200, {"items": []})
        assert post("https://example.com")[0] == 403
    finally:
        hub.shutdown()
