"""Put "Music Coach" in the Start menu (so Windows search finds it) and on the Desktop.

    python -m midi_coach.shortcut

Both shortcuts run "Launch Music Coach.bat" from the repo with the coach logo
(static/coach.ico). Running it again rewrites them in place, so they keep pointing at this
copy of the repo. The launcher behind them always opens the current code (midi_coach.launch).
"""

from __future__ import annotations

import pathlib
import subprocess

STATIC = pathlib.Path(__file__).resolve().parent / "static"
REPO = STATIC.parent.parent
NAME = "Music Coach"
DESCRIPTION = "Practice piano or flute with the coach page"


def _script(lnk: str) -> str:
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    return "\n".join([
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + lnk + ")",
        f"$s.TargetPath = {q(REPO / 'Launch Music Coach.bat')}",
        f"$s.WorkingDirectory = {q(REPO)}",
        f"$s.IconLocation = {q(str(STATIC / 'coach.ico') + ',0')}",
        f"$s.Description = {q(DESCRIPTION)}",
        "$s.Save()",
        "$s.FullName",
    ])


def install() -> list[str]:
    made = []
    for folder in ("Programs", "Desktop"):
        lnk = f"(Join-Path ([Environment]::GetFolderPath('{folder}')) '{NAME}.lnk')"
        out = subprocess.run(["powershell", "-NoProfile", "-Command", _script(lnk)],
                             capture_output=True, text=True, check=True)
        made.append(out.stdout.strip())
    return made


if __name__ == "__main__":
    for path in install():
        print("wrote", path)
    print("Windows can take a minute to show the new icon; search the Start menu for \"Music Coach\".")
