# AI Prompt — Generate a Colour Script

Copy everything below this line and paste it into any AI (Claude, ChatGPT, Gemini, etc.), then add your request at the bottom.

---

You are writing a JavaScript colour script for a Piano MIDI Visualiser web app.

## Execution environment

The script runs as `new Function('api', code)(api)` in a browser tab.

- **No imports, no fetch, no require** — plain ES2020 browser JS only
- The return value of the script is ignored; all interaction is through the `api` object
- Errors are caught and shown as an alert; the rest of the app keeps running

## API reference

### Static setup (runs once when script is applied)

```js
api.setNote(n, r, g, b)
```
Set a specific MIDI note to a colour. `n` = 0–127. `r`/`g`/`b` = 0–255 integers.
Pass `null` for `r` to clear the note back to the default colour.

```js
api.setOctave(oct, r, g, b)
```
Set all notes of a pitch class. `oct` = 0 (C) to 11 (B). Applies to every octave.

```js
api.setAll(r, g, b)
```
Set all 128 notes to the same colour.

```js
api.setChannel(ch, r, g, b)
```
Set all notes on a MIDI channel. `ch` = 0–15. Channel colours override per-note colours.

```js
api.setZone(ch, lo, hi, r, g, b)
```
Set a range of notes on a specific channel. Highest priority in the colour stack.

```js
const [r, g, b] = api.hsvToRgb(h, s, v)
```
Convert HSV to RGB. All three inputs are 0–1 floats. Returns an array `[r, g, b]` with values 0–255.

### Event callbacks (optional — registered during static setup)

```js
api.onNoteOn(function(note, velocity, channel) { ... })
```
Called every time a note is struck. `note` = 0–127, `velocity` = 1–127, `channel` = 0–15.

```js
api.onNoteOff(function(note, channel) { ... })
```
Called when a note is released (or when sustain pedal releases it).

```js
api.onFrame(function(activeNotes, now, dt) { ... })
```
Called every animation frame (~60 fps).
- `activeNotes` — `Set` of currently held MIDI note numbers
- `now` — `performance.now()` in milliseconds
- `dt` — seconds since the previous frame (typically ~0.016)

Callbacks can call any `api.*` method. Changes to note colours are visible immediately on the same frame.

## MIDI note number reference

| Note | Number |
|------|--------|
| A0 (lowest piano key) | 21 |
| C4 (middle C) | 60 |
| A4 (concert pitch) | 69 |
| C8 (highest piano key) | 108 |

**Piano range:** 21–108 (88 keys)

**Pitch classes (n % 12):** C=0, C#=1, D=2, D#=3, E=4, F=5, F#=6, G=7, G#=8, A=9, Bb=10, B=11

## Built-in examples

### Rainbow keyboard (static)
```js
for (let n = 0; n < 128; n++) {
  const hue = ((n - 21) / 87 % 1 + 1) % 1;
  const [r, g, b] = api.hsvToRgb(hue, 0.9, 1.0);
  api.setNote(n, r, g, b);
}
```

### Fire (static, low=red, high=yellow)
```js
for (let n = 0; n < 128; n++) {
  const t = Math.max(0, Math.min(1, (n - 21) / 87));
  api.setNote(n, 255, Math.round(t * 200), 0);
}
```

### Ice (static, low=teal, high=bright cyan)
```js
for (let n = 0; n < 128; n++) {
  const t = Math.max(0, Math.min(1, (n - 21) / 87));
  api.setNote(n, 0, Math.round(180 + t * 75), 255);
}
```

### Velocity-reactive with rainbow animation (uses all three callbacks)
```js
// Dark base
api.setAll(0, 30, 60);

// Struck note turns bright; brightness reflects velocity
api.onNoteOn(function(note, velocity, channel) {
  const b = Math.round(velocity * 2);
  api.setNote(note, b, b, 255);
});

// Released note reverts to base colour
api.onNoteOff(function(note, channel) {
  api.setNote(note, null);
});

// Held notes cycle through rainbow
api.onFrame(function(activeNotes, now, dt) {
  for (const n of activeNotes) {
    const [r, g, b] = api.hsvToRgb((now / 2000 + n / 12) % 1, 1, 1);
    api.setNote(n, r, g, b);
  }
});
```

## Output format

Respond with **only** the JavaScript code, no markdown fences, no explanation. The code will be pasted directly into the script editor and executed.

---

## Your request

[describe the colour effect you want here]
