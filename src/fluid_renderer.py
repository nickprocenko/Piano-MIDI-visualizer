"""GPU-accelerated Navier-Stokes fluid simulation via moderngl.

Renders an ink/plasma fluid field that rises from active note positions,
creating the luminous fluid-aura effect seen in high-end piano visualizers.

Architecture
------------
A standalone moderngl context (headless, no extra window) runs the full
simulation pipeline in ping-pong framebuffers at half screen resolution.
Each frame the result is read back as RGBA8 pixels and returned as a
pygame.Surface for compositing with BLEND_RGBA_ADD behind the note trails.

If moderngl is unavailable or OpenGL 3.3 cannot be initialised, every
public method is a silent no-op and get_surface() returns None, so the
rest of the app continues unchanged.

Shader source ported from PavelDoGreat/WebGL-Fluid-Simulation (MIT).
GLSL ES 3.0 → GLSL 3.30 core changes applied:
  - removed all `precision` qualifiers
  - texture2D → texture
  - varying/attribute → in/out
  - gl_FragColor → explicit out vec4
  - #version 300 es → #version 330 core
"""

from __future__ import annotations

from typing import Optional

try:
    import moderngl
    import numpy as np
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shader source constants
# ---------------------------------------------------------------------------

_VERT = """
#version 330 core
in vec2 in_vert;
out vec2 vUv;
void main() {
    vUv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

_ADVECT = """
#version 330 core
uniform sampler2D u_velocity;
uniform sampler2D u_quantity;
uniform vec2      u_texel;
uniform float     u_dt;
uniform float     u_dissipation;
in  vec2 vUv;
out vec4 fragColor;
void main() {
    vec2 vel = texture(u_velocity, vUv).xy;
    vec2 pos = vUv - u_dt * vel * u_texel;
    pos = clamp(pos, u_texel, 1.0 - u_texel);
    fragColor = u_dissipation * texture(u_quantity, pos);
}
"""

_DIVERGENCE = """
#version 330 core
uniform sampler2D u_velocity;
uniform vec2      u_texel;
in  vec2 vUv;
out vec4 fragColor;
void main() {
    float L = texture(u_velocity, vUv - vec2(u_texel.x, 0.0)).x;
    float R = texture(u_velocity, vUv + vec2(u_texel.x, 0.0)).x;
    float B = texture(u_velocity, vUv - vec2(0.0, u_texel.y)).y;
    float T = texture(u_velocity, vUv + vec2(0.0, u_texel.y)).y;
    fragColor = vec4(0.5 * (R - L + T - B), 0.0, 0.0, 1.0);
}
"""

_CURL = """
#version 330 core
uniform sampler2D u_velocity;
uniform vec2      u_texel;
in  vec2 vUv;
out vec4 fragColor;
void main() {
    float L = texture(u_velocity, vUv - vec2(u_texel.x, 0.0)).y;
    float R = texture(u_velocity, vUv + vec2(u_texel.x, 0.0)).y;
    float B = texture(u_velocity, vUv - vec2(0.0, u_texel.y)).x;
    float T = texture(u_velocity, vUv + vec2(0.0, u_texel.y)).x;
    fragColor = vec4(0.5 * (R - L - (T - B)), 0.0, 0.0, 1.0);
}
"""

_VORTICITY = """
#version 330 core
uniform sampler2D u_velocity;
uniform sampler2D u_curl_tex;
uniform vec2      u_texel;
uniform float     u_dt;
uniform float     u_curl_strength;
in  vec2 vUv;
out vec4 fragColor;
void main() {
    float L = texture(u_curl_tex, vUv - vec2(u_texel.x, 0.0)).x;
    float R = texture(u_curl_tex, vUv + vec2(u_texel.x, 0.0)).x;
    float B = texture(u_curl_tex, vUv - vec2(0.0, u_texel.y)).x;
    float T = texture(u_curl_tex, vUv + vec2(0.0, u_texel.y)).x;
    float c = texture(u_curl_tex, vUv).x;
    vec2 force = 0.5 * vec2(abs(T) - abs(B), abs(R) - abs(L));
    float len = length(force) + 0.0001;
    force = (force / len) * u_curl_strength * c;
    vec2 vel = texture(u_velocity, vUv).xy;
    fragColor = vec4(vel + force * u_dt, 0.0, 1.0);
}
"""

_PRESSURE = """
#version 330 core
uniform sampler2D u_pressure;
uniform sampler2D u_divergence;
uniform vec2      u_texel;
in  vec2 vUv;
out vec4 fragColor;
void main() {
    float L = texture(u_pressure, vUv - vec2(u_texel.x, 0.0)).x;
    float R = texture(u_pressure, vUv + vec2(u_texel.x, 0.0)).x;
    float B = texture(u_pressure, vUv - vec2(0.0, u_texel.y)).x;
    float T = texture(u_pressure, vUv + vec2(0.0, u_texel.y)).x;
    float div = texture(u_divergence, vUv).x;
    fragColor = vec4((L + R + B + T - div) * 0.25, 0.0, 0.0, 1.0);
}
"""

_GRADIENT_SUBTRACT = """
#version 330 core
uniform sampler2D u_pressure;
uniform sampler2D u_velocity;
uniform vec2      u_texel;
in  vec2 vUv;
out vec4 fragColor;
void main() {
    float L = texture(u_pressure, vUv - vec2(u_texel.x, 0.0)).x;
    float R = texture(u_pressure, vUv + vec2(u_texel.x, 0.0)).x;
    float B = texture(u_pressure, vUv - vec2(0.0, u_texel.y)).x;
    float T = texture(u_pressure, vUv + vec2(0.0, u_texel.y)).x;
    vec2 vel = texture(u_velocity, vUv).xy;
    fragColor = vec4(vel - 0.5 * vec2(R - L, T - B), 0.0, 1.0);
}
"""

_SPLAT = """
#version 330 core
uniform sampler2D u_target;
uniform vec2      u_point;
uniform vec3      u_color;
uniform float     u_radius;
uniform float     u_aspect;
in  vec2 vUv;
out vec4 fragColor;
void main() {
    vec2 p = vUv - u_point;
    p.x *= u_aspect;
    float splat = exp(-dot(p, p) / (u_radius * u_radius));
    vec3 base = texture(u_target, vUv).rgb;
    fragColor = vec4(base + splat * u_color, 1.0);
}
"""

_DISPLAY = """
#version 330 core
uniform sampler2D u_dye;
uniform float     u_intensity;
in  vec2 vUv;
out vec4 fragColor;
void main() {
    vec3 col = texture(u_dye, vUv).rgb * u_intensity;
    // Reinhard tonemap + gamma so bright splats don't hard-clip
    col = col / (col + vec3(0.5));
    col = pow(max(col, vec3(0.0)), vec3(1.0 / 2.2));
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    float alpha = clamp(lum * 2.0, 0.0, 1.0);
    fragColor = vec4(col, alpha);
}
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PRESSURE_ITERS = 20
_CURL_STRENGTH  = 28.0
_VEL_DISSIPATION = 0.98
_DYE_DISSIPATION = 0.987


# ---------------------------------------------------------------------------
# FluidRenderer
# ---------------------------------------------------------------------------

class FluidRenderer:
    """Manages a headless OpenGL fluid simulation.

    Exports frames as pygame.Surface objects via get_surface().  All methods
    are silent no-ops when the OpenGL context is unavailable.
    """

    def __init__(
        self,
        screen_width: int,
        screen_height: int,
        sim_scale: float = 0.5,
    ) -> None:
        self._enabled = False
        self._cached_surf: Optional[object] = None  # pygame.Surface | None

        if not _DEPS_AVAILABLE:
            return

        self._sw = screen_width
        self._sh = screen_height
        self._sim_w = max(2, int(screen_width  * sim_scale))
        self._sim_h = max(2, int(screen_height * sim_scale))
        self._aspect = self._sim_w / float(self._sim_h)
        self._texel   = (1.0 / self._sim_w, 1.0 / self._sim_h)

        try:
            self._ctx = moderngl.create_standalone_context(require=330)
        except Exception:
            return

        try:
            self._build_programs()
            self._build_geometry()
            self._build_textures()
            self._build_fbos()
        except Exception:
            try:
                self._ctx.release()
            except Exception:
                pass
            return

        self._enabled = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._enabled

    def add_splat(
        self,
        norm_x: float,
        norm_y: float,
        vel_x: float,
        vel_y: float,
        r: float,
        g: float,
        b: float,
        radius: float = 0.012,
    ) -> None:
        """Inject a Gaussian blob of velocity + dye at a normalised position.

        norm_x / norm_y are in [0, 1] with (0,0) at top-left (pygame coords).
        They are flipped to OpenGL bottom-left convention internally.
        """
        if not self._enabled:
            return

        gl_y = 1.0 - norm_y  # flip y for OpenGL

        prog  = self._progs["splat"]
        point = (norm_x, gl_y)

        # --- splat dye ---
        self._dye_fbos[self._dye_w].use()
        self._ctx.viewport = (0, 0, self._sim_w, self._sim_h)
        prog["u_target"]  = 0
        self._textures["dye"][self._dye_r].use(location=0)
        prog["u_point"].value   = point
        prog["u_color"].value   = (r * 8.0, g * 8.0, b * 8.0)
        prog["u_radius"].value  = radius
        prog["u_aspect"].value  = self._aspect
        self._vaos["splat"].render(moderngl.TRIANGLE_STRIP)
        self._dye_r, self._dye_w = self._dye_w, self._dye_r

        # --- splat velocity ---
        self._vel_fbos[self._vel_w].use()
        prog["u_target"] = 0
        self._textures["vel"][self._vel_r].use(location=0)
        prog["u_point"].value  = point
        prog["u_color"].value  = (vel_x * 0.00015, -vel_y * 0.00015, 0.0)
        prog["u_radius"].value = radius * 2.0
        self._vaos["splat"].render(moderngl.TRIANGLE_STRIP)
        self._vel_r, self._vel_w = self._vel_w, self._vel_r

    def step(self, dt_sec: float) -> None:
        """Advance one simulation frame."""
        if not self._enabled:
            return

        dt = min(dt_sec, 0.033)
        self._ctx.viewport = (0, 0, self._sim_w, self._sim_h)
        tx = self._texel

        # 1. Advect velocity
        self._advect("vel", tx, dt, _VEL_DISSIPATION)
        # 2. Curl
        self._curl(tx)
        # 3. Vorticity confinement
        self._vorticity(tx, dt)
        # 4. Divergence
        self._divergence(tx)
        # 5. Zero-init pressure for Jacobi stability
        zero = b"\x00" * (self._sim_w * self._sim_h * 4)
        self._textures["pres"][0].write(zero)
        self._textures["pres"][1].write(zero)
        self._pres_r, self._pres_w = 0, 1
        # 6. Jacobi pressure iterations
        for _ in range(_PRESSURE_ITERS):
            self._pressure_jacobi(tx)
        # 7. Gradient subtraction
        self._gradient_subtract(tx)
        # 8. Advect dye
        self._advect("dye", tx, dt, _DYE_DISSIPATION)

    def get_surface(self) -> Optional[object]:
        """Render dye field and return a pygame.Surface (RGBA, sim resolution).

        Returns None when unavailable.  Caller should upscale to screen size
        with pygame.transform.smoothscale before blitting.
        """
        if not self._enabled:
            return None

        import pygame  # imported lazily to avoid circular import at module level

        self._ctx.viewport = (0, 0, self._sim_w, self._sim_h)
        prog = self._progs["display"]
        self._display_fbo.use()
        prog["u_dye"]       = 0
        prog["u_intensity"].value = 1.0
        self._textures["dye"][self._dye_r].use(location=0)
        self._vaos["display"].render(moderngl.TRIANGLE_STRIP)

        raw = self._display_fbo.read(components=4, dtype="u1")
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(
            (self._sim_h, self._sim_w, 4)
        )
        arr = np.ascontiguousarray(np.flipud(arr))
        surf = pygame.image.frombuffer(
            arr.tobytes(), (self._sim_w, self._sim_h), "RGBA"
        )
        self._cached_surf = surf.convert_alpha()
        return self._cached_surf

    def destroy(self) -> None:
        """Release all OpenGL resources."""
        if not self._enabled:
            return
        self._enabled = False
        try:
            self._ctx.release()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Private: build
    # ------------------------------------------------------------------

    def _build_programs(self) -> None:
        ctx = self._ctx
        self._progs = {
            "advect":    ctx.program(vertex_shader=_VERT, fragment_shader=_ADVECT),
            "divergence":ctx.program(vertex_shader=_VERT, fragment_shader=_DIVERGENCE),
            "curl":      ctx.program(vertex_shader=_VERT, fragment_shader=_CURL),
            "vorticity": ctx.program(vertex_shader=_VERT, fragment_shader=_VORTICITY),
            "pressure":  ctx.program(vertex_shader=_VERT, fragment_shader=_PRESSURE),
            "gradient_subtract": ctx.program(
                vertex_shader=_VERT, fragment_shader=_GRADIENT_SUBTRACT
            ),
            "splat":   ctx.program(vertex_shader=_VERT, fragment_shader=_SPLAT),
            "display": ctx.program(vertex_shader=_VERT, fragment_shader=_DISPLAY),
        }

    def _build_geometry(self) -> None:
        import numpy as _np
        verts = _np.array(
            [-1.0, -1.0,  1.0, -1.0, -1.0,  1.0,  1.0,  1.0],
            dtype=_np.float32,
        )
        vbo = self._ctx.buffer(verts.tobytes())
        # One VAO per program so each is bound to the correct attribute location
        self._vaos = {
            name: self._ctx.simple_vertex_array(prog, vbo, "in_vert")
            for name, prog in self._progs.items()
        }

    def _make_tex(self, components: int, dtype: str = "f4") -> object:
        tex = self._ctx.texture(
            (self._sim_w, self._sim_h), components, dtype=dtype
        )
        tex.filter    = (moderngl.LINEAR, moderngl.LINEAR)
        tex.repeat_x  = False
        tex.repeat_y  = False
        return tex

    def _build_textures(self) -> None:
        self._textures = {
            "vel":  [self._make_tex(2), self._make_tex(2)],   # RG32F velocity
            "pres": [self._make_tex(1), self._make_tex(1)],   # R32F pressure
            "div":   self._make_tex(1),                        # R32F divergence (scratch)
            "curl":  self._make_tex(1),                        # R32F curl (scratch)
            "dye":  [self._make_tex(4), self._make_tex(4)],   # RGBA32F dye
            "display": self._make_tex(4, dtype="u1"),          # RGBA8 for readback
        }
        self._vel_r,  self._vel_w  = 0, 1
        self._pres_r, self._pres_w = 0, 1
        self._dye_r,  self._dye_w  = 0, 1

    def _build_fbos(self) -> None:
        ctx = self._ctx
        t   = self._textures
        self._vel_fbos  = [
            ctx.framebuffer(color_attachments=[t["vel"][0]]),
            ctx.framebuffer(color_attachments=[t["vel"][1]]),
        ]
        self._pres_fbos = [
            ctx.framebuffer(color_attachments=[t["pres"][0]]),
            ctx.framebuffer(color_attachments=[t["pres"][1]]),
        ]
        self._div_fbo   = ctx.framebuffer(color_attachments=[t["div"]])
        self._curl_fbo  = ctx.framebuffer(color_attachments=[t["curl"]])
        self._dye_fbos  = [
            ctx.framebuffer(color_attachments=[t["dye"][0]]),
            ctx.framebuffer(color_attachments=[t["dye"][1]]),
        ]
        self._display_fbo = ctx.framebuffer(color_attachments=[t["display"]])

    # ------------------------------------------------------------------
    # Private: simulation passes
    # ------------------------------------------------------------------

    def _advect(self, field: str, texel: tuple, dt: float, diss: float) -> None:
        prog = self._progs["advect"]
        if field == "vel":
            write_fbo = self._vel_fbos[self._vel_w]
            qty_tex   = self._textures["vel"][self._vel_r]
        else:
            write_fbo = self._dye_fbos[self._dye_w]
            qty_tex   = self._textures["dye"][self._dye_r]

        write_fbo.use()
        prog["u_velocity"]    = 0
        prog["u_quantity"]    = 1
        self._textures["vel"][self._vel_r].use(location=0)
        qty_tex.use(location=1)
        prog["u_texel"].value       = texel
        prog["u_dt"].value          = dt
        prog["u_dissipation"].value = diss
        self._vaos["advect"].render(moderngl.TRIANGLE_STRIP)

        if field == "vel":
            self._vel_r, self._vel_w = self._vel_w, self._vel_r
        else:
            self._dye_r, self._dye_w = self._dye_w, self._dye_r

    def _curl(self, texel: tuple) -> None:
        prog = self._progs["curl"]
        self._curl_fbo.use()
        prog["u_velocity"] = 0
        self._textures["vel"][self._vel_r].use(location=0)
        prog["u_texel"].value = texel
        self._vaos["curl"].render(moderngl.TRIANGLE_STRIP)

    def _vorticity(self, texel: tuple, dt: float) -> None:
        prog = self._progs["vorticity"]
        self._vel_fbos[self._vel_w].use()
        prog["u_velocity"]      = 0
        prog["u_curl_tex"]      = 1
        self._textures["vel"][self._vel_r].use(location=0)
        self._textures["curl"].use(location=1)
        prog["u_texel"].value        = texel
        prog["u_dt"].value           = dt
        prog["u_curl_strength"].value = _CURL_STRENGTH
        self._vaos["vorticity"].render(moderngl.TRIANGLE_STRIP)
        self._vel_r, self._vel_w = self._vel_w, self._vel_r

    def _divergence(self, texel: tuple) -> None:
        prog = self._progs["divergence"]
        self._div_fbo.use()
        prog["u_velocity"] = 0
        self._textures["vel"][self._vel_r].use(location=0)
        prog["u_texel"].value = texel
        self._vaos["divergence"].render(moderngl.TRIANGLE_STRIP)

    def _pressure_jacobi(self, texel: tuple) -> None:
        prog = self._progs["pressure"]
        self._pres_fbos[self._pres_w].use()
        prog["u_pressure"]   = 0
        prog["u_divergence"] = 1
        self._textures["pres"][self._pres_r].use(location=0)
        self._textures["div"].use(location=1)
        prog["u_texel"].value = texel
        self._vaos["pressure"].render(moderngl.TRIANGLE_STRIP)
        self._pres_r, self._pres_w = self._pres_w, self._pres_r

    def _gradient_subtract(self, texel: tuple) -> None:
        prog = self._progs["gradient_subtract"]
        self._vel_fbos[self._vel_w].use()
        prog["u_pressure"] = 0
        prog["u_velocity"] = 1
        self._textures["pres"][self._pres_r].use(location=0)
        self._textures["vel"][self._vel_r].use(location=1)
        prog["u_texel"].value = texel
        self._vaos["gradient_subtract"].render(moderngl.TRIANGLE_STRIP)
        self._vel_r, self._vel_w = self._vel_w, self._vel_r
