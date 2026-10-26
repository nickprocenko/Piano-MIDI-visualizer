"""One run of Claude Code in headless mode (`claude -p`) on the pianist's claude.ai account.

Everything that hands work to Claude Code goes through here: the Maestro's deep questions
(deep.py), the Atlas's lesson generator, the goal planner and song research. A run can ask
for structured output (--json-schema; the answer comes back as 'structured'), use tools
(--tools, allowed without asking), connect to an MCP server (extra arguments), resume an
earlier session (--resume, always the last arguments), and is told when the account hit its
usage limit, so a long batch can stop and pick up later. It runs in a folder of its own so
no project's CLAUDE.md is loaded, with API keys removed from the environment so it can't
bill the API.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess

from . import shared_dir

TIMEOUT_SEC = 6 * 60
# Removed from Claude Code's environment: it must use the subscription, not an API key, and
# must not think it's running inside another Claude Code session.
STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")
LIMIT_RE = re.compile(r"usage limit|rate limit|limit reached|limit will reset|out of (extra )?usage|too many requests|\b429\b",
                      re.IGNORECASE)


def find_claude() -> str | None:
    explicit = os.environ.get("MIDI_COACH_CLAUDE")
    if explicit:
        return explicit if pathlib.Path(explicit).exists() else None
    found = shutil.which("claude")
    if found:
        return found
    local = pathlib.Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(local) if local.exists() else None


def command(model: str, schema: dict | None = None, system: str | None = None, tools: str = "",
            resume: str | None = None, extra: list[str] | None = None) -> list[str]:
    """The command line. tools: comma-separated built-in tools it may use (all allowed
    without asking); extra: more arguments (an MCP config, allowed MCP tools)."""
    args = [find_claude() or "claude", "-p", "--output-format", "json", "--model", model, "--tools", tools,
            "--permission-mode", "dontAsk"]
    if tools and not any(a == "--allowedTools" for a in extra or []):
        args += ["--allowedTools", tools]
    if schema is not None:
        args += ["--json-schema", json.dumps(schema)]
    if system:
        args += ["--append-system-prompt", system]
    args += extra or []
    return args + (["--resume", resume] if resume else [])


def run(prompt: str, model: str, schema: dict | None = None, system: str | None = None, tools: str = "",
        resume: str | None = None, timeout: int = TIMEOUT_SEC, runner=subprocess.run, extra: list[str] | None = None,
        cwd: str | pathlib.Path | None = None) -> dict:
    """{result, structured, session_id, cost_usd} or {error, usage_limit}. runner:
    subprocess.run, replaceable in tests; cwd: where it runs (default <home>/atlas/generator)."""
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
    folder = pathlib.Path(cwd) if cwd else shared_dir() / "generator"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        done = runner(command(model, schema, system, tools, resume, extra), input=prompt, capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=timeout, cwd=str(folder), env=env,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"error": f"Claude Code took longer than {timeout // 60} minutes.", "usage_limit": False}
    except FileNotFoundError:
        return {"error": "Claude Code isn't installed.", "usage_limit": False}
    try:
        out = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        text = (done.stderr or done.stdout or f"claude exited with {done.returncode}").strip()[-300:]
        return {"error": text, "usage_limit": bool(LIMIT_RE.search(text))}
    if out.get("is_error") or done.returncode:
        text = str(out.get("result") or out.get("subtype") or f"claude exited with {done.returncode}")[:300]
        limited = out.get("api_error_status") == 429 or bool(LIMIT_RE.search(text))
        return {"error": text, "usage_limit": limited, "session_id": out.get("session_id")}
    return {"result": out.get("result") or "", "structured": out.get("structured_output"),
            "session_id": out.get("session_id"), "cost_usd": out.get("total_cost_usd")}
