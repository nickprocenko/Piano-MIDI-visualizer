"""Draw the falling notes' hands (Sheet ▸ Hands on the keys) at chosen moments of a piece, to
PNGs, in a headless Chrome or Edge running the coach page's own roll.js and hands3d.js - so the
hands can be looked at, and a change to them checked, without the page.

    python -m midi_coach.hands_render <score> <out_dir> [moments] [options]

Moments (default: every beat of the first four bars):
    --at 12.5,14,20        seconds into the piece
    --beats 32,33.5        beats
    --bars 5 8 [--every 0.5]   bars 5 to 8, every half beat (default every beat)

Options:
    --size 1600x900     the page's size in CSS pixels      --scale 1.5   device pixel ratio
    --keys 21-108       the keyboard's range (MIDI pitches; default the piece's, as on the page)
    --crop              keep only the keys and the hands
    --warm 3            seconds of playback before each moment, so the hands arrive as they do
                        while it plays (moments closer together play straight through)

The score is loaded as the coach page loads it (the part choices and Clean apply), and played
at its own tempo in 60 frames a second: the hands ease from frame to frame as on the page. Each
moment is `<out_dir>/<seconds>s.png`; `frames.json` has, per moment, the beat, where the keys
are, each hand's fingertips (x, y in page pixels, press, on), how far each 3D fingertip
missed its key (cm) and where each 3D hand and its finger joints were (`pose`, cm).
"""

from __future__ import annotations

import argparse
import bisect
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .render import browser

STATIC = pathlib.Path(__file__).parent / "static"
FPS = 60
TIMELINE_STEP = 0.02  # seconds between the samples of the piece's time -> beat map
TYPES = {".js": "application/javascript", ".html": "text/html", ".json": "application/json",
         ".glb": "model/gltf-binary", ".css": "text/css", ".png": "image/png"}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script type="importmap">{"imports": {"three": "./vendor/three/three.module.min.js"}}</script>
<style>html,body{margin:0;background:#0f0f14;overflow:hidden}#roll{display:block;width:100vw;height:100vh}</style>
</head><body><canvas id="roll"></canvas>
<script>
window.onerror = (msg, src, line) => { fetch('/__error', {method: 'POST', body: msg + ' (' + src + ':' + line + ')'}); };
window.onunhandledrejection = e => { fetch('/__error', {method: 'POST', body: String(e.reason && e.reason.stack || e.reason)}); };
for (const level of ['warn', 'error']) {  // e.g. why the 3D hands didn't load
  const was = console[level];
  console[level] = (...a) => { was(...a); fetch('/__error', {method: 'POST', body: a.map(x => x && x.stack || String(x)).join(' ')}); };
}
</script>
<script src="roll.js"></script>
<script type="module">
const job = await (await fetch('/__job.json')).json();
const mode = await coachRoll.handsLoaded();
coachRoll.score({notes: job.notes, bars: job.bars});
if (job.keys) coachRoll.keyRange(job.keys[0], job.keys[1]);
const tl = job.timeline;  // [[seconds, beat], ...] evenly spaced
const beatAt = t => {
  const i = Math.max(0, Math.min(tl.length - 2, Math.floor(t / job.step)));
  const [t0, b0] = tl[i], [t1, b1] = tl[i + 1];
  return b0 + (b1 - b0) * (t - t0) / (t1 - t0);
};
const canvas = document.getElementById('roll');
const step = 1 / job.fps, frames = [];
let t = null;
for (const m of job.moments) {
  if (t === null || m.t - t > job.warm) t = Math.max(job.start, m.t - job.warm);
  for (; t < m.t - 1e-6; t += step) coachRoll.frameAt(beatAt(t), t * 1000, true);
  t = m.t;
  const info = coachRoll.frameAt(beatAt(t), t * 1000);
  t += step;
  const blob = await new Promise(r => canvas.toBlob(r, 'image/png'));
  await fetch('/__save/' + m.name + '.png', {method: 'POST', body: blob});
  frames.push({name: m.name, seconds: m.t, ...info});
}
await fetch('/__save/frames.json', {method: 'POST', body: JSON.stringify({hands: mode, dpr: devicePixelRatio, frames}, null, 1)});
await fetch('/__done', {method: 'POST', body: mode});
</script></body></html>"""


def build_job(score, moments: list[float], keys: tuple[int, int] | None, warm: float) -> dict:
    """What the page needs: the notes as the coach page gets them, the bars, the piece's
    time -> beat map, and the moments to draw (seconds, in order)."""
    from .display import roll_notes

    end = max([n.end for n in score.notes] + moments) + 1.0
    count = int(end / TIMELINE_STEP) + 2
    timeline = [[round(i * TIMELINE_STEP, 4), round(score.beat_of(i * TIMELINE_STEP), 5)] for i in range(count)]
    bars = [{"number": b.number, "start_beat": round(b.start_beat, 4), "end_beat": round(b.end_beat, 4)} for b in score.bars]
    return {"notes": roll_notes(score), "bars": bars, "timeline": timeline, "step": TIMELINE_STEP,
            "fps": FPS, "warm": warm, "start": 0.0, "keys": list(keys) if keys else None,
            "moments": [{"t": round(t, 4), "name": moment_name(t)} for t in sorted(set(moments))]}


def moment_name(t: float) -> str:
    return f"{t:08.3f}s".replace(".", "_")


def seconds_of_beat(score, beat: float) -> float:
    """The time a beat falls at (the inverse of score.beat_of, which only ever rises)."""
    lo, hi = 0.0, max(1.0, score.notes[-1].end if score.notes else 1.0)
    while score.beat_of(hi) < beat and hi < 1e5:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if score.beat_of(mid) < beat:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def moments_of(score, at: str | None, beats: str | None, bars: list[int] | None, every: float) -> list[float]:
    nums = lambda s: [float(x) for x in re.split(r"[,\s]+", s.strip()) if x]  # noqa: E731
    if at:
        return nums(at)
    if beats:
        return [seconds_of_beat(score, b) for b in nums(beats)]
    if bars:
        first, last = bars
    else:
        first = score.bars[0].number if score.bars else 1
        last = first + 3
    chosen = [b for b in score.bars if first <= b.number <= last]
    if not chosen:
        raise ValueError(f"No bars {first}-{last} in this piece (it has {len(score.bars)}).")
    start, stop = chosen[0].start_beat, chosen[-1].end_beat
    out, b = [], start
    while b < stop - 1e-6:
        out.append(seconds_of_beat(score, b))
        b += every
    return out


def run_page(job: dict, out: pathlib.Path, size: tuple[int, int], scale: float, timeout: float = 600) -> str:
    """Serve the page and the static files, let a headless browser draw every moment, and
    save what it sends back into out. Returns '3d' or '2d' (which hands were drawn)."""
    out.mkdir(parents=True, exist_ok=True)
    done = threading.Event()
    result: dict = {}
    page = PAGE.encode()
    job_bytes = json.dumps(job).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/__render.html":
                body, kind = page, "text/html"
            elif path == "/__job.json":
                body, kind = job_bytes, "application/json"
            else:
                f = (STATIC / path.lstrip("/")).resolve()
                if STATIC.resolve() not in f.parents or not f.is_file():
                    self.send_error(404)
                    return
                body, kind = f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path.startswith("/__save/"):
                name = re.sub(r"[^\w.-]", "_", self.path[len("/__save/"):])
                (out / name).write_bytes(body)
            elif self.path == "/__error":
                result.setdefault("errors", []).append(body.decode("utf-8", "replace"))
                print("page error:", body.decode("utf-8", "replace"), file=sys.stderr)
            elif self.path == "/__done":
                result["mode"] = body.decode()
                done.set()
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = tempfile.mkdtemp(prefix="hands-render-")
    w, h = size
    proc = subprocess.Popen(
        [browser(), "--headless=new", "--hide-scrollbars", f"--window-size={w},{h}",
         f"--force-device-scale-factor={scale}", f"--user-data-dir={profile}", "--no-first-run",
         "--no-default-browser-check", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
         "--ignore-gpu-blocklist", "--disable-background-timer-throttling", "--remote-debugging-port=0",
         f"http://127.0.0.1:{server.server_address[1]}/__render.html"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not done.wait(timeout):
            raise TimeoutError("The page didn't finish drawing" + (": " + "; ".join(result["errors"]) if result.get("errors") else "."))
    finally:
        proc.kill()
        proc.wait(timeout=30)
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    return result["mode"]


def crop_to_hands(out: pathlib.Path) -> None:
    """Each PNG cut down to the keys and the hands: from a little above the note line to the
    bottom of the page."""
    from PIL import Image

    meta = json.loads((out / "frames.json").read_text(encoding="utf-8"))
    dpr = meta["dpr"]
    for fr in meta["frames"]:
        lay = fr.get("layout")
        if not lay:
            continue
        top = max(0, int((lay["floor"] - 0.8 * lay["keyH"]) * dpr))
        path = out / f"{fr['name']}.png"
        with Image.open(path) as im:
            im.crop((0, top, im.width, im.height)).save(path)


def render(ref: str, out: str | pathlib.Path, moments: list[float] | None = None, *, at: str | None = None,
           beats: str | None = None, bars: list[int] | None = None, every: float = 1.0,
           size: tuple[int, int] = (1600, 900), scale: float = 1.0, keys: tuple[int, int] | None = None,
           warm: float = 3.0, crop: bool = False) -> dict:
    from . import library

    score = library.get_score(ref)
    if moments is None:
        moments = moments_of(score, at, beats, bars, every)
    out = pathlib.Path(out).resolve()
    job = build_job(score, moments, keys, warm)
    mode = run_page(job, out, size, scale)
    if crop:
        crop_to_hands(out)
    return {"hands": mode, "out": str(out), "moments": [m["name"] for m in job["moments"]]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m midi_coach.hands_render", description=__doc__.split("\n\n")[0])
    ap.add_argument("score")
    ap.add_argument("out")
    ap.add_argument("--at")
    ap.add_argument("--beats")
    ap.add_argument("--bars", nargs=2, type=int)
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--size", default="1600x900")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--keys")
    ap.add_argument("--warm", type=float, default=3.0)
    ap.add_argument("--crop", action="store_true")
    a = ap.parse_args(argv)
    w, h = (int(x) for x in a.size.lower().split("x"))
    keys = tuple(int(x) for x in a.keys.split("-")) if a.keys else None
    res = render(a.score, a.out, at=a.at, beats=a.beats, bars=a.bars, every=a.every, size=(w, h),
                 scale=a.scale, keys=keys, warm=a.warm, crop=a.crop)
    print(f"{len(res['moments'])} frames ({res['hands']} hands) in {res['out']}")


if __name__ == "__main__":
    main()
