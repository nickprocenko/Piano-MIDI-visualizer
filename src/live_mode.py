"""Live (stream) mode driver — feeds the FluidRenderer with ambient splats.

Live mode renders one full-screen fluid effect tinted to the current colour.
There is no piano, no falling notes, no background slideshow.  The colour
is driven by whatever is currently in App._color_current (audience client,
kick chat, OBS colour-wheel overlay, web panel, or theme).

Three emission patterns are supported via config["live_mode"]["pattern"]:
  - "jets"  — bottom-edge upward emitters + occasional mid-height swirls
              (default; mimics the highway's rising fluid).
  - "orbs"  — a small swarm of wandering emitters that drift around the
              screen in continuous loops, leaving glowing trails.
  - "pulse" — centre radial pulses that bloom outward at a steady rhythm.

If the FluidRenderer is unavailable (no moderngl / no GL 3.3), every
method is a silent no-op.
"""

from __future__ import annotations

import math
import random
from typing import Optional


_PATTERNS = ("jets", "orbs", "pulse")

# --- jets timings -----------------------------------------------------------
_JET_INTERVAL_MS_MIN = 90.0
_JET_INTERVAL_MS_MAX = 180.0
_SWIRL_INTERVAL_MS_MIN = 700.0
_SWIRL_INTERVAL_MS_MAX = 1500.0

# --- orbs config ------------------------------------------------------------
_ORB_COUNT = 4
_ORB_SPEED = 0.18         # screen-fraction per second
_ORB_SPLAT_INTERVAL_MS = 60.0

# --- pulse config -----------------------------------------------------------
_PULSE_INTERVAL_MS = 900.0
_PULSE_RAYS = 8


class LiveModeDriver:
    """Owns the timing + RNG for ambient splat emission in live mode."""

    def __init__(
        self,
        fluid_renderer: Optional[object],
        pattern: str = "jets",
    ) -> None:
        self._fluid = fluid_renderer
        self._pattern = pattern if pattern in _PATTERNS else "jets"

        # Shared bookkeeping
        self._elapsed_ms = 0.0

        # Jets state
        self._next_jet_ms = 0.0
        self._next_swirl_ms = 0.0

        # Orbs state — each orb has position + velocity in normalised coords.
        self._orbs: list[dict[str, float]] = []
        for _ in range(_ORB_COUNT):
            angle = random.uniform(0, math.tau)
            self._orbs.append({
                "x": random.uniform(0.2, 0.8),
                "y": random.uniform(0.3, 0.7),
                "vx": math.cos(angle) * _ORB_SPEED,
                "vy": math.sin(angle) * _ORB_SPEED,
                "phase": random.uniform(0.0, math.tau),
            })
        self._next_orb_splat_ms = 0.0

        # Pulse state
        self._next_pulse_ms = 0.0

    @property
    def available(self) -> bool:
        return self._fluid is not None and getattr(self._fluid, "available", False)

    def step(self, dt_ms: float, color_rgb: tuple[float, float, float]) -> None:
        """Advance the fluid sim one frame and emit ambient splats."""
        if not self.available:
            return

        dt_sec = max(0.001, dt_ms / 1000.0)
        self._fluid.step(dt_sec)  # type: ignore[attr-defined]

        self._elapsed_ms += dt_ms

        r, g, b = color_rgb
        nr, ng, nb = r / 255.0, g / 255.0, b / 255.0

        if self._pattern == "jets":
            self._tick_jets(nr, ng, nb)
        elif self._pattern == "orbs":
            self._tick_orbs(dt_sec, nr, ng, nb)
        elif self._pattern == "pulse":
            self._tick_pulse(nr, ng, nb)

    def emit_note_splat(
        self,
        norm_x: float,
        color_rgb: tuple[float, float, float],
        velocity_y: float = -260.0,
    ) -> None:
        """Emit a one-off splat from the bottom edge — used for MIDI keypress."""
        if not self.available:
            return
        r, g, b = color_rgb
        self._fluid.add_splat(  # type: ignore[attr-defined]
            max(0.02, min(0.98, norm_x)),
            0.94,
            0.0,
            velocity_y,
            r / 255.0,
            g / 255.0,
            b / 255.0,
            radius=0.022,
        )

    # ------------------------------------------------------------------
    # Jets pattern
    # ------------------------------------------------------------------

    def _tick_jets(self, nr: float, ng: float, nb: float) -> None:
        if self._elapsed_ms >= self._next_jet_ms:
            self._emit_jet(nr, ng, nb)
            self._next_jet_ms = self._elapsed_ms + random.uniform(
                _JET_INTERVAL_MS_MIN, _JET_INTERVAL_MS_MAX
            )
        if self._elapsed_ms >= self._next_swirl_ms:
            self._emit_swirl(nr, ng, nb)
            self._next_swirl_ms = self._elapsed_ms + random.uniform(
                _SWIRL_INTERVAL_MS_MIN, _SWIRL_INTERVAL_MS_MAX
            )

    def _emit_jet(self, nr: float, ng: float, nb: float) -> None:
        for _ in range(2):
            x = random.uniform(0.05, 0.95)
            vx = random.uniform(-30.0, 30.0)
            vy = random.uniform(-340.0, -220.0)
            radius = random.uniform(0.018, 0.028)
            self._fluid.add_splat(  # type: ignore[attr-defined]
                x, 0.96, vx, vy, nr, ng, nb, radius=radius
            )

    def _emit_swirl(self, nr: float, ng: float, nb: float) -> None:
        y = random.uniform(0.35, 0.7)
        side_vx = random.choice([-220.0, 220.0])
        x_left = random.uniform(0.1, 0.35)
        x_right = random.uniform(0.65, 0.9)
        cr, cg, cb = nr * 0.4, ng * 0.4, nb * 0.4
        self._fluid.add_splat(  # type: ignore[attr-defined]
            x_left, y, side_vx, 0.0, cr, cg, cb, radius=0.04
        )
        self._fluid.add_splat(  # type: ignore[attr-defined]
            x_right, y, -side_vx, 0.0, cr, cg, cb, radius=0.04
        )

    # ------------------------------------------------------------------
    # Orbs pattern
    # ------------------------------------------------------------------

    def _tick_orbs(self, dt_sec: float, nr: float, ng: float, nb: float) -> None:
        # Move + bounce off edges with a small wobble for organic motion.
        for orb in self._orbs:
            orb["phase"] += dt_sec * 1.4
            wobble = math.sin(orb["phase"]) * 0.04
            orb["x"] += orb["vx"] * dt_sec
            orb["y"] += orb["vy"] * dt_sec + wobble * dt_sec
            if orb["x"] < 0.05 or orb["x"] > 0.95:
                orb["vx"] = -orb["vx"]
                orb["x"] = max(0.05, min(0.95, orb["x"]))
            if orb["y"] < 0.10 or orb["y"] > 0.90:
                orb["vy"] = -orb["vy"]
                orb["y"] = max(0.10, min(0.90, orb["y"]))

        if self._elapsed_ms < self._next_orb_splat_ms:
            return
        self._next_orb_splat_ms = self._elapsed_ms + _ORB_SPLAT_INTERVAL_MS
        for orb in self._orbs:
            # Splat at the orb position with velocity matching its motion.
            self._fluid.add_splat(  # type: ignore[attr-defined]
                orb["x"],
                orb["y"],
                orb["vx"] * 600.0,
                orb["vy"] * 600.0,
                nr * 0.7,
                ng * 0.7,
                nb * 0.7,
                radius=0.024,
            )

    # ------------------------------------------------------------------
    # Pulse pattern
    # ------------------------------------------------------------------

    def _tick_pulse(self, nr: float, ng: float, nb: float) -> None:
        if self._elapsed_ms < self._next_pulse_ms:
            return
        self._next_pulse_ms = self._elapsed_ms + _PULSE_INTERVAL_MS

        # Centre-bloom: emit N rays outward from screen centre.
        for i in range(_PULSE_RAYS):
            theta = (i / _PULSE_RAYS) * math.tau + random.uniform(-0.08, 0.08)
            speed = random.uniform(360.0, 480.0)
            vx = math.cos(theta) * speed
            vy = math.sin(theta) * speed
            self._fluid.add_splat(  # type: ignore[attr-defined]
                0.5, 0.5, vx, vy, nr, ng, nb, radius=0.028,
            )
        # Inner bright core for visual punch.
        self._fluid.add_splat(  # type: ignore[attr-defined]
            0.5, 0.5, 0.0, 0.0, nr * 1.3, ng * 1.3, nb * 1.3, radius=0.035,
        )
