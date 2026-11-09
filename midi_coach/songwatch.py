"""Notice new songs as they arrive, so nobody has to rescan the library by hand.

A background thread looks every POLL_SEC at the song folders (File → Song folders) and, when
that's switched on, the top of the Downloads folder. It doesn't list every file each time (the
band library is thousands of files): it keeps each folder's modified time, which Windows bumps
when a file is added, renamed or removed in it, and lists only the folders that changed.

A new MIDI or MusicXML file counts once its size has held still for one look, so a file still
being copied in isn't opened half written (browsers download to .crdownload / .part and rename,
which is caught the same way). A new file in Downloads is copied into
<home>/references/downloads (songfind.keep), so the library has it from then on.

The coach's own lessons folder isn't watched: those files are written by the coach, not new songs.
Set MIDI_COACH_SONG_WATCH=off to turn the thread off (the tests do).
"""

from __future__ import annotations

import os
import pathlib
import threading
import time
from typing import Callable

from . import library

POLL_SEC = 3.0


def _key(path: pathlib.Path | str) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _is_song(path: pathlib.Path) -> bool:
    return path.suffix.lower() in library.REF_SUFFIXES


def _mtime(path: pathlib.Path) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


class Watcher:
    """The folders' state between looks. poll() returns the songs that arrived since the last one."""

    def __init__(self) -> None:
        self.roots: tuple = ()
        self.dirs: dict[str, tuple[pathlib.Path, int | None, bool]] = {}  # key -> (folder, mtime, recursive)
        self.files: set[str] = set()
        self.pending: dict[str, tuple[pathlib.Path, int]] = {}  # key -> (file, size last seen)

    # -- which folders -----------------------------------------------------------------------

    @staticmethod
    def wanted() -> tuple:
        """(folder, recursive) for every folder to watch now: the song folders (and everything
        inside them) and, when switched on, Downloads (its top level only)."""
        from . import songfind

        skip = _key(library.profile_home() / "lessons")
        roots = [(f, True) for f in library.reference_folders() if _key(f) != skip]
        if library.song_sources().get("watch_downloads") and songfind.downloads_dir().is_dir():
            roots.append((songfind.downloads_dir(), False))
        return tuple((pathlib.Path(f), r) for f, r in roots)

    def prime(self, roots: tuple | None = None) -> None:
        """Take in what's there now, quietly: none of it is new."""
        self.roots = self.wanted() if roots is None else roots
        self.dirs, self.files, self.pending = {}, set(), {}
        for root, recursive in self.roots:
            self._take_in(root, recursive, new=None)

    def _take_in(self, folder: pathlib.Path, recursive: bool, new: list | None) -> None:
        """Note `folder` (and, if recursive, every folder inside it) and its songs; songs not
        seen before go to `new` (None: priming, nothing is new)."""
        stack = [folder]
        while stack:
            d = stack.pop()
            if d.name == library.BROKEN_DIR:
                continue
            self.dirs[_key(d)] = (d, _mtime(d), recursive)
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if recursive and _key(e.path) not in self.dirs:
                            stack.append(pathlib.Path(e.path))
                    elif e.is_file() and _is_song(pathlib.Path(e.name)):
                        k = _key(e.path)
                        if k not in self.files:
                            self.files.add(k)
                            if new is not None:
                                new.append(pathlib.Path(e.path))
                except OSError:
                    continue

    # -- each look ---------------------------------------------------------------------------

    def poll(self) -> list[pathlib.Path]:
        roots = self.wanted()
        if roots != self.roots:  # a folder added or removed in File → Song folders, or a profile switch
            self.prime(roots)
            return []
        appeared: list[pathlib.Path] = []
        for k, (d, seen, recursive) in list(self.dirs.items()):
            now = _mtime(d)
            if now == seen:
                continue
            if now is None:  # the folder went away
                self.dirs.pop(k, None)
                continue
            self._take_in(d, recursive, appeared)
        for f in appeared:
            self.pending[_key(f)] = (f, -1)
        return self._settled()

    def _settled(self) -> list[pathlib.Path]:
        """The pending files whose size held still since the last look."""
        ready = []
        for k, (f, size) in list(self.pending.items()):
            try:
                now = f.stat().st_size
            except OSError:  # renamed or deleted already
                self.pending.pop(k)
                self.files.discard(k)
                continue
            if now > 0 and now == size:
                self.pending.pop(k)
                ready.append(f)
            else:
                self.pending[k] = (f, now)
        return ready

    def is_download(self, path: pathlib.Path) -> bool:
        return any(not recursive and _key(path.parent) == _key(root) for root, recursive in self.roots)


# -- the thread ------------------------------------------------------------------------------

_started = threading.Lock()
_thread: threading.Thread | None = None


def handle(watcher: Watcher, found: list[pathlib.Path]) -> list[dict]:
    """What arrived, as the page shows it: a download is copied into the library first."""
    from . import songfind

    out = []
    for f in found:
        if watcher.is_download(f):
            try:
                f = songfind.keep(f)
            except OSError:
                continue
            watcher.files.add(_key(f))  # the copy is no news of its own
        out.append({"title": f.stem, "path": str(f), "folder": f.parent.name})
    return out


def start(on_new: Callable[[list[dict]], None]) -> bool:
    """Start watching (once per process). `on_new` gets [{title, path, folder}] from the thread."""
    global _thread
    if os.environ.get("MIDI_COACH_SONG_WATCH", "").lower() in {"off", "0", "no"}:
        return False
    with _started:
        if _thread is not None:
            return True

        def run() -> None:
            watcher = Watcher()
            watcher.prime()
            while True:
                time.sleep(POLL_SEC)
                try:
                    songs = handle(watcher, watcher.poll())
                    if songs:
                        on_new(songs)
                except Exception:  # a bad look mustn't end the watching
                    pass

        _thread = threading.Thread(target=run, name="song-watch", daemon=True)
        _thread.start()
    return True
