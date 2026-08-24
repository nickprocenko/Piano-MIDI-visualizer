# Drum Pad Lighting Script — AI Prompt

Copy everything below into Claude, ChatGPT, or any other assistant, fill in the request at
the bottom, and paste the returned code into **Settings → Drum LEDs → Pad Script**.

The **Copy AI Prompt** button in that panel does the same thing but also embeds the pad's
name, its LED count, and whatever script it currently has — prefer that when you're
iterating on an existing effect.

---

You are writing a JavaScript lighting script for one drum in a MIDI drum-kit LED visualiser.

CONTEXT: The strip is a RING around the circumference of the top of a drum. Pixel 0 and the
last pixel are physically adjacent — always wrap. Positions expressed as fractions go 0..1
once round the ring.

EXECUTION: runs as `new Function('api', code)(api)` in a browser.
No imports, no fetch, no require — plain ES2020 browser JS only.
Return value is ignored; interact only through the api object.

API REFERENCE:

```
api.len                       ring length in pixels
api.set(i, r, g, b)           write pixel i (wraps); r/g/b are 0-255
api.add(i, r, g, b)           additive write (wraps)
api.fill(r, g, b)             set the whole ring
api.arc(centre, width, r,g,b) soft-edged arc; centre and width are 0..1 fractions
api.hsvToRgb(h, s, v)         h/s/v all 0-1; returns an OBJECT {r,g,b} with 0-255
                              fields — destructure as {r,g,b}, NOT as [r,g,b]
api.rand(seed, n)             deterministic 0..1 noise — pass hit.seed so a pattern
                              stays stable for the life of one hit

api.onHit(fn)    fn(velocity, alt, note)
                 velocity 0..1, alt = true for a rim / cross-stick / edge hit
api.onFrame(fn)  fn(now, dt, hits)
                 now = ms, dt = seconds since last frame
                 hits = array of live hits, each {age (seconds), vel (0..1), alt, seed, index}
                 `index` counts hits on this pad since page load — use it to make
                 successive strokes differ (hue stepping, alternating halves).
```

IMPORTANT: `onFrame` must draw the WHOLE ring every frame. The buffer is reset before your
`onFrame` runs, so decay is your job: derive brightness from `hit.age`, e.g.
`Math.exp(-hit.age / 0.25)`.

Drums are impulses, not gates — a pad sends note-on and note-off within a few milliseconds,
so there is no "note held" state. Everything is driven by how long ago a hit landed.

EXAMPLE — velocity flash with a rim accent:

```js
api.onFrame(function(now, dt, hits){
  api.fill(0,0,0);
  for (const h of hits) {
    const a = Math.exp(-h.age / 0.22) * h.vel;
    const c = h.alt ? [255,255,255] : [0,180,255];
    for (let i = 0; i < api.len; i++) api.add(i, c[0]*a, c[1]*a, c[2]*a);
  }
});
```

EXAMPLE — comet that laps the ring once per hit:

```js
api.onFrame(function(now, dt, hits){
  api.fill(0,0,0);
  for (const h of hits) {
    const a = Math.exp(-h.age / 0.4) * h.vel;
    api.arc((h.age * 3) % 1, 0.15, 255*a, 120*a, 0);
  }
});
```

EXAMPLE — each stroke a new colour, so a roll paints a rainbow:

```js
api.onFrame(function(now, dt, hits){
  api.fill(0,0,0);
  for (const h of hits) {
    const a = Math.exp(-h.age / 0.3) * h.vel;
    const c = api.hsvToRgb((h.index * 0.13) % 1, 0.95, 1);
    for (let i = 0; i < api.len; i++) api.add(i, c.r*a, c.g*a, c.b*a);
  }
});
```

CURRENT SCRIPT (modify or replace entirely):

```
// empty — write a new script from scratch
```

Respond with ONLY the JavaScript code, no markdown fences, no explanation.

YOUR REQUEST:
[describe the lighting effect you want for this drum here]
