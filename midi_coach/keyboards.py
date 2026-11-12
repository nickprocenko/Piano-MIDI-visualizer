"""More than one keyboard at once, like an organ's manuals: each MIDI input is a keyboard with a
role, saved in <home>/keyboards.json (this machine's setup, shared by every profile).

    upper    the right hand's keyboard (an organ's upper manual, the Swell)
    lower    the left hand's (the lower manual, the Great)
    both     one keyboard for both hands, split by pitch (notes.split_hands): the default
    pedals   a pedalboard (bass pedals), written with the left hand's staff
    off      plugged in, not listened to

A keyboard is a port, optionally only one MIDI channel of it (an organ that sends both manuals
down one cable, each on its own channel). While two or more keyboards are on, the recorder
(midi_io.Recorder) opens them all and stamps every note with its keyboard's slot as the MIDI
channel (slot 0 -> channel 1, ...), so a take remembers where each note came from and the
take's .mid carries it. The take's meta lists the keyboards in slot order with the hand each
played (`inputs`), and library.take_notes gives every note its keyboard's hand (Note.hand), so
a take is written out with the hands as they were played, whatever the pitch. Grading still
goes by pitch alone: a note counts on whichever keyboard it is played.

Which hand a keyboard plays can change per song: a track of the Playing menu can be routed to a
keyboard (tracks.py, the track's `keyboard`), and that keyboard then plays the track's part
(`hands_for`). With one keyboard (or none set up) nothing here applies: the input is chosen as
before (MIDI_COACH_INPUT, the JUNO, the page's MIDI input).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

ROLES = ("upper", "lower", "both", "pedals", "off")
ROLE_NAMES = {"upper": "Upper (right hand)", "lower": "Lower (left hand)", "both": "Both hands (split by pitch)",
              "pedals": "Pedalboard (feet)", "off": "Off"}
ROLE_HAND = {"upper": "right", "lower": "left", "pedals": "left", "both": None}
PART_HAND = {"right": "right", "left": "left", "pedals": "left"}  # a track's part -> the hand that writes it
MAX = 16  # one MIDI channel each


@dataclass
class Keyboard:
    port: str
    role: str = "both"
    channel: int | None = None  # 0-15: only this channel of the port; None: all of it

    @property
    def id(self) -> str:
        """How a track names the keyboard it's routed to: stable while the setup is edited."""
        return self.port if self.channel is None else f"{self.port} #{self.channel + 1}"

    def label(self) -> str:
        role = {"upper": "Upper", "lower": "Lower", "both": "Both hands", "pedals": "Pedals"}.get(self.role, self.role)
        return f"{role}: {self.id}"

    def takes(self, port: str, channel: int) -> bool:
        return self.port == port and (self.channel is None or self.channel == channel)


def _path():
    from . import library
    return library.home() / "keyboards.json"


def clean(entries) -> list[Keyboard]:
    """Keyboards from saved or posted data: unknown roles are 'both', a bad channel is all of
    them, a port listed twice with the same channel is kept once."""
    out: list[Keyboard] = []
    for e in entries or []:
        if not isinstance(e, dict) or not str(e.get("port") or "").strip():
            continue
        role = str(e.get("role") or "both").lower()
        channel = e.get("channel")
        try:
            channel = int(channel) if channel not in (None, "") else None
        except (TypeError, ValueError):
            channel = None
        if channel is not None and not 0 <= channel <= 15:
            channel = None
        kb = Keyboard(str(e["port"]).strip(), role if role in ROLES else "both", channel)
        if all(k.id != kb.id for k in out):
            out.append(kb)
    return out[:MAX]


def load() -> list[Keyboard]:
    """Every keyboard set up, in slot order, off ones included."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return clean(data.get("keyboards") if isinstance(data, dict) else data)


def save(entries) -> list[Keyboard]:
    kbs = clean(entries)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"keyboards": [asdict(k) for k in kbs]}, indent=1), encoding="utf-8")
    return kbs


def active(kbs: list[Keyboard] | None = None) -> list[Keyboard]:
    """The keyboards a run listens to: those not off."""
    return [k for k in (load() if kbs is None else kbs) if k.role != "off"]


def several(kbs: list[Keyboard] | None = None) -> bool:
    """Two or more keyboards on: runs listen to all of them (else the one input, as before)."""
    return len(active(kbs)) >= 2


def slot_of(kbs: list[Keyboard], port: str, channel: int) -> int | None:
    """The slot (index in kbs) a message from `port` on `channel` belongs to, or None."""
    for i, k in enumerate(kbs):
        if k.takes(port, channel):
            return i
    return None


def default_keyboard(kbs: list[Keyboard], part: str) -> Keyboard | None:
    """The keyboard a track with this part is played on when it isn't routed: the right hand on
    the upper, the left on the lower, the pedals on the pedalboard (else the lower); a part for
    both hands or a named part on the one 'both' keyboard if there is one, else no single one."""
    want = {"right": ("upper", "both"), "left": ("lower", "both"), "pedals": ("pedals", "lower")}.get(part, ("both",))
    for role in want:
        for k in kbs:
            if k.role == role:
                return k
    return None


def hands_for(kbs: list[Keyboard], routed: dict[str, str] | None = None) -> list[str | None]:
    """The hand each keyboard (by slot) plays for a song: its role's, unless tracks are routed
    to it ({keyboard id: part}); routed to one hand's part (or the pedals) it plays that hand,
    to parts of both hands (or a part split between them) it's split by pitch (None)."""
    by_id: dict[str, set] = {}
    for kid, part in (routed or {}).items():
        by_id.setdefault(kid, set()).add(PART_HAND.get(part))
    hands = []
    for k in kbs:
        if k.id in by_id:
            got = by_id[k.id]
            hands.append(next(iter(got)) if len(got) == 1 else None)
        else:
            hands.append(ROLE_HAND.get(k.role))
    return hands


def describe(kbs: list[Keyboard] | None = None) -> list[dict]:
    """For the page: each keyboard with its slot, id and label."""
    kbs = load() if kbs is None else kbs
    return [{**asdict(k), "slot": i, "id": k.id, "label": k.label()} for i, k in enumerate(kbs)]
