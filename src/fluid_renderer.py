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

Shader source ported from nickprocenko/WebGL-Fluid-Simulation (MIT).
Improvements over the original port:
  - Neighbour UV varyings (vL/vR/vT/vB) pre-computed in a dedicated vertex
    shader so physics fragment shaders avoid per-pixel texel arithmetic.
  - Boundary-clamped divergence, pressure Jacobi, and gradient-subtract
    shaders that preserve correct Neumann boundary conditions at the edges.
  - Vorticity confinement with y-force inversion and velocity clamping to
    prevent numerical blow-up.
  - Advection uses the `result / (1 + dissipation * dt)` decay form so
    dissipation parameters behave consistently regardless of frame rate.
  - Pressure field is seeded each step with a CLEAR shader (multiply by a
    configurable pressure factor) rather than zeroed, preserving history.
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

# Simple vertex shader – used by advect, splat, clear, display.
# Only outputs vUv; no neighbour varyings needed.
_VERT_SIMPLE = """
#version 330 core
in vec2 in_vert;
out vec2 vUv;
void main() {
    vUv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

# Full vertex shader – used by divergence, curl, vorticity, pressure,
# gradient_subtract.  Pre-computes the four neighbour UVs so the fragment
# shaders never need to add/subtract texel offsets themselves.
_VERT_FULL = """
#version 330 core
in  vec2 in_vert;
out vec2 vUv;
out vec2 vL;
out vec2 vR;
out vec2 vT;
out vec2 vB;
uniform vec2 u_texelSize;
void main() {
    vUv = in_vert * 0.5 + 0.5;
    vL  = vUv - vec2(u_texelSize.x, 0.0);
    vR  = vUv + vec2(u_texelSize.x, 0.0);
    vT  = vUv + vec2(0.0, u_texelSize.y);
    vB  = vUv - vec2(0.0, u_texelSize.y);
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

# Advection – bilinear result / (1 + dissipation * dt) decay.
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
    vec2 coord = vUv - u_dt * texture(u_velocity, vUv).xy * u_texel;
    vec4 result = texture(u_quantity, coord);
    float decay = 1.0 + u_dissipation * u_dt;
    fragColor = result / decay;
}
"""

# Divergence – boundary-clamped (Neumann: zero-normal-velocity at walls).
_DIVERGENCE = """
#version 330 core
uniform sampler2D u_velocity;
in  vec2 vUv;
in  vec2 vL;
in  vec2 vR;
in  vec2 vT;
in  vec2 vB;
out vec4 fragColor;
void main() {
    float L = texture(u_velocity, vL).x;
    float R = texture(u_velocity, vR).x;
    float T = texture(u_velocity, vT).y;
    float B = texture(u_velocity, vB).y;
    vec2  C = texture(u_velocity, vUv).xy;
    if (vL.x < 0.0) { L = -C.x; }
    if (vR.x > 1.0) { R = -C.x; }
    if (vT.y > 1.0) { T = -C.y; }
    if (vB.y < 0.0) { B = -C.y; }
    fragColor = vec4(0.5 * (R - L + T - B), 0.0, 0.0, 1.0);
}
"""

# Curl (scalar vorticity).
_CURL = """
#version 330 core
uniform sampler2D u_velocity;
in  vec2 vUv;
in  vec2 vL;
in  vec2 vR;
in  vec2 vT;
in  vec2 vB;
out vec4 fragColor;
void main() {
    float L = texture(u_velocity, vL).y;
    float R = texture(u_velocity, vR).y;
    float T = texture(u_velocity, vT).x;
    float B = texture(u_velocity, vB).x;
    fragColor = vec4(0.5 * (R - L - T + B), 0.0, 0.0, 1.0);
}
"""

# Vorticity confinement – y-force inverted to match WebGL orientation;
# velocity result clamped to [-1000, 1000] to prevent blow-up.
_VORTICITY = """
#version 330 core
uniform sampler2D u_velocity;
uniform sampler2D u_curl_tex;
uniform float     u_dt;
uniform float     u_curl_strength;
in  vec2 vUv;
in  vec2 vL;
in  vec2 vR;
in  vec2 vT;
in  vec2 vB;
out vec4 fragColor;
void main() {
    float L = texture(u_curl_tex, vL).x;
    float R = texture(u_curl_tex, vR).x;
    float T = texture(u_curl_tex, vT).x;
    float B = texture(u_curl_tex, vB).x;
    float C = texture(u_curl_tex, vUv).x;
    vec2 force = 0.5 * vec2(abs(T) - abs(B), abs(R) - abs(L));
    force /= length(force) + 0.0001;
    force *= u_curl_strength * C;
    force.y *= -1.0;
    vec2 vel = texture(u_velocity, vUv).xy + force * u_dt;
    vel = clamp(vel, -1000.0, 1000.0);
    fragColor = vec4(vel, 0.0, 1.0);
}
"""

# Clear – multiplies existing texture by a scalar (used to seed pressure).
_CLEAR = """
#version 330 core
uniform sampler2D u_texture;
uniform float     u_value;
in  vec2 vUv;
out vec4 fragColor;
void main() {
    fragColor = u_value * texture(u_texture, vUv);
}
"""

# Pressure Jacobi – boundary-clamped.
_PRESSURE = """
#version 330 core
uniform sampler2D u_pressure;
uniform sampler2D u_divergence;
in  vec2 vUv;
in  vec2 vL;
in  vec2 vR;
in  vec2 vT;
in  vec2 vB;
out vec4 fragColor;
void main() {
    float pL  = texture(u_pressure, vL).x;
    float pR  = texture(u_pressure, vR).x;
    float pT  = texture(u_pressure, vT).x;
    float pB  = texture(u_pressure, vB).x;
    float pC  = texture(u_pressure, vUv).x;
    if (vL.x < 0.0) { pL = pC; }
    if (vR.x > 1.0) { pR = pC; }
    if (vT.y > 1.0) { pT = pC; }
    if (vB.y < 0.0) { pB = pC; }
    float div = texture(u_divergence, vUv).x;
    fragColor = vec4((pL + pR + pB + pT - div) * 0.25, 0.0, 0.0, 1.0);
}
"""

# Gradient subtract – boundary-clamped, full-stencil (no 0.5 factor).
_GRADIENT_SUBTRACT = """
#version 330 core
uniform sampler2D u_pressure;
uniform sampler2D u_velocity;
in  vec2 vUv;
in  vec2 vL;
in  vec2 vR;
in  vec2 vT;
in  vec2 vB;
out vec4 fragColor;
void main() {
    float pL = texture(u_pressure, vL).x;
    float pR = texture(u_pressure, vR).x;
    float pT = texture(u_pressure, vT).x;
    float pB = texture(u_pressure, vB).x;
    float pC = texture(u_pressure, vUv).x;
    if (vL.x < 0.0) { pL = pC; }
    if (vR.x > 1.0) { pR = pC; }
    if (vT.y > 1.0) { pT = pC; }
    if (vB.y < 0.0) { pB = pC; }
    vec2 vel = texture(u_velocity, vUv).xy - vec2(pR - pL, pT - pB);
    fragColor = vec4(vel, 0.0, 1.0);
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
# Defaults (can be overridden via FluidRenderer constructor)
# ---------------------------------------------------------------------------

_PRESSURE_ITERS = 20

# Vorticity confinement coefficient (0 = off, higher = tighter swirls).
_DEFAULT_CURL = 30.0

# Advection uses decay = 1 / (1 + dissipation * dt).
# At dt ≈ 0.0167 s (60 fps):
#   vel_diss=0.7  → per-frame retention ≈ 0.988 (1.2 % loss/frame)
#   dye_diss=2.2  → per-frame retention ≈ 0.966 (3.4 % loss/frame)
# These match the defaults in nickprocenko/WebGL-Fluid-Simulation settings.js.
_DEFAULT_VEL_DISS = 0.7
_DEFAULT_DYE_DISS = 2.2

# How much of the previous pressure field to retain each step (0–1).
# 0.8 = 80 % retained → converges faster while preserving pressure history.
_DEFAULT_PRESSURE = 0.8


# ---------------------------------------------------------------------------
# FluidRenderer
# ---------------------------------------------------------------------------

class FluidRenderer:
    """Manages a headless OpenGL fluid simulation.

    Exports frames as pygame.Surface objects via get_surface().  All methods
    are silent no-ops when the OpenGL context is unavailable.

    Parameters
    ----------
    screen_width / screen_height
        Dimensions of the pygame display surface.
    sim_scale
        Fraction of the screen size used for the simulation grid (0.5 = half).
    curl_strength
        Vorticity confinement coefficient (higher = more swirling).
    vel_dissipation
        Velocity decay rate (higher = velocity fades faster).
    dye_dissipation
        Dye/colour decay rate (higher = colour fades faster).
    pressure
        Pressure field retention factor per step (0 = reset each frame,
        1 = fully retained).
    """

    def __init__(
        self,
        screen_width: int,
        screen_height: int,
        sim_scale: float = 0.5,
        curl_strength: float = _DEFAULT_CURL,
        vel_dissipation: float = _DEFAULT_VEL_DISS,
        dye_dissipation: float = _DEFAULT_DYE_DISS,
        pressure: float = _DEFAULT_PRESSURE,
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
        self._texel  = (1.0 / self._sim_w, 1.0 / self._sim_h)

        # Configurable simulation parameters
        self._curl_strength  = float(curl_strength)
        self._vel_dissipation = float(vel_dissipation)
        self._dye_dissipation = float(dye_dissipation)
        self._pressure       = float(pressure)

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

    def update_config(
        self,
        curl_strength: Optional[float] = None,
        vel_dissipation: Optional[float] = None,
        dye_dissipation: Optional[float] = None,
        pressure: Optional[float] = None,
    ) -> None:
        """Update one or more simulation parameters at runtime."""
        if curl_strength   is not None: self._curl_strength   = float(curl_strength)
        if vel_dissipation is not None: self._vel_dissipation = float(vel_dissipation)
        if dye_dissipation is not None: self._dye_dissipation = float(dye_dissipation)
        if pressure        is not None: self._pressure        = float(pressure)

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

        # Set neighbour-UV texelSize on all full-vertex-shader programs once.
        for name in self._full_prog_names:
            self._progs[name]["u_texelSize"].value = tx

        # 1. Advect velocity
        self._advect("vel", tx, dt, self._vel_dissipation)
        # 2. Curl
        self._curl()
        # 3. Vorticity confinement
        self._vorticity(dt)
        # 4. Divergence
        self._divergence()
        # 5. Seed pressure via CLEAR (preserves history weighted by pressure factor)
        self._clear_pressure()
        # 6. Jacobi pressure iterations
        for _ in range(_PRESSURE_ITERS):
            self._pressure_jacobi()
        # 7. Gradient subtraction
        self._gradient_subtract()
        # 8. Advect dye
        self._advect("dye", tx, dt, self._dye_dissipation)

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
        prog["u_dye"]           = 0
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
        # Programs that only need vUv (simple vertex shader)
        simple = {
            "advect":  ctx.program(vertex_shader=_VERT_SIMPLE, fragment_shader=_ADVECT),
            "clear":   ctx.program(vertex_shader=_VERT_SIMPLE, fragment_shader=_CLEAR),
            "splat":   ctx.program(vertex_shader=_VERT_SIMPLE, fragment_shader=_SPLAT),
            "display": ctx.program(vertex_shader=_VERT_SIMPLE, fragment_shader=_DISPLAY),
        }
        # Programs that need neighbour varyings (full vertex shader)
        full = {
            "divergence":        ctx.program(vertex_shader=_VERT_FULL, fragment_shader=_DIVERGENCE),
            "curl":              ctx.program(vertex_shader=_VERT_FULL, fragment_shader=_CURL),
            "vorticity":         ctx.program(vertex_shader=_VERT_FULL, fragment_shader=_VORTICITY),
            "pressure":          ctx.program(vertex_shader=_VERT_FULL, fragment_shader=_PRESSURE),
            "gradient_subtract": ctx.program(vertex_shader=_VERT_FULL, fragment_shader=_GRADIENT_SUBTRACT),
        }
        self._progs = {**simple, **full}
        self._full_prog_names = set(full.keys())

    def _build_geometry(self) -> None:
        verts = np.array(
            [-1.0, -1.0,  1.0, -1.0, -1.0,  1.0,  1.0,  1.0],
            dtype=np.float32,
        )
        vbo = self._ctx.buffer(verts.tobytes())
        # One VAO per program so each binds to the correct attribute location.
        self._vaos = {
            name: self._ctx.simple_vertex_array(prog, vbo, "in_vert")
            for name, prog in self._progs.items()
        }

    def _make_tex(self, components: int, dtype: str = "f4") -> object:
        tex = self._ctx.texture(
            (self._sim_w, self._sim_h), components, dtype=dtype
        )
        tex.filter   = (moderngl.LINEAR, moderngl.LINEAR)
        tex.repeat_x = False
        tex.repeat_y = False
        return tex

    def _build_textures(self) -> None:
        self._textures = {
            "vel":     [self._make_tex(2), self._make_tex(2)],  # RG32F velocity
            "pres":    [self._make_tex(1), self._make_tex(1)],  # R32F  pressure
            "div":      self._make_tex(1),                       # R32F  divergence scratch
            "curl":     self._make_tex(1),                       # R32F  curl scratch
            "dye":     [self._make_tex(4), self._make_tex(4)],  # RGBA32F dye
            "display":  self._make_tex(4, dtype="u1"),           # RGBA8  readback
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
        self._div_fbo     = ctx.framebuffer(color_attachments=[t["div"]])
        self._curl_fbo    = ctx.framebuffer(color_attachments=[t["curl"]])
        self._dye_fbos    = [
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
        prog["u_velocity"]          = 0
        prog["u_quantity"]          = 1
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

    def _curl(self) -> None:
        prog = self._progs["curl"]
        self._curl_fbo.use()
        prog["u_velocity"] = 0
        self._textures["vel"][self._vel_r].use(location=0)
        self._vaos["curl"].render(moderngl.TRIANGLE_STRIP)

    def _vorticity(self, dt: float) -> None:
        prog = self._progs["vorticity"]
        self._vel_fbos[self._vel_w].use()
        prog["u_velocity"]           = 0
        prog["u_curl_tex"]           = 1
        self._textures["vel"][self._vel_r].use(location=0)
        self._textures["curl"].use(location=1)
        prog["u_dt"].value           = dt
        prog["u_curl_strength"].value = self._curl_strength
        self._vaos["vorticity"].render(moderngl.TRIANGLE_STRIP)
        self._vel_r, self._vel_w = self._vel_w, self._vel_r

    def _divergence(self) -> None:
        prog = self._progs["divergence"]
        self._div_fbo.use()
        prog["u_velocity"] = 0
        self._textures["vel"][self._vel_r].use(location=0)
        self._vaos["divergence"].render(moderngl.TRIANGLE_STRIP)

    def _clear_pressure(self) -> None:
        """Seed the pressure buffer: multiply existing values by _pressure factor."""
        prog = self._progs["clear"]
        self._pres_fbos[self._pres_w].use()
        prog["u_texture"]    = 0
        prog["u_value"].value = self._pressure
        self._textures["pres"][self._pres_r].use(location=0)
        self._vaos["clear"].render(moderngl.TRIANGLE_STRIP)
        self._pres_r, self._pres_w = self._pres_w, self._pres_r

    def _pressure_jacobi(self) -> None:
        prog = self._progs["pressure"]
        self._pres_fbos[self._pres_w].use()
        prog["u_pressure"]   = 0
        prog["u_divergence"] = 1
        self._textures["pres"][self._pres_r].use(location=0)
        self._textures["div"].use(location=1)
        self._vaos["pressure"].render(moderngl.TRIANGLE_STRIP)
        self._pres_r, self._pres_w = self._pres_w, self._pres_r

    def _gradient_subtract(self) -> None:
        prog = self._progs["gradient_subtract"]
        self._vel_fbos[self._vel_w].use()
        prog["u_pressure"] = 0
        prog["u_velocity"] = 1
        self._textures["pres"][self._pres_r].use(location=0)
        self._textures["vel"][self._vel_r].use(location=1)
        self._vaos["gradient_subtract"].render(moderngl.TRIANGLE_STRIP)
        self._vel_r, self._vel_w = self._vel_w, self._vel_r
