"""Download songs that aren't in the reference library yet from bitmidi.com.

fetch_alternates.py only looks for other versions of songs already under reference/midiworld;
this looks up titles you name, for an artist, and saves what it finds the same way:
reference/bitmidi/<Artist>/<Artist> - <Title> [bitmidi <id>].mid (up to MAX_VERSIONS each,
most viewed first). Same polite pacing, same duplicate checks.

    python tools/fetch_songs.py "Pink Floyd" "Breathe" "Us and Them" "Eclipse"

A song with no match is reported, not guessed. Check what comes back before using it: a
file's name is only what its uploader called it.
"""

from __future__ import annotations

import hashlib
import re
import sys

from fetch_alternates import MAX_VERSIONS, SITE, TARGET, get, matches, safe, search, valid_midi


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    artist, titles = sys.argv[1], sys.argv[2:]
    TARGET.mkdir(parents=True, exist_ok=True)
    have_ids = {int(m.group(1)) for f in TARGET.rglob("*.mid") if (m := re.search(r"\[bitmidi (\d+)\]", f.name))}
    have_hashes = {hashlib.sha1(f.read_bytes()).hexdigest() for f in TARGET.rglob("*.mid")}
    by_artist = search(artist, 4)
    for title in titles:
        found = {r["id"]: r for r in search(f"{title} {artist}") + search(title, 2) + by_artist}
        hits = sorted((r for r in found.values() if matches(artist, title, r)), key=lambda r: -(r.get("views") or 0))
        saved = []
        for r in hits[:MAX_VERSIONS]:
            if r["id"] in have_ids:
                saved.append(f"{r['id']} (already had)")
                continue
            data = get(SITE + r["downloadUrl"])
            if not data or not valid_midi(data):
                continue
            digest = hashlib.sha1(data).hexdigest()
            if digest in have_hashes:
                continue
            folder = TARGET / safe(artist)
            folder.mkdir(exist_ok=True)
            (folder / f"{safe(artist)} - {safe(title)} [bitmidi {r['id']}].mid").write_bytes(data)
            have_ids.add(r["id"])
            have_hashes.add(digest)
            saved.append(f"{r['id']} ({r.get('name')})")
        print(f"{title}: {', '.join(saved) if saved else 'nothing found'}", flush=True)


if __name__ == "__main__":
    main()
