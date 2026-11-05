"""The backlog runner: triage first, two workers on batches that share no files, each in its own
worktree; stuck items set aside; a usage limit gives the work back and waits. Claude Code is
replaced by a fake that does what a worker would."""

import os
import time

from midi_coach import bugs, fixgit, runner
from midi_coach.tests.test_fixgit import home, log_of, repo, report  # noqa: F401  (fixtures)


class FakeClaude:
    """Stands in for claude_run.run: records each call and runs `act(name, tree)` as the worker."""

    def __init__(self, act=None, out=None):
        self.calls, self.act, self.out = [], act, out or {"result": "done"}

    def __call__(self, prompt, model, tools="", cwd=None, timeout=0, env=None, extra=None):
        self.calls.append({"prompt": prompt, "cwd": cwd, "env": env, "extra": extra})
        if self.act:
            before = os.environ.get("MIDI_COACH_REPO")
            os.environ["MIDI_COACH_REPO"] = env["MIDI_COACH_REPO"]  # what the worker's own commands see
            try:
                self.act(prompt.split(",", 1)[0].removeprefix("You are "), cwd)
            finally:
                os.environ["MIDI_COACH_REPO"] = before
        return self.out


def test_untriaged_items_are_triaged_first_by_one_worker(home, repo):
    a, b = report("video button"), report("tiles overlap", kind="bug")

    def triage(name, tree):
        bugs.triage(a, "top bar", "S", ["page.html"])
        bugs.triage(b, "top bar", "S", ["page.html"])

    fake = FakeClaude(triage)
    started = runner.Runner(launch=fake, wait=True).tick()
    assert started[0].startswith("worker-1: triage 2")
    call = fake.calls[0]
    assert "Triage these open items" in call["prompt"] and a in call["prompt"] and b in call["prompt"]
    assert call["cwd"] == home / "workers" / "worker-1" and call["env"]["MIDI_COACH_REPO"] == str(call["cwd"])
    rules = call["extra"][1]
    assert "Edit(./**)" in rules and "Bash(.venv/Scripts/python:*)" in rules and "Bash(git status:*)" in rules
    assert "Bash(git push" not in rules and "Bash(git commit" not in rules
    assert all(it["claimed"] is None and it["triage"] for it in bugs.items("open"))  # back in the queue
    assert len(started) == 2 and "batch 'top bar'" in started[1]  # the other slot builds straight away


def test_two_workers_build_separate_batches_on_side_branches(home, repo):
    video, names = report("video button"), report("note names", kind="bug")
    bugs.triage(video, "top bar", "S", ["page.html"])
    bugs.triage(names, "sheet", "S", ["notes.py"])
    fixes = {"top bar": ("page.html", "<button>Video</button> <!-- top -->\n"), "sheet": ("notes.py", "TEMPO = 99\n")}

    def build(name, tree):
        claimed = [it for it in bugs.items("open") if (it["claimed"] or {}).get("by") == name][0]
        path, text = fixes[claimed["triage"]["area"]]
        (tree / path).write_text(text, encoding="utf-8")
        assert "commit" in bugs.mark_ready(claimed["id"], "Fixed.", files=[path], by=name)

    fake = FakeClaude(build)
    started = runner.Runner(launch=fake, wait=True).tick()
    assert [s.split(":")[0] for s in started] == ["worker-1", "worker-2"]
    assert {it["id"] for it in bugs.items("check")} == {video, names}
    assert log_of(repo)[0] == "start"  # nothing reached your branch yet
    assert (fake.calls[0]["cwd"] / ".venv").exists() or not (fixgit.repo() / ".venv").exists()
    ports = {c["prompt"].split("throwaway coach on port ")[1].split()[0] for c in fake.calls}
    assert ports == {"8799", "8800"}  # each worker's throwaway coach on its own port
    assert bugs.verify(video, works=True)["merged"] and "top" in (repo / "page.html").read_text(encoding="utf-8")


def test_an_item_a_worker_leaves_is_set_aside_not_retried(home, repo):
    item = report("video button")
    bugs.triage(item, "top bar", "S", ["page.html"])
    fake = FakeClaude(out={"result": "I couldn't find the button.\nstuck"})
    r = runner.Runner(launch=fake, wait=True)
    r.tick()
    it = bugs.items("open")[0]
    assert it["stuck"]["by"] == "worker-1" and "didn't finish" in it["stuck"]["why"] and it["claimed"] is None
    assert r.tick() == [] and len(fake.calls) == 1  # not tried again
    assert bugs.batches()["stuck"][0]["id"] == item
    bugs.unstick(item)
    assert r.tick()  # back in the queue


def test_a_usage_limit_gives_the_work_back_and_waits(home, repo):
    item = report("video button")
    bugs.triage(item, "top bar", "S", ["page.html"])
    fake = FakeClaude(out={"error": "usage limit reached", "usage_limit": True})
    r = runner.Runner(launch=fake, wait=True)
    r.tick()
    it = bugs.items("open")[0]
    assert it["claimed"] is None and it["stuck"] is None  # given back, not stuck
    assert r.paused_until > time.time() and r.tick() == []
    r.paused_until = 0
    assert r.tick()  # tries again after the wait
