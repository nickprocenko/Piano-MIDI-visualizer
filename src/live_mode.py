"""Live (stream) mode driver — feeds the FluidRenderer with ambient splats.

Live mode renders one full-screen fluid effect tinted to the current colour.
There is no piano, no falling notes, no background slideshow.  The colour
is driven by whatever is currently in App._color_current (audience client,
kick chat, OBS colour-wheel overlay, web panel, or theme).

The driver auto-emits two kinds of splats so the field is always alive:
  - "jets":  bottom-edge upward emitters that mimic the highway's rising
             fluid, distributed across the screen width.
  - "swirl": occasional sideways pushes that keep the field churning so it
             never settles into a static gradient.

If the FluidRenderer is unavailable (no moderngl / no GL 3.3), every method
is a silent no-op.
"""

from __future__ import annotations

import math
import random
from typing import Optional


_JET_INTERVAL_MS_MIN = 90.0
_JET_INTERVAL_MS_MAX = 180.0
_SWIRL_INTERVAL_MS_MIN = 700.0
_SWIRL_INTERVAL_MS_MAX = 1500.0


class LiveModeDriver:
    """Owns the timing + RNG for ambient splat emission in live mode."""

    def __init__(self, fluid_renderer: Optional[object]) -> None:
        self._fluid = fluid_renderer
        self._next_jet_ms = 0.0
        self._next_swirl_ms = 0.0
        self._phase = random.uniform(0.0, math.tau)
        self._elapsed_ms = 0.0

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
        self._phase += dt_sec * 0.6

        r, g, b = color_rgb
        # Normalize to 0..1; the fluid splat shader multiplies by ~8 internally.
        nr, ng, nb = r / 255.0, g / 255.0, b / 255.0

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
    # Internal emitters
    # ------------------------------------------------------------------

    def _emit_jet(self, nr: float, ng: float, nb: float) -> None:
        # Two jets per tick spaced apart so the field fills evenly.
        for _ in range(2):
            x = random.uniform(0.05, 0.95)
            # Slight horizontal wobble for variety.
            vx = random.uniform(-30.0, 30.0)
            vy = random.uniform(-340.0, -220.0)
            radius = random.uniform(0.018, 0.028)
            self._fluid.add_splat(  # type: ignore[attr-defined]
                x, 0.96, vx, vy, nr, ng, nb, radius=radius
            )

    def _emit_swirl(self, nr: float, ng: float, nb: float) -> None:
        # Two opposing pushes near mid-height to keep the field rotating.
        y = random.uniform(0.35, 0.7)
        side_vx = random.choice([-220.0, 220.0])
        x_left = random.uniform(0.1, 0.35)
        x_right = random.uniform(0.65, 0.9)
        # Faint colour so swirls don't blow out brightness.
        cr, cg, cb = nr * 0.4, ng * 0.4, nb * 0.4
        self._fluid.add_splat(  # type: ignore[attr-defined]
            x_left, y, side_vx, 0.0, cr, cg, cb, radius=0.04
        )
        self._fluid.add_splat(  # type: ignore[attr-defined]
            x_right, y, -side_vx, 0.0, cr, cg, cb, radius=0.04
        )
