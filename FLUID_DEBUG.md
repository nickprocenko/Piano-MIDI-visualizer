# Fluid Rendering Bug Investigation

## Symptom
"The effect is being drawn off of the screen to the far right — I can see a faded edge rising up."

---

## What I verified (coordinate system is correct)

| Step | Value | Verdict |
|------|-------|---------|
| Piano layout width (`sw`) | `screen.get_size()[0]` = full display width | ✓ |
| GL renderer width (`self._w`) | `screen.get_size()[0]` = same display width | ✓ |
| Note x in pixels (`cx = trail["x"]`) | `rect.centerx` ∈ [0, sw] | ✓ |
| UV conversion | `nx = cx / self._w` ∈ [0, 1], clamped | ✓ |
| UV → screen mapping | composite samples `texture(uFluid, vUV)` 1:1 | ✓ |
| Y-flip | `ny = 1 - head_y / self._h` (pygame→GL) | ✓ |
| Viewport in `_step_fluid` | explicitly set `(0, 0, fw, fh)`, restored after | ✓ |
| Viewport in composite | explicitly set `(0, 0, w, h)` before `ctx.screen.use()` | ✓ |
| Texture wrap | `_DoubleFBO` sets `repeat_x = repeat_y = False` | ✓ |

**Conclusion: UV coordinates are mathematically correct. The center of every fluid splat is placed at the piano key's correct screen position.**

---

## Root causes of "faded edge at the right"

### 1. Edge attenuation (`edge_fade`) silences high notes
`_queue_fluid_splat` computes:
```python
h_margin = radius / aspect          # ≈ 0.040 / 1.78 ≈ 0.022 UV units
edge_fade = (1.0 - nx) / h_margin   # right-edge term
```
For **C8** (`nx ≈ 0.990`): `edge_fade = 0.010 / 0.022 ≈ 0.45` — color and velocity are cut to **45%**.  
For **B7** (`nx ≈ 0.975`): `edge_fade ≈ 1.14 → 1.0` — full brightness.

So the rightmost 2–3 keys get significantly dimmer fluid. The user is probably playing **upper-register notes** and seeing a dim, slow-rising blur near the right edge. This is the edge-fade working as intended, but the user perceives it as "off-screen."

### 2. Radius is ~7× too small compared to Dobryakov
Dobryakov's corrected radius ≈ **0.445** (SPLAT_RADIUS 0.25 × aspect 1.78).  
Our radius: **0.040–0.060**.  
Gaussian half-max x-extent: `sqrt(r * ln2) / aspect`
- Dobryakov: `sqrt(0.445 × 0.693) / 1.78 ≈ 0.31 / 1.78 ≈ 0.175 UV` (35% of screen width per side)
- Ours:      `sqrt(0.055 × 0.693) / 1.78 ≈ 0.195 / 1.78 ≈ 0.11 UV` (11% per side)

Our blobs are too small to blend across adjacent notes — they appear as isolated blobs rather than interconnected ink flows.

### 3. Color per-frame is too low for small radius
With the small radius, the peak intensity builds up correctly over time, but the Gaussian falls off so steeply that neighboring notes' dye never really merges.  
`cr = r * 0.06 * strength` at min strength → only `~0.01` per channel per frame.

### 4. Vorticity (45) is too strong for a slow-building dye field
With almost no initial dye, strong vorticity just creates numerical swirling noise before any meaningful ink forms.

---

## What to fix

| Parameter | Current | Target | Reason |
|-----------|---------|--------|--------|
| `uRadius` (dye) | 0.040–0.060 | 0.12–0.18 | Match Dobryakov's blob scale |
| `uRadius` (velocity) | same | same as dye | Keep consistent |
| Color multiplier (`cr`) | `0.06 * strength` | `0.04 * strength` | Slightly lower to avoid saturation with larger radius |
| `uCurlStrength` | 45 | 15–20 | Reduce noise before dye builds up |
| `vel_scale` | 280 | 120 | Velocity was strong enough; reduce with larger blobs |
| `upward` | 300 | 200 | Same reasoning |

### Optional: enable glow on note bars
`glow_on = False` is hardcoded — the note bars have no bloom. Setting:
```python
glow_on = glow_str > 0.0
```
would make the bars visually glow and confirm their position independently of the fluid.

### Why NOT a coordinate bug
Both note bars and fluid use `cx` → `nx = cx / self._w`. If bars are correctly positioned (which the vertex shader math confirms), fluid IS also at the correct position. The "far right" is almost certainly **correct placement of high-register notes** combined with edge-fade attenuation making them look faint.

---

## Files involved
- [`src/gl_renderer.py`](src/gl_renderer.py) — `_queue_fluid_splat` (line 656), `_FS_FLUID_SPLAT` (line 232), `_step_fluid` (line 915), `draw_trail` (line 695)
