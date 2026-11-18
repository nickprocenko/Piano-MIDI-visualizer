// Falling notes: the web visualizer's view of a piece, on the coach page as an option to the
// sheet (View: Sheet / Falling notes / Both). The score's notes fall onto a keyboard as the
// coach's cursor moves, in the visualizer's hand colours; hits turn green and misses red as the
// run grades them, and the keys you hold light up (green if the piece wants them, red if not).
// It reads the same event stream as the sheet: the notes come with GET score
// ([beat, length in beats, pitch, role, finger]); cursorBeat, marks, heat, flash, session and keys
// arrive through coachRoll.event().
// Learn with hands (Sheet ▸ Finger numbers / Hands on the keys): each hand's note carries the
// finger the coach suggests (fingering.py, 1 = thumb ... 5), printed on the falling note, and a
// pair of hands plays the piece on the keyboard with those fingers, moving ahead to the keys
// coming up and pressing each one as the cursor reaches it. This file works out where each finger
// goes; hands3d.js draws the hands in 3D (three.js and open-source hand models), with flat 2D
// hands here as the fallback.
"use strict";
window.coachRoll = (() => {
  const canvas = document.getElementById('roll');
  const ctx = canvas.getContext('2d');
  // Right / left as the visualizer draws them (its Learn Mode channel colours)
  const COLORS = {right: [0, 230, 230], left: [180, 80, 255], pedals: [255, 170, 60], vocals: [240, 120, 200]};
  const OTHER = [150, 160, 180];
  const HIT = [21, 154, 60], MISS = [212, 32, 32];
  const EASE_MS = {steady: 300, learn: 150}, SNAP_BEATS = {steady: 0.5, learn: 8};  // as in notation.html
  const BLACK = new Set([1, 3, 6, 8, 10]);
  const store = {
    get(k, d) { try { const v = localStorage.getItem('coach.roll.' + k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('coach.roll.' + k, v); } catch (e) {} },
  };

  let notes = [], bars = [], heat = [], maxLen = 4, lo = 48, hi = 84;
  let byPitch = new Map();
  let hidden = new Set(), played = new Set(['right', 'left', 'pedals', 'vocals']);
  let held = new Set();
  let flash = null;
  let span = Math.max(2, Math.min(32, Number(store.get('beats', '8')) || 8));  // beats between the top and the keys
  // Note names printed inside the falling notes (Sheet ▸ Names on falling notes), spelled with
  // sharps or flats as the piece's key suggests: the score sent here has pitches, not spellings.
  let names = store.get('names', '') === '1';
  let fingerNumbers = store.get('fingers', '1') === '1';  // Sheet ▸ Finger numbers on falling notes
  let handsOn = store.get('hands', '1') === '1';  // Sheet ▸ Hands on the keys
  const SHARPS = ['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B'];
  const FLATS = ['C', 'D♭', 'D', 'E♭', 'E', 'F', 'G♭', 'G', 'A♭', 'A', 'B♭', 'B'];
  let spelling = SHARPS;
  // The cursor, moving the way the sheet's does: at bps from target, parking at until (Learn),
  // with a short ease from where it was drawn so a correction never jolts.
  const cur = {target: 0, bps: 0, at: 0, until: null, ease: EASE_MS.learn, offset: 0, seen: false, speed: 1};
  let shown = false, raf = 0, width = 0, height = 0;
  let layout = null;  // where the last frame put the keys (for hands_render.py)
  let pan = 0, ppbShown = 0;  // beats dragged away from the cursor (as the sheet pans); pixels per beat drawn

  function cursorBase(now) {
    if (!(cur.bps > 0)) return cur.target;
    const at = cur.target + cur.bps * (now - cur.at) / 1000;
    return cur.until === null ? at : Math.min(at, cur.until);
  }
  function cursorAt(now) {
    const t = (now - cur.at) / cur.ease;
    return cursorBase(now) + cur.offset * (t >= 1 ? 0 : 0.5 * (1 + Math.cos(Math.PI * t)));
  }

  function score(payload) {
    notes = (payload.notes || []).map(([b, d, p, role, f, g]) => ({b, d, p, role, f: f || 0, g: g || 0, mark: ''}))
      .sort((x, y) => x.b - y.b || x.p - y.p);
    indexFingers();
    bars = payload.bars || [];
    heat = [];
    byPitch = new Map();
    for (const n of notes) {
      if (!byPitch.has(n.p)) byPitch.set(n.p, []);
      byPitch.get(n.p).push(n);
    }
    maxLen = notes.reduce((m, n) => Math.max(m, n.d), 1);
    // The keyboard spans the piece in whole octaves, three at least, within the 88 keys.
    const pitches = notes.map(n => n.p);
    lo = pitches.length ? Math.min(...pitches) : 48;
    hi = pitches.length ? Math.max(...pitches) : 84;
    lo = Math.max(21, lo - lo % 12);
    hi = Math.min(108, hi + 11 - hi % 12);
    while (hi - lo < 35) {
      if (hi < 108) hi = Math.min(108, hi + 12);
      else if (lo > 21) lo = Math.max(21, lo - 12);
      else break;
    }
    if (!cur.seen && notes.length) cur.target = notes[0].b;
    spelling = guessSpelling(notes);
  }

  // New notes for the same piece: like score(), but the hands, the keyboard's range and the key
  // spelling stay as they are, so the hands carry on from where they are instead of starting over.
  // For a live source whose notes are revised as it's heard (radio_hands).
  function update(payload) {
    notes = (payload.notes || []).map(([b, d, p, role, f, g]) => ({b, d, p, role, f: f || 0, g: g || 0, mark: ''}))
      .sort((x, y) => x.b - y.b || x.p - y.p);
    indexFingers(true);
    byPitch = new Map();
    for (const n of notes) {
      if (!byPitch.has(n.p)) byPitch.set(n.p, []);
      byPitch.get(n.p).push(n);
    }
    maxLen = notes.reduce((m, n) => Math.max(m, n.d), 1);
  }

  // The major key (or its relative minor) whose scale holds most of the music, by beats held;
  // keys with fewer sharps or flats win a tie. Its signature says sharps or flats.
  function guessSpelling(list) {
    const weight = new Array(12).fill(0);
    for (const n of list) weight[((n.p % 12) + 12) % 12] += Math.max(0.25, n.d);
    const MAJOR = [0, 2, 4, 5, 7, 9, 11];
    const ORDER = [0, 7, 5, 2, 10, 9, 3, 4, 8, 11, 1, 6];  // C, G, F, D, B♭, A, E♭, E, A♭, B, D♭, F♯
    const FLAT_KEYS = new Set([5, 10, 3, 8, 1]);
    let best = 0, bestFit = -1;
    for (const t of ORDER) {
      const fit = MAJOR.reduce((s, i) => s + weight[(t + i) % 12], 0);
      if (fit > bestFit + 1e-9) { best = t; bestFit = fit; }
    }
    return FLAT_KEYS.has(best) ? FLATS : SHARPS;
  }

  function showNames(on) { names = !!on; store.set('names', names ? '1' : ''); }
  function showFingers(on) { fingerNumbers = !!on; store.set('fingers', fingerNumbers ? '1' : ''); }
  function showHands(on) { handsOn = !!on; store.set('hands', handsOn ? '1' : ''); }

  function findNote(beat, pitch) {
    let best = null;
    for (const n of byPitch.get(pitch) || []) {
      const off = Math.abs(n.b - beat);
      if (off < 0.02 && (!best || off < Math.abs(best.b - beat))) best = n;
    }
    return best;
  }

  function event(m) {
    const now = performance.now();
    if (m.type === 'cursorBeat') {
      const drawn = cur.seen ? cursorAt(now) : null;
      cur.seen = true;
      pan = 0;  // the next cursor update snaps a dragged view back, as on the sheet
      cur.target = m.beat; cur.bps = m.bps || 0; cur.at = now;
      cur.until = typeof m.until === 'number' ? m.until : null;
      cur.speed = m.speed > 0 ? m.speed : 1;  // the run's tempo, as a share of the piece's
      const steady = cur.bps > 0 && cur.until === null;  // Rehearse / Listen: moving at tempo
      cur.ease = steady ? EASE_MS.steady : EASE_MS.learn;
      cur.offset = drawn === null ? 0 : drawn - cursorBase(now);
      if (Math.abs(cur.offset) > (steady ? SNAP_BEATS.steady : SNAP_BEATS.learn)) cur.offset = 0;
    } else if (m.type === 'session' && !m.active) {
      cur.target = cursorAt(now); cur.at = now; cur.bps = 0; cur.until = null; cur.offset = 0; cur.speed = 1;
    } else if (m.type === 'marks') {
      if (m.reset) notes.forEach(n => { n.mark = ''; });
      for (const k of m.marks || []) {
        const n = findNote(k.beat, k.pitch);
        if (n) n.mark = k.status;
      }
    } else if (m.type === 'heat') {
      heat = m.bars || [];
    } else if (m.type === 'flash') {
      flash = {text: '✗ ' + m.text + (m.hint ? '  ·  play ' + m.hint : ''), until: now + (m.hint ? 1600 : 700)};
    } else if (m.type === 'keys') {
      held = new Set(m.on || []);
    }
  }

  // What's shown (the Playing menu's Show boxes) and what you play (the rest is drawn faint).
  function parts(hiddenRoles, playedRoles) {
    hidden = new Set(hiddenRoles || []);
    played = new Set(playedRoles || []);
  }

  function show(on) {
    shown = !!on;
    if (shown && !raf) raf = requestAnimationFrame(frame);
  }

  // -- drawing ---------------------------------------------------------------

  // The keys laid out as a piano's: a black key is 0.58 of a white key wide and sits off the
  // edge between its white keys as on a real keyboard (C♯ and D♯ spread apart, F♯ and A♯
  // spread from G♯), so at the back every key is about as wide, and B–C and E–F don't gape.
  const BLACK_SHIFT = {1: -0.12, 3: 0.12, 6: -0.17, 8: 0, 10: 0.17};  // white keys, from the edge
  function keyboard(keyH, lo, hi) {
    let whites = 0;
    for (let p = lo; p <= hi; p++) if (!BLACK.has(p % 12)) whites++;
    const ww = width / whites, bw = ww * 0.58;
    const keys = new Map();
    let i = 0;
    for (let p = lo; p <= hi; p++) {
      if (BLACK.has(p % 12)) keys.set(p, {x: (i + BLACK_SHIFT[p % 12]) * ww - bw / 2, w: bw, black: true, h: keyH * 0.62});
      else keys.set(p, {x: i++ * ww, w: ww, black: false, h: keyH});
    }
    return keys;
  }

  const rgb = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const lighter = (c, k) => c.map(v => Math.min(255, v + k));
  const roleColor = role => COLORS[role] || OTHER;

  function noteColor(n) {
    return n.mark === 'hit' ? HIT : n.mark === 'missed' ? MISS : roleColor(n.role);
  }

  function draw(now) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    width = w; height = h;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#0f0f14';
    ctx.fillRect(0, 0, w, h);
    if (!notes.length) {
      ctx.fillStyle = '#8d93a8';
      ctx.font = '15px "Segoe UI", Arial, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Pick a song or lesson to see its notes fall onto the keys.', w / 2, h / 2);
      return;
    }
    const withHands = handsOn && hasFingers();
    const countWhites = (a, b) => { let n = 0; for (let p = a; p <= b; p++) if (!BLACK.has(p % 12)) n++; return n; };
    // With the hands on, the picture is a piano video's: keys in a piano's proportions (KEY_LONG
    // white keys long) taking KEYS_TALL of the page, so the keyboard shows octaves beyond the
    // piece's until its keys are narrow enough for that, and the hands and wrists below them.
    let a = lo, b = hi;
    if (withHands && !rangeSet) {
      const need = 0.85 * w * KEY_LONG / (h * KEYS_TALL);
      while (countWhites(a, b) < need && (a > 21 || b < 108)) {
        if (a > 21) a = Math.max(21, a - 12);
        if (countWhites(a, b) < need && b < 108) b = Math.min(108, b + 12);
      }
    }
    const whites = countWhites(a, b);
    const keyH = Math.max(50, withHands ? Math.min(h * KEYS_TALL, (w / whites) * KEY_LONG) : Math.min(h * 0.26, (w / whites) * 5.2));
    const room = withHands ? Math.min(keyH * HAND_ROOM, h * 0.32) : 0;  // under the keys: the backs of the hands, the wrists
    const floor = h - keyH - room;
    const ppb = floor / span;  // pixels per beat
    ppbShown = ppb;
    const beat = cursorAt(now) + pan;
    const keys = keyboard(keyH, a, b);
    layout = {width: w, height: h, floor, keyH, ww: w / whites, lo: a, hi: b};
    const yOf = b => floor - (b - beat) * ppb;

    // Bars that went badly (the heat map), then bar lines with their numbers
    for (const b of heat) {
      const top = Math.max(0, yOf(b.end)), bottom = Math.min(floor, yOf(b.start));
      if (bottom > top && b.value > 0) { ctx.fillStyle = `rgba(212,32,32,${0.06 + 0.16 * b.value})`; ctx.fillRect(0, top, w, bottom - top); }
    }
    ctx.font = '11px "Segoe UI", Arial, sans-serif';
    ctx.textAlign = 'left';
    for (const bar of bars) {
      const y = yOf(bar.start_beat);
      if (y > floor || y < 0) continue;
      ctx.fillStyle = 'rgba(255,255,255,.09)';
      ctx.fillRect(0, Math.round(y), w, 1);
      ctx.fillStyle = 'rgba(141,147,168,.75)';
      ctx.fillText(String(bar.number), 6, y - 4);
    }

    // The notes in view: white keys' first, so the black keys' notes sit on top
    const guide = new Map();  // pitch -> colour of the note due now, lit on its key
    const first = lowerBound(beat - maxLen);
    for (const blackPass of [false, true]) {
      for (let i = first; i < notes.length; i++) {
        const n = notes[i];
        if (n.b > beat + span) break;
        if (n.b + n.d < beat || hidden.has(n.role)) continue;
        const k = keys.get(n.p);
        if (!k || k.black !== blackPass) continue;
        const mine = played.has(n.role);
        const bottom = Math.min(floor, yOf(n.b)), top = Math.max(0, yOf(n.b + n.d));
        if (mine && n.b <= beat + 0.05 && n.mark !== 'missed' && !guide.has(n.p)) guide.set(n.p, noteColor(n));
        if (bottom - top < 1) continue;
        const c = noteColor(n);
        const due = n.mark === 'pending';
        ctx.globalAlpha = !mine ? 0.22 : due ? 0.95 : n.mark ? 0.8 : 0.6;
        ctx.fillStyle = rgb(c);
        ctx.beginPath(); ctx.roundRect(k.x + 1, top, k.w - 2, bottom - top, 3); ctx.fill();
        if (due) {
          ctx.globalAlpha = 1;
          ctx.strokeStyle = rgb(lighter(c, 90));
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        if (names) noteName(n, k, top, bottom, mine);
        if (fingerNumbers && n.f) fingerBadge(n, k, top, bottom, mine, n.b <= beat);
      }
    }
    ctx.globalAlpha = 1;

    // The keys: held ones green when the piece wants them now, red when it doesn't; the
    // notes due now tinted in their hand's colour, so you can see what to play.
    const at = beat - pan;  // what you hold is judged at the cursor, wherever the view was dragged
    const wanted = p => (byPitch.get(p) || []).some(n => !hidden.has(n.role) && n.b - 0.25 <= at && at <= n.b + n.d);
    const keyFill = (p, k) => {
      if (held.has(p)) return rgb(wanted(p) ? HIT : MISS);
      const g = guide.get(p);
      if (g) return rgb(k.black ? g : lighter(g, 70));
      return k.black ? '#1a1b22' : '#e9eaf0';
    };
    for (const [p, k] of keys) {
      if (k.black) continue;
      ctx.fillStyle = keyFill(p, k);
      ctx.fillRect(k.x + 0.5, floor, k.w - 1, k.h);
      if (p % 12 === 0) {  // C, with its octave, for finding your place
        ctx.fillStyle = 'rgba(20,22,30,.55)';
        ctx.font = `${Math.max(9, Math.min(12, k.w * 0.45))}px "Segoe UI", Arial, sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillText('C' + (p / 12 - 1), k.x + k.w / 2, floor + k.h - 6);
      }
    }
    for (const [p, k] of keys) {
      if (!k.black) continue;
      ctx.fillStyle = keyFill(p, k);
      ctx.beginPath(); ctx.roundRect(k.x, floor, k.w, k.h, [0, 0, 3, 3]); ctx.fill();
    }
    ctx.fillStyle = 'rgba(0,180,180,.85)';  // the line the notes are played on
    ctx.fillRect(0, floor - 1, w, 2);

    if (withHands) {
      const below = ctx.createLinearGradient(0, floor + keyH, 0, h);
      below.addColorStop(0, '#2a2b34'); below.addColorStop(1, '#14151b');
      ctx.fillStyle = below;  // the key bed and the player's side of the keyboard
      ctx.fillRect(0, floor + keyH, w, room);
      drawHands(now, keys, w / whites, floor, keyH, at);
    }

    if (flash && now < flash.until) {
      ctx.globalAlpha = Math.min(1, (flash.until - now) / 200);
      ctx.fillStyle = '#d42020';
      ctx.font = '600 22px "Segoe UI", Arial, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(flash.text, w / 2, floor - 14);
      ctx.globalAlpha = 1;
    }
  }

  // The letter name inside a falling note, at its bottom end (the end that reaches the keys
  // first), sized to fit the note's width; left off a note too small to hold it.
  function noteName(n, k, top, bottom, mine) {
    const text = spelling[((n.p % 12) + 12) % 12];
    const room = k.w - 4;
    let size = Math.min(14, room * (text.length > 1 ? 0.62 : 0.8));
    if (size < 7 || bottom - top < size + 4) return;
    ctx.font = `600 ${size}px "Segoe UI", Arial, sans-serif`;
    const tw = ctx.measureText(text).width;
    if (tw > room) {
      size *= room / tw;
      if (size < 7) return;
      ctx.font = `600 ${size}px "Segoe UI", Arial, sans-serif`;
    }
    ctx.globalAlpha = 1;
    ctx.fillStyle = mine ? 'rgba(10,12,18,.9)' : 'rgba(220,224,236,.5)';  // a faint part's note is dark
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    const lift = fingerNumbers && n.f ? badgeRadius(k) * 2 + 3 : 0;  // above the finger number
    if (bottom - top < size + 4 + lift) return;
    ctx.fillText(text, k.x + k.w / 2, bottom - 4 - lift);
  }

  // -- finger numbers ----------------------------------------------------------

  const badgeRadius = k => Math.min(9, k.w * 0.42);

  // The suggested finger in a disc at the falling note's bottom end (the end that reaches the
  // keys first); on a note too short to hold it, the disc sits just above the note (unless it
  // is already being played: the hands show that finger).
  function fingerBadge(n, k, top, bottom, mine, started) {
    const r = badgeRadius(k);
    if (r < 4) return;
    const cx = k.x + k.w / 2;
    const fits = bottom - top >= 2 * r + 4;
    if (!fits && started) return;
    const cy = fits ? bottom - r - 2 : top - r - 1;
    if (cy < r) return;
    ctx.globalAlpha = mine ? 1 : 0.45;
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI);
    ctx.fillStyle = 'rgba(12,14,20,.82)'; ctx.fill();
    ctx.lineWidth = 1.2; ctx.strokeStyle = 'rgba(255,255,255,.85)'; ctx.stroke();
    ctx.fillStyle = '#fff';
    ctx.font = `700 ${Math.round(r * 1.3)}px "Segoe UI", Arial, sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(String(n.f), cx, cy + 0.5);
    ctx.textBaseline = 'alphabetic';
    ctx.globalAlpha = 1;
  }

  function lowerBound(beat) {
    let a = 0, b = notes.length;
    while (a < b) { const m = (a + b) >> 1; if (notes[m].b < beat) a = m + 1; else b = m; }
    return a;
  }

  function frame(now) {
    raf = 0;
    if (!shown) return;
    draw(now);
    raf = requestAnimationFrame(frame);
  }

  // Scroll to change how much music is in view (how fast the notes fall).
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    span = Math.max(2, Math.min(32, span * (e.deltaY > 0 ? 1.15 : 1 / 1.15)));
    store.set('beats', span.toFixed(2));
  }, {passive: false});

  // Drag up and down to look through the piece while the cursor is parked, the way the sheet
  // pans: grab the notes and pull them down to see what's coming. The next cursor update snaps
  // back; nothing pans while the cursor moves at tempo (Rehearse / Listen).
  const gliding = () => cur.bps > 0 && cur.until === null;
  function panBy(dy) {
    if (!notes.length || !(ppbShown > 0) || gliding()) return;
    const base = cursorAt(performance.now());
    const start = notes[0].b, end = notes.reduce((m, n) => Math.max(m, n.b + n.d), start);
    // Keep some of the piece in view: the keys at most a view below its start, at most its end.
    pan = Math.max(start - span - base, Math.min(end - base, pan + dy / ppbShown));
  }
  canvas.style.touchAction = 'none';
  canvas.style.cursor = 'grab';
  let dragY = null;
  canvas.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    e.preventDefault();
    dragY = e.clientY;
    canvas.setPointerCapture(e.pointerId);
    canvas.style.cursor = 'grabbing';
  });
  canvas.addEventListener('pointermove', e => {
    if (dragY === null) return;
    panBy(e.clientY - dragY);
    dragY = e.clientY;
  });
  const endDrag = () => { dragY = null; canvas.style.cursor = 'grab'; };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  // -- the hands ---------------------------------------------------------------
  // Fingertips on the keys, the backs of the hands on the player's side, drawn in 3D by
  // hands3d.js (or flat, below, when it can't load). A finger goes to the key of its note
  // sounding now and lets go of it when the note ends; shortly before its next note it reaches
  // for that key; otherwise it rests beside its neighbours, a key or so apart, as a relaxed hand's
  // fingers do. The hand sits where its fingers' keys put it, opens as wide as they ask (an
  // octave, up to a tenth), and glides between positions; with nothing to play for a beat or so
  // it rests, lifted off the keys. Fingers 2 to 5 never cross or lie on each other. All of it
  // eased per frame.

  const HAND_ROOM = 1.3;  // keyboard heights under the keys, for the backs of the hands and the wrists
  const KEY_LONG = 6.5, KEYS_TALL = 0.24;  // with the hands on: a key's length in white keys; the keys' share of the page's height
  const TIP_WHITE = 0.58, TIP_BLACK = 0.38;  // where a fingertip plays a white / black key, down from its far end
  const HAND_TAU = 220;  // ms: how slowly a hand making way for the other moves aside
  // ms: how long the hand takes to a new position, to open or close, and a finger to a key or
  // (slower) to where it rests. These are springs' times: a move starts gently, is quickest
  // halfway and settles, as an arm's does, rather than jumping off and creeping in.
  // The hand takes the time it has: a HAND_SHARE of the wait until its next note, from as quick
  // as a leap at speed to an unhurried move (less unhurried while it holds a key it's leaving),
  // so it doesn't dart to the next chord and then wait there. A finger late for its key
  // (the same finger's last note only just over) hurries likewise, to be on the key as it plays.
  const HAND_TIME = [90, 260], HAND_HELD = 150, HAND_SHARE = 0.25;
  const SPREAD_TIME = 140, FINGER_TIME = [60, 170], FINGER_QUICK = 25;
  const AHEAD = 0.5;  // how much the notes coming count against the keys held, in placing the hand
  const HOLD_REACH = 1.2;  // white keys a finger holding a key lets the hand move on from under it
  const STRIKE_MS = 40, DOWN_MS = 110;  // a finger starts down this long before its note; and stays down at least this long
  const LIFT_BEATS = 0.25, LEAP_KEYS = 8;  // beats a finger is up before its next note; white keys past which a held key is let go
  const LOOK = 1, ARRIVE = 0.15;  // beats before its next note a finger starts toward that key; and is over it
  const SPREAD = [0.8, 2.3];  // white keys between neighbouring fingers: closed up, to a tenth across the hand
  const RELAXED = [0.9, 1.15];  // white keys between resting neighbours: closed up, opened
  const THUMB_GAP = 2.2;  // white keys from the index to a resting thumb
  const MIN_GAP = 0.8;  // white keys at least between neighbouring fingers (2 to 5) not on keys
  const CLEAR = 3.0;  // white keys a hand making way keeps from the other's fingertips
  const REST = [0.5, 1.5];  // beats from a hand's last note (or to its next) at which it starts to rest, and is at rest
  const PALM_GIVE = 0.4;  // how much of the fingers' stretch widens the palm
  const LENGTH = [0, 0.62, 0.9, 1.0, 0.94, 0.74];  // finger lengths, the middle finger's = 1
  const SKIN = [240, 200, 170];
  const SWEEP_LEAD = 0.25, SWEEP_TAIL = 0.15;  // beats before a glissando the hand gets ready (flat, wrist up) at its first key; and eases out after
  const SWEEP_TIME = 45;  // ms: how closely the palm follows the slide
  // Slow motion: a run slowed down (Learn / Rehearse / Listen below 100%) plays the hands'
  // every move slowed down with it, up to SLOW_MAX times, so the times above are stretched by
  // 1 / speed: the hand travels to the next chord, opens and turns, and each finger reaches and
  // strikes, as at tempo, only slower, which is what a learner wants to watch. The lift and turn
  // of a leap stay as big as at tempo (they go by how fast the hand would be moving at tempo),
  // and grow up to ACCENT more at the slowest, to make the move easy to see.
  const SLOW_MAX = 4, ACCENT = 0.4, SLOW_TAU = 400;  // ms SLOW_TAU: how gently a speed change takes effect
  let slowMo = 1;
  let sweeps = {right: [], left: []};  // hand -> [{b0, b1, from, to}]: glissandos, first and last beat, first and last key
  let byFinger = {right: null, left: null};  // hand -> [finger] -> notes by beat
  const handState = {right: newHand(), left: newHand()};
  let lastFrame = 0, lastAt = 0, beatRate = 0;
  let rangeSet = false;  // keyRange() chose the keys: don't widen them
  const smooth = u => { u = Math.max(0, Math.min(1, u)); return u * u * (3 - 2 * u); };

  // on: how far each finger has gone to a key (0 = resting, 1 = over it or on it);
  // to: where the anchor is heading, itself eased (see glideTo);
  // rest: how far the hand is into a rest (0 = playing, 1 = lifted off the keys)
  // va, vs, vx: how fast the anchor, the spread and each fingertip are moving (pixels a ms)
  function newHand() {
    return {anchor: null, spread: null, to: null, vto: 0, rest: 0, glide: 0, va: 0, vs: 0, x: [0, 0, 0, 0, 0, 0], vx: [0, 0, 0, 0, 0, 0],
            y: [0, 0, 0, 0, 0, 0], press: [0, 0, 0, 0, 0, 0], on: [0, 0, 0, 0, 0, 0]};
  }

  // A critically damped spring: cur going to target at speed vel, to get there in about
  // `time` ms; returns [where it is, how fast] dt ms on.
  function spring(cur, target, vel, time, dt) {
    const w = 2 / time, x = w * dt, e = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
    const change = cur - target, temp = (vel + w * change) * dt;
    return [target + (change + temp) * e, (vel - w * temp) * e];
  }

  // A move that starts as gently as it ends, as an arm's does: cur follows a point that is
  // itself sprung toward target, each over half the time. Returns [cur, vel, the point, its speed].
  function glideTo(cur, vel, to, vto, target, time, dt) {
    [to, vto] = spring(to, target, vto, time / 2, dt);
    [cur, vel] = spring(cur, to, vel, time / 2, dt);
    return [cur, vel, to, vto];
  }

  // The hand that best fits points {f, x, w}: x = anchor + dir·(f−1)·spread, by weighted least
  // squares. With spread given only the anchor is fitted; without, both, when two fingers or more
  // pin the spread down (else null). The thumb passing under the hand says nothing of its spread.
  function fitHand(pts, dir, spread) {
    if (spread === undefined) {
      const two = pts.filter(p => p.f > 1);
      const lo = two.length ? Math.min(...two.map(p => dir * p.x)) : Infinity;
      pts = pts.filter(p => p.f > 1 || dir * p.x < lo);
    }
    let w = 0, mf = 0, mx = 0;
    for (const p of pts) { w += p.w; mf += p.w * dir * (p.f - 1); mx += p.w * p.x; }
    if (!w) return null;
    mf /= w; mx /= w;
    if (spread === undefined) {
      let sxy = 0, sxx = 0;
      for (const p of pts) { const u = dir * (p.f - 1) - mf; sxy += p.w * u * (p.x - mx); sxx += p.w * u * u; }
      if (sxx < 1e-6) return null;
      spread = sxy / sxx;
    }
    return {anchor: mx - mf * spread, spread};
  }

  function indexFingers(keepHands = false) {
    byFinger = {right: null, left: null};
    for (const n of notes) {
      if (!n.f || (n.role !== 'right' && n.role !== 'left')) continue;
      const hand = byFinger[n.role] || (byFinger[n.role] = [[], [], [], [], [], []]);
      hand[n.f].push(n);  // notes are sorted by beat already
    }
    // A glissando's notes (an organ's palm roll-up: no finger, the glissando's number in g) are
    // one slide of the hand from where it starts to where it ends, not fingered notes.
    sweeps = {right: [], left: []};
    const runs = new Map();
    for (const n of notes) {
      if (!n.g || (n.role !== 'right' && n.role !== 'left')) continue;
      const key = n.role + n.g;
      if (!runs.has(key)) runs.set(key, []);
      runs.get(key).push(n);
    }
    for (const list of runs.values()) {
      const role = list[0].role, k = Math.max(1, Math.ceil(list.length / 5));
      const mean = a => Math.round(a.reduce((s, n) => s + n.p, 0) / a.length);
      sweeps[role].push({b0: list[0].b, b1: list[list.length - 1].b, from: mean(list.slice(0, k)), to: mean(list.slice(-k))});
      if (!byFinger[role]) byFinger[role] = [[], [], [], [], [], []];
    }
    if (!keepHands) { handState.right = newHand(); handState.left = newHand(); }
  }

  // The glissando a hand is in at beat `at`, or null: how far along it is (u, 0 to 1), and how
  // much the hand is in the glide (glide: it flattens and lifts its wrist as the slide starts and
  // eases out as it ends).
  function sweepAt(hand, at) {
    for (const s of sweeps[hand]) {
      if (at < s.b0 - SWEEP_LEAD || at > s.b1 + SWEEP_TAIL) continue;
      const u = Math.max(0, Math.min(1, (at - s.b0) / Math.max(0.05, s.b1 - s.b0)));
      return {s, u, glide: smooth((at - s.b0 + SWEEP_LEAD) / SWEEP_LEAD) * (1 - smooth((at - s.b1) / SWEEP_TAIL))};
    }
    return null;
  }
  const hasFingers = () => !!(byFinger.right || byFinger.left);

  // The first of a finger's notes starting after beat
  function after(list, beat) {
    let a = 0, b = list.length;
    while (a < b) { const m = (a + b) >> 1; if (list[m].b <= beat) a = m + 1; else b = m; }
    return a;
  }

  // Where each finger of a hand is going now: {x, black, press, reach, weight} or null (no note
  // near); reach is how far it has gone toward a coming note's key (1 for a note sounding).
  // Also how far the hand is into a rest (out.rest).
  function targets(hand, keys, at, ww) {
    // in beats: a finger goes down a moment before its note, to be at the bottom of the key as
    // it sounds, and stays down long enough to be seen, however short the note
    const early = Math.max(0.02, Math.min(0.12, STRIKE_MS * slowMo * beatRate)), down = Math.min(0.25, DOWN_MS * slowMo * beatRate);
    const out = [null];
    let lastEnd = -Infinity, nextStart = Infinity, sounding = false;
    for (let f = 1; f <= 5; f++) {
      const list = byFinger[hand][f];
      const i = after(list, at + early);
      const prev = list[i - 1], next = list[i];
      if (prev) lastEnd = Math.max(lastEnd, prev.b + prev.d);
      if (next) nextStart = Math.min(nextStart, next.b);
      let pick = null, press = 0, weight = 0, reach = 0;
      let kind = '';
      // a note's finger lifts before the same finger's next note (a repeated key, fast notes),
      // so the press is seen, not smeared into one long hold
      const end = prev ? Math.min(Math.max(prev.b + prev.d, prev.b + down), next ? next.b - Math.min(LIFT_BEATS, 0.4 * (next.b - prev.b)) : Infinity) : 0;
      if (prev && at < end - 0.03) { pick = prev; press = 1; reach = 1; kind = 'now'; sounding = true; }
      else if (next && next.b - at <= LOOK) {
        pick = next; kind = 'next';
        weight = 0.3 + 2 * (1 - (next.b - at) / LOOK);
        reach = smooth((LOOK - (next.b - at)) / (LOOK - ARRIVE));
      }
      const k = pick && keys.get(pick.p);
      out.push(k ? {x: k.x + k.w / 2, black: k.black, press, reach, weight, kind, b: pick.b} : null);
    }
    // What places the hand: the keys it holds now and the next chord it reaches for (notes a
    // beat beyond that belong to the position after); with neither it stays where it was.
    // A held key the hand can't stay on while it leaps to the next chord is let go as it goes.
    for (let f = 1; f <= 5; f++) {
      const t = out[f];
      if (t && t.kind === 'now' && out.some(o => o && o.kind === 'next' && Math.abs(o.x - t.x) > LEAP_KEYS * ww)) out[f] = null;
    }
    const live = out.filter(t => t && t.kind === 'now');
    const soon = out.filter(t => t && t.kind === 'next');
    const first = Math.min(...soon.map(t => t.b));
    for (const t of out) {
      if (!t) continue;
      t.places = t.kind === 'now' || t.b <= first + 1;
    }
    const gap = sounding ? 0 : Math.min(at - lastEnd, nextStart - at);
    out.rest = smooth((gap - REST[0]) / (REST[1] - REST[0]));
    out.wait = beatRate > 0 ? (nextStart - at) / beatRate : Infinity;  // ms to the hand's next note
    return out;
  }

  function updateHand(hand, keys, ww, floor, keyH, at, dt, bound = null) {
    const st = handState[hand], dir = hand === 'right' ? 1 : -1;
    const tg = targets(hand, keys, at, ww);
    // In a glissando no finger plays a key: the hand lies flat, fingers together, and its palm
    // slides along the keys from the first to the last (the coming chord's fingers wait until
    // it's over, so they don't grab for their keys while the palm is still on its way).
    const sw = sweepAt(hand, at), kFrom = sw && keys.get(sw.s.from), kTo = sw && keys.get(sw.s.to);
    const gliding = !!(sw && kFrom && kTo);
    if (gliding) { for (let f = 1; f <= 5; f++) tg[f] = null; tg.rest = 0; }
    // The keys that place the hand, weighted (notes sounding count most), and the ones coming
    // next, which say how far it opens when only one key is down (an arpeggio under a held note).
    // The hand opens for the keys it holds (for the coming chord when it holds none). It sits
    // where those and the coming chord's keys put it: on its way to the next position while it
    // still holds this one, as far as the fingers holding keys can stay on them.
    const held = [], coming = [], near = [];
    for (let f = 1; f <= 5; f++) {
      const t = tg[f];
      if (!t) continue;
      if (t.kind === 'now') held.push({f, x: t.x, w: 1});
      else if (t.places) coming.push({f, x: t.x, w: t.weight});
      else near.push({f, x: t.x, w: t.weight * 0.5});
    }
    const shape = held.length ? held : coming;
    const others = (held.length ? coming.map(p => ({...p, w: p.w * 0.5})) : []).concat(near);
    const close = others.filter(p => shape.some(q => Math.abs(p.x - q.x) <= 9 * ww));
    const fitted = fitHand(shape, dir) || fitHand(shape.concat(close), dir);
    let spread = Math.max(SPREAD[0] * ww, Math.min(SPREAD[1] * ww, fitted ? fitted.spread : ww));
    const place = held.length ? held.concat(coming.map(p => ({...p, w: p.w * AHEAD}))) : coming;
    let anchor = place.length ? fitHand(place, dir, spread).anchor : st.anchor;
    if (gliding) {  // the middle finger rides the slide, the others lie closed up beside it
      const mid = kFrom.x + kFrom.w / 2 + (kTo.x + kTo.w / 2 - kFrom.x - kFrom.w / 2) * sw.u;
      spread = SPREAD[0] * ww;
      anchor = mid - dir * 2 * spread;
    }
    if (held.length && coming.length) {
      let lo = -Infinity, hi = Infinity;
      for (const p of held) {
        const natural = p.x - dir * (p.f - 1) * spread;
        lo = Math.max(lo, natural - HOLD_REACH * ww); hi = Math.min(hi, natural + HOLD_REACH * ww);
      }
      anchor = lo <= hi ? Math.max(lo, Math.min(hi, anchor)) : fitHand(held, dir, spread).anchor;
    }
    if (anchor === null) {  // before the first note: over the hand's first keys
      for (let f = 1; f <= 5 && anchor === null; f++) {
        const n = byFinger[hand][f][0], k = n && keys.get(n.p);
        if (k) anchor = k.x + k.w / 2 - dir * (f - 1) * spread;
      }
      if (anchor === null) return false;
    }
    const ease = tau => 1 - Math.exp(-dt / (tau * slowMo));  // every time here slowed with the run
    const was = st.anchor;
    if (st.anchor === null) { st.anchor = st.to = anchor; st.spread = spread; }
    else {
      const time = Math.max(HAND_TIME[0], Math.min(held.length ? HAND_HELD : HAND_TIME[1], tg.wait * HAND_SHARE / slowMo));
      if (gliding) { [st.anchor, st.va] = spring(st.anchor, anchor, st.va, SWEEP_TIME * slowMo, dt); st.to = st.anchor; st.vto = st.va; }
      else [st.anchor, st.va, st.to, st.vto] = glideTo(st.anchor, st.va, st.to, st.vto, anchor, time * slowMo, dt);
      [st.spread, st.vs] = spring(st.spread, spread, st.vs, SPREAD_TIME * slowMo, dt);
    }
    st.rest += (tg.rest - st.rest) * ease(150);
    st.glide += ((gliding ? sw.glide : 0) - st.glide) * ease(60);
    const whiteY = floor + keyH * TIP_WHITE, blackY = floor + keyH * TIP_BLACK;
    const hit = [null, null, null, null, null, null];
    for (let f = 1; f <= 5; f++) {
      const natural = st.anchor + dir * (f - 1) * st.spread;
      let t = tg[f];
      // a note for a later position stays out of reach, except the thumb passing under the
      // hand (or a finger going over it), which reaches further
      const off = (t ? t.x - natural : 0) * dir, reach = f === 1 ? (off > 0 ? 4.5 : 1.5) : (off < 0 ? 3.5 : 2);
      if (t && !t.press && Math.abs(off) > reach * ww) t = null;
      hit[f] = t;
    }
    // Resting fingers lie beside the ones on keys, a relaxed key or so apart (the thumb a little
    // further from the index); with no key down, the hand closes up around where it is. A finger
    // going to its next key leaves its resting place for it as the note comes.
    const relaxed = Math.max(RELAXED[0] * ww, Math.min(RELAXED[1] * ww, st.spread));
    const stepAfter = f => (f === 1 ? THUMB_GAP * ww : relaxed);  // from finger f to f + 1
    const between = (a, b) => { let s = 0; for (let k = Math.min(a, b); k < Math.max(a, b); k++) s += stepAfter(k); return s; };
    const closed = f => st.anchor + dir * (2.5 * st.spread - THUMB_GAP * ww - 1.5 * relaxed + between(1, f));
    const resting = ref => {
      const out = [0];
      const known = [1, 2, 3, 4, 5].filter(f => ref[f] !== null);
      for (let f = 1; f <= 5; f++) {
        if (ref[f] !== null) { out.push(ref[f]); continue; }
        const lo = known.filter(k => k < f).pop(), hi = known.find(k => k > f);
        if (!known.length) out.push(closed(f));
        else if (lo === undefined) out.push(ref[hi] - dir * between(f, hi));
        else if (hi === undefined) out.push(ref[lo] + dir * between(lo, f));
        else out.push(ref[lo] + (ref[hi] - ref[lo]) * between(lo, f) / between(lo, hi));
      }
      return out;
    };
    const ref = [null, null, null, null, null, null];
    for (let f = 1; f <= 5; f++) if (hit[f] && hit[f].press) ref[f] = hit[f].x;
    const first = resting(ref);
    for (let f = 1; f <= 5; f++) {
      if (hit[f] && !hit[f].press) ref[f] = first[f] + (hit[f].x - first[f]) * hit[f].reach;
    }
    const want = resting(ref);
    // Fingers 2 to 5 never cross or lie on each other: one not pressing steps aside (both
    // halfway when neither is), and a resting thumb stays on its side of the index.
    const fixed = f => !!(hit[f] && hit[f].press);
    const gap = MIN_GAP * Math.min(ww, st.spread);
    for (let pass = 0; pass < 4; pass++) {
      for (let f = 2; f <= 4; f++) {
        const short = gap - dir * (want[f + 1] - want[f]);
        if (short <= 0 || (fixed(f) && fixed(f + 1))) continue;
        const share = fixed(f) ? 0 : fixed(f + 1) ? 1 : 0.5;
        want[f] -= dir * short * share;
        want[f + 1] += dir * short * (1 - share);
      }
    }
    if (!hit[1] && dir * (want[2] - want[1]) < gap) want[1] = want[2] - dir * gap;
    // Keeping out of the other hand's way (bound: as near it as this hand's fingers may come):
    // with no key down the whole hand moves aside, else the fingers not on keys keep back.
    if (bound !== null) {
      const past = f => dir * (bound - want[f]);
      if (![1, 2, 3, 4, 5].some(fixed)) {
        const most = Math.max(0, ...[1, 2, 3, 4, 5].map(past));
        for (let f = 1; f <= 5; f++) want[f] += dir * most;
        st.anchor += dir * most * ease(HAND_TAU);
        st.to += dir * most * ease(HAND_TAU);
      } else {
        for (let f = 1; f <= 5; f++) if (!fixed(f) && past(f) > 0) want[f] = bound;
      }
    }
    for (let f = 1; f <= 5; f++) {
      const t = hit[f], x = want[f], y = t && t.black && t.reach > 0.5 ? blackY : whiteY;
      if (!st.x[f]) { st.x[f] = x; st.y[f] = y; }
      // a finger going to a key or on one gets there quickly; one at rest is carried along
      // with the hand and settles into its place slowly, so the fingers don't fidget
      const busy = t ? Math.max(t.press, t.reach) : 0;
      if (was !== null) st.x[f] += (st.anchor - was) * (1 - busy);
      let time = (FINGER_TIME[1] + (FINGER_TIME[0] - FINGER_TIME[1]) * busy) * slowMo;
      if (t && t.kind === 'next' && beatRate > 0) time = Math.max(FINGER_QUICK * slowMo, Math.min(time, (t.b - at) / beatRate * HAND_SHARE));
      else if (t && t.press) time = Math.min(time, FINGER_QUICK * slowMo);
      [st.x[f], st.vx[f]] = spring(st.x[f], x, st.vx[f], time, dt);
      st.y[f] += (y - st.y[f]) * ease(80);
      const press = t ? t.press : 0;
      st.press[f] += (press - st.press[f]) * ease(press > st.press[f] ? 22 : 70);  // down fast, up slower
      st.on[f] += ((t ? t.reach : 0) - st.on[f]) * ease(60);
    }
    // Fingers 2 to 5 keep their order on the way, too: one hurrying to its key doesn't pass
    // through a neighbour still settling (the one on a key stays, the other gives way)
    const room = 0.45 * Math.min(ww, st.spread);
    for (let f = 2; f <= 4; f++) {
      const short = room - dir * (st.x[f + 1] - st.x[f]);
      if (short <= 0 || (fixed(f) && fixed(f + 1))) continue;
      const share = fixed(f) ? 0 : fixed(f + 1) ? 1 : 0.5;
      st.x[f] -= dir * short * share;
      st.x[f + 1] += dir * short * (1 - share);
    }
    // and a thumb with no key to go to stays out from under the index
    if (!hit[1] && dir * (st.x[2] - st.x[1]) < 1.2 * ww) st.x[1] = st.x[2] - dir * 1.2 * ww;
    return true;
  }

  // The 3D hands (hands3d.js: three.js and the WebXR hand models) load the first time hands
  // are drawn. Nothing is drawn while they load; if they can't (no WebGL, a file missing) the
  // 2D hands below stand in.
  let hands3d, loading3d = null;
  function threeD() {
    if (hands3d === undefined && !loading3d) {
      loading3d = import('./hands3d.js').then(m => m.create()).then(h => { hands3d = h; }, e => {
        console.warn('3D hands unavailable, drawing flat ones:', e);
        hands3d = null;
      });
    }
    return hands3d;
  }

  let quietHands = false;  // frameAt's quiet frames: the hands move but aren't drawn
  function drawHands(now, keys, ww, floor, keyH, at) {
    const dt = lastFrame ? Math.min(100, now - lastFrame) : 16;
    // how fast the piece is going (beats a ms), from the frames that moved it forward
    if (lastFrame && now > lastFrame && at > lastAt && at - lastAt < 1) {
      beatRate += ((at - lastAt) / (now - lastFrame) - beatRate) * (beatRate ? 0.2 : 1);
    }
    lastFrame = now; lastAt = at;
    const slowTo = Math.max(1, Math.min(SLOW_MAX, 1 / (cur.speed || 1)));
    slowMo += (slowTo - slowMo) * (1 - Math.exp(-dt / SLOW_TAU));
    // The hands keep out of each other's way: the one less busy (fewer fingers on or going to
    // keys, last frame; a resting hand least) stays CLEAR white keys from the other's
    // fingertips (unless they've crossed, as in a crossing passage); hands as busy as each
    // other meet in 3D, one over the other.
    const bound = {left: null, right: null};
    const L = handState.left, R = handState.right;
    if (['left', 'right'].every(h => byFinger[h] && !hidden.has(h) && handState[h].anchor !== null)) {
      const tips = st => st.x.slice(1), mean = a => a.reduce((s, v) => s + v, 0) / a.length;
      const down = st => st.on.reduce((s, v) => s + v, 0) - 3 * st.rest;
      if (mean(tips(L)) < mean(tips(R))) {
        if (down(L) < down(R) - 0.5) bound.left = Math.min(...tips(R)) - CLEAR * ww;
        else if (down(R) < down(L) - 0.5) bound.right = Math.max(...tips(L)) + CLEAR * ww;
      }
    }
    const list = [];
    for (const hand of ['left', 'right']) {
      if (!byFinger[hand] || hidden.has(hand)) continue;
      if (!updateHand(hand, keys, ww, floor, keyH, at, dt, bound[hand])) continue;
      list.push({hand, alpha: played.has(hand) ? 1 : 0.42});
    }
    const three = threeD();
    if (three === undefined || quietHands) return;
    if (!three) {
      for (const h of list) drawHand(h.hand, ww, floor, keyH, h.alpha);
      return;
    }
    const view = {w: width, h: height, dpr: window.devicePixelRatio || 1, floor, keyH, ww, seatX: width / 2, dt,
                  whiteY: floor + keyH * TIP_WHITE, blackY: floor + keyH * TIP_BLACK};
    const labels = three.draw(ctx, view, list.map(({hand, alpha}) => {
      const st = handState[hand];
      const tips = [null];
      for (let f = 1; f <= 5; f++) tips.push({x: st.x[f], y: st.y[f], press: st.press[f], on: st.on[f]});
      return {hand, alpha, tint: COLORS[hand] || OTHER, tips, rest: st.rest, glide: st.glide, speed: st.va * 1000 * slowMo,
              slow: slowMo, accent: 1 + ACCENT * (slowMo - 1) / (SLOW_MAX - 1)};
    }));
    // each finger's number on its first bone
    const size = Math.round(Math.max(9, Math.min(14, ww * 0.34)));
    ctx.font = `700 ${size}px "Segoe UI", Arial, sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (const l of labels) {
      ctx.fillStyle = `rgba(58,30,20,${0.72 * l.alpha})`;
      ctx.fillText(String(l.f), l.x, l.y);
    }
    ctx.textBaseline = 'alphabetic';
  }

  const shade = (c, k) => c.map(v => Math.max(0, Math.min(255, Math.round(v + k))));
  const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

  // A segment of a finger, shaded across its width like a cylinder.
  function bone(x1, y1, x2, y2, width, base, alpha) {
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len, ny = dx / len;
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, half = width / 2;
    const g = ctx.createLinearGradient(mx - nx * half, my - ny * half, mx + nx * half, my + ny * half);
    const light = nx < 0 ? 1 : -1;  // the side facing the upper left gets the highlight
    const stops = [rgb(shade(base, -55), alpha), rgb(shade(base, 30), alpha), rgb(base, alpha), rgb(shade(base, -70), alpha)];
    if (light < 0) stops.reverse();
    g.addColorStop(0, stops[0]); g.addColorStop(0.3, stops[1]); g.addColorStop(0.6, stops[2]); g.addColorStop(1, stops[3]);
    ctx.strokeStyle = g;
    ctx.lineWidth = width;
    ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  }

  function drawHand(hand, ww, floor, keyH, alpha) {
    const st = handState[hand], dir = hand === 'right' ? 1 : -1;
    const tint = COLORS[hand] || OTHER;
    const skin = mix(SKIN, tint, hand === 'right' ? 0.06 : 0.1);
    const L = keyH * 0.62;  // the middle finger's length
    const knuckleY = floor + keyH * 0.8 + L * 0.95;
    const width = Math.max(6, Math.min(ww * 0.66, keyH * 0.2));
    // the palm widens with part of the fingers' stretch (an octave opens it about a third)
    const pw = ww * (1 + PALM_GIVE * Math.max(0, (st.spread || ww) / ww - 1));
    // knuckles: along the palm's top edge, a little under a white key apart, the outer ones lower
    const kn = [null, null];
    for (let f = 2; f <= 5; f++) {
      kn.push({x: st.anchor + dir * ((f - 1) * pw * 0.9 + ww * 0.12), y: knuckleY + [0, 0, 0.06, 0, 0.04, 0.16][f] * L});
    }
    const thumbBase = {x: kn[2].x - dir * pw * 0.75, y: knuckleY + L * 0.62};
    const wristY = knuckleY + L * 1.7;

    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,.45)';
    ctx.shadowBlur = Math.max(4, ww * 0.25);
    ctx.shadowOffsetX = ww * 0.08; ctx.shadowOffsetY = ww * 0.14;

    // the palm, from the outer knuckle round to the thumb, into the wrist under the keyboard
    const outer = {x: kn[5].x + dir * width * 0.55, y: kn[5].y};
    const pg = ctx.createRadialGradient(st.anchor + dir * pw * 1.2, knuckleY + L * 0.35, ww * 0.3,
      st.anchor + dir * pw * 1.5, knuckleY + L * 0.6, pw * 3.6);
    pg.addColorStop(0, rgb(shade(skin, 22), alpha)); pg.addColorStop(0.7, rgb(skin, alpha)); pg.addColorStop(1, rgb(shade(skin, -60), alpha));
    ctx.fillStyle = pg;
    ctx.beginPath();
    ctx.moveTo(kn[2].x - dir * width * 0.5, kn[2].y - width * 0.2);
    ctx.quadraticCurveTo((kn[2].x + outer.x) / 2, knuckleY - width * 0.45, outer.x, outer.y);
    ctx.quadraticCurveTo(outer.x + dir * ww * 0.25, knuckleY + L * 0.8, outer.x - dir * ww * 0.1, wristY);
    ctx.lineTo(thumbBase.x + dir * ww * 0.55, wristY);
    ctx.quadraticCurveTo(thumbBase.x - dir * ww * 0.2, knuckleY + L * 1.0, thumbBase.x - dir * width * 0.25, thumbBase.y);
    ctx.closePath();
    ctx.fill();

    // fingers, outer to inner so the index lies over its neighbours, the thumb last
    // the thumb under the hand when it passes under (its tip beyond the index's)
    const under = (st.x[1] - st.x[2]) * dir > -ww * 0.3;
    const order = under ? [1, 5, 4, 3, 2] : [5, 4, 3, 2, 1];
    const tips = [];
    for (const f of order) {
      const base = f === 1 ? thumbBase : kn[f];
      const p = st.press[f];
      const tipX = st.x[f], tipY = st.y[f] + p * keyH * 0.05;
      const w = (f === 1 ? width * 1.12 : f === 5 ? width * 0.86 : width) * (1 - 0.06 * p);
      const c = shade(skin, -14 * p - (f === 1 ? 6 : 0));
      ctx.shadowOffsetY = ww * (0.14 - 0.1 * p);  // a pressed finger sits on its key
      // three bones (two for the thumb), the joints bending a little outward as it curls
      const segs = f === 1 ? [0.55, 1] : [0.46, 0.76, 1];
      const bend = (f === 1 ? -dir : 0) * ww * 0.15;
      let px = base.x, py = base.y;
      for (let i = 0; i < segs.length; i++) {
        const t = segs[i];
        const curve = Math.sin(Math.PI * t) * bend;
        const x = base.x + (tipX - base.x) * t + curve, y = base.y + (tipY - base.y) * t;
        bone(px, py, x, y, w * (1 - 0.12 * t), c, alpha);
        px = x; py = y;
      }
      tips.push({f, x: tipX, y: tipY, w, p, base});
    }
    ctx.restore();

    // nails, the finger numbers, and a ring where a finger presses
    for (const t of tips) {
      const len = Math.hypot(t.x - t.base.x, t.y - t.base.y) || 1;
      const ux = (t.x - t.base.x) / len, uy = (t.y - t.base.y) / len;
      ctx.save();
      ctx.translate(t.x - ux * t.w * 0.18, t.y - uy * t.w * 0.18);
      ctx.rotate(Math.atan2(uy, ux) + Math.PI / 2);
      ctx.fillStyle = `rgba(255,236,228,${0.55 * alpha})`;
      ctx.beginPath(); ctx.ellipse(0, 0, t.w * 0.28, t.w * 0.34, 0, 0, 2 * Math.PI); ctx.fill();
      ctx.restore();
      if (t.p > 0.05) {
        ctx.globalAlpha = t.p * alpha;
        ctx.strokeStyle = rgb(lighter(tint, 40));
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(t.x, t.y, t.w * 0.62, 0, 2 * Math.PI); ctx.stroke();
        ctx.globalAlpha = 1;
      }
      const size = Math.max(9, Math.min(15, t.w * 0.62));
      const nx = t.x - ux * len * 0.42, ny = t.y - uy * len * 0.42;  // on the middle of the finger
      ctx.font = `700 ${Math.round(size)}px "Segoe UI", Arial, sans-serif`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = `rgba(40,26,20,${0.8 * alpha})`;
      ctx.fillText(String(t.f), nx, ny);
      ctx.textBaseline = 'alphabetic';
    }
  }

  // -- drawing off the page (python -m midi_coach.hands_render) -----------------
  // A frame of the piece at `beat`, drawn as if the clock read `now` (ms), so the hands ease
  // between frames as they do while it plays; quiet frames move the hands without drawing them.
  // Returns where the keys are and each hand's fingertips.
  function frameAt(beat, now, quiet = false) {
    Object.assign(cur, {target: beat, bps: 0, at: now, until: null, offset: 0, seen: true});
    pan = 0;
    quietHands = quiet;
    try { draw(now); } finally { quietHands = false; }
    if (quiet) return null;
    const hands = {};
    for (const hand of ['left', 'right']) {
      const st = handState[hand];
      if (!byFinger[hand] || st.anchor === null) continue;
      const r = v => Math.round(v * 100) / 100;
      hands[hand] = {anchor: r(st.anchor), spread: r(st.spread), rest: r(st.rest), tips: [1, 2, 3, 4, 5].map(f =>
        ({f, x: r(st.x[f]), y: r(st.y[f]), press: r(st.press[f]), on: r(st.on[f])}))};
    }
    const dbg = (hands3d && hands3d.debug) || {};
    return {beat, layout, hands, misses: dbg.misses || [], pose: dbg.pose || []};
  }
  // The keyboard from lo to hi (MIDI pitches) instead of the piece's own range
  function keyRange(a, b) { lo = a; hi = b; rangeSet = true; }
  // Resolves to '3d' when the 3D hands are drawn, '2d' when the flat ones stand in
  function handsLoaded() { threeD(); return loading3d.then(() => (hands3d ? '3d' : '2d')); }

  return {score, update, event, parts, show, showNames, names: () => names,
          showFingers, fingers: () => fingerNumbers, showHands, hands: () => handsOn,
          frameAt, keyRange, handsLoaded};
})();
