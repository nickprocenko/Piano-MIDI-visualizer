# Examples

Preset save files for the Piano MIDI Visualiser. Each `.json` file can be loaded via the **Import Settings** button in the app (top-right menu).

> MIDI files are not included — load your own from the file picker after importing a preset.

| File | Description |
|------|-------------|
| `claire-de-lune.json` | Moonlight palette — soft blue-white trails, fluid ripple, dark background |
| `riders-on-the-storm.json` | Split keyboard — white lightning left (≤ B3), electric purple right (≥ C4); stormy black background. Add lightning GIFs via the Images slideshow for the full effect. |
| `moonlight-sonata.json` | Midnight blue (low) → moonlit silver-white (high); near-black interior for deep glow from edges; moon dust particles, gentle fluid ripple, halo pulse |
| `light-my-fire.json` | Deep crimson (low) → golden amber (high); bright yellow interior for burning hot core; sparks, smoke, press smoke, high-intensity fluid with orange tint |
| `what-a-wonderful-world.json` | Warm amber (low) → golden ivory (high); slow trails, moon dust, gentle fluid drift — nostalgic and unhurried |
| `ocarina-of-time.json` | Emerald forest green (low) → Triforce gold (high, quadratic fade); moon dust sparkle, halo pulse, swirling green fluid — mystical and ethereal |
| `mario-theme.json` | Full rainbow keyboard, white-hot core, sparks, high fluid energy, fast scroll speed — arcade bounce |
| `raindrop-prelude.json` | Steel blue (low) → cool grey-white (high); MIDI note 68 (A♭4) highlighted icy blue — the recurring Chopin raindrop; high-persistence fluid simulates rain falling into still water |
| `here-comes-the-sun.json` | Sunrise orange (low) → brilliant sun yellow (high); sparks like sunrays, halo pulse, warm golden fluid — uplifting and solar |

## AI Prompts

The `prompts/` folder contains ready-made prompts you can paste into any AI (Claude, ChatGPT, Gemini, etc.) to generate content for the app:

| Prompt | Generates |
|--------|-----------|
| `prompts/script.md` | JavaScript colour script for the Script editor |
| `prompts/preset.md` | JSON save file importable via Import Settings |

The app also has a **Copy AI Prompt** button directly in the Script editor (Notes → Color Mode → Script) that copies a prompt pre-loaded with the current script and full API docs.
