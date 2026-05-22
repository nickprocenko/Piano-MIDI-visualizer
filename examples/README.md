# Examples

Preset save files for the Piano MIDI Visualiser. Each `.json` file can be loaded via the **Import Settings** button in the app (top-right menu).

> MIDI files are not included — load your own from the file picker after importing a preset.

| File | Description |
|------|-------------|
| `claire-de-lune.json` | Moonlight palette — soft blue-white trails, fluid ripple, dark background |
| `riders-on-the-storm.json` | Split keyboard — white lightning left (≤ B3), electric purple right (≥ C4); stormy black background. Add lightning GIFs via the Images slideshow for the full effect. |
| `moonlight-sonata.json` | Midnight blue (low) → moonlit silver-white (high); near-black interior for deep glow from edges; moon dust particles, gentle fluid ripple, halo pulse |
| `light-my-fire.json` | Deep crimson (low) → golden amber (high); bright yellow interior for burning hot core; sparks, smoke, press smoke, high-intensity fluid with orange tint |

## AI Prompts

The `prompts/` folder contains ready-made prompts you can paste into any AI (Claude, ChatGPT, Gemini, etc.) to generate content for the app:

| Prompt | Generates |
|--------|-----------|
| `prompts/script.md` | JavaScript colour script for the Script editor |
| `prompts/preset.md` | JSON save file importable via Import Settings |

The app also has a **Copy AI Prompt** button directly in the Script editor (Notes → Color Mode → Script) that copies a prompt pre-loaded with the current script and full API docs.
