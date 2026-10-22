"""Practice on the coach sheet-music page without Claude.

    python -m midi_coach.practice              (from the repo root, with the .venv Python)
    python -m midi_coach.practice great gig    (open a piece from the reference library)

Opens http://127.0.0.1:8765/ with the named piece, else the newest lesson from
~/MidiCoach/lessons, loaded. The
page's menu picks the lesson, MIDI input, Learn / Rehearse, hand, bars, tempo and loop.
Every pass is saved and graded as a take, so Claude can review them later (list_takes,
progress). Don't run this while Claude Desktop's midi-coach is open: both would want the
same keyboard and display port.
"""

from __future__ import annotations

import os
import pathlib
import sys
import threading

from . import server


def main() -> None:
    url = server.hub.start()
    query = " ".join(sys.argv[1:]).strip()
    lessons = server.PAGE_COMMANDS["lessons"]({})["lessons"]
    path = str(server.library.resolve_reference(query)) if query else lessons[0]["path"] if lessons else None
    if path:
        server.hub.load_score(server.library.get_score(path))
        server.hub.status(f"{pathlib.Path(path).stem} · pick Learn or Rehearse and press Start")
    if not os.environ.get("MIDI_COACH_NO_BROWSER"):
        server.hub.open_browser()
    print(f"Piano Coach practice page: {url}  (Ctrl+C to quit)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


if __name__ == "__main__":
    main()
