"""Draw a MusicXML score as a PNG, with the same library the coach page uses (OSMD), in a
headless Chrome or Edge - so a score can be looked at, not just its notes checked.

    python -m midi_coach.render lesson.musicxml out.png [first_bar last_bar]
"""

from __future__ import annotations

import json
import os
import pathlib
import re
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
const xml = %(xml)s;
osmd.load(xml).then(() => {
  if (xml.includes("<measure-numbering>none</measure-numbering>")) osmd.EngravingRules.RenderMeasureNumbers = false;
  osmd.render(); document.title = "rendered"; })
  .catch(e => { document.body.innerText = "OSMD error: " + e; });
</script></body></html>"""


def browser() -> str:
    for path in [os.environ.get("MIDI_COACH_BROWSER", "")] + list(BROWSERS):
        if path and pathlib.Path(path).is_file():
            return path
    raise FileNotFoundError("No Chrome or Edge found; set MIDI_COACH_BROWSER to one.")


ATTRIBUTES = ("divisions", "key", "time", "clef")  # in the order MusicXML wants them


def from_bar(xml: str, first: int) -> str:
    """The score without its bars before `first`, each part's divisions, key, time signature
    and clef in force carried into that bar. OSMD told to draw from a later bar keeps the key
    signature but draws the clef the piece starts with, so an excerpt of a right hand that went
    to the treble clef earlier would show its notes on the bass staff."""
    def part(m: re.Match) -> str:
        body = m.group(0)
        state: dict[str, str] = {}
        bars = list(re.finditer(r'<measure\b[^>]*\bnumber="(-?\d+)"[^>]*>(.*?)</measure>\s*', body, re.S))
        for bar in bars:
            inside = bar.group(2)
            if int(bar.group(1)) < first:
                for name in ATTRIBUTES:
                    found = re.findall(rf"<{name}\b.*?</{name}>", inside, re.S)
                    state[name] = found[-1] if found else state.get(name, "")
                continue
            own = re.search(r"<attributes>(.*?)</attributes>", inside, re.S)
            for name in ATTRIBUTES:
                if own and re.search(rf"<{name}\b", own.group(1)):
                    state[name] = re.search(rf"<{name}\b.*?</{name}>", own.group(1), re.S).group(0)
            merged = "<attributes>" + "".join(state.get(n, "") for n in ATTRIBUTES) + "</attributes>"
            inside = inside.replace(own.group(0), merged, 1) if own else merged + inside
            return body[:bars[0].start()] + body[bar.start():bar.start(2)] + inside + body[bar.end(2):]
        return body

    return re.sub(r"<part\s[^>]*>.*?</part>", part, xml, flags=re.S)


def render_png(score: str | pathlib.Path, out: str | pathlib.Path, first: int = 1, last: int = 8,
               width: int = 1500, height: int | None = None) -> pathlib.Path:
    """Draw bars first..last of a MusicXML file (path, or the XML itself) to a PNG."""
    text = str(score)
    xml = pathlib.Path(text).read_text(encoding="utf-8") if not text.lstrip().startswith("<") else text
    if first > 1:  # OSMD counts the bars it draws from by their place in the file, not their number
        xml, first, last = from_bar(xml, first), 1, last - first + 1
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
