# AI Prompt — Generate a Preset Save File

Copy everything below this line and paste it into any AI (Claude, ChatGPT, Gemini, etc.), then add your request at the bottom.

---

You are generating a JSON preset file for a Piano MIDI Visualiser web app.

## How presets work

The file is loaded via the **Import Settings** button (top-right menu in the app). It replaces the current visual configuration. MIDI files are not included in presets — the user loads those separately.

The format is a plain JSON object. Unknown keys are ignored; missing keys fall back to defaults. You only need to include the keys you want to change.

## Full schema with defaults

```json
{
  "note_style": {
    "speed_px_per_sec": 420,
    "width_px": 12,
    "edge_roundness_px": 4,
    "outer_edge_width_px": 2,
    "inner_blend_percent": 35,

    "color_r": 0,
    "color_g": 230,
    "color_b": 230,
    "interior_r": 120,
    "interior_g": 255,
    "interior_b": 255,

    "glow_strength_percent": 80,
    "highlight_strength_percent": 70,
    "spark_amount_percent": 100,
    "smoke_amount_percent": 100,
    "decay_speed": 80,
    "decay_value": 20,

    "effect_glow_enabled": 1,
    "effect_highlight_enabled": 1,
    "effect_sparks_enabled": 1,
    "effect_smoke_enabled": 1,
    "effect_press_smoke_enabled": 0,
    "effect_moon_dust_enabled": 0,
    "moon_dust_amount_percent": 100,
    "moon_dust_opacity_percent": 100,
    "effect_steam_smoke_enabled": 0,
    "effect_halo_pulse_enabled": 0,

    "effect_fluid_enabled": 0,
    "fluid_intensity": 80,
    "fluid_curl": 30,
    "fluid_density_dissipation": 15,
    "fluid_velocity_dissipation": 7,
    "fluid_pressure": 80,
    "fluid_splat_size": 20,
    "fluid_opacity": 80,
    "fluid_color_strength": 100,
    "fluid_own_color": 0,
    "fluid_own_r": 0,
    "fluid_own_g": 230,
    "fluid_own_b": 230,

    "color_mode": "solid",
    "note_colors": null,
    "user_script": ""
  },
  "keyboard_style": {
    "height_percent": 18,
    "brightness": 100,
    "visible": 1,
    "width_percent": 100
  },
  "display_style": {
    "background_color": "#0f0f14",
    "background_image": "",
    "bg_slide_ms": 5000,
    "bg_fade_ms": 1000
  },
  "led_output": {
    "enabled": 0,
    "transport": "none",
    "led_count": 177,
    "mirror_per_key": 2,
    "led_sustain": 0,
    "led_fade_amount": 0,
    "led_fade_speed": 80
  },
  "audience_control": {
    "enabled": 0,
    "ws_url": "",
    "transition_ms": 220
  },
  "user_themes": [],
  "note_color_themes": [],
  "active_note_theme": { "type": "builtin", "index": 0 }
}
```

## Most impactful fields for aesthetics

| Field | Effect |
|-------|--------|
| `display_style.background_color` | Canvas background — dark colours work best |
| `note_style.color_r/g/b` | Main trail/note colour (RGB 0–255) |
| `note_style.interior_r/g/b` | Bright core highlight inside the trail |
| `note_style.speed_px_per_sec` | Trail scroll speed (200=slow, 420=default, 700=fast) |
| `note_style.effect_sparks_enabled` | 1=on, 0=off |
| `note_style.effect_smoke_enabled` | 1=on, 0=off |
| `note_style.effect_glow_enabled` | 1=on, 0=off |
| `note_style.effect_fluid_enabled` | 1=on — enables fluid simulation ripple |
| `note_style.fluid_opacity` | 0–100, how visible the fluid layer is |
| `note_style.glow_strength_percent` | 0–100 |

## Worked example

See `examples/claire-de-lune.json` in this repository for a complete moonlight-themed preset (soft blue-white trails, fluid ripple, near-black background, no sparks).

## Output format

Respond with **only** the JSON object, no markdown fences, no explanation. It will be saved as a `.json` file and imported directly into the app.

---

## Your request

[describe the mood, piece, or visual style you want here]
