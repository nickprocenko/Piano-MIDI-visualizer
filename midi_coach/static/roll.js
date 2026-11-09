// Falling notes: the web visualizer's view of a piece, on the coach page as an option to the
// sheet (View: Sheet / Falling notes / Both). The score's notes fall onto a keyboard as the
// coach's cursor moves, in the visualizer's hand colours; hits turn green and misses red as the
// run grades them, and the keys you hold light up (green if the piece wants them, red if not).
// It reads the same event stream as the sheet: the notes come with GET score
// ([beat, length in beats, pitch, role]); cursorBeat, marks, heat, flash, session and keys
// arrive through coachRoll.event().
"use strict";
window.coachRoll = (() => {
  const canvas = document.getElementById('roll');
  const ctx = canvas.getContext('2d');
  // Right / left in the visualizer's first two track colours
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
    notes = (payload.notes || []).map(([b, d, p, role]) => ({b, d, p, role, mark: ''}))
      .sort((x, y) => x.b - y.b || x.p - y.p);
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
    const keyH = Math.max(50, Math.min(h * 0.26, (w / whites) * 5.2));
    const floor = h - keyH;
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
    ctx.fillText(text, k.x + k.w / 2, bottom - 4);
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

  return {score, event, parts, show, showNames, names: () => names};
})();
