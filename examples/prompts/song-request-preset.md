# AI Prompt — Song Request to Preset JSON (Canonical)

Copy everything below this line and paste it into any AI, then replace the request block at the bottom.

---

You are generating a JSON preset for the Piano MIDI Visualiser web app.

## Output rules

- Respond with **JSON only**
- No markdown fences
- No explanation text
- Keep all numeric values in sensible ranges

## Song request input format (required)

Use this exact structure:

song_title: <text>  
mood: <text>  
energy: <1-10>  
references: <optional text, or "none">

## What to generate

Generate one cohesive preset from the song request:

1. note/effect/fluid settings (`note_style`, optional `keyboard_style`, `display_style`)
2. colour script text in `note_style.user_script`
3. slideshow plan under `slideshow`

## Slideshow contract

Use:

{
  "slideshow": {
    "clear_existing": true,
    "items": [
      {
        "source": "giphy",
        "query": "song keywords",
        "limit": 1,
        "slide_ms": 7000,
        "fade_ms": 1200,
        "gif_speed_pct": 100
      },
      {
        "source": "url",
        "url": "https://...",
        "slide_ms": 6000,
        "fade_ms": 1000
      }
    ]
  }
}

Rules:
- Include 3–8 slideshow items when possible
- `slide_ms`: 500–30000
- `fade_ms`: 0–5000
- `gif_speed_pct` (optional): 10–300
- For Giphy entries use `source: "giphy"` with `query` and `limit` (1–3)

## Recommended key set

Return only keys you intentionally want to change:
- `note_style`
- `keyboard_style`
- `display_style`
- `led_output`
- `audience_control`
- `note_color_themes`
- `active_note_theme`
- `slideshow`

---

## Song request

song_title: Light My Fire  
mood: psychedelic, fiery, dramatic  
energy: 8  
references: 1960s stage lights, lava lamp motion, orange-red smoke
