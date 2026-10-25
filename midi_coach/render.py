"""Draw a MusicXML score as a PNG, with the same library the coach page uses (OSMD), in a
headless Chrome or Edge - so a score can be looked at, not just its notes checked.

    python -m midi_coach.render lesson.musicxml out.png [first_bar last_bar]
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

OSMD = "https://cdn.jsdelivr.net/npm/opensheetmusicdisplay@1.9.3/build/opensheetmusicdisplay.min.js"
BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

PAGE = """<!doctype html><html><head><meta charset="utf-8"><script src="%(osmd)s"></script>
<style>html,body{margin:0;background:#fff}#score{width:%(width)dpx}</style></head>
<body><div id="score"></div><script>
const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay("score", {
  autoResize: false, backend: "svg", drawTitle: true, drawPartNames: true,
  drawFromMeasureNumber: %(first)d, drawUpToMeasureNumber: %(last)d});
osmd.load(%(xml)s).then(() => { osmd.render(); document.title = "rendered"; })
  .catch(e => { document.body.innerText = "OSMD error: " + e; });
</script></body></html>"""


def browser() -> str:
    for path in [os.environ.get("MIDI_COACH_BROWSER", "")] + list(BROWSERS):
        if path and pathlib.Path(path).is_file():
            return path
    raise FileNotFoundError("No Chrome or Edge found; set MIDI_COACH_BROWSER to one.")


def render_png(score: str | pathlib.Path, out: str | pathlib.Path, first: int = 1, last: int = 8,
               width: int = 1500, height: int | None = None) -> pathlib.Path:
    """Draw bars first..last of a MusicXML file (path, or the XML itself) to a PNG."""
    text = str(score)
    xml = pathlib.Path(text).read_text(encoding="utf-8") if not text.lstrip().startswith("<") else text
    out = pathlib.Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    height = height or 420 + 110 * (last - first + 1)  # room for a few systems of three staves
    with tempfile.TemporaryDirectory() as tmp:
        page = pathlib.Path(tmp) / "score.html"
        page.write_text(PAGE % {"osmd": OSMD, "width": width, "first": first, "last": last,
                                "xml": json.dumps(xml)}, encoding="utf-8")
        subprocess.run([browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={width},{height}", "--virtual-time-budget=20000",
                        f"--screenshot={out}", page.as_uri()],
                       check=True, capture_output=True, timeout=120)
    if not out.is_file():
        raise RuntimeError("The browser didn't write a screenshot.")
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    print(render_png(a[0], a[1], *(int(x) for x in a[2:4])))
