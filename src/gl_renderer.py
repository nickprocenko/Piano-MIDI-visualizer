"""OpenGL-accelerated effects renderer using moderngl (OpenGL 3.3 core).

Replaces the highway effects layer with GPU rendering:
  - Note bars: SDF rounded-rect with vertical gradient and center highlight
  - Glow: exponential radial falloff quads rendered into a half-res HDR FBO
  - Bloom: two-pass separable Gaussian blur, additively composited
  - Particles: soft-edge UV-based circles with premultiplied alpha
  - Chromatic aberration on the bloom pass
  - Background and piano/UI overlay blitted as pygame surface textures

Particle physics (spawn_sparks, update_particles, etc.) remain in note_fx.py
and are called unchanged from app.py — this renderer only handles drawing.
"""

from __future__ import annotations

import math
import numpy as np
import moderngl
import pygame

# ---------------------------------------------------------------------------
# GLSL shader sources
# ---------------------------------------------------------------------------

# Shared full-screen quad vertex shader (NDC in, UV out)
_VS_QUAD = """
#version 330 core
in vec2 in_pos;
in vec2 in_uv;
out vec2 vUV;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    vUV = in_uv;
}
"""

# Simple texture blit with optional alpha scale (background + UI overlay)
_FS_BLIT = """
#version 330 core
in vec2 vUV;
uniform sampler2D uTex;
uniform float uAlpha;
out vec4 fragColor;
void main() {
    vec4 c = texture(uTex, vUV);
    fragColor = vec4(c.rgb, c.a * uAlpha);
}
"""

# Note bar vertex shader: pixel coords → NDC, passes per-vertex attributes
_VS_NOTE = """
#version 330 core
in vec2 in_pos;
in vec2 in_uv;
in vec3 in_ctop;
in vec3 in_cbot;
in float in_round;
in vec2 in_size;

out vec2 vUV;
out vec3 vCtop;
out vec3 vCbot;
out float vRound;
out vec2 vSize;

uniform vec2 uScreen;

void main() {
    vec2 ndc = vec2(in_pos.x / uScreen.x * 2.0 - 1.0,
                    1.0 - in_pos.y / uScreen.y * 2.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
    vUV    = in_uv;
    vCtop  = in_ctop;
    vCbot  = in_cbot;
    vRound = in_round;
    vSize  = in_size;
}
"""

# Note bar fragment: SDF rounded rect + vertical gradient + center brightening
_FS_NOTE = """
#version 330 core
in vec2 vUV;
in vec3 vCtop;
in vec3 vCbot;
in float vRound;
in vec2 vSize;
out vec4 fragColor;

float sdRoundBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

void main() {
    vec3 color = mix(vCtop, vCbot, vUV.y);

    vec2 p = (vUV - 0.5) * vSize;
    float r = min(vRound, min(vSize.x, vSize.y) * 0.5);
    float d = sdRoundBox(p, vSize * 0.5, r);
    float alpha = 1.0 - smoothstep(-0.8, 0.8, d);

    // Subtle vertical center-column highlight
    float cx = 1.0 - abs(vUV.x - 0.5) * 2.2;
    color = min(vec3(1.0), color + color * cx * cx * 0.18);

    fragColor = vec4(color * alpha, alpha);
}
"""

# Glow fragment: exponential falloff from bar edge (rendered into bloom FBO)
_FS_GLOW = """
#version 330 core
in vec2 vUV;
in vec3 vCtop;
in vec3 vCbot;
in float vRound;
in vec2 vSize;
out vec4 fragColor;

void main() {
    vec3 color = mix(vCtop, vCbot, vUV.y);

    vec2 p = (vUV - 0.5) * vSize;
    // Distance outside the inner bar boundary
    vec2 inner = vSize * 0.5 - vRound;
    vec2 d2 = max(abs(p) - inner, 0.0);
    float edgeDist = length(d2);
    float maxGlow = min(vSize.x, vSize.y) * 0.8 + 10.0;
    float t = edgeDist / max(maxGlow, 1.0);
    float falloff = exp(-t * t * 4.5);

    fragColor = vec4(color * falloff, falloff);
}
"""

# Particle quad fragment: soft UV circle, premultiplied alpha output
_VS_PART = """
#version 330 core
in vec2 in_pos;
in vec2 in_uv;
in vec4 in_color;
out vec2 vUV;
out vec4 vColor;
uniform vec2 uScreen;
void main() {
    vec2 ndc = vec2(in_pos.x / uScreen.x * 2.0 - 1.0,
                    1.0 - in_pos.y / uScreen.y * 2.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
    vUV   = in_uv;
    vColor = in_color;
}
"""

_FS_PART = """
#version 330 core
in vec2 vUV;
in vec4 vColor;
out vec4 fragColor;
void main() {
    float dist = length(vUV - 0.5) * 2.0;
    float alpha = vColor.a * (1.0 - smoothstep(0.55, 1.0, dist));
    if (alpha < 0.004) discard;
    fragColor = vec4(vColor.rgb * alpha, alpha);
}
"""

# Separable Gaussian blur (9-tap, sigma≈2); uDir = (1,0) or (0,1)
_FS_BLUR = """
#version 330 core
in vec2 vUV;
uniform sampler2D uTex;
uniform vec2 uDir;
out vec4 fragColor;
const float W[5] = float[](0.2270, 0.1945, 0.1216, 0.0540, 0.0162);
void main() {
    vec2 step = uDir / vec2(textureSize(uTex, 0));
    vec3 acc = texture(uTex, vUV).rgb * W[0];
    for (int i = 1; i < 5; i++) {
        acc += texture(uTex, vUV + float(i) * step).rgb * W[i];
        acc += texture(uTex, vUV - float(i) * step).rgb * W[i];
    }
    fragColor = vec4(acc, 1.0);
}
"""

# Final composite: scene + blurred bloom, Reinhard tone-map, chromatic aberration
_FS_COMPOSITE = """
#version 330 core
in vec2 vUV;
uniform sampler2D uScene;
uniform sampler2D uBloom;
uniform sampler2D uFluid;
uniform float uBloomStr;
uniform float uCAShift;
out vec4 fragColor;
void main() {
    vec3 scene = texture(uScene, vUV).rgb;
    vec4 fluid = texture(uFluid, vUV);
    vec3 bloom;
    if (uCAShift > 0.0) {
        float r = texture(uBloom, vUV + vec2( uCAShift, 0.0)).r;
        float g = texture(uBloom, vUV).g;
        float b = texture(uBloom, vUV + vec2(-uCAShift, 0.0)).b;
        bloom = vec3(r, g, b);
    } else {
        bloom = texture(uBloom, vUV).rgb;
    }
    // Tone-map only the bloom so base note colors are not darkened
    vec3 bloom_contrib = bloom * uBloomStr;
    // Dobryakov-style: display raw dye additively, scaled so adjacent note blobs blend
    // smoothly rather than each saturating to white independently.
    // Reinhard denominator 0.15 keeps mid-level dye vivid; * 0.55 leaves room for scene + bloom.
    vec3 fluid_show = fluid.rgb / (fluid.rgb + vec3(0.15)) * 0.55;
    vec3 hdr = scene + fluid_show + bloom_contrib / (bloom_contrib + vec3(1.0));
    fragColor = vec4(clamp(hdr, 0.0, 1.0), 1.0);
}
"""

_FS_FLUID_COPY = """
#version 330 core
in vec2 vUV;
uniform sampler2D uTex;
uniform float uDissipation;
out vec4 fragColor;
void main() {
    fragColor = texture(uTex, vUV) * uDissipation;
}
"""

_FS_FLUID_SPLAT = """
#version 330 core
in vec2 vUV;
uniform sampler2D uTarget;
uniform vec2 uPoint;
uniform vec3 uColor;
uniform float uRadius;
uniform float uAspect;
out vec4 fragColor;
void main() {
    vec2 p = vUV - uPoint;
    p.x *= uAspect;
    vec4 base = texture(uTarget, vUV);
    float splat = exp(-dot(p, p) / max(0.00001, uRadius));
    fragColor = base + vec4(uColor * splat, splat);
}
"""

_FS_FLUID_ADVECT = """
#version 330 core
in vec2 vUV;
uniform sampler2D uVelocity;
uniform sampler2D uSource;
uniform vec2 uTexelSize;
uniform float uDt;
uniform float uDissipation;
out vec4 fragColor;
void main() {
    vec2 coord = vUV - uDt * texture(uVelocity, vUV).xy * uTexelSize;
    fragColor = texture(uSource, coord) * uDissipation;
}
"""

_FS_FLUID_DIVERGENCE = """
#version 330 core
in vec2 vUV;
uniform sampler2D uVelocity;
uniform vec2 uTexelSize;
out vec4 fragColor;
void main() {
    float L = texture(uVelocity, vUV - vec2(uTexelSize.x, 0.0)).x;
    float R = texture(uVelocity, vUV + vec2(uTexelSize.x, 0.0)).x;
    float B = texture(uVelocity, vUV - vec2(0.0, uTexelSize.y)).y;
    float T = texture(uVelocity, vUV + vec2(0.0, uTexelSize.y)).y;
    float div = 0.5 * (R - L + T - B);
    fragColor = vec4(div, 0.0, 0.0, 1.0);
}
"""

_FS_FLUID_CURL = """
#version 330 core
in vec2 vUV;
uniform sampler2D uVelocity;
uniform vec2 uTexelSize;
out vec4 fragColor;
void main() {
    float L = texture(uVelocity, vUV - vec2(uTexelSize.x, 0.0)).y;
    float R = texture(uVelocity, vUV + vec2(uTexelSize.x, 0.0)).y;
    float B = texture(uVelocity, vUV - vec2(0.0, uTexelSize.y)).x;
    float T = texture(uVelocity, vUV + vec2(0.0, uTexelSize.y)).x;
    float curl = R - L - T + B;
    fragColor = vec4(curl, 0.0, 0.0, 1.0);
}
"""

_FS_FLUID_VORTICITY = """
#version 330 core
in vec2 vUV;
uniform sampler2D uVelocity;
uniform sampler2D uCurl;
uniform vec2 uTexelSize;
uniform float uDt;
uniform float uCurlStrength;
out vec4 fragColor;
void main() {
    float L = abs(texture(uCurl, vUV - vec2(uTexelSize.x, 0.0)).x);
    float R = abs(texture(uCurl, vUV + vec2(uTexelSize.x, 0.0)).x);
    float B = abs(texture(uCurl, vUV - vec2(0.0, uTexelSize.y)).x);
    float T = abs(texture(uCurl, vUV + vec2(0.0, uTexelSize.y)).x);
    float C = texture(uCurl, vUV).x;
    vec2 force = 0.5 * vec2(T - B, R - L);
    force /= length(force) + 0.0001;
    force *= uCurlStrength * C;
    vec2 vel = texture(uVelocity, vUV).xy;
    fragColor = vec4(vel + force * uDt, 0.0, 1.0);
}
"""

_FS_FLUID_PRESSURE = """
#version 330 core
in vec2 vUV;
uniform sampler2D uPressure;
uniform sampler2D uDivergence;
uniform vec2 uTexelSize;
out vec4 fragColor;
void main() {
    float L = texture(uPressure, vUV - vec2(uTexelSize.x, 0.0)).x;
    float R = texture(uPressure, vUV + vec2(uTexelSize.x, 0.0)).x;
    float B = texture(uPressure, vUV - vec2(0.0, uTexelSize.y)).x;
    float T = texture(uPressure, vUV + vec2(0.0, uTexelSize.y)).x;
    float div = texture(uDivergence, vUV).x;
    float p = (L + R + B + T - div) * 0.25;
    fragColor = vec4(p, 0.0, 0.0, 1.0);
}
"""

_FS_FLUID_GRADIENT = """
#version 330 core
in vec2 vUV;
uniform sampler2D uPressure;
uniform sampler2D uVelocity;
uniform vec2 uTexelSize;
out vec4 fragColor;
void main() {
    float L = texture(uPressure, vUV - vec2(uTexelSize.x, 0.0)).x;
    float R = texture(uPressure, vUV + vec2(uTexelSize.x, 0.0)).x;
    float B = texture(uPressure, vUV - vec2(0.0, uTexelSize.y)).x;
    float T = texture(uPressure, vUV + vec2(0.0, uTexelSize.y)).x;
    vec2 vel = texture(uVelocity, vUV).xy - vec2(R - L, T - B);
    fragColor = vec4(vel, 0.0, 1.0);
}
"""

# Full-screen quad geometry (NDC), standard UVs (V=0 at bottom, V=1 at top)
# Works for both FBO blits (GL Y-up) and pygame surface uploads with flip=True
_QUAD_VERTS = np.array([
    -1, -1,  0, 0,
     1, -1,  1, 0,
    -1,  1,  0, 1,
     1, -1,  1, 0,
     1,  1,  1, 1,
    -1,  1,  0, 1,
], dtype="f4")

# ---------------------------------------------------------------------------
# Renderer class
# ---------------------------------------------------------------------------

class _DoubleFBO:
    def __init__(self, ctx: moderngl.Context, size: tuple[int, int], components: int = 4, dtype: str = "f2") -> None:
        self.read_tex = ctx.texture(size, components, dtype=dtype)
        self.write_tex = ctx.texture(size, components, dtype=dtype)
        self.read_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.write_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.read_tex.repeat_x = self.read_tex.repeat_y = False
        self.write_tex.repeat_x = self.write_tex.repeat_y = False
        self.read_fbo = ctx.framebuffer(color_attachments=[self.read_tex])
        self.write_fbo = ctx.framebuffer(color_attachments=[self.write_tex])

    def swap(self) -> None:
        self.read_tex, self.write_tex = self.write_tex, self.read_tex
        self.read_fbo, self.write_fbo = self.write_fbo, self.read_fbo

    def release(self) -> None:
        self.read_tex.release()
        self.write_tex.release()
        self.read_fbo.release()
        self.write_fbo.release()

class GLEffectsRenderer:
    """GPU-accelerated note trail renderer.

    Public API matches NoteEffectRenderer so app.py can swap them:
        begin_frame()
        draw_trail(trail, note_style)
        end_frame(bg_surf, bg_alpha, overlay_surf)
        present_pygame(surf)   # non-highway UI screens
    """

    # Per-vertex floats for bar/glow quads
    _BAR_FPV = 13   # pos(2) uv(2) ctop(3) cbot(3) round(1) size(2)
    # Per-vertex floats for particle quads
    _PART_FPV = 8   # pos(2) uv(2) color(4)

    def __init__(self, ctx: moderngl.Context, screen_size: tuple[int, int]) -> None:
        self._ctx = ctx
        self._w, self._h = screen_size

        # Compile all shader programs
        self._prog_blit = ctx.program(vertex_shader=_VS_QUAD,  fragment_shader=_FS_BLIT)
        self._prog_blur = ctx.program(vertex_shader=_VS_QUAD,  fragment_shader=_FS_BLUR)
        self._prog_comp = ctx.program(vertex_shader=_VS_QUAD,  fragment_shader=_FS_COMPOSITE)
        self._prog_note = ctx.program(vertex_shader=_VS_NOTE,  fragment_shader=_FS_NOTE)
        self._prog_glow = ctx.program(vertex_shader=_VS_NOTE,  fragment_shader=_FS_GLOW)
        self._prog_part = ctx.program(vertex_shader=_VS_PART,  fragment_shader=_FS_PART)
        self._prog_fluid_copy = ctx.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_FLUID_COPY)
        self._prog_fluid_splat = ctx.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_FLUID_SPLAT)
        self._prog_fluid_advect = ctx.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_FLUID_ADVECT)
        self._prog_fluid_div = ctx.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_FLUID_DIVERGENCE)
        self._prog_fluid_curl = ctx.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_FLUID_CURL)
        self._prog_fluid_vorticity = ctx.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_FLUID_VORTICITY)
        self._prog_fluid_pressure = ctx.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_FLUID_PRESSURE)
        self._prog_fluid_gradient = ctx.program(vertex_shader=_VS_QUAD, fragment_shader=_FS_FLUID_GRADIENT)

        # Full-screen quad VAOs (one per program that uses it)
        quad_buf = ctx.buffer(data=_QUAD_VERTS.tobytes())
        self._quad_blit = ctx.vertex_array(self._prog_blit, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_blur = ctx.vertex_array(self._prog_blur, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_comp = ctx.vertex_array(self._prog_comp, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_fluid_copy = ctx.vertex_array(self._prog_fluid_copy, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_fluid_splat = ctx.vertex_array(self._prog_fluid_splat, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_fluid_advect = ctx.vertex_array(self._prog_fluid_advect, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_fluid_div = ctx.vertex_array(self._prog_fluid_div, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_fluid_curl = ctx.vertex_array(self._prog_fluid_curl, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_fluid_vorticity = ctx.vertex_array(self._prog_fluid_vorticity, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_fluid_pressure = ctx.vertex_array(self._prog_fluid_pressure, [(quad_buf, "2f 2f", "in_pos", "in_uv")])
        self._quad_fluid_gradient = ctx.vertex_array(self._prog_fluid_gradient, [(quad_buf, "2f 2f", "in_pos", "in_uv")])

        # Dynamic VBOs/VAOs for batched geometry (populated each frame)
        self._bar_vbo:  moderngl.Buffer | None = None
        self._glow_vbo: moderngl.Buffer | None = None
        self._part_vbo: moderngl.Buffer | None = None
        self._bar_vao:  moderngl.VertexArray | None = None
        self._glow_vao: moderngl.VertexArray | None = None
        self._part_vao: moderngl.VertexArray | None = None

        # Lazily-created textures for pygame surface uploads
        self._bg_tex: moderngl.Texture | None = None
        self._ui_tex: moderngl.Texture | None = None

        # FBOs and their color textures (created in resize)
        self._scene_fbo: moderngl.Framebuffer | None = None
        self._glow_fbo:  moderngl.Framebuffer | None = None
        self._blur_fbo:  moderngl.Framebuffer | None = None
        self._scene_tex: moderngl.Texture | None = None
        self._glow_tex:  moderngl.Texture | None = None
        self._blur_tex:  moderngl.Texture | None = None
        self._fluid_velocity: _DoubleFBO | None = None
        self._fluid_dye: _DoubleFBO | None = None
        self._fluid_pressure: _DoubleFBO | None = None
        self._fluid_divergence_fbo: moderngl.Framebuffer | None = None
        self._fluid_divergence_tex: moderngl.Texture | None = None
        self._fluid_curl_fbo: moderngl.Framebuffer | None = None
        self._fluid_curl_tex: moderngl.Texture | None = None
        self._fluid_size: tuple[int, int] = (1, 1)

        # Batch lists — filled by draw_trail, consumed by end_frame
        self._bar_verts:  list[float] = []
        self._glow_verts: list[float] = []
        self._part_verts: list[float] = []
        self._fluid_splats: list[tuple[float, float, float, float, float, float, float, float]] = []
        self._trail_heads: dict[object, tuple[float, float]] = {}
        self._fluid_enabled_this_frame = False

        self.resize(screen_size)

    # ------------------------------------------------------------------
    # Resize
    # ------------------------------------------------------------------

    def resize(self, screen_size: tuple[int, int]) -> None:
        """Recreate size-dependent FBOs.  Call on window resize."""
        ctx = self._ctx
        w, h = screen_size
        self._w, self._h = w, h

        # Full-res scene FBO (RGBA8)
        scene_tex = ctx.texture((w, h), 4)
        scene_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        scene_depth = ctx.depth_renderbuffer((w, h))
        self._scene_fbo = ctx.framebuffer(
            color_attachments=[scene_tex], depth_attachment=scene_depth
        )
        self._scene_tex = scene_tex

        # Half-res glow + blur FBOs (RGB F16 for HDR accumulation)
        bw, bh = max(1, w // 2), max(1, h // 2)
        glow_tex = ctx.texture((bw, bh), 3, dtype="f2")
        glow_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._glow_fbo = ctx.framebuffer(color_attachments=[glow_tex])
        self._glow_tex = glow_tex

        blur_tex = ctx.texture((bw, bh), 3, dtype="f2")
        blur_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._blur_fbo = ctx.framebuffer(color_attachments=[blur_tex])
        self._blur_tex = blur_tex

        fw = max(96, min(512, w // 2))
        fh = max(54, min(288, h // 2))
        self._fluid_size = (fw, fh)
        for obj in (
            self._fluid_velocity,
            self._fluid_dye,
            self._fluid_pressure,
        ):
            if obj is not None:
                obj.release()
        if self._fluid_divergence_fbo is not None:
            self._fluid_divergence_fbo.release()
        if self._fluid_divergence_tex is not None:
            self._fluid_divergence_tex.release()
        if self._fluid_curl_fbo is not None:
            self._fluid_curl_fbo.release()
        if self._fluid_curl_tex is not None:
            self._fluid_curl_tex.release()
        self._fluid_velocity = _DoubleFBO(ctx, (fw, fh), 4, "f2")
        self._fluid_dye = _DoubleFBO(ctx, (fw, fh), 4, "f2")
        self._fluid_pressure = _DoubleFBO(ctx, (fw, fh), 4, "f2")
        self._fluid_divergence_tex = ctx.texture((fw, fh), 4, dtype="f2")
        self._fluid_divergence_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._fluid_divergence_tex.repeat_x = self._fluid_divergence_tex.repeat_y = False
        self._fluid_divergence_fbo = ctx.framebuffer(color_attachments=[self._fluid_divergence_tex])
        self._fluid_curl_tex = ctx.texture((fw, fh), 4, dtype="f2")
        self._fluid_curl_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._fluid_curl_tex.repeat_x = self._fluid_curl_tex.repeat_y = False
        self._fluid_curl_fbo = ctx.framebuffer(color_attachments=[self._fluid_curl_tex])
        for fbo in (
            self._fluid_velocity.read_fbo,
            self._fluid_velocity.write_fbo,
            self._fluid_dye.read_fbo,
            self._fluid_dye.write_fbo,
            self._fluid_pressure.read_fbo,
            self._fluid_pressure.write_fbo,
            self._fluid_divergence_fbo,
            self._fluid_curl_fbo,
        ):
            fbo.use()
            ctx.clear(0.0, 0.0, 0.0, 0.0)

        # Invalidate cached surface textures (size may have changed)
        self._bg_tex = None
        self._ui_tex = None
        self._trail_heads.clear()

    # ------------------------------------------------------------------
    # Surface → texture upload
    # ------------------------------------------------------------------

    def _surf_to_tex(
        self,
        surf: pygame.Surface,
        existing: moderngl.Texture | None,
    ) -> moderngl.Texture:
        """Upload a pygame Surface as an RGBA GL texture, flipping Y for GL origin."""
        sw, sh = surf.get_size()
        if existing is None or existing.size != (sw, sh):
            existing = self._ctx.texture((sw, sh), 4)
            existing.filter = (moderngl.LINEAR, moderngl.LINEAR)
        data = pygame.image.tobytes(surf, "RGBA", True)  # True = flip vertically
        existing.write(data)
        return existing

    # ------------------------------------------------------------------
    # Non-highway UI blit (menu / settings screens)
    # ------------------------------------------------------------------

    def present_pygame(self, surf: pygame.Surface) -> None:
        """Blit a full-screen pygame surface to the GL default framebuffer."""
        ctx = self._ctx
        ctx.screen.use()
        ctx.viewport = (0, 0, self._w, self._h)
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self._ui_tex = self._surf_to_tex(surf, self._ui_tex)
        self._ui_tex.use(0)
        self._prog_blit["uTex"]   = 0
        self._prog_blit["uAlpha"] = 1.0
        self._quad_blit.render(moderngl.TRIANGLES)

    # ------------------------------------------------------------------
    # Frame API — data collection (no GPU calls until end_frame)
    # ------------------------------------------------------------------

    def begin_frame(self) -> None:
        """Clear batch lists.  Call once before draw_trail calls."""
        self._bar_verts.clear()
        self._glow_verts.clear()
        self._part_verts.clear()
        self._fluid_splats.clear()
        self._fluid_enabled_this_frame = False

    # ------------------------------------------------------------------
    # Vertex emitters
    # ------------------------------------------------------------------

    def _emit_bar_verts(
        self,
        dst: list[float],
        cx: float, top_y: float, bot_y: float, w: float,
        cr_t: float, cg_t: float, cb_t: float,
        cr_b: float, cg_b: float, cb_b: float,
        roundness: float,
        pad: float = 0.0,
    ) -> None:
        """Append 6 vertices (2 triangles) for one axis-aligned bar quad."""
        x0 = cx - w * 0.5 - pad
        x1 = cx + w * 0.5 + pad
        y0 = top_y - pad
        y1 = bot_y + pad
        bw = x1 - x0
        bh = y1 - y0
        r  = min(roundness, bw * 0.5, bh * 0.5)

        def _v(px: float, py: float, u: float, v: float) -> None:
            dst.extend([px, py, u, v, cr_t, cg_t, cb_t, cr_b, cg_b, cb_b, r, bw, bh])

        _v(x0, y0, 0.0, 0.0)
        _v(x1, y0, 1.0, 0.0)
        _v(x1, y1, 1.0, 1.0)
        _v(x0, y0, 0.0, 0.0)
        _v(x1, y1, 1.0, 1.0)
        _v(x0, y1, 0.0, 1.0)

    def _emit_particle_quad(
        self,
        x: float, y: float,
        r: float, g: float, b: float, a: float,
        radius: float,
    ) -> None:
        """Append 6 vertices for one soft-circle particle quad."""
        x0, x1 = x - radius, x + radius
        y0, y1 = y - radius, y + radius

        def _v(px: float, py: float, u: float, v: float) -> None:
            self._part_verts.extend([px, py, u, v, r, g, b, a])

        _v(x0, y0, 0.0, 0.0)
        _v(x1, y0, 1.0, 0.0)
        _v(x1, y1, 1.0, 1.0)
        _v(x0, y0, 0.0, 0.0)
        _v(x1, y1, 1.0, 1.0)
        _v(x0, y1, 0.0, 1.0)

    def _queue_fluid_splat(
        self,
        trail: dict,
        x: float,
        y: float,
        r: float,
        g: float,
        b: float,
        strength: float,
    ) -> None:
        key = trail.get("note", id(trail))
        prev = self._trail_heads.get(key)
        if prev is None:
            dx = 0.0
            dy = -90.0
        else:
            dx = x - prev[0]
            dy = y - prev[1]
        self._trail_heads[key] = (x, y)
        nx = max(0.0, min(1.0, x / max(1.0, float(self._w))))
        ny = max(0.0, min(1.0, 1.0 - y / max(1.0, float(self._h))))
        # vel in UV-space units/sec (uDt=1/60 applied in advect shader)
        vel_scale = 280.0 * strength
        upward = 300.0 * strength   # +vy = upward in UV space (ny=1 is top)
        vx = max(-700.0, min(700.0, dx * vel_scale))
        vy = max(-700.0, min(700.0, -dy * vel_scale + upward))
        # Dobryakov uses 0.25; keep smaller so adjacent piano notes stay distinct
        radius = max(0.030, min(0.060, 0.040 + 0.020 * strength))
        # Low per-frame color so blobs blend rather than saturate to white individually
        cr = r * 0.06 * strength
        cg = g * 0.06 * strength
        cb = b * 0.06 * strength
        # Fade splats near screen edges to prevent clamp-to-edge boundary accumulation.
        # A splat whose center is within one radius of the border gets attenuated so
        # the Gaussian tail never "piles up" at the rightmost/leftmost texture column.
        aspect = float(self._w) / max(1.0, float(self._h))
        h_margin = radius / aspect  # horizontal extent in UV units
        v_margin = radius            # vertical extent in UV units
        edge_fade = min(
            max(0.0, min(1.0, nx / max(0.001, h_margin))),          # left edge
            max(0.0, min(1.0, (1.0 - nx) / max(0.001, h_margin))),  # right edge
            max(0.0, min(1.0, ny / max(0.001, v_margin))),           # bottom edge
            max(0.0, min(1.0, (1.0 - ny) / max(0.001, v_margin))),  # top edge
        )
        cr *= edge_fade
        cg *= edge_fade
        cb *= edge_fade
        vx *= edge_fade
        vy *= edge_fade
        self._fluid_splats.append((nx, ny, vx, vy, cr, cg, cb, radius))

    # ------------------------------------------------------------------
    # draw_trail — mirrors NoteEffectRenderer.draw_trail but emits to lists
    # ------------------------------------------------------------------

    def draw_trail(self, trail: dict, note_style: dict) -> None:  # noqa: C901
        """Collect one trail's geometry.  No GPU work happens here."""
        # --- colours ---
        r  = note_style["color_r"]    / 255.0
        g  = note_style["color_g"]    / 255.0
        b  = note_style["color_b"]    / 255.0
        ir = int(note_style.get("interior_r", min(255, note_style["color_r"] + 90))) / 255.0
        ig = int(note_style.get("interior_g", min(255, note_style["color_g"] + 90))) / 255.0
        ib = int(note_style.get("interior_b", min(255, note_style["color_b"] + 90))) / 255.0
        blend = max(0.0, min(1.0, float(note_style.get("inner_blend_percent", 35)) / 100.0))
        ir = ir * (1.0 - blend) + r * blend
        ig = ig * (1.0 - blend) + g * blend
        ib = ib * (1.0 - blend) + b * blend

        # --- style params ---
        glow_str  = max(0.0, min(1.8, float(note_style.get("glow_strength_percent",    80)) / 100.0))
        hl_str    = max(0.0, min(1.7, float(note_style.get("highlight_strength_percent", 70)) / 100.0))
        sp_str    = max(0.0, min(3.0, float(note_style.get("spark_amount_percent",     100)) / 100.0))
        sm_str    = max(0.0, min(3.0, float(note_style.get("smoke_amount_percent",     100)) / 100.0))
        decay_spd = max(0.0, float(note_style.get("decay_speed", 80)))
        decay_flr = max(0.0, min(1.0, float(note_style.get("decay_value", 20)) / 100.0))
        roundness = float(max(0, int(note_style.get("edge_roundness_px", 4))))
        edge_w    = int(note_style.get("outer_edge_width_px", 2))

        glow_on  = False
        hl_on    = False
        sp_on    = False
        sm_on    = False
        mist_on  = False
        moon_on  = bool(note_style.get("effect_moon_dust_enabled", 0))
        steam_on = bool(note_style.get("effect_steam_smoke_enabled", 0))
        pulse_on = False

        top_y = float(trail["top_y"])
        bot_y = float(trail["bottom_y"])
        cx    = float(trail["x"])
        w     = float(trail["width"])

        if bot_y < 0 or top_y > self._h or w <= 0:
            return

        bot_bright = max(decay_flr, 1.0 - decay_spd / 100.0)
        # Always feed active note heads into the fluid sim — this IS the primary effect
        if not bool(trail.get("released", False)):
            self._fluid_enabled_this_frame = True
            head_y = top_y
            head_boost = min(1.0, max(0.20, (bot_y - top_y) / 140.0))
            self._queue_fluid_splat(trail, cx, head_y, max(r, ir * 0.92), max(g, ig * 0.92), max(b, ib * 0.92), head_boost)

        # Halo pulse
        if pulse_on and glow_on:
            phase = (pygame.time.get_ticks() * 0.004) + (cx * 0.012)
            glow_str = max(0.08, glow_str * (0.80 + 0.26 * math.sin(phase)))

        # ── Note bar quads → _bar_verts ────────────────────────────────
        inset = max(0, min(edge_w, int(w) // 4))

        # Outer bar
        self._emit_bar_verts(
            self._bar_verts,
            cx, top_y, bot_y, w,
            r, g, b,
            r * bot_bright, g * bot_bright, b * bot_bright,
            roundness,
        )
        # Inner bar (brighter interior colour)
        inner_w = w - inset * 2
        inner_h = (bot_y - top_y) - inset * 2
        if inner_w > 0 and inner_h > 0:
            self._emit_bar_verts(
                self._bar_verts,
                cx, top_y + inset, bot_y - inset, inner_w,
                ir, ig, ib,
                ir * bot_bright, ig * bot_bright, ib * bot_bright,
                max(0.0, roundness - inset),
            )

        if hl_on and hl_str > 0.0:
            hl_w   = max(3.0, min(w / 5.0, w / 3.0))
            hl_a   = 0.45 * hl_str
            hl_r   = min(1.0, r * 0.50 + 0.50)
            hl_g   = min(1.0, g * 0.50 + 0.50)
            hl_b_c = min(1.0, b * 0.50 + 0.50)
            # Left specular
            self._emit_bar_verts(
                self._bar_verts,
                cx - w * 0.5 + hl_w * 0.5 + 1, top_y + 1, bot_y - 1, hl_w,
                hl_r * hl_a, hl_g * hl_a, hl_b_c * hl_a,
                hl_r * hl_a * bot_bright, hl_g * hl_a * bot_bright, hl_b_c * hl_a * bot_bright,
                max(0.0, roundness - 2),
            )
            # Right specular (dimmer)
            hr_a = hl_a * 0.45
            self._emit_bar_verts(
                self._bar_verts,
                cx + w * 0.5 - hl_w * 0.5 - 1, top_y + 1, bot_y - 1, hl_w * 0.7,
                hl_r * hr_a, hl_g * hr_a, hl_b_c * hr_a,
                hl_r * hr_a * bot_bright, hl_g * hr_a * bot_bright, hl_b_c * hr_a * bot_bright,
                max(0.0, roundness - 2),
            )

        # ── Glow quads → _glow_verts ───────────────────────────────────
        if glow_on and glow_str > 0.0:
            gr = r * glow_str
            gg = g * glow_str
            gb = b * glow_str
            # Tight inner glow
            self._emit_bar_verts(
                self._glow_verts,
                cx, top_y, bot_y, w,
                gr, gg, gb,
                gr * bot_bright, gg * bot_bright, gb * bot_bright,
                roundness, pad=14.0,
            )
            # Wide outer glow
            self._emit_bar_verts(
                self._glow_verts,
                cx, top_y, bot_y, w,
                gr * 0.5, gg * 0.5, gb * 0.5,
                gr * 0.5 * bot_bright, gg * 0.5 * bot_bright, gb * 0.5 * bot_bright,
                roundness, pad=36.0,
            )
            # Active note head — extra emit-point cap at the key
            if not bool(trail.get("released", False)):
                cap_h = min(12.0, (bot_y - top_y) * 0.12 + 4.0)
                self._emit_bar_verts(
                    self._glow_verts,
                    cx, bot_y - cap_h, bot_y, w,
                    min(1.0, ir + 0.25), min(1.0, ig + 0.25), min(1.0, ib + 0.25),
                    min(1.0, ir + 0.10), min(1.0, ig + 0.10), min(1.0, ib + 0.10),
                    roundness, pad=10.0,
                )

        # ── Sparks → _part_verts ───────────────────────────────────────
        if moon_on:
            age_ms = float(trail.get("age_ms", 0.0))
            stem_len = max(1.0, bot_y - top_y)
            count = max(5, min(18, int(5 + stem_len // 58)))
            span = max(10.0, stem_len - 10.0)
            base_phase = (age_ms * 0.0048) + (cx * 0.014)
            for i in range(count):
                t = i / float(max(1, count - 1))
                y_anchor = bot_y - t * span
                ang = base_phase + i * 1.51
                orbit = w * (0.65 + 0.95 * t) + 8.0 + (i % 3) * 4.0
                px = cx + math.sin(ang) * orbit
                py = y_anchor + math.cos(ang * 1.18 + t * 2.7) * (5.0 + 10.0 * t)
                tw = 0.50 + 0.50 * math.sin((ang * 2.8) + i * 0.65)
                a = min(0.90, 0.16 + 0.44 * max(0.0, tw) + t * 0.13)
                size = 1.4 if (i % 4) else 2.4
                self._emit_particle_quad(px, py, 1.0, 0.88, 0.34, a, size)

        if sp_on and sp_str > 0.0:
            for sp in trail.get("sparks", ()):
                lf = sp["life"] / sp["max_life"]
                a  = lf * lf * min(1.4, sp_str)
                if a <= 0.0:
                    continue
                sz = sp["size"] * (0.75 + 0.75 * lf)
                # Warm ember tones
                sr = min(1.0, r * 0.55 + 0.61)
                sg = min(1.0, g * 0.55 + 0.55)
                sb = min(1.0, b * 0.50 + 0.45)
                self._emit_particle_quad(sp["x"], sp["y"], sr, sg, sb, a, sz)
                # Motion-trail dot at midpoint to prev position
                if "prev_x" in sp:
                    mid_x = (sp["x"] + sp["prev_x"]) * 0.5
                    mid_y = (sp["y"] + sp["prev_y"]) * 0.5
                    self._emit_particle_quad(mid_x, mid_y, sr, sg, sb, a * 0.35, sz * 0.55)

        # ── Smoke → _part_verts ────────────────────────────────────────
        if sm_on and sm_str > 0.0:
            for sm in trail.get("smoke", ()):
                lf = sm["life"] / sm["max_life"]
                a  = lf * lf * min(1.4, sm_str) * 0.55
                if a <= 0.0:
                    continue
                rad = sm["radius"] * (1.0 + 0.25 * (1.0 - lf))
                sr  = min(1.0, r * 0.60 + 0.32)
                sg  = min(1.0, g * 0.60 + 0.32)
                sb  = min(1.0, b * 0.60 + 0.32)
                self._emit_particle_quad(sm["x"], sm["y"], sr, sg, sb, a, rad)

        # ── Press mist → _part_verts ───────────────────────────────────
        # Fluid plumes: colorful splats that diffuse, curl, and bloom outward.
        if mist_on:
            for ms in trail.get("mist", ()):
                lf = ms["life"] / ms["max_life"]
                a  = lf * lf * 0.45
                if a <= 0.0:
                    continue
                rad = ms["radius"] * (1.0 + 0.30 * (1.0 - lf))
                mr  = min(1.0, ir * 0.55 + 0.43)
                mg  = min(1.0, ig * 0.55 + 0.43)
                mb  = min(1.0, ib * 0.60 + 0.47)
                self._emit_particle_quad(ms["x"], ms["y"], mr, mg, mb, a, rad)

    # ------------------------------------------------------------------
    # end_frame — all GPU work for one frame
    # ------------------------------------------------------------------

    def _copy_fluid(self, tex: moderngl.Texture, target: _DoubleFBO, dissipation: float) -> None:
        target.write_fbo.use()
        tex.use(0)
        self._prog_fluid_copy["uTex"] = 0
        self._prog_fluid_copy["uDissipation"] = dissipation
        self._quad_fluid_copy.render(moderngl.TRIANGLES)
        target.swap()

    def _splat_fluid(self, target: _DoubleFBO, point: tuple[float, float], color: tuple[float, float, float], radius: float) -> None:
        target.write_fbo.use()
        target.read_tex.use(0)
        self._prog_fluid_splat["uTarget"] = 0
        self._prog_fluid_splat["uPoint"] = point
        self._prog_fluid_splat["uColor"] = color
        self._prog_fluid_splat["uRadius"] = radius
        self._prog_fluid_splat["uAspect"] = float(self._w) / float(max(1, self._h))
        self._quad_fluid_splat.render(moderngl.TRIANGLES)
        target.swap()

    def _step_fluid(self) -> bool:
        if self._fluid_velocity is None or self._fluid_dye is None or self._fluid_pressure is None:
            return False
        if self._fluid_divergence_fbo is None or self._fluid_divergence_tex is None:
            return False
        if self._fluid_curl_fbo is None or self._fluid_curl_tex is None:
            return False

        ctx = self._ctx
        fw, fh = self._fluid_size
        old_viewport = ctx.viewport
        ctx.viewport = (0, 0, fw, fh)
        ctx.disable(moderngl.BLEND)
        texel = (1.0 / float(fw), 1.0 / float(fh))
        dt = 1.0 / 60.0

        self._prog_fluid_curl["uVelocity"] = 0
        self._prog_fluid_curl["uTexelSize"] = texel
        self._fluid_velocity.read_tex.use(0)
        self._fluid_curl_fbo.use()
        self._quad_fluid_curl.render(moderngl.TRIANGLES)

        self._prog_fluid_vorticity["uVelocity"] = 0
        self._prog_fluid_vorticity["uCurl"] = 1
        self._prog_fluid_vorticity["uTexelSize"] = texel
        self._prog_fluid_vorticity["uDt"] = dt
        self._prog_fluid_vorticity["uCurlStrength"] = 45.0
        self._fluid_velocity.read_tex.use(0)
        self._fluid_curl_tex.use(1)
        self._fluid_velocity.write_fbo.use()
        self._quad_fluid_vorticity.render(moderngl.TRIANGLES)
        self._fluid_velocity.swap()

        self._prog_fluid_div["uVelocity"] = 0
        self._prog_fluid_div["uTexelSize"] = texel
        self._fluid_velocity.read_tex.use(0)
        self._fluid_divergence_fbo.use()
        self._quad_fluid_div.render(moderngl.TRIANGLES)

        self._copy_fluid(self._fluid_pressure.read_tex, self._fluid_pressure, 0.80)
        for _ in range(20):
            self._prog_fluid_pressure["uPressure"] = 0
            self._prog_fluid_pressure["uDivergence"] = 1
            self._prog_fluid_pressure["uTexelSize"] = texel
            self._fluid_pressure.read_tex.use(0)
            self._fluid_divergence_tex.use(1)
            self._fluid_pressure.write_fbo.use()
            self._quad_fluid_pressure.render(moderngl.TRIANGLES)
            self._fluid_pressure.swap()

        self._prog_fluid_gradient["uPressure"] = 0
        self._prog_fluid_gradient["uVelocity"] = 1
        self._prog_fluid_gradient["uTexelSize"] = texel
        self._fluid_pressure.read_tex.use(0)
        self._fluid_velocity.read_tex.use(1)
        self._fluid_velocity.write_fbo.use()
        self._quad_fluid_gradient.render(moderngl.TRIANGLES)
        self._fluid_velocity.swap()

        self._prog_fluid_advect["uVelocity"] = 0
        self._prog_fluid_advect["uSource"] = 1
        self._prog_fluid_advect["uTexelSize"] = texel
        self._prog_fluid_advect["uDt"] = dt
        self._prog_fluid_advect["uDissipation"] = 0.992
        self._fluid_velocity.read_tex.use(0)
        self._fluid_velocity.read_tex.use(1)
        self._fluid_velocity.write_fbo.use()
        self._quad_fluid_advect.render(moderngl.TRIANGLES)
        self._fluid_velocity.swap()

        self._prog_fluid_advect["uVelocity"] = 0
        self._prog_fluid_advect["uSource"] = 1
        self._prog_fluid_advect["uTexelSize"] = texel
        self._prog_fluid_advect["uDt"] = dt
        self._prog_fluid_advect["uDissipation"] = 0.975
        self._fluid_velocity.read_tex.use(0)
        self._fluid_dye.read_tex.use(1)
        self._fluid_dye.write_fbo.use()
        self._quad_fluid_advect.render(moderngl.TRIANGLES)
        self._fluid_dye.swap()

        for nx, ny, vx, vy, cr, cg, cb, radius in self._fluid_splats:
            self._splat_fluid(self._fluid_velocity, (nx, ny), (vx, vy, 0.0), radius)
            self._splat_fluid(self._fluid_dye, (nx, ny), (cr, cg, cb), radius * 1.55)

        ctx.viewport = old_viewport
        return True

    def end_frame(
        self,
        bg_surf: pygame.Surface,
        bg_alpha: float,
        overlay_surf: pygame.Surface,
    ) -> None:
        """Render batched geometry, run bloom, composite to the screen.

        bg_surf     — background image (pygame.Surface, drawn with pygame)
        bg_alpha    — 0.0..1.0 opacity for the background layer
        overlay_surf — piano + UI text on a SRCALPHA pygame.Surface
        """
        ctx = self._ctx
        w, h = self._w, self._h
        bw = self._glow_fbo.width
        bh = self._glow_fbo.height
        bar_fmt  = "2f 2f 3f 3f 1f 2f"
        bar_attr = ("in_pos", "in_uv", "in_ctop", "in_cbot", "in_round", "in_size")
        prt_fmt  = "2f 2f 4f"
        prt_attr = ("in_pos", "in_uv", "in_color")

        # Helper: upload list → VBO, (re)create VAO if buffer grew
        def _upload(data, vbo_attr, vao_attr, prog, fmt, attrs):
            vbo_old, vao_old = vbo_attr[0], vao_attr[0]
            if not data:
                return vbo_old, vao_old, 0
            arr = np.array(data, dtype="f4")
            nb  = arr.nbytes
            if vbo_old is None or vbo_old.size < nb:
                if vbo_old:
                    vbo_old.release()
                vbo_new = ctx.buffer(arr.tobytes(), dynamic=True)
                vao_new = ctx.vertex_array(prog, [(vbo_new, fmt, *attrs)])
                return vbo_new, vao_new, len(arr)
            vbo_old.write(arr.tobytes())
            if vao_old is None:
                vao_old = ctx.vertex_array(prog, [(vbo_old, fmt, *attrs)])
            return vbo_old, vao_old, len(arr)

        self._bar_vbo,  self._bar_vao,  n_bar  = _upload(
            self._bar_verts,  [self._bar_vbo],  [self._bar_vao],
            self._prog_note, bar_fmt, bar_attr)
        self._glow_vbo, self._glow_vao, n_glow = _upload(
            self._glow_verts, [self._glow_vbo], [self._glow_vao],
            self._prog_glow, bar_fmt, bar_attr)
        self._part_vbo, self._part_vao, n_part = _upload(
            self._part_verts, [self._part_vbo], [self._part_vao],
            self._prog_part, prt_fmt, prt_attr)

        n_bar_verts  = n_bar  // self._BAR_FPV
        n_glow_verts = n_glow // self._BAR_FPV
        n_part_verts = n_part // self._PART_FPV
        has_scene_geometry = n_bar_verts > 0 or n_part_verts > 0
        fluid_active = self._step_fluid()

        # ── 1. Note bars → scene FBO ───────────────────────────────────
        # Explicit viewport on every pass: moderngl's fbo.use() sets ctx.viewport to
        # the FBO size, so without explicit resets the glow/blur half-res passes would
        # leave the viewport at (0,0,w/2,h/2) for the final screen composite.
        self._scene_fbo.use()
        ctx.viewport = (0, 0, w, h)
        ctx.clear(0.0, 0.0, 0.0, 0.0)
        if has_scene_geometry:
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA  # premultiplied alpha

        if n_bar_verts > 0:
            self._prog_note["uScreen"] = (float(w), float(h))
            self._bar_vao.render(moderngl.TRIANGLES, vertices=n_bar_verts)

        # Particles additively on top of note bars
        if n_part_verts > 0:
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            self._prog_part["uScreen"] = (float(w), float(h))
            self._part_vao.render(moderngl.TRIANGLES, vertices=n_part_verts)
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        # ── 2. Glow quads → glow FBO (half-res, additive) ─────────────
        self._glow_fbo.use()
        ctx.viewport = (0, 0, bw, bh)
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        ctx.blend_func = moderngl.ONE, moderngl.ONE

        if n_glow_verts > 0:
            self._prog_glow["uScreen"] = (float(w), float(h))
            self._glow_vao.render(moderngl.TRIANGLES, vertices=n_glow_verts)

        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        # ── 3. Bloom: 2× separable Gaussian blur (ping-pong) ──────────
        def _blur_pass(src_tex, src_fbo, dst_fbo, direction):
            dst_fbo.use()
            ctx.viewport = (0, 0, bw, bh)
            ctx.clear(0.0, 0.0, 0.0, 1.0)
            src_tex.use(0)
            self._prog_blur["uTex"] = 0
            self._prog_blur["uDir"] = direction
            self._quad_blur.render(moderngl.TRIANGLES)

        ctx.disable(moderngl.BLEND)
        # Pass 1
        _blur_pass(self._glow_tex, self._glow_fbo, self._blur_fbo, (1.0, 0.0))
        _blur_pass(self._blur_tex, self._blur_fbo, self._glow_fbo, (0.0, 1.0))
        # Pass 2 (wider bloom)
        _blur_pass(self._glow_tex, self._glow_fbo, self._blur_fbo, (1.0, 0.0))
        _blur_pass(self._blur_tex, self._blur_fbo, self._glow_fbo, (0.0, 1.0))
        # glow_fbo now contains the final blurred bloom

        # ── 4. Composite → default framebuffer ────────────────────────
        ctx.screen.use()
        ctx.viewport = (0, 0, w, h)
        ctx.clear(0.039, 0.039, 0.039, 1.0)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        # Background layer
        self._bg_tex = self._surf_to_tex(bg_surf, self._bg_tex)
        self._bg_tex.use(0)
        self._prog_blit["uTex"]   = 0
        self._prog_blit["uAlpha"] = float(bg_alpha)
        self._quad_blit.render(moderngl.TRIANGLES)

        # Scene + bloom composite (Reinhard + chromatic aberration)
        if has_scene_geometry or n_glow_verts > 0 or fluid_active:
            ctx.disable(moderngl.BLEND)
            self._scene_tex.use(0)
            self._glow_tex.use(1)
            if self._fluid_dye is not None:
                self._fluid_dye.read_tex.use(2)
            else:
                self._glow_tex.use(2)
            self._prog_comp["uScene"]    = 0
            self._prog_comp["uBloom"]    = 1
            self._prog_comp["uFluid"]    = 2
            self._prog_comp["uBloomStr"] = 1.8
            self._prog_comp["uCAShift"]  = 0.0015
            self._quad_comp.render(moderngl.TRIANGLES)

        # UI overlay (piano + text) — SRCALPHA surface on top
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self._ui_tex = self._surf_to_tex(overlay_surf, self._ui_tex)
        self._ui_tex.use(0)
        self._prog_blit["uTex"]   = 0
        self._prog_blit["uAlpha"] = 1.0
        self._quad_blit.render(moderngl.TRIANGLES)
