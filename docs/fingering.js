// Woodwind fingering charts (midi-coach): which keys are down for each written note, and a small
// vertical diagram of them in the usual chart style: the left hand at the top in blue, the right
// hand under it in red, a key that's down filled, one that's up hollow. Used by the sheet
// (notation.html: a diagram under each note, Sheet ▸ Fingering) and the coach page (the Find the
// notes intro and the fingering monitor beside the tuner).
//
// Notes are written pitch as MIDI numbers (an alto saxophone's are the written notes, 9 above how
// they sound, as on its sheet). A note with no chart entry gets no diagram: better none than a
// wrong one. One standard fingering per note; alternates (the flute's 1-and-1 B flat, the sax's
// side B flat) are left for the lesson text.
(function (root) {
  'use strict';

  // Flute keys: T thumb, Tb the thumb's B flat lever, L1-L3, Gs (G sharp, left little finger),
  // R1-R3, Eb (right little finger), Cs and C (the foot joint's keys).
  const F = s => s.split(' ').filter(Boolean);
  const FLUTE = {
    60: F('T L1 L2 L3 R1 R2 R3 C'),
    61: F('T L1 L2 L3 R1 R2 R3 Cs'),
    62: F('T L1 L2 L3 R1 R2 R3'),
    63: F('T L1 L2 L3 R1 R2 R3 Eb'),
    64: F('T L1 L2 L3 R1 R2 Eb'),
    65: F('T L1 L2 L3 R1 Eb'),
    66: F('T L1 L2 L3 R3 Eb'),
    67: F('T L1 L2 L3 Eb'),
    68: F('T L1 L2 L3 Gs Eb'),
    69: F('T L1 L2 Eb'),
    70: F('T Tb L1 Eb'),
    71: F('T L1 Eb'),
    72: F('L1 Eb'),
    73: F('Eb'),
    74: F('T L2 L3 R1 R2 R3'),
    75: F('T L2 L3 R1 R2 R3 Eb'),
    84: F('L1 Eb'),
    85: F('L2 L3 Eb'),
    86: F('T L1 L2 R1 R2 Eb'),
    87: F('T L1 L2 L3 R1 R2 R3 Eb'),
  };
  for (let m = 76; m <= 83; m++) FLUTE[m] = FLUTE[m - 12];  // E to B: the low fingers, faster air

  // Alto saxophone keys: O octave (thumb), pD pEb pF (palm keys), L1 bis L2 L3, Gs Cs B Bb (left
  // little finger's table), sE sC sBb (right side keys), R1-R3, Eb and C (right little finger).
  const SAX = {
    58: F('L1 L2 L3 Bb R1 R2 R3'),
    59: F('L1 L2 L3 B R1 R2 R3'),
    60: F('L1 L2 L3 R1 R2 R3 C'),
    61: F('L1 L2 L3 Cs R1 R2 R3'),
    62: F('L1 L2 L3 R1 R2 R3'),
    63: F('L1 L2 L3 R1 R2 R3 Eb'),
    64: F('L1 L2 L3 R1 R2'),
    65: F('L1 L2 L3 R1'),
    66: F('L1 L2 L3 R2'),
    67: F('L1 L2 L3'),
    68: F('L1 L2 L3 Gs'),
    69: F('L1 L2'),
    70: F('L1 bis'),
    71: F('L1'),
    72: F('L2'),
    73: [],
    86: F('O pD'),
    87: F('O pD pEb'),
    88: F('O pD pEb sE'),
    89: F('O pD pEb sE pF'),
  };
  for (let m = 74; m <= 85; m++) SAX[m] = ['O', ...SAX[m - 12]];  // D to C sharp: the same, with the octave key

  const CHARTS = {flute: FLUTE, sax: SAX};
  const LEFT = {flute: new Set(['T', 'Tb', 'L1', 'L2', 'L3', 'Gs']),  // the left hand's keys (blue); the rest are the right's
                sax: new Set(['O', 'pD', 'pEb', 'pF', 'L1', 'bis', 'L2', 'L3', 'Gs', 'Cs', 'B', 'Bb'])};
  const NAMES = ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'];

  // Where each key is drawn, in a 12 x 31 box: [shape, x, y, w, h] (o: oval, r: rounded bar).
  const BIG = 1.55, SM = 0.8;
  const LAYOUT = {
    flute: {
      Tb: ['o', 2.4, 2.6, SM, SM], T: ['o', 2.4, 5.0, 1.15, 1.4],
      L1: ['o', 6, 3.2, BIG, BIG], L2: ['o', 6, 7.0, BIG, BIG], L3: ['o', 6, 10.8, BIG, BIG],
      Gs: ['o', 9.4, 12.2, 1.05, 0.7],
      R1: ['o', 6, 16.6, BIG, BIG], R2: ['o', 6, 20.4, BIG, BIG], R3: ['o', 6, 24.2, BIG, BIG],
      Eb: ['o', 3.1, 27.4, 1.05, 0.75], Cs: ['r', 7.4, 27.6, 1.3, 0.45], C: ['r', 7.4, 29.2, 1.3, 0.45],
    },
    sax: {
      pD: ['o', 3.6, 1.0, SM, 0.6], pEb: ['o', 6, 0.8, SM, 0.6], pF: ['o', 8.4, 1.0, SM, 0.6],
      O: ['o', 2.2, 5.0, 1.0, 1.3],
      L1: ['o', 6, 4.2, BIG, BIG], bis: ['o', 6, 6.55, 0.55, 0.55], L2: ['o', 6, 8.9, BIG, BIG], L3: ['o', 6, 12.6, BIG, BIG],
      Gs: ['o', 9.6, 12.4, 0.95, 0.65], Cs: ['o', 8.9, 14.5, 0.6, 0.6], B: ['o', 10.5, 14.5, 0.6, 0.6], Bb: ['o', 9.7, 16.1, 0.6, 0.6],
      sE: ['r', 2.0, 16.6, 0.45, 0.9], sC: ['r', 2.0, 18.9, 0.45, 0.9], sBb: ['r', 2.0, 21.2, 0.45, 0.9],
      R1: ['o', 6, 18.2, BIG, BIG], R2: ['o', 6, 22.0, BIG, BIG], R3: ['o', 6, 25.8, BIG, BIG],
      Eb: ['o', 4.6, 29.0, 0.95, 0.65], C: ['o', 7.4, 29.4, 0.95, 0.65],
    },
  };
  const BOX = {w: 12, h: 31};

  function chart(instrument, midi) {
    const c = CHARTS[instrument];
    const keys = c && c[Math.round(midi)];
    return keys ? keys.slice() : null;
  }
  const has = instrument => !!CHARTS[instrument];
  const same = (instrument, a, b) => {
    const x = chart(instrument, a), y = chart(instrument, b);
    return !!x && !!y && x.slice().sort().join() === y.slice().sort().join();
  };
  const name = midi => NAMES[((midi % 12) + 12) % 12] + (Math.floor(midi / 12) - 1);

  // The diagram as an SVG string. opts: height (px, default 62), colours left/right/open/line,
  // title (a tooltip; default the note's name and the keys down).
  function svg(instrument, midi, opts = {}) {
    const keys = chart(instrument, midi);
    if (!keys) return '';
    const down = new Set(keys);
    if (down.has('Tb')) down.add('T');
    const h = opts.height || 62, w = h * BOX.w / BOX.h;
    const left = opts.left || '#2563d9', right = opts.right || '#e0352b';
    const open = opts.open || '#fff', line = opts.line || '#1b1f2a';
    const parts = [];
    // The body between the hands, faint, so the column reads as one instrument.
    parts.push(`<line x1="6" y1="13.6" x2="6" y2="${instrument === 'sax' ? 15.8 : 14.2}" stroke="${line}" stroke-width="0.25" opacity=".35"/>`);
    for (const [k, [shape, x, y, rw, rh]] of Object.entries(LAYOUT[instrument])) {
      const on = down.has(k);
      const fill = on ? (LEFT[instrument].has(k) ? left : right) : open;
      const sw = rw >= 1.2 ? 0.35 : 0.28;
      if (shape === 'o') parts.push(`<ellipse cx="${x}" cy="${y}" rx="${rw}" ry="${rh}" fill="${fill}" stroke="${line}" stroke-width="${sw}"/>`);
      else parts.push(`<rect x="${x - rw}" y="${y - rh}" width="${2 * rw}" height="${2 * rh}" rx="${Math.min(rw, rh)}" fill="${fill}" stroke="${line}" stroke-width="${sw}"/>`);
    }
    const title = opts.title === undefined ? `${name(midi)}: ${keys.length ? keys.join(' ') : 'no keys down'}` : opts.title;
    return `<svg class="fingering" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${BOX.w} ${BOX.h}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" role="img" aria-label="${title}">` +
           (title ? `<title>${title}</title>` : '') + parts.join('') + '</svg>';
  }

  root.Fingering = {chart, has, same, svg, name, BOX, instruments: Object.keys(CHARTS)};
})(typeof window !== 'undefined' ? window : globalThis);
