"""One-step setup of midi-coach for Claude Desktop.

    python midi_coach\\setup_claude_desktop.py            (from the repo root)

1. Creates .venv in the repo and installs midi_coach/requirements.txt
2. Lists MIDI ports so you can confirm the keyboard is visible
3. Adds a "midi-coach" entry to claude_desktop_config.json (backing up the
   original; other servers and settings are preserved)

Options:
    --input NAME    set MIDI_COACH_INPUT (e.g. Coach when using a loopMIDI port)
    --output NAME   set MIDI_COACH_OUTPUT (default JUNO)
    --no-install    skip venv creation / pip install (uses .venv if present, else this Python)
    --dry-run       show the config that would be written, change nothing
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO / "midi_coach" / "requirements.txt"
IS_WINDOWS = os.name == "nt"


def venv_python(venv: pathlib.Path) -> pathlib.Path:
    return venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def step(text: str) -> None:
    print(f"\n== {text}")


def install(no_install: bool) -> pathlib.Path:
    venv = REPO / ".venv"
    py = venv_python(venv)
    if no_install:
        return py if py.exists() else pathlib.Path(sys.executable)
    if not py.exists():
        step(f"Creating virtual environment in {venv}")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
    step("Installing midi-coach dependencies (music21 is large; this can take a few minutes)")
    subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    return py


def show_ports(py: pathlib.Path) -> None:
    step("MIDI ports")
    code = (
        "import json,sys; sys.path.insert(0, sys.argv[1])\n"
        "from midi_coach.midi_io import list_ports\n"
        "print(json.dumps(list_ports()))"
    )
    try:
        out = subprocess.run([str(py), "-c", code, str(REPO)], capture_output=True, text=True, timeout=60)
    except Exception as exc:
        print(f"  could not list ports: {exc}")
        return
    if out.returncode != 0:
        print("  could not list ports:\n  " + (out.stderr.strip().splitlines() or ["unknown error"])[-1])
        return
    ports = json.loads(out.stdout.strip().splitlines()[-1])
    for kind in ("inputs", "outputs"):
        names = ports.get(kind) or []
        print(f"  {kind}: " + (", ".join(names) if names else "(none)"))
    if not any("juno" in n.lower() for n in ports.get("inputs", [])):
        print("  ! No JUNO input found. Is the USB cable connected and the keyboard on? "
              "(Fine if you'll use a loopMIDI port with --input.)")


def config_paths() -> list[pathlib.Path]:
    """Claude Desktop config locations: standard install, Microsoft Store install, macOS."""
    found: list[pathlib.Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        found.append(pathlib.Path(appdata) / "Claude" / "claude_desktop_config.json")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for pkg in (pathlib.Path(local) / "Packages").glob("Claude_*"):
            found.append(pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")
    if sys.platform == "darwin":
        found.append(pathlib.Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    existing = [p for p in found if p.exists() or p.parent.exists()]
    return existing or found[:1]


def server_entry(py: pathlib.Path, input_port: str | None, output_port: str | None) -> dict:
    env = {"PYTHONPATH": str(REPO)}
    if input_port:
        env["MIDI_COACH_INPUT"] = input_port
    if output_port:
        env["MIDI_COACH_OUTPUT"] = output_port
    return {"command": str(py), "args": ["-m", "midi_coach"], "env": env}


def write_config(path: pathlib.Path, entry: dict, dry_run: bool) -> None:
    data: dict = {}
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            try:
                data = json.loads(text)
            except ValueError as exc:
                print(f"  ! {path} is not valid JSON ({exc}); not touching it. Add this under \"mcpServers\":")
                print(json.dumps({"midi-coach": entry}, indent=2))
                return
    data.setdefault("mcpServers", {})["midi-coach"] = entry
    if dry_run:
        print(f"  would write {path}:\n" + json.dumps(data, indent=2))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + time.strftime(".bak-%Y%m%d-%H%M%S"))
        shutil.copy2(path, backup)
        print(f"  backup: {backup}")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  updated: {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input")
    ap.add_argument("--output", default="JUNO")
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if sys.version_info < (3, 10):
        print(f"Python 3.10 or newer is required (this is {sys.version.split()[0]}).")
        return 1
    py = install(args.no_install or args.dry_run)
    show_ports(py)
    step("Claude Desktop config")
    entry = server_entry(py, args.input, args.output)
    for path in config_paths():
        write_config(path, entry, args.dry_run)
    step("Next")
    print("  1. Quit Claude Desktop completely (right-click its tray icon > Quit) and open it again.")
    print("  2. In a new chat, ask: \"List my MIDI ports with midi-coach.\"")
    print("  3. Close the visualizer first if it is using the JUNO (or set up loopMIDI, see midi_coach/README.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
