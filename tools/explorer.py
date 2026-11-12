"""Explorer: drive the coach page like a restless user and write down what breaks.

    .venv\\Scripts\\python tools\\explorer.py [--steps 150] [--seed 1] [--width 1280 --height 800] [--file]

It starts its OWN coach (a throwaway MIDI_COACH_HOME holding a few copied songs, port 8890) and
never touches your coach on 8765 or your data. A headless Chrome/Edge (Playwright) then clicks,
types and flips selects at random, and records:

  js_error       an uncaught exception or rejected promise on the page, or console.error
  http_error     a request answered 4xx/5xx, or failed outright
  dead_click     a visible control that changed nothing on the page and sent no request (low confidence)
  overflow       an element wider than the window (a horizontal scrollbar), or a control cut off
  server_crash   the coach process died

Controls whose text says delete / remove / reset / restart / quit / clear / sign out are skipped.
Findings go to %USERPROFILE%\\MidiCoach\\explorer\\<time>\\ (findings.md + screenshots). With --file
each distinct finding is also written to bug_reports/open as a normal report, which the backlog
runner will then pick up and try to fix: leave it off to read them first.
The Critic (looking at screenshots for improvements) is separate; it reads the PNGs saved here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PORT = 8890
SKIP = re.compile(r"delete|remove|reset|restart|quit|exit|clear|erase|sign.?out|log.?out|uninstall|wipe|discard|"
                  r"update|install|upload|import|export|share|bluetooth|connect", re.I)
CLICKABLE = ("button, [role=button], [role=tab], a[href^='#'], summary, select, input[type=checkbox], "
             "input[type=range], input[type=text], [onclick], .tab, .btn")
JS_SNAPSHOT = "() => document.body.innerText.length + ':' + document.body.innerHTML.length + ':' + document.querySelectorAll('*').length"
JS_OVERFLOW = """() => {
  const w = document.documentElement.clientWidth, out = [];
  if (document.documentElement.scrollWidth > w + 2) out.push('page scrolls sideways (' + document.documentElement.scrollWidth + ' > ' + w + ')');
  for (const el of document.querySelectorAll('button, select, input, [role=tab]')) {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || r.width === 0) continue;
    if (r.right > w + 2 || r.left < -2) out.push((el.innerText || el.id || el.className || el.tagName).toString().trim().slice(0, 40) + ' is outside the window');
  }
  return out.slice(0, 5);
}"""


def start_coach(tmp: pathlib.Path) -> subprocess.Popen:
    from midi_coach import library
    lessons = tmp / "lessons" / "Test"
    lessons.mkdir(parents=True)
    for p in library.scan_references()[:400]:
        if p.suffix.lower() in (".mid", ".midi") and 3000 < p.stat().st_size < 60000:
            shutil.copy(p, lessons / p.name)
            if len(list(lessons.iterdir())) >= 4:
                break
    env = dict(os.environ, MIDI_COACH_HOME=str(tmp), MIDI_COACH_DISPLAY_PORT=str(PORT), MIDI_COACH_NO_BROWSER="1",
               MIDI_COACH_VAULT="off", PYTHONIOENCODING="utf-8")
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    proc = subprocess.Popen([str(py if py.exists() else sys.executable), "-m", "midi_coach.practice"], cwd=ROOT, env=env,
                            stdout=(tmp / "coach.log").open("w"), stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
            return proc
        except Exception:
            if proc.poll() is not None:
                break
            time.sleep(1)
    raise SystemExit(f"coach did not start; see {tmp / 'coach.log'}")


class Findings:
    def __init__(self, out: pathlib.Path) -> None:
        self.out, self.items, self.seen = out, [], set()

    def add(self, page, kind: str, detail: str, trail: list[str]) -> None:
        sig = kind + ":" + re.sub(r"\d+", "N", detail)[:120]
        if sig in self.seen:
            return
        self.seen.add(sig)
        n = len(self.items) + 1
        shot = f"{n:02d}-{kind}.png"
        try:
            page.screenshot(path=str(self.out / shot))
        except Exception:
            shot = ""
        self.items.append({"n": n, "kind": kind, "detail": detail, "trail": trail[-8:], "shot": shot})
        print(f"  [{kind}] {detail[:110]}")


def explore(args, out: pathlib.Path, proc: subprocess.Popen) -> Findings:
    from playwright.sync_api import sync_playwright

    rng, found, trail = random.Random(args.seed), Findings(out), []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        requests = {"n": 0}
        page.on("request", lambda r: requests.__setitem__("n", requests["n"] + 1))
        page.on("pageerror", lambda e: found.add(page, "js_error", str(e)[:300], trail))
        page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
                and found.add(page, "js_error", "console.error: " + m.text[:300], trail))
        page.on("requestfailed", lambda r: "/events" not in r.url and "favicon" not in r.url
                and found.add(page, "http_error", f"{r.method} {r.url} failed: {r.failure}", trail))
        page.on("response", lambda r: r.status >= 400 and "favicon" not in r.url
                and found.add(page, "http_error", f"{r.request.method} {r.url.replace(f'http://127.0.0.1:{PORT}', '')} -> {r.status}", trail))
        page.on("dialog", lambda d: d.dismiss())
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(out / "00-start.png"))
        for step in range(1, args.steps + 1):
            if proc.poll() is not None:
                found.add(page, "server_crash", f"coach exited with code {proc.returncode}", trail)
                break
            if not page.url.startswith(f"http://127.0.0.1:{PORT}"):
                page.goto(f"http://127.0.0.1:{PORT}/")
            try:
                els = [e for e in page.query_selector_all(CLICKABLE) if e.is_visible() and e.is_enabled()]
                rng.shuffle(els)
                el = next((e for e in els if not SKIP.search((e.inner_text() or "") + " " + (e.get_attribute("id") or "")
                                                             + " " + (e.get_attribute("title") or ""))), None)
                if el is None:
                    page.goto(f"http://127.0.0.1:{PORT}/")
                    continue
                label = ((el.inner_text() or el.get_attribute("id") or el.get_attribute("title") or el.evaluate("e => e.tagName"))
                         .strip().replace("\n", " ")[:40])
                tag = el.evaluate("e => e.tagName + (e.type ? ':' + e.type : '')")
                before, reqs = page.evaluate(JS_SNAPSHOT), requests["n"]
                if tag == "SELECT":
                    opts = el.evaluate("e => [...e.options].map(o => o.value)")
                    el.select_option(rng.choice(opts))
                elif tag == "INPUT:range":
                    el.fill(str(rng.randint(0, 100)))
                elif tag == "INPUT:text":
                    el.fill(rng.choice(["", "x" * 500, "0", "-1", "<b>hi</b>", "ü漢字", "99999999999"]))
                    el.press("Enter")
                else:
                    el.click(timeout=800)
                trail.append(f"{step}: {tag} '{label}'")
                page.wait_for_timeout(250)
                if page.evaluate(JS_SNAPSHOT) == before and requests["n"] == reqs and tag.startswith(("BUTTON", "A")):
                    found.add(page, "dead_click", f"'{label}' did nothing visible", trail)
                for msg in page.evaluate(JS_OVERFLOW):
                    found.add(page, "overflow", msg, trail)
                if step % 25 == 0:
                    page.screenshot(path=str(out / f"view-{step:03d}.png"))
            except Exception as exc:
                trail.append(f"{step}: (blocked: {str(exc).splitlines()[0][:50]})")
        browser.close()
    return found


def write(found: Findings, args) -> pathlib.Path:
    lines = [f"# Explorer {time.strftime('%Y-%m-%d %H:%M')}  seed {args.seed}  {args.width}x{args.height}  {args.steps} steps", ""]
    if not found.items:
        lines.append("Nothing broke.")
    for it in found.items:
        lines += [f"## {it['n']}. {it['kind']}: {it['detail']}", "", "Steps before it:", *[f"- {t}" for t in it["trail"]], ""]
        if it["shot"]:
            lines += [f"![]({it['shot']})", ""]
    path = found.out / "findings.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def file_reports(found: Findings) -> None:
    from midi_coach import bugs
    folder_root = bugs.reports_dir("bug")
    folder_root.mkdir(parents=True, exist_ok=True)
    for it in found.items:
        if it["kind"] == "dead_click":
            continue  # low confidence: read in findings.md, don't queue work for it
        sig = hashlib.sha1((it["kind"] + re.sub(r"\d+", "N", it["detail"])).encode()).hexdigest()[:8]
        if any(sig in p.name for p in folder_root.glob("*")):
            continue
        d = folder_root / f"{time.strftime('%Y-%m-%d_%H-%M-%S')}-explorer-{sig}"
        d.mkdir()
        if it["shot"]:
            shutil.copy(found.out / it["shot"], d / "now.png")
        (d / "report.md").write_text(
            f"# Bug report {time.strftime('%Y-%m-%d %H:%M:%S')} (found by the Explorer)\n\n## What was said\n\n"
            f"{it['kind']}: {it['detail']}\n\nSteps before it:\n" + "\n".join(f"- {t}" for t in it["trail"])
            + "\n\n## Screenshots (window in front)\n\n- now.png\n", encoding="utf-8")
    bugs.write_backlog()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=150)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--file", action="store_true", help="also file findings as bug reports for the runner")
    a = ap.parse_args()
    from midi_coach.library import home
    out = home() / "explorer" / time.strftime("%Y-%m-%d_%H-%M-%S")
    out.mkdir(parents=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="explorer_home_"))
    proc = start_coach(tmp)
    try:
        res = explore(a, out, proc)
    finally:
        proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{len(res.items)} findings -> {write(res, a)}")
    if a.file:
        file_reports(res)
