"""Parametric controller box for the piano LED bridge (draft, measure your parts first).

Run:   uv run --with build123d controller_box.py
Makes: controller_box_base.step/.stl and controller_box_lid.step/.stl next to this file.
STEP opens in Fusion 360 / FreeCAD for editing; STL goes to a slicer or a print service.

Holds: a 70x50 mm perfboard carrier (ESP32-S3 DevKit + 74AHCT125 + terminal bus) on 4 M3 standoffs.
Cutouts: USB-C (to PC) on the left wall; barrel jack + GX16-4 strip socket on the right wall;
vent slots in the lid. Lid fixes with 4 M3 screws into corner bosses (use heat-set inserts or
self-tapping M3).
"""
from pathlib import Path

from build123d import (Align, Box, BuildPart, Cylinder, Locations, Mode, Pos,
                       export_step, export_stl)

# ---- measure these -------------------------------------------------------------------------
INNER_X, INNER_Y, INNER_Z = 110.0, 75.0, 32.0   # space inside the box
WALL = 2.4                                       # wall / floor thickness (3 perimeters at 0.4)
LID_T = 2.4
CORNER_BOSS_D, SCREW_HOLE_D = 8.0, 2.8          # 2.8 = M3 self-tap; use 4.0 for heat-set inserts

BOARD_X, BOARD_Y = 70.0, 50.0                    # perfboard size
BOARD_HOLES = (66.0, 46.0)                       # mounting-hole spacing on the perfboard
STANDOFF_H, STANDOFF_D = 6.0, 6.0
BOARD_OFFSET_X = -12.0                           # shift board toward the USB wall

USB_W, USB_H, USB_Z = 12.0, 7.0, 14.0           # USB-C opening; USB_Z = height of port centre
JACK_D, JACK_Z = 11.0, 16.0                      # 5.5x2.1 panel jack hole (check its datasheet)
GX16_D, GX16_Z = 16.2, 16.0                      # GX16 panel socket hole
VENT_W, VENT_L, VENT_N = 2.0, 40.0, 7
# ---------------------------------------------------------------------------------------------

OUT_X, OUT_Y, OUT_Z = INNER_X + 2 * WALL, INNER_Y + 2 * WALL, INNER_Z + WALL
corner = (INNER_X / 2 - CORNER_BOSS_D / 2 + 0.5, INNER_Y / 2 - CORNER_BOSS_D / 2 + 0.5)
corners = [(sx * corner[0], sy * corner[1]) for sx in (-1, 1) for sy in (-1, 1)]

with BuildPart() as base:
    Box(OUT_X, OUT_Y, OUT_Z, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations(Pos(0, 0, WALL)):  # hollow it out
        Box(INNER_X, INNER_Y, INNER_Z + 1, align=(Align.CENTER, Align.CENTER, Align.MIN),
            mode=Mode.SUBTRACT)
    # corner bosses for the lid screws
    with Locations(*[Pos(x, y, WALL) for x, y in corners]):
        Cylinder(CORNER_BOSS_D / 2, INNER_Z, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations(*[Pos(x, y, WALL + INNER_Z - 12) for x, y in corners]):
        Cylinder(SCREW_HOLE_D / 2, 12.5, align=(Align.CENTER, Align.CENTER, Align.MIN),
                 mode=Mode.SUBTRACT)
    # board standoffs
    hx, hy = BOARD_HOLES[0] / 2, BOARD_HOLES[1] / 2
    pts = [Pos(BOARD_OFFSET_X + sx * hx, sy * hy, WALL) for sx in (-1, 1) for sy in (-1, 1)]
    with Locations(*pts):
        Cylinder(STANDOFF_D / 2, STANDOFF_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations(*pts):
        Cylinder(SCREW_HOLE_D / 2, STANDOFF_H + 0.1, align=(Align.CENTER, Align.CENTER, Align.MIN),
                 mode=Mode.SUBTRACT)
    # left wall: USB-C
    with Locations(Pos(-OUT_X / 2, 0, USB_Z)):
        Box(WALL * 3, USB_W, USB_H, mode=Mode.SUBTRACT)
    # right wall: barrel jack and GX16 socket
    with Locations(Pos(OUT_X / 2, -INNER_Y / 4, JACK_Z)):
        Cylinder(JACK_D / 2, WALL * 3, rotation=(0, 90, 0), mode=Mode.SUBTRACT)
    with Locations(Pos(OUT_X / 2, INNER_Y / 4, GX16_Z)):
        Cylinder(GX16_D / 2, WALL * 3, rotation=(0, 90, 0), mode=Mode.SUBTRACT)

with BuildPart() as lid:
    Box(OUT_X, OUT_Y, LID_T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    # lip that drops inside the walls so the lid locates itself
    with Locations(Pos(0, 0, -2)):
        Box(INNER_X - 0.6, INNER_Y - 0.6, 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
        Box(INNER_X - 0.6 - 2 * 1.6, INNER_Y - 0.6 - 2 * 1.6, 2,
            align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)
    with Locations(*[Pos(x, y, -2) for x, y in corners]):  # clear the bosses
        Cylinder(CORNER_BOSS_D / 2 + 0.4, 2, align=(Align.CENTER, Align.CENTER, Align.MIN),
                 mode=Mode.SUBTRACT)
    with Locations(*[Pos(x, y, -3) for x, y in corners]):
        Cylinder(3.4 / 2, LID_T + 4, align=(Align.CENTER, Align.CENTER, Align.MIN),
                 mode=Mode.SUBTRACT)
    pitch = VENT_W * 2.5
    with Locations(*[Pos(20, (i - (VENT_N - 1) / 2) * pitch, LID_T / 2) for i in range(VENT_N)]):
        Box(VENT_L, VENT_W, LID_T * 3, mode=Mode.SUBTRACT)

here = Path(__file__).parent
for name, part in (("base", base.part), ("lid", lid.part)):
    export_step(part, here / f"controller_box_{name}.step")
    export_stl(part, here / f"controller_box_{name}.stl")
    bb = part.bounding_box()
    print(f"{name}: {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm, volume {part.volume / 1000:.1f} cm3")
