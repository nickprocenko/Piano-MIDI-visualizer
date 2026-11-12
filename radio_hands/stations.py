"""Find stations in Radio Browser (radio-browser.info): a free, community-kept directory of about
50,000 internet radio stations, searchable by name, country, province/state and genre.

The API asks clients to pick one of its mirrors and to report a 'click' when a station is
played (that's how its popularity ranking works), so tune() does that.
"""

from __future__ import annotations

import json
import random
import threading
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "RadioHands/0.1 (personal piano practice)"
FALLBACK = ["de1.api.radio-browser.info", "de2.api.radio-browser.info", "fi1.api.radio-browser.info"]
TIMEOUT_SEC = 10
_servers: list[str] = []
_lock = threading.Lock()


def _servers_list() -> list[str]:
    with _lock:
        if not _servers:
            try:
                data = _fetch("https://all.api.radio-browser.info/json/servers")
                names = sorted({s["name"] for s in data if s.get("name")})
            except Exception:  # noqa: BLE001 - the mirror list itself is down: use known mirrors
                names = []
            _servers.extend(random.sample(names, len(names)) if names else FALLBACK)
        return list(_servers)


def _fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
        return json.loads(res.read().decode("utf-8", "replace"))


def _get(path: str, params: dict | None = None):
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    last = None
    for server in _servers_list() + [s for s in FALLBACK if s not in _servers]:
        try:
            return _fetch(f"https://{server}{path}{query}")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
    raise ConnectionError("Couldn't reach the station directory (radio-browser.info).") from last


def _station(s: dict) -> dict:
    return {"uuid": s.get("stationuuid"), "name": (s.get("name") or "").strip(), "url": s.get("url_resolved") or s.get("url"),
            "homepage": s.get("homepage"), "favicon": s.get("favicon"), "country": s.get("country"),
            "countrycode": s.get("countrycode"), "state": s.get("state"), "tags": s.get("tags"),
            "codec": s.get("codec"), "bitrate": s.get("bitrate"), "hls": bool(s.get("hls")),
            "votes": s.get("votes"), "clicks": s.get("clickcount"), "ok": bool(s.get("lastcheckok"))}


def search(name: str = "", countrycode: str = "", state: str = "", tag: str = "", limit: int = 80) -> list[dict]:
    """Working stations matching all that's given, most played first."""
    params = {"hidebroken": "true", "order": "clickcount", "reverse": "true", "limit": str(limit)}
    if name:
        params["name"] = name
    if countrycode:
        params["countrycode"] = countrycode.upper()
    if state:
        params["state"] = state
    if tag:
        params["tag"] = tag.lower()
    stations = [_station(s) for s in _get("/json/stations/search", params)]
    seen, out = set(), []
    for s in stations:  # the directory lists some stations twice
        key = (s["name"].lower(), s["url"])
        if s["url"] and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def states(country: str) -> list[dict]:
    """A country's provinces/states with stations: [{name, stations}] (country by name, e.g. 'Canada')."""
    rows = _get(f"/json/states/{urllib.parse.quote(country)}/", {"order": "stationcount", "reverse": "true", "hidebroken": "true"})
    return [{"name": r["name"], "stations": r.get("stationcount", 0)} for r in rows if r.get("name") and r.get("stationcount", 0) >= 2]


def countries() -> list[dict]:
    rows = _get("/json/countries", {"order": "name", "hidebroken": "true"})
    return [{"name": r["name"], "code": r.get("iso_3166_1"), "stations": r.get("stationcount", 0)}
            for r in rows if r.get("iso_3166_1") and r.get("stationcount", 0) >= 5]


def clicked(uuid: str) -> None:
    """Tell the directory a station was played (best effort, in the background)."""
    if not uuid:
        return

    def go():
        try:
            _get(f"/json/url/{urllib.parse.quote(uuid)}")
        except Exception:  # noqa: BLE001 - only a courtesy
            pass

    threading.Thread(target=go, daemon=True).start()
