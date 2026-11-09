// Falling notes: the web visualizer's view of a piece, on the coach page as an option to the
// sheet (View: Sheet / Falling notes / Both). The score's notes fall onto a keyboard as the
// coach's cursor moves, in the visualizer's hand colours; hits turn green and misses red as the
// run grades them, and the keys you hold light up (green if the piece wants them, red if not).
// It reads the same event stream as the sheet: the notes come with GET score
// ([beat, length in beats, pitch, role, finger]); cursorBeat, marks, heat, flash, session and keys
// arrive through coachRoll.event().
// Learn with hands (Sheet ▸ Finger numbers / Hands on the keys): each hand's note carries the
// finger the coach suggests (fingering.py, 1 = thumb ... 5), printed on the falling note, and a
// stylized pair of hands plays the piece on the keyboard with those fingers, moving ahead to the
// keys coming up and pressing each one as the cursor reaches it.
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
  const cur = {target: 0, bps: 0, at: 0, until: null, ease: EASE_MS.learn, offset: 0, seen: false};
  let shown = false, raf = 0, width = 0, height = 0;
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
    notes = (payload.notes || []).map(([b, d, p, role, f]) => ({b, d, p, role, f: f || 0, mark: ''}))
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
      const steady = cur.bps > 0 && cur.until === null;  // Rehearse / Listen: moving at tempo
      cur.ease = steady ? EASE_MS.steady : EASE_MS.learn;
      cur.offset = drawn === null ? 0 : drawn - cursorBase(now);
      if (Math.abs(cur.offset) > (steady ? SNAP_BEATS.steady : SNAP_BEATS.learn)) cur.offset = 0;
    } else if (m.type === 'session' && !m.active) {
      cur.target = cursorAt(now); cur.at = now; cur.bps = 0; cur.until = null; cur.offset = 0;
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

  function keyboard(keyH) {
    let whites = 0;
    for (let p = lo; p <= hi; p++) if (!BLACK.has(p % 12)) whites++;
    const ww = width / whites, bw = ww * 0.6;
    const keys = new Map();
    let i = 0;
    for (let p = lo; p <= hi; p++) {
      if (BLACK.has(p % 12)) keys.set(p, {x: i * ww - bw / 2, w: bw, black: true, h: keyH * 0.62});
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
    let whites = 0;
    for (let p = lo; p <= hi; p++) if (!BLACK.has(p % 12)) whites++;
    const withHands = handsOn && hasFingers();
    const keyH = Math.max(50, Math.min(h * (withHands ? 0.2 : 0.26), (w / whites) * 5.2));
    const room = withHands ? keyH * HAND_ROOM : 0;  // under the keys: where the palms rest
    const floor = h - keyH - room;
    const ppb = floor / span;  // pixels per beat
    ppbShown = ppb;
    const beat = cursorAt(now) + pan;
    const keys = keyboard(keyH);
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
  // Stylized, lit from the upper left, seen from the player's seat: fingertips on the keys,
  // palms on the player's side. Each finger goes to the key of its note sounding now, or leans
  // toward its next note; the hand sits where its fingers' keys put it, and glides between
  // positions. Fingers without a note rest a white key apart. All of it eased per frame.

  const HAND_ROOM = 0.75;  // keyboard heights under the keys, for the palms
  const LOOK = 1.5;  // beats ahead a finger leans toward its next note
  const LENGTH = [0, 0.62, 0.9, 1.0, 0.94, 0.74];  // finger lengths, the middle finger's = 1
  const SKIN = [240, 200, 170];
  let byFinger = {right: null, left: null};  // hand -> [finger] -> notes by beat
  const handState = {right: newHand(), left: newHand()};
  let lastFrame = 0;

  function newHand() { return {anchor: null, x: [0, 0, 0, 0, 0, 0], y: [0, 0, 0, 0, 0, 0], press: [0, 0, 0, 0, 0, 0]}; }

  function indexFingers() {
    byFinger = {right: null, left: null};
    for (const n of notes) {
      if (!n.f || (n.role !== 'right' && n.role !== 'left')) continue;
      const hand = byFinger[n.role] || (byFinger[n.role] = [[], [], [], [], [], []]);
      hand[n.f].push(n);  // notes are sorted by beat already
    }
    handState.right = newHand(); handState.left = newHand();
  }
  const hasFingers = () => !!(byFinger.right || byFinger.left);

  // The first of a finger's notes starting after beat
  function after(list, beat) {
    let a = 0, b = list.length;
    while (a < b) { const m = (a + b) >> 1; if (list[m].b <= beat) a = m + 1; else b = m; }
    return a;
  }

  // Where each finger of a hand is going now: {x, black, press, weight} or null (no note near).
  function targets(hand, keys, at) {
    const out = [null];
    for (let f = 1; f <= 5; f++) {
      const list = byFinger[hand][f];
      const i = after(list, at + 0.02);
      const prev = list[i - 1], next = list[i];
      let pick = null, press = 0, weight = 0;
      let kind = '';
      if (prev && at < prev.b + prev.d - 0.03) { pick = prev; press = 1; kind = 'now'; }  // sounding
      else if (next && next.b - at <= LOOK) { pick = next; kind = 'next'; weight = 0.3 + 2 * (1 - (next.b - at) / LOOK); }
      else if (prev && at - (prev.b + prev.d) <= 1) { pick = prev; kind = 'past'; weight = 0.25; }
      const k = pick && keys.get(pick.p);
      out.push(k ? {x: k.x + k.w / 2, black: k.black, press, weight, kind, b: pick.b} : null);
    }
    // What places the hand: the keys it holds now; else the next chord it reaches for (notes
    // a beat beyond that belong to the position after); else where it last played.
    const live = out.filter(t => t && t.kind === 'now');
    const soon = out.filter(t => t && t.kind === 'next');
    const first = Math.min(...soon.map(t => t.b));
    for (const t of out) {
      if (!t) continue;
      t.places = live.length ? t.kind === 'now' : soon.length ? t.kind === 'next' && t.b <= first + 1 : true;
    }
    return out;
  }

  function updateHand(hand, keys, ww, floor, keyH, at, dt) {
    const st = handState[hand], dir = hand === 'right' ? 1 : -1;
    const tg = targets(hand, keys, at);
    // The thumb's place each finger's key asks for, weighted: notes sounding count most.
    let sum = 0, wsum = 0;
    for (let f = 1; f <= 5; f++) {
      const t = tg[f];
      if (!t || !t.places) continue;
      const w = t.kind === 'now' ? 1 : t.weight;
      sum += w * (t.x - dir * (f - 1) * ww); wsum += w;
    }
    let anchor = wsum ? sum / wsum : st.anchor;
    if (anchor === null) {  // before the first note: over the hand's first keys
      for (let f = 1; f <= 5 && anchor === null; f++) {
        const n = byFinger[hand][f][0], k = n && keys.get(n.p);
        if (k) anchor = k.x + k.w / 2 - dir * (f - 1) * ww;
      }
      if (anchor === null) return false;
    }
    const ease = tau => 1 - Math.exp(-dt / tau);
    st.anchor = st.anchor === null ? anchor : st.anchor + (anchor - st.anchor) * ease(110);
    const whiteY = floor + keyH * 0.8, blackY = floor + keyH * 0.45;
    for (let f = 1; f <= 5; f++) {
      const natural = st.anchor + dir * (f - 1) * ww;
      let t = tg[f];
      // a note for a later position stays out of reach, except the thumb passing under the
      // hand (or a finger going over it), which reaches further
      const off = (t ? t.x - natural : 0) * dir, reach = f === 1 ? (off > 0 ? 4.5 : 1.5) : (off < 0 ? 3.5 : 2);
      if (t && !t.press && Math.abs(off) > reach * ww) t = null;
      const x = t ? t.x : natural, y = t && t.black ? blackY : whiteY;
      if (!st.x[f]) { st.x[f] = x; st.y[f] = y; }
      st.x[f] += (x - st.x[f]) * ease(t && t.press ? 45 : 80);
      st.y[f] += (y - st.y[f]) * ease(80);
      st.press[f] += ((t ? t.press : 0) - st.press[f]) * ease(35);
    }
    return true;
  }

  function drawHands(now, keys, ww, floor, keyH, at) {
    const dt = lastFrame ? Math.min(100, now - lastFrame) : 16;
    lastFrame = now;
    for (const hand of ['left', 'right']) {
      if (!byFinger[hand] || hidden.has(hand)) continue;
      if (!updateHand(hand, keys, ww, floor, keyH, at, dt)) continue;
      drawHand(hand, ww, floor, keyH, played.has(hand) ? 0.95 : 0.42);
    }
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
    // knuckles: along the palm's top edge, a little under a white key apart, the outer ones lower
    const kn = [null, null];
    for (let f = 2; f <= 5; f++) {
      kn.push({x: st.anchor + dir * ((f - 1) * ww * 0.9 + ww * 0.12), y: knuckleY + [0, 0, 0.06, 0, 0.04, 0.16][f] * L});
    }
    const thumbBase = {x: kn[2].x - dir * ww * 0.75, y: knuckleY + L * 0.62};
    const wristY = knuckleY + L * 1.7;

    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,.45)';
    ctx.shadowBlur = Math.max(4, ww * 0.25);
    ctx.shadowOffsetX = ww * 0.08; ctx.shadowOffsetY = ww * 0.14;

    // the palm, from the outer knuckle round to the thumb, into the wrist under the keyboard
    const outer = {x: kn[5].x + dir * width * 0.55, y: kn[5].y};
    const pg = ctx.createRadialGradient(st.anchor + dir * ww * 1.2, knuckleY + L * 0.35, ww * 0.3,
      st.anchor + dir * ww * 1.5, knuckleY + L * 0.6, ww * 3.6);
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

  return {score, event, parts, show, showNames, names: () => names,
          showFingers, fingers: () => fingerNumbers, showHands, hands: () => handsOn};
})();
