"""The Music Coach logo: a beamed pair of notes over a keyboard, in the coach page's teal.

    python -m midi_coach.icon        (rewrites static/coach.ico and static/coach.png)

Drawn at 1024 px and scaled down. Below 48 px the keyboard turns to noise, so the small
sizes (taskbar, browser tab) show the notes alone, larger.
"""

from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageChops, ImageDraw, ImageFilter

STATIC = pathlib.Path(__file__).resolve().parent / "static"
S = 1024
ACCENT = (0, 196, 196)
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def _gradient(top, bottom) -> Image.Image:
    col = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / (S - 1)
        col.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return col.resize((S, S))


def _tile_mask(inset: int = 0) -> Image.Image:
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((inset, inset, S - 1 - inset, S - 1 - inset), radius=220 - inset, fill=255)
    return mask


def _notes(scale: float, dx: float, dy: float) -> Image.Image:
    """Two note heads, stems and a slanted beam, as an alpha mask."""
    layer = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(layer)
    pt = lambda x, y: (dx + x * scale, dy + y * scale)
    heads = [(330, 640), (690, 570)]
    rx, ry, stem_w, beam_h = 118, 84, 46, 96
    for cx, cy in heads:
        head = Image.new("L", (S, S), 0)
        x, y = pt(cx, cy)
        ImageDraw.Draw(head).ellipse((x - rx * scale, y - ry * scale, x + rx * scale, y + ry * scale), fill=255)
        layer = ImageChops.lighter(layer, head.rotate(24, center=(x, y), resample=Image.BICUBIC))
    d = ImageDraw.Draw(layer)
    # stems rise from the right edge of each head; the beam joins their tops on the same slant as the heads
    tops = []
    for cx, cy in heads:
        sx = cx + rx * math.cos(math.radians(24)) - stem_w / 2 - 6
        top = cy - 420
        d.rectangle((*pt(sx - stem_w / 2, top), *pt(sx + stem_w / 2, cy - 20)), fill=255)
        tops.append((sx, top))
    (x0, y0), (x1, y1) = tops
    x0 -= stem_w / 2
    x1 += stem_w / 2
    d.polygon([pt(x0, y0), pt(x1, y1), pt(x1, y1 + beam_h), pt(x0, y0 + beam_h)], fill=255)
    return layer


def _keyboard(top: int) -> tuple[Image.Image, Image.Image]:
    """White keys and black keys (two masks) filling the tile from `top` down."""
    white = Image.new("L", (S, S), 0)
    black = Image.new("L", (S, S), 0)
    dw, db = ImageDraw.Draw(white), ImageDraw.Draw(black)
    n, gap = 7, 14
    w = S / n
    for k in range(n):
        dw.rectangle((k * w + gap / 2, top, (k + 1) * w - gap / 2, S), fill=255)
    for k in (1, 2, 4, 5, 6):  # C D | F G A: black keys after these whites
        cx = k * w
        db.rectangle((cx - w * 0.32, top - 2, cx + w * 0.32, top + (S - top) * 0.58), fill=255)
    tile = _tile_mask(0)
    return ImageChops.multiply(white, tile), ImageChops.multiply(black, tile)


def draw(small: bool = False) -> Image.Image:
    img = _gradient((24, 36, 60), (8, 10, 16)).convert("RGBA")
    if small:
        notes = _notes(1.18, -90, -170)
    else:
        notes = _notes(0.92, 40, -80)
        white, black = _keyboard(730)
        img.paste((226, 234, 240, 255), (0, 0), white)
        img.paste((10, 12, 18, 255), (0, 0), black)
        # a teal line where the keys meet the tile, like a lit key bed
        bed = Image.new("L", (S, S), 0)
        ImageDraw.Draw(bed).rectangle((0, 716, S, 730), fill=255)
        img.paste(ACCENT + (255,), (0, 0), bed)
    glow = notes.filter(ImageFilter.GaussianBlur(28)).point(lambda v: v * 0.55)
    img.paste(ACCENT + (255,), (0, 0), glow)
    img.paste((150, 255, 250, 255) if small else ACCENT + (255,), (0, 0), notes)
    # inner edge highlight, then cut to the rounded tile
    rim = ImageChops.subtract(_tile_mask(0), _tile_mask(10))
    img.paste((255, 255, 255, 40), (0, 0), rim)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), _tile_mask(0))
    return out


def build(static: pathlib.Path = STATIC) -> None:
    big, small = draw(), draw(small=True)
    frames = [(small if size < 48 else big).resize((size, size), Image.LANCZOS) for size in ICO_SIZES]
    frames[-1].save(static / "coach.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])
    big.resize((256, 256), Image.LANCZOS).save(static / "coach.png")


if __name__ == "__main__":
    build()
    print(f"wrote {STATIC / 'coach.ico'} and {STATIC / 'coach.png'}")
