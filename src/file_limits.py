"""Centralized file-size guards for user-selected MIDI and media assets."""

from __future__ import annotations

import pathlib

_MB = 1024 * 1024

# MIDI files are normally tiny. A hard cap avoids pathological files and long
# recursive folder scans surfacing inputs the app should never try to load.
MAX_MIDI_FILE_BYTES = 16 * _MB

# Background media is decoded in-memory, so keep the cap conservative.
MAX_MEDIA_FILE_BYTES = 64 * _MB


def get_file_size_bytes(path: pathlib.Path) -> int | None:
    """Return the file size in bytes, or None when it cannot be read."""
    try:
        return int(path.stat().st_size)
    except OSError:
        return None


def is_within_size_limit(path: pathlib.Path, max_bytes: int) -> bool:
    """Return True when *path* exists and does not exceed *max_bytes*."""
    size = get_file_size_bytes(path)
    return size is not None and size <= int(max_bytes)


def is_allowed_midi_file(path: pathlib.Path) -> bool:
    """Return True when the MIDI file is safe to list/load."""
    return is_within_size_limit(path, MAX_MIDI_FILE_BYTES)


def is_allowed_media_file(path: pathlib.Path) -> bool:
    """Return True when the media file is safe to preview/load."""
    return is_within_size_limit(path, MAX_MEDIA_FILE_BYTES)


def format_limit_mb(max_bytes: int) -> str:
    """Return a human-readable MB label for a size limit."""
    return f"{int(max_bytes) // _MB} MB"