"""Visual effects for note trail rendering: glow, edge highlights, sparks, smoke.

Performance design notes
------------------------
* A single SRCALPHA surface (same size as the screen) is allocated once per
  renderer instance and cleared each frame.  All translucent glow/spark/smoke
  pixels are drawn onto that surface; the finished composite is blitted to the
  screen in one call.  This trades one large blit for many small per-alpha-
  surface blits — a net win on CPU-bound pygame apps.
* Particle counts are hard-capped (5 sparks, 6 smoke puffs) so worst-case
  cost stays bounded even with all 88 keys held simultaneously.
* The glow is drawn as 3 concentric, increasingly opaque rounded rects — no
  surface scaling or per-pixel operations required.
"""

from __future__ import annotations

import math
import random

import pygame

# ── Tuning constants ──────────────────────────────────────────────────────────
_GLOW_PAD: int = 20          # px glow extends beyond each edge of the bar
_MAX_SPARKS: int = 7         # sparks spawned per note press
_MAX_SMOKE: int = 8          # smoke puffs spawned per note release
_SPARK_LIFE_MS: float = 460.0
_SMOKE_LIFE_MS: float = 1080.0  # longer life lets wisps drift further
_SPARK_GRAVITY: float = 240.0   # px/s² downward pull on sparks
_BLOOM_DOWNSCALE: int = 6    # lower resolution bloom buffer for cheap blur


class NoteEffectRenderer:
    """Renders note trail ribbons with glow, highlights, sparks, and smoke.

    Typical per-frame usage::

        renderer.begin_frame()
        for trail in trails:
            renderer.draw_trail(trail, note_style)
        renderer.end_frame()

    The *trail* dict is the same dict used by ``app.py`` / ``notes_settings.py``
    and contains at minimum: ``x``, ``top_y``, ``bottom_y``, ``width``.
    Particle lists (``sparks``, ``smoke``) are stored directly in the dict so
    they travel/expire alongside the ribbon.
    """

    def __init__(self, screen: pygame.Surface) -> None:
        self._screen = screen
        self._fx_surf: pygame.Surface | None = None
        self._bloom_downsample: pygame.Surface | None = None
        self._bloom_upsample: pygame.Surface | None = None
        self._frame_bloom_strength: float = 0.0
        self.resize(screen)

    def resize(self, screen: pygame.Surface) -> None:
        """Recreate the compositing surface if the screen is resized."""
        self._screen = screen
        w, h = screen.get_size()
        self._fx_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        bloom_w = max(1, w // _BLOOM_DOWNSCALE)
        bloom_h = max(1, h // _BLOOM_DOWNSCALE)
        self._bloom_downsample = pygame.Surface((bloom_w, bloom_h), pygame.SRCALPHA)
        self._bloom_upsample = pygame.Surface((w, h), pygame.SRCALPHA)

    def set_target(self, screen: pygame.Surface) -> None:
        """Retarget drawing to *screen*, resizing buffers only when needed."""
        if self._screen is screen:
            return
        if self._fx_surf is None or self._fx_surf.get_size() != screen.get_size():
            self.resize(screen)
            return
        self._screen = screen

    # ── Frame API ─────────────────────────────────────────────────────────────

    def begin_frame(self) -> None:
        """Clear the compositing surface.  Call once before drawing any trails."""
        if self._fx_surf is not None:
            self._fx_surf.fill((0, 0, 0, 0))
        if self._bloom_downsample is not None:
            self._bloom_downsample.fill((0, 0, 0, 0))
        self._frame_bloom_strength = 0.0

    def end_frame(self) -> None:
        """Alpha-composite the fx surface onto the screen.  Call after all trails."""
        if self._fx_surf is None:
            return

        if (
            self._frame_bloom_strength > 0.0
            and self._bloom_downsample is not None
            and self._bloom_upsample is not None
        ):
            self._bloom_upsample.fill((0, 0, 0, 0))
            pygame.transform.scale(self._bloom_downsample, self._screen.get_size(), self._bloom_upsample)
            self._bloom_upsample.set_alpha(max(1, int(145 * min(1.35, self._frame_bloom_strength))))
            self._screen.blit(self._bloom_upsample, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

        self._screen.blit(self._fx_surf, (0, 0))

    def _blit_rounded_gradient(
        self,
        target: pygame.Surface,
        rect: pygame.Rect,
        top_color: tuple[int, int, int],
        bottom_color: tuple[int, int, int],
        roundness: int,
        clip_rect: pygame.Rect | None = None,
        alpha: int = 255,
    ) -> None:
        """Draw a vertical gradient clipped to a rounded rectangle.

        Rendering into a local SRCALPHA surface preserves corner roundness even
        when the gradient is drawn in horizontal bands for speed.
        """
        if rect.width <= 0 or rect.height <= 0:
            return

        surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        mask = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        radius = min(roundness, rect.width // 2, rect.height // 2)

        band_h = max(2, min(6, rect.height // 12 if rect.height > 12 else 2))
        for y in range(0, rect.height, band_h):
            seg_h = min(band_h, rect.height - y)
            t = y / float(max(1, rect.height - 1))
            color = (
                int(top_color[0] + (bottom_color[0] - top_color[0]) * t),
                int(top_color[1] + (bottom_color[1] - top_color[1]) * t),
                int(top_color[2] + (bottom_color[2] - top_color[2]) * t),
            )
            pygame.draw.rect(surf, (*color, alpha), pygame.Rect(0, y, rect.width, seg_h))

        pygame.draw.rect(
            mask,
            (255, 255, 255, 255),
            pygame.Rect(0, 0, rect.width, rect.height),
            border_radius=radius,
        )
        surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        if clip_rect is not None:
            clipped = rect.clip(clip_rect)
            if clipped.width <= 0 or clipped.height <= 0:
                return
            src_rect = pygame.Rect(
                clipped.left - rect.left,
                clipped.top - rect.top,
                clipped.width,
                clipped.height,
            )
            target.blit(surf, clipped.topleft, area=src_rect)
            return

        target.blit(surf, rect.topleft)

    def draw_trail(
        self,
        trail: dict,
        note_style: dict[str, int],
        clip_rect: pygame.Rect | None = None,
    ) -> None:
        """Draw one trail ribbon plus its particles.

        ``clip_rect`` limits all drawing to that region (used in the settings
        preview to prevent glow leaking outside the preview panel).
        """
        r = note_style["color_r"]
        g = note_style["color_g"]
        b = note_style["color_b"]
        ir = int(note_style.get("interior_r", min(255, r + 90)))
        ig = int(note_style.get("interior_g", min(255, g + 90)))
        ib = int(note_style.get("interior_b", min(255, b + 90)))
        blend = max(0.0, min(1.0, float(note_style.get("inner_blend_percent", 35)) / 100.0))
        # Higher blend softens the transition by moving inner color toward outer.
        ir = int(ir * (1.0 - blend) + r * blend)
        ig = int(ig * (1.0 - blend) + g * blend)
        ib = int(ib * (1.0 - blend) + b * blend)
        glow_strength = max(0.0, min(1.8, float(note_style.get("glow_strength_percent", 80)) / 100.0))
        highlight_strength = max(0.0, min(1.7, float(note_style.get("highlight_strength_percent", 70)) / 100.0))
        spark_strength = max(0.0, min(3.0, float(note_style.get("spark_amount_percent", 100)) / 100.0))
        smoke_strength = max(0.0, min(3.0, float(note_style.get("smoke_amount_percent", 100)) / 100.0))
        glow_enabled = bool(note_style.get("effect_glow_enabled", 1))
        highlight_enabled = bool(note_style.get("effect_highlight_enabled", 1))
        sparks_enabled = bool(note_style.get("effect_sparks_enabled", 1))
        smoke_enabled = bool(note_style.get("effect_smoke_enabled", 1))
        press_smoke_enabled = bool(note_style.get("effect_press_smoke_enabled", 0))
        moon_dust_enabled = bool(note_style.get("effect_moon_dust_enabled", 0))
        halo_pulse_enabled = bool(note_style.get("effect_halo_pulse_enabled", 0))
        roundness = max(0, int(note_style.get("edge_roundness_px", 4)))
        decay_speed = max(0.0, float(note_style.get("decay_speed", 80)))
        decay_floor = max(0.0, min(1.0, float(note_style.get("decay_value", 20)) / 100.0))

        top_y = int(float(trail["top_y"]))
        bottom_y = int(float(trail["bottom_y"]))
        height = max(2, bottom_y - top_y)
        cx = int(float(trail["x"]))
        w = int(float(trail["width"]))
        half_w = w // 2

        # Quick off-screen reject
        scr_h = self._screen.get_height()
        if bottom_y < 0 or top_y > scr_h:
            return

        # ── Glow layers (onto fx surface, 3 concentric rings) ──────────────
        if glow_enabled and glow_strength > 0.0:
            if halo_pulse_enabled:
                pulse_phase = (pygame.time.get_ticks() * 0.004) + (cx * 0.012)
                glow_strength *= 0.80 + 0.26 * math.sin(pulse_phase)
                glow_strength = max(0.08, glow_strength)
            self._frame_bloom_strength = max(self._frame_bloom_strength, glow_strength * 0.90)
            glow_scale = max(decay_floor, 1.0 - 0.5 * (decay_speed / 100.0))
            glow_r = int(max(0, min(255, r * glow_scale)))
            glow_g = int(max(0, min(255, g * glow_scale)))
            glow_b = int(max(0, min(255, b * glow_scale)))
            bloom_scale_x = 1.0
            bloom_scale_y = 1.0
            if self._bloom_downsample is not None:
                bloom_scale_x = self._bloom_downsample.get_width() / max(1, self._screen.get_width())
                bloom_scale_y = self._bloom_downsample.get_height() / max(1, self._screen.get_height())
            for pad, alpha in (
                (_GLOW_PAD,            int(20 * glow_strength)),
                (_GLOW_PAD * 2 // 3,   int(40 * glow_strength)),
                (_GLOW_PAD // 3,       int(82 * glow_strength)),
            ):
                if alpha <= 0:
                    continue
                gr = pygame.Rect(
                    cx - half_w - pad, top_y - pad,
                    w + pad * 2,       height + pad * 2,
                )
                if clip_rect:
                    gr = gr.clip(clip_rect)
                if gr.width > 0 and gr.height > 0:
                    pygame.draw.rect(self._fx_surf, (glow_r, glow_g, glow_b, alpha), gr, border_radius=max(0, roundness + pad // 4))
                    if self._bloom_downsample is not None:
                        bloom_rect = pygame.Rect(
                            int(gr.left * bloom_scale_x),
                            int(gr.top * bloom_scale_y),
                            max(1, int(math.ceil(gr.width * bloom_scale_x))),
                            max(1, int(math.ceil(gr.height * bloom_scale_y))),
                        )
                        pygame.draw.rect(
                            self._bloom_downsample,
                            (glow_r, glow_g, glow_b, min(255, alpha * 2)),
                            bloom_rect,
                            border_radius=max(0, int((roundness + pad // 4) * min(bloom_scale_x, bloom_scale_y))),
                        )

        # ── Claire moon-dust sparkles (subtle, airy twinkles) ──────────────
        if moon_dust_enabled and self._fx_surf is not None:
            age_ms = float(trail.get("age_ms", 0.0))
            stem_len = max(1, height)
            # Longer notes get a denser field of fireflies along the stem.
            swarm_count = max(4, min(14, 4 + stem_len // 70))
            span = max(10, stem_len - 10)
            base_phase = (age_ms * 0.0058) + (cx * 0.014)
            for i in range(swarm_count):
                t = i / float(max(1, swarm_count - 1))
                y_anchor = bottom_y - int(t * span)
                ang = base_phase + i * 1.37
                orbit = w * (0.55 + 0.75 * t) + 7 + (i % 3) * 3
                px = cx + int(math.sin(ang) * orbit)
                py = y_anchor + int(math.cos(ang * 1.24 + t * 2.7) * (4 + int(8 * t)))
                if clip_rect and not clip_rect.collidepoint(px, py):
                    continue
                tw = 0.52 + 0.48 * math.sin((ang * 2.5) + i * 0.65)
                alpha = max(0, min(255, int(40 + 90 * max(0.0, tw) + t * 38)))
                size = 1 if (i % 4) else 2
                sc = (
                    min(255, int(0.55 * ir + 120)),
                    min(255, int(0.55 * ig + 120)),
                    min(255, int(0.60 * ib + 128)),
                    alpha,
                )
                pygame.draw.circle(self._fx_surf, sc, (px, py), size)

        # ── Core bar (main surface) ─────────────────────────────────────────
        bar = pygame.Rect(cx - half_w, top_y, w, height)
        if bar.width > 0 and bar.height > 0:
            gradient_scale = decay_speed / 100.0
            bottom_bright = max(decay_floor, 1.0 - gradient_scale)
            outer_top = (r, g, b)
            outer_bottom = (
                int(max(0, min(255, r * bottom_bright))),
                int(max(0, min(255, g * bottom_bright))),
                int(max(0, min(255, b * bottom_bright))),
            )
            self._blit_rounded_gradient(
                self._screen,
                bar,
                outer_top,
                outer_bottom,
                roundness,
                clip_rect,
            )

            edge_w = int(note_style.get("outer_edge_width_px", 2))
            inset = max(1, min(edge_w, max(1, bar.width // 4)))
            if bar.width > inset * 2 and bar.height > inset * 2:
                inner = bar.inflate(-inset * 2, -inset * 2)
                inner_top = (ir, ig, ib)
                inner_bottom = (
                    int(max(0, min(255, ir * bottom_bright))),
                    int(max(0, min(255, ig * bottom_bright))),
                    int(max(0, min(255, ib * bottom_bright))),
                )
                self._blit_rounded_gradient(
                    self._screen,
                    inner,
                    inner_top,
                    inner_bottom,
                    max(0, roundness - inset),
                    clip_rect,
                )

            if highlight_enabled and highlight_strength > 0.0:
                # Soft inset highlight avoids hard edge seams on the left side.
                hl_w = max(2, min(max(2, w // 10), max(2, bar.width // 5)))
                hl = pygame.Rect(bar.left + 1, bar.top + 1, hl_w, max(1, bar.height - 2))
                hl_top = (min(255, int(r * 1.12)), min(255, int(g * 1.12)), min(255, int(b * 1.12)))
                hl_bottom = (
                    int(max(0, min(255, hl_top[0] * bottom_bright))),
                    int(max(0, min(255, hl_top[1] * bottom_bright))),
                    int(max(0, min(255, hl_top[2] * bottom_bright))),
                )
                self._blit_rounded_gradient(
                    self._screen,
                    hl,
                    hl_top,
                    hl_bottom,
                    max(0, roundness - 2),
                    clip_rect,
                    alpha=max(1, int(62 * highlight_strength)),
                )

        # ── Sparks ──────────────────────────────────────────────────────────
        for sp in trail.get("sparks", ()):
            if not sparks_enabled or spark_strength <= 0.0:
                continue
            life_frac = sp["life"] / sp["max_life"]
            alpha = int(230 * life_frac * life_frac * min(1.4, spark_strength))
            alpha = max(0, min(255, alpha))
            if alpha <= 0:
                continue
            sx, sy = int(sp["x"]), int(sp["y"])
            if clip_rect and not clip_rect.collidepoint(sx, sy):
                continue
            sz = max(1, int(sp["size"] * (0.75 + 0.75 * life_frac)))
            sc = (
                min(255, int(0.35 * r + 170)),
                min(255, int(0.35 * g + 170)),
                min(255, int(0.35 * b + 170)),
                alpha,
            )
            pygame.draw.circle(self._fx_surf, sc, (sx, sy), sz)

        # ── Smoke ───────────────────────────────────────────────────────────
        for sm in trail.get("smoke", ()):
            if not smoke_enabled or smoke_strength <= 0.0:
                continue
            life_frac = sm["life"] / sm["max_life"]
            # Fade out quickly at the end so wisps vanish rather than blob-out
            alpha = int(64 * life_frac * life_frac * min(1.4, smoke_strength))
            alpha = max(0, min(255, alpha))
            if alpha <= 0:
                continue
            sx, sy = int(sm["x"]), int(sm["y"])
            if clip_rect and not clip_rect.collidepoint(sx, sy):
                continue
            # Wisps expand only slightly — stay thin as they drift
            rad = max(1, int(sm["radius"] * (1.0 + 0.20 * (1.0 - life_frac))))
            sc = (
                min(255, int(r * 0.35 + 95)),
                min(255, int(g * 0.35 + 95)),
                min(255, int(b * 0.35 + 95)),
                alpha,
            )
            pygame.draw.circle(self._fx_surf, sc, (sx, sy), rad)

        # ── Start mist (note-on atmospheric smoke) ────────────────────────
        for ms in trail.get("mist", ()):
            if not press_smoke_enabled:
                continue
            life_frac = ms["life"] / ms["max_life"]
            alpha = int(56 * life_frac * life_frac)
            alpha = max(0, min(255, alpha))
            if alpha <= 0:
                continue
            sx, sy = int(ms["x"]), int(ms["y"])
            if clip_rect and not clip_rect.collidepoint(sx, sy):
                continue
            rad = max(1, int(ms["radius"] * (1.0 + 0.30 * (1.0 - life_frac))))
            sc = (
                min(255, int(ir * 0.45 + 110)),
                min(255, int(ig * 0.45 + 110)),
                min(255, int(ib * 0.50 + 120)),
                alpha,
            )
            pygame.draw.circle(self._fx_surf, sc, (sx, sy), rad)

    # ── Particle lifecycle (static so callers don't need a renderer instance) ─

    @staticmethod
    def spawn_sparks(trail: dict, note_style: dict[str, int] | None = None) -> None:
        """Burst sparks from the bottom of a ribbon.  Call on note press."""
        if note_style is not None:
            if not bool(note_style.get("effect_sparks_enabled", 1)):
                trail["sparks"] = []
                return
            spark_strength = max(0.0, min(2.0, float(note_style.get("spark_amount_percent", 100)) / 100.0))
        else:
            spark_strength = 1.0

        count = max(0, int(round(_MAX_SPARKS * spark_strength)))
        if count <= 0:
            trail["sparks"] = []
            return

        cx = float(trail["x"])
        oy = float(trail["bottom_y"])
        sparks = []
        for _ in range(count):
            # Keep angle in the upper hemisphere so sparks fly upward/outward
            angle = random.uniform(-math.pi * 0.90, -math.pi * 0.10)
            speed = random.uniform(70, 190)
            sparks.append({
                "x":        cx + random.uniform(-4, 4),
                "y":        oy,
                "vx":       math.cos(angle) * speed,
                "vy":       math.sin(angle) * speed,
                "life":     _SPARK_LIFE_MS,
                "max_life": _SPARK_LIFE_MS,
                "size":     random.uniform(1.6, 3.2),
            })
        trail["sparks"] = sparks

    @staticmethod
    def spawn_press_smoke(trail: dict, note_style: dict[str, int] | None = None) -> None:
        """Emit light mist from the note stem when a note begins."""
        if note_style is not None:
            if not bool(note_style.get("effect_press_smoke_enabled", 0)):
                trail["mist"] = []
                return
            press_strength = max(0.0, min(2.5, float(note_style.get("press_smoke_amount_percent", 100)) / 100.0))
        else:
            press_strength = 1.0

        count = max(0, int(round((4 + _MAX_SMOKE // 2) * press_strength)))
        if count <= 0:
            trail["mist"] = []
            return

        cx = float(trail["x"])
        oy = float(trail["bottom_y"])
        mist = []
        for _ in range(count):
            life = _SMOKE_LIFE_MS * random.uniform(0.45, 0.80)
            mist.append({
                "x":        cx + random.uniform(-12, 12),
                "y":        oy - random.uniform(2, 14),
                "vx":       random.uniform(-18, 18),
                "vy":       random.uniform(-18, -50),
                "life":     life,
                "max_life": life,
                "radius":   random.uniform(1.8, 4.5),
                "phase":    random.uniform(0.0, math.pi * 2.0),
            })
        trail["mist"] = mist

    @staticmethod
    def spawn_smoke(trail: dict, note_style: dict[str, int] | None = None) -> None:
        """Emit wispy smoke tendrils from the bottom of a ribbon.  Call on note release."""
        if note_style is not None:
            if not bool(note_style.get("effect_smoke_enabled", 1)):
                trail["smoke"] = []
                return
            smoke_strength = max(0.0, min(2.0, float(note_style.get("smoke_amount_percent", 100)) / 100.0))
            steam_mode = bool(note_style.get("effect_steam_smoke_enabled", 0))
        else:
            smoke_strength = 1.0
            steam_mode = False

        smoke_cap = _MAX_SMOKE + 3 if steam_mode else _MAX_SMOKE
        count = max(0, int(round(smoke_cap * smoke_strength)))
        if count <= 0:
            trail["smoke"] = []
            return

        cx = float(trail["x"])
        oy = float(trail["bottom_y"])
        smoke = []
        for _ in range(count):
            if steam_mode:
                life = _SMOKE_LIFE_MS * random.uniform(1.15, 1.55)
                smoke.append({
                    "x":        cx + random.uniform(-20, 20),
                    "y":        oy,
                    "vx":       random.uniform(-14, 14),
                    "vy":       random.uniform(-30, -66),
                    "life":     life,
                    "max_life": life,
                    "radius":   random.uniform(3.2, 7.0),
                    "steam":    True,
                    "phase":    random.uniform(0.0, math.pi * 2.0),
                })
            else:
                smoke.append({
                    "x":        cx + random.uniform(-16, 16),
                    "y":        oy,
                    # Faster upward drift + a horizontal component = wispy streaks
                    "vx":       random.uniform(-28, 28),
                    "vy":       random.uniform(-40, -90),
                    "life":     _SMOKE_LIFE_MS,
                    "max_life": _SMOKE_LIFE_MS,
                    # Smaller, thinner starting radius for wisps instead of blobs
                    "radius":   random.uniform(2.0, 5.0),
                })
        trail["smoke"] = smoke

    @staticmethod
    def update_particles(trails: list[dict], dt: int) -> None:
        """Advance spark and smoke particles for all trails.

        Should be called once per frame before drawing.
        ``dt`` is the frame delta in milliseconds.
        """
        dt_s = dt / 1000.0
        for trail in trails:
            sparks = trail.get("sparks")
            if sparks:
                alive: list[dict] = []
                for sp in sparks:
                    sp["life"] -= dt
                    if sp["life"] > 0:
                        sp["x"] += sp["vx"] * dt_s
                        sp["y"] += sp["vy"] * dt_s
                        sp["vx"] *= 0.985
                        sp["vy"] += _SPARK_GRAVITY * dt_s
                        alive.append(sp)
                trail["sparks"] = alive

            smoke = trail.get("smoke")
            if smoke:
                alive_sm: list[dict] = []
                for sm in smoke:
                    sm["life"] -= dt
                    if sm["life"] > 0:
                        if sm.get("steam"):
                            phase = float(sm.get("phase", 0.0))
                            curl = math.sin((sm["max_life"] - sm["life"]) * 0.010 + phase)
                            sm["x"] += (sm.get("vx", 0) + curl * 9.0) * dt_s
                        else:
                            sm["x"] += sm.get("vx", 0) * dt_s
                        sm["y"] += sm["vy"] * dt_s
                        sm["vx"] = sm.get("vx", 0) * 0.992
                        alive_sm.append(sm)
                trail["smoke"] = alive_sm

            mist = trail.get("mist")
            if mist:
                alive_mist: list[dict] = []
                for ms in mist:
                    ms["life"] -= dt
                    if ms["life"] > 0:
                        phase = float(ms.get("phase", 0.0))
                        curl = math.sin((ms["max_life"] - ms["life"]) * 0.014 + phase)
                        ms["x"] += (ms.get("vx", 0) + curl * 6.0) * dt_s
                        ms["y"] += ms["vy"] * dt_s
                        ms["vx"] = ms.get("vx", 0) * 0.986
                        alive_mist.append(ms)
                trail["mist"] = alive_mist
