// Guitar view: the chords heard on the radio as a note highway. Six string lanes run away from
// you in perspective; each chord comes down them as a slab with its name, the fret to press on
// each string, and x for strings left out, and is struck at the bright line. Below it, chord
// boxes show the shape now and the one after. Chord shapes come from a table of open chords and
// movable barre shapes (the song's slash bass is dropped: the shape is the plain chord).
"use strict";
(() => {
  // strings, low E to high e
  const COLORS = ['#ff6b6b', '#ffb347', '#f6e05e', '#5ad19a', '#4cc9f0', '#b794f6'];
  const PC = {C: 0, 'C#': 1, Db: 1, D: 2, 'D#': 3, Eb: 3, E: 4, F: 5, 'F#': 6, Gb: 6, G: 7, 'G#': 8, Ab: 8, A: 9, 'A#': 10, Bb: 10, B: 11};

  // Open shapes by chord name; frets low E to high e, -1 = not played
  const OPEN = {
    C: [-1, 3, 2, 0, 1, 0], D: [-1, -1, 0, 2, 3, 2], E: [0, 2, 2, 1, 0, 0], G: [3, 2, 0, 0, 0, 3], A: [-1, 0, 2, 2, 2, 0],
    Am: [-1, 0, 2, 2, 1, 0], Dm: [-1, -1, 0, 2, 3, 1], Em: [0, 2, 2, 0, 0, 0],
    C7: [-1, 3, 2, 3, 1, 0], D7: [-1, -1, 0, 2, 1, 2], E7: [0, 2, 0, 1, 0, 0], G7: [3, 2, 0, 0, 0, 1], A7: [-1, 0, 2, 0, 2, 0], B7: [-1, 2, 1, 2, 0, 2],
    Am7: [-1, 0, 2, 0, 1, 0], Dm7: [-1, -1, 0, 2, 1, 1], Em7: [0, 2, 0, 0, 0, 0],
    Cmaj7: [-1, 3, 2, 0, 0, 0], Fmaj7: [-1, -1, 3, 2, 1, 0], Gmaj7: [3, 2, 0, 0, 0, 2], Amaj7: [-1, 0, 2, 1, 2, 0], Dmaj7: [-1, -1, 0, 2, 2, 2],
    Asus2: [-1, 0, 2, 2, 0, 0], Asus4: [-1, 0, 2, 2, 3, 0], Dsus2: [-1, -1, 0, 2, 3, 0], Dsus4: [-1, -1, 0, 2, 3, 3], Esus4: [0, 2, 2, 2, 0, 0],
    Cadd9: [-1, 3, 2, 0, 3, 0], Gadd9: [3, 0, 0, 2, 0, 3],
  };
  // Movable shapes: offsets from the root fret f, rooted on the low E string or on the A string
  const E_SHAPE = {
    '': f => [f, f + 2, f + 2, f + 1, f, f], m: f => [f, f + 2, f + 2, f, f, f], 7: f => [f, f + 2, f, f + 1, f, f],
    m7: f => [f, f + 2, f, f, f, f], maj7: f => [f, f + 2, f + 1, f + 1, f, f], sus4: f => [f, f + 2, f + 2, f + 2, f, f],
    5: f => [f, f + 2, f + 2, -1, -1, -1],
  };
  const A_SHAPE = {
    '': f => [-1, f, f + 2, f + 2, f + 2, f], m: f => [-1, f, f + 2, f + 2, f + 1, f], 7: f => [-1, f, f + 2, f, f + 2, f],
    m7: f => [-1, f, f + 2, f, f + 1, f], maj7: f => [-1, f, f + 2, f + 1, f + 2, f], sus4: f => [-1, f, f + 2, f + 2, f + 3, f],
    sus2: f => [-1, f, f + 2, f + 2, f, f], 5: f => [-1, f, f + 2, f + 2, -1, -1],
  };

  // 'F#m7/C#' -> {root: 6, quality: 'm7', name: 'F#m7'}
  function parse(name) {
    const m = /^([A-G][b#]?)([^/]*)(?:\/.*)?$/.exec(name || '');
    if (!m || !(m[1] in PC)) return null;
    let q = m[2];
    if (q === 'maj' || q === 'M' || q === '') q = '';
    else if (/^(m|min|-)$/.test(q)) q = 'm';
    else if (/^(maj7|M7|maj9|M9)$/.test(q)) q = 'maj7';
    else if (/^(m7|min7|-7|m9|m11|m6|min9)$/.test(q)) q = 'm7';
    else if (/^(7|9|11|13|7sus4)$/.test(q)) q = '7';
    else if (/^(sus4|sus)$/.test(q)) q = 'sus4';
    else if (q === 'sus2') q = 'sus2';
    else if (q === '5') q = '5';
    else if (/^(6|add9|add2|2)$/.test(q)) q = q === '6' ? '' : 'add9';
    else if (/^(dim|dim7|m7b5|°)/.test(q)) q = 'm';
    else q = /^m(?!aj)/.test(q) ? 'm' : '';
    return {root: PC[m[1]], quality: q, key: m[1] + q};
  }

  // {frets: [6], base: lowest fretted position} for a chord name, or null
  function shape(name) {
    const c = parse(name);
    if (!c) return null;
    let frets = OPEN[c.key] || (c.quality === 'add9' ? OPEN[c.key.replace('add9', '')] : null);  // add9: its own shape, else the plain chord
    if (!frets) {
      const q = c.quality === 'add9' ? '' : c.quality;
      const fe = (c.root - 4 + 12) % 12 || 12, fa = (c.root - 9 + 12) % 12 || 12;
      const e = E_SHAPE[q] ? {f: fe, make: E_SHAPE[q]} : null, a = A_SHAPE[q] ? {f: fa, make: A_SHAPE[q]} : null;
      const pick = e && (!a || fe <= fa + 1) ? e : a || e;
      frets = pick ? pick.make(pick.f) : (q.startsWith('m') ? E_SHAPE.m : E_SHAPE['']) (fe);
    }
    const fretted = frets.filter(f => f > 0);
    return {frets, base: fretted.length ? Math.min(...fretted) : 0, name};
  }

  // -- drawing -----------------------------------------------------------------------------------
  const WINDOW = 7;        // seconds of chords shown ahead
  const K = 4;             // perspective strength
  const PMIN = 1 / (1 + K);
  const cache = new Map();
  const shapeOf = n => { if (!cache.has(n)) cache.set(n, shape(n)); return cache.get(n); };

  function draw(canvas, t, segs, live, now) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const bg = ctx.createLinearGradient(0, 0, 0, h);
    bg.addColorStop(0, '#07080d'); bg.addColorStop(1, '#10121b');
    ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

    // the chord boxes sit under the highway; the strike line is just above them
    const bh = Math.max(64, Math.min(h * 0.3, 170)), bw = Math.min(150, w * 0.22, bh * 0.95), by = h - bh - 12;
    const y0 = h * 0.02, y1 = Math.max(y0 + 60, Math.min(h * 0.66, by - Math.min(44, h * 0.12)));   // far end; strike line
    const cx = w / 2;
    const nearW = Math.min(w * 0.62, 760, Math.max(300, (y1 - y0) * 2.4)), farW = nearW * 0.16;   // lane field width at the strike line / far end
    // time ahead (s) -> screen fraction 0 (far) .. 1 (strike line)
    const frac = dt => { const p = 1 / (1 + K * Math.max(0, dt) / WINDOW); return (p - PMIN) / (1 - PMIN); };
    const yAt = f => y0 + (y1 - y0) * f;
    const widthAt = f => farW + (nearW - farW) * f;
    const laneX = (i, f) => cx + (i - 2.5) * widthAt(f) / 6;
    const scale = f => 0.28 + 0.72 * f;

    // lanes
    for (let i = 0; i < 6; i++) {
      ctx.strokeStyle = COLORS[i] + '55'; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(laneX(i, 0), yAt(0)); ctx.lineTo(laneX(i, 1), yAt(1)); ctx.stroke();
    }
    // road edge
    ctx.strokeStyle = 'rgba(255,255,255,.1)'; ctx.lineWidth = 1;
    for (const s of [-0.5, 5.5]) { ctx.beginPath(); ctx.moveTo(cx + (s - 2.5) * farW / 6, yAt(0)); ctx.lineTo(cx + (s - 2.5) * nearW / 6, yAt(1)); ctx.stroke(); }
    // seconds scrolling past
    ctx.lineWidth = 1;
    for (let s = Math.ceil(t); s < t + WINDOW; s++) {
      const f = frac(s - t);
      ctx.strokeStyle = `rgba(255,255,255,${0.04 + 0.1 * f})`;
      ctx.beginPath(); ctx.moveTo(cx - (widthAt(f) / 6) * 3, yAt(f)); ctx.lineTo(cx + (widthAt(f) / 6) * 3, yAt(f)); ctx.stroke();
    }

    // chords: far ones first so near ones draw over them
    const known = segs.filter(s => s[2] && s[0] < live && s[1] > t - 0.4)
      .map(s => ({t0: s[0], t1: Math.min(s[1], live), name: s[2]})).sort((a, b) => b.t0 - a.t0);
    let current = null, next = null;
    for (const s of known) if (s.t0 <= t + 0.05 && s.t1 > t) current = s;
    for (const s of known) if (s.t0 > t && (!next || s.t0 < next.t0)) next = s;
    const labels = [];
    for (const s of known) {
      const sh = shapeOf(s.name);
      if (!sh || s.t0 - t > WINDOW) continue;
      const fNear = frac(Math.max(0, s.t0 - t)), fFar = frac(Math.max(0, Math.min(s.t1, t + WINDOW) - t));
      const active = s.t0 <= t + 0.05 && s.t1 > t;
      const live_ = active ? 1 : 0;
      // the slab
      ctx.beginPath();
      ctx.moveTo(laneX(-0.5, fFar), yAt(fFar)); ctx.lineTo(laneX(5.5, fFar), yAt(fFar));
      ctx.lineTo(laneX(5.5, fNear), yAt(fNear)); ctx.lineTo(laneX(-0.5, fNear), yAt(fNear)); ctx.closePath();
      ctx.fillStyle = active ? 'rgba(0,180,180,.16)' : 'rgba(255,255,255,.05)'; ctx.fill();
      // sustain lines along the played strings
      for (let i = 0; i < 6; i++) {
        if (sh.frets[i] < 0) continue;
        ctx.strokeStyle = COLORS[i] + (active ? 'cc' : '77'); ctx.lineWidth = 2 + 2 * fNear;
        ctx.beginPath(); ctx.moveTo(laneX(i, fFar), yAt(fFar)); ctx.lineTo(laneX(i, fNear), yAt(fNear)); ctx.stroke();
      }
      // the leading edge: a bar, a dot per string, the name
      const f = fNear, y = yAt(f), k = scale(f), r = Math.max(5, (widthAt(f) / 6) * 0.27);
      ctx.strokeStyle = active ? '#00e0e0' : 'rgba(255,255,255,.45)'; ctx.lineWidth = 2 + 2 * k;
      ctx.beginPath(); ctx.moveTo(laneX(-0.5, f), y); ctx.lineTo(laneX(5.5, f), y); ctx.stroke();
      for (let i = 0; i < 6; i++) {
        const fr = sh.frets[i], x = laneX(i, f);
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        if (fr < 0) {
          ctx.strokeStyle = 'rgba(255,255,255,.35)'; ctx.lineWidth = 2;
          const d = r * 0.5; ctx.beginPath(); ctx.moveTo(x - d, y - d); ctx.lineTo(x + d, y + d); ctx.moveTo(x + d, y - d); ctx.lineTo(x - d, y + d); ctx.stroke();
          continue;
        }
        ctx.beginPath(); ctx.arc(x, y - r * 0.2, r, 0, Math.PI * 2);
        ctx.fillStyle = COLORS[i]; ctx.fill();
        ctx.strokeStyle = active ? '#fff' : 'rgba(0,0,0,.4)'; ctx.lineWidth = active ? 2 : 1; ctx.stroke();
        ctx.fillStyle = '#10121b'; ctx.font = `700 ${Math.round(r * 1.15)}px "Segoe UI", Arial, sans-serif`;
        ctx.fillText(String(fr), x, y - r * 0.2 + 1);
      }
      labels.push({text: s.name.split('/')[0], y: y - r * 1.5 - 2, size: Math.round(Math.min(30, h * 0.075) * k + 6), active});
      void live_;
    }
    // chord names, nearest first; one that would land on a nearer name is left out
    ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    let taken = Infinity;
    for (const l of labels.reverse()) {
      if (l.y > taken - l.size * 0.9) continue;
      ctx.fillStyle = l.active ? '#fff' : 'rgba(230,233,242,.85)';
      ctx.font = `700 ${l.size}px "Segoe UI", Arial, sans-serif`;
      ctx.fillText(l.text, cx, l.y);
      taken = l.y - l.size;
    }

    // the strike line
    ctx.strokeStyle = 'rgba(0,224,224,.9)'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(laneX(-0.7, 1), yAt(1)); ctx.lineTo(laneX(5.7, 1), yAt(1)); ctx.stroke();
    if (current) {  // a glow on it while a chord rings
      const g = ctx.createLinearGradient(0, yAt(1) - 40, 0, yAt(1) + 10);
      g.addColorStop(0, 'rgba(0,224,224,0)'); g.addColorStop(1, 'rgba(0,224,224,.22)');
      ctx.fillStyle = g; ctx.fillRect(laneX(-0.7, 1), yAt(1) - 40, laneX(5.7, 1) - laneX(-0.7, 1), 50);
    }

    // chord boxes under the highway
    box(ctx, current && shapeOf(current.name), current ? current.name : '', 'NOW', cx - bw - 20, by, bw, bh, 1);
    box(ctx, next && shapeOf(next.name), next ? next.name : '', 'NEXT', cx + 20, by, bw, bh, 0.7);
  }

  // A chord box: strings upright, five frets from the lowest used position
  function box(ctx, sh, name, label, x, y, w, h, alpha) {
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = 'rgba(18,21,30,.9)'; ctx.strokeStyle = 'rgba(255,255,255,.1)';
    ctx.beginPath(); ctx.roundRect(x - 8, y - 6, w + 16, h + 12, 10); ctx.fill(); ctx.stroke();
    ctx.fillStyle = '#8d93a8'; ctx.font = '600 11px "Segoe UI", Arial, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(label, x, y - 2);
    ctx.fillStyle = '#e6e9f2'; ctx.font = `700 ${w < 130 ? 15 : 20}px "Segoe UI", Arial, sans-serif`; ctx.textAlign = "right";
    ctx.fillText(name ? name.split('/')[0] : '–', x + w, y - 4);
    if (sh) {
      const top = y + 34, fh = (h - 44) / 5, gx = x + 14, gw = w - 28, sp = gw / 5;
      const base = Math.max(...sh.frets) > 4 ? sh.base : 1;
      ctx.strokeStyle = 'rgba(255,255,255,.35)'; ctx.lineWidth = 1;
      for (let f = 0; f <= 5; f++) { ctx.beginPath(); ctx.moveTo(gx, top + f * fh); ctx.lineTo(gx + gw, top + f * fh); ctx.lineWidth = f === 0 && base === 1 ? 4 : 1; ctx.stroke(); }
      for (let i = 0; i < 6; i++) { ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(gx + i * sp, top); ctx.lineTo(gx + i * sp, top + 5 * fh); ctx.stroke(); }
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (let i = 0; i < 6; i++) {
        const fr = sh.frets[i], sx = gx + i * sp;
        if (fr < 0) { ctx.fillStyle = '#8d93a8'; ctx.font = '12px "Segoe UI", Arial'; ctx.fillText('×', sx, top - 9); continue; }
        if (fr === 0) { ctx.strokeStyle = '#8d93a8'; ctx.beginPath(); ctx.arc(sx, top - 9, 4, 0, Math.PI * 2); ctx.stroke(); continue; }
        ctx.fillStyle = COLORS[i];
        ctx.beginPath(); ctx.arc(sx, top + (fr - base + 0.5) * fh, Math.min(fh * 0.4, 8), 0, Math.PI * 2); ctx.fill();
      }
      if (base > 1) { ctx.fillStyle = '#8d93a8'; ctx.font = '11px "Segoe UI", Arial'; ctx.textAlign = 'right'; ctx.fillText(base + 'fr', gx - 2, top + fh * 0.5); }
    }
    ctx.restore();
  }

  if (typeof window !== "undefined") window.guitarHighway = {draw, shape, parse};
  if (typeof module !== 'undefined') module.exports = {shape, parse};
})();
