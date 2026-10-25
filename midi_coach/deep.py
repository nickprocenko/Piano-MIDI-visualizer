"""Deep questions: the Maestro hands them to Claude Code, on the pianist's Claude subscription.

Quick commands stay with the voice chat (chat.py, Claude API). A question that needs real
teaching - a spoken lesson on a song, why a bar is hard, a practice plan - goes to `claude -p`
(Claude Code's headless mode) signed in with the pianist's claude.ai account, so it uses no API
credits. That run connects back to this coach through a local MCP endpoint with every
midi-coach tool (inspect the score, play passages, start a Learn run, speak with `say`), so it
teaches through the same keyboard, page and voice.

If Claude Code isn't installed or the run fails (signed out, usage limit), the question is
saved to an inbox that Claude Desktop reads with the maestro_inbox tool.

Also here: the Maestro's notebook (maestro_notes.md), lasting facts about the pianist that the
voice chat, these runs and Claude Desktop all read and add to.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import shutil
import socket
import subprocess
import threading
import time

from .library import home

log = logging.getLogger("midi-coach")

DEFAULT_MODEL = "sonnet"
MCP_PORT = 8780
RUN_TIMEOUT_SEC = 6 * 60
RESUME_WITHIN_SEC = 2 * 60 * 60  # a follow-up within this continues the same lesson
NOTES_CONTEXT_CHARS = 2500
# Kept out of the run's environment: an API key would bill the API instead of the subscription,
# and CLAUDECODE makes a nested run refuse to start when the coach was launched from Claude Code.
STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")

TEACHER_PROMPT = """\
You are the Maestro, the piano teacher in the pianist's practice app, taking over a question \
the quick voice assistant passed to you because it needs real teaching. The pianist is sitting \
at their keyboard (a Roland JUNO-DS88, 88 keys) with the coach page open. They hear you; they \
don't read you.

Speak to them only with the midi-coach say tool. Each say call: two to four short spoken \
sentences, plain words only, no lists, markdown, emoji or symbols ("bar five", "F sharp", \
"eighty percent"). Use several say calls for a longer explanation, one idea each. Your final \
text reply is not spoken: end with a one-line summary of what you did, for the log.

Character: a strict, dry-humoured teacher who clearly wants the pianist to get better and \
explains generously when asked. Praise only what was earned. Criticise the playing, never the \
person.

Teaching a song or a passage: look before you speak. status shows the score on screen; \
inspect_reference gives its parts, bars and key; chords_in_score names each bar's chord; \
progress shows where the pianist keeps going wrong. Teach one section per question: what it is \
and where it sits in the song, what each hand does, the harmony underneath, the hard spot and \
how to practise it. Demonstrate with play (just those bars, one hand if that helps, slower), \
then set it up with start_recording(mode="wait", bars=..., hand=...) so they can try it, tell \
them to go ahead, and stop there. They will ask for the next section; this conversation \
continues, so you know where you left off.

Song background, theory, practice plans: answer from what you know, and say so when you're not \
sure. Only quote scores and numbers that the tools or the practice context give you.

Use remember for lasting facts about the pianist (goals, pieces they're learning, weak spots, \
how they like to be taught, where a lesson left off), one short line each.\
"""


def find_claude() -> str | None:
    explicit = os.environ.get("MIDI_COACH_CLAUDE")
    if explicit:
        return explicit if pathlib.Path(explicit).exists() else None
    found = shutil.which("claude")
    if found:
        return found
    local = pathlib.Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(local) if local.exists() else None


# ---------------------------------------------------------------------------
# Notebook and inbox
# ---------------------------------------------------------------------------


def notes_path() -> pathlib.Path:
    return home() / "maestro_notes.md"


def read_notes(limit: int | None = None) -> str:
    try:
        text = notes_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if limit and len(text) > limit:  # the newest lines matter most
        text = text[-limit:]
        text = text[text.find("\n") + 1:]
    return text


def remember(note: str) -> dict:
    note = " ".join((note or "").split())
    if not note:
        return {"error": "Nothing to remember."}
    with notes_path().open("a", encoding="utf-8") as f:
        f.write(f"- {time.strftime('%Y-%m-%d')}: {note}\n")
    return {"remembered": note}


def inbox_path() -> pathlib.Path:
    return home() / "maestro_inbox.json"


def _load_inbox() -> list:
    try:
        data = json.loads(inbox_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def leave_in_inbox(question: str, context: str, why: str = "") -> dict:
    items = _load_inbox()
    items.append({"asked": time.strftime("%Y-%m-%d %H:%M"), "question": question, "context": context,
                  **({"why_not_answered": why} if why else {})})
    inbox_path().write_text(json.dumps(items, indent=1), encoding="utf-8")
    return {"saved_to_inbox": True, "waiting": len(items)}


def take_inbox(clear: bool = True) -> list:
    items = _load_inbox()
    if clear and items:
        inbox_path().write_text("[]", encoding="utf-8")
    return items


# ---------------------------------------------------------------------------
# The coach's tools over local HTTP (stdio belongs to Claude Desktop)
# ---------------------------------------------------------------------------


class Endpoint:
    def __init__(self, server) -> None:
        self.server = server
        self.url: str | None = None
        self._lock = threading.Lock()

    def start(self) -> str:
        with self._lock:
            if self.url:
                return self.url
            import uvicorn

            base = int(os.environ.get("MIDI_COACH_MCP_PORT") or MCP_PORT)
            for port in range(base, base + 10):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    sock.bind(("127.0.0.1", port))
                    break
                except OSError:
                    sock.close()
            else:
                raise RuntimeError(f"No free port for the coach's MCP endpoint from {base}")
            app = self.server.streamable_http_app(stateless_http=True, json_response=True)
            for name in ("mcp.server.streamable_http", "mcp.server.streamable_http_manager", "uvicorn.error"):
                logging.getLogger(name).setLevel(logging.WARNING)  # a line per request otherwise
            # log_config=None: uvicorn's default access log writes to stdout, which is MCP's.
            web = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, lifespan="on"))
            threading.Thread(target=web.run, kwargs={"sockets": [sock]}, daemon=True).start()
            deadline = time.time() + 10
            while not web.started:
                if time.time() > deadline:
                    raise RuntimeError("The coach's MCP endpoint didn't start")
                time.sleep(0.05)
            self.url = f"http://127.0.0.1:{port}/mcp"
            return self.url


# ---------------------------------------------------------------------------
# The hand-off
# ---------------------------------------------------------------------------


class DeepTeacher:
    """Runs one deep question at a time in the background.

    endpoint: Endpoint (or anything with start() -> MCP URL).
    speak: callable(text) that says a line as the Maestro.
    run: subprocess.run, replaceable in tests.
    """

    def __init__(self, endpoint, speak, run=subprocess.run) -> None:
        self.endpoint = endpoint
        self.speak = speak
        self._run = run
        self.busy = False
        self.spoken = 0  # say calls during the current question
        self.session_id: str | None = None
        self._last = 0.0
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        if find_claude():
            return True, ""
        return False, "Claude Code isn't installed (see the README), so deep questions go to Claude Desktop's inbox."

    def ask(self, question: str, context: str, wait: bool = False) -> dict:
        question = " ".join((question or "").split())
        if not question:
            return {"error": "No question to pass on."}
        ok, why = self.available()
        if not ok:
            return {**leave_in_inbox(question, context, why), "why": why}
        with self._lock:
            if self.busy:
                return {"error": "Still working on the last deep question."}
            self.busy, self.spoken = True, 0
        worker = threading.Thread(target=self._answer, args=(question, context), daemon=True)
        worker.start()
        if wait:
            worker.join()
        return {"handed_off": True, "note": "The answer will be spoken in about half a minute."}

    def _answer(self, question: str, context: str) -> None:
        try:
            resume = self.session_id if time.time() - self._last < RESUME_WITHIN_SEC else None
            out = self._claude(question, context, resume)
            if out.get("error") and resume:  # an old session can vanish: start a fresh one
                out = self._claude(question, context, None)
            if out.get("error"):
                log.warning("deep question failed: %s", out["error"])
                leave_in_inbox(question, context, out["error"])
                self.speak("I couldn't think that one through right now, so I've left your question "
                           "in the inbox for Claude Desktop.")
                return
            self.session_id, self._last = out.get("session_id"), time.time()
            if not self.spoken and out.get("result"):  # it answered in text instead of with say
                self.speak(" ".join(out["result"].split())[:600])
        except Exception as exc:
            log.warning("deep question failed: %s", exc)
            leave_in_inbox(question, context, str(exc))
            self.speak("Something went wrong thinking that over. Your question is in the inbox for Claude Desktop.")
        finally:
            self.busy = False

    def command(self, resume: str | None) -> list[str]:
        mcp = {"mcpServers": {"midi-coach": {"type": "http", "url": self.endpoint.start()}}}
        args = [find_claude() or "claude", "-p", "--output-format", "json",
                "--model", os.environ.get("MIDI_COACH_DEEP_MODEL") or DEFAULT_MODEL,
                "--mcp-config", json.dumps(mcp), "--strict-mcp-config",
                "--tools", "WebSearch", "--allowedTools", "mcp__midi-coach,WebSearch", "--permission-mode", "dontAsk",
                "--append-system-prompt", TEACHER_PROMPT]
        return args + (["--resume", resume] if resume else [])

    def _claude(self, question: str, context: str, resume: str | None) -> dict:
        notes = read_notes(NOTES_CONTEXT_CHARS)
        prompt = (f"[Practice context]\n{context}\n\n"
                  + (f"[Your notebook on the pianist]\n{notes}\n\n" if notes and not resume else "")
                  + f"[The pianist asked]\n{question}")
        env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
        cwd = home() / "maestro"  # its own folder, so no project's CLAUDE.md is loaded
        cwd.mkdir(exist_ok=True)
        try:
            done = self._run(self.command(resume), input=prompt, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=RUN_TIMEOUT_SEC, cwd=str(cwd), env=env,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return {"error": f"Claude Code took longer than {RUN_TIMEOUT_SEC // 60} minutes."}
        try:
            out = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"error": (done.stderr or done.stdout or f"claude exited with {done.returncode}").strip()[-300:]}
        if out.get("is_error") or done.returncode:
            return {"error": str(out.get("result") or out.get("subtype") or f"claude exited with {done.returncode}")[:300]}
        return {"result": out.get("result") or "", "session_id": out.get("session_id")}
