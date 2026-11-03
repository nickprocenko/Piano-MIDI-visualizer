// The Atlas view and the step panel of the coach page (loaded after coach.html's script,
// whose helpers - $, cmd, esc, store, statusEl, portSel - it uses).
//
// The tree comes from cmd('atlas') with a fixed position for every node (atlas/layout.py),
// so this only draws: the zoom decides which level is shown (tier -> strand -> family ->
// requirement -> stage), only what's in view is drawn, and edges are the bundles of that
// level. Clicking zooms one level in, as far as a requirement (selected, not zoomed inside);
// clicking a stage opens it in the side panel, and
// "Practice" opens its lesson above the sheet music.
"use strict";

const atlas = {data: null, byId: new Map(), kids: new Map(), states: {}, view: {x: 0, y: 0, s: 0.05},
               level: 'tier', hover: null, selected: null, raf: 0, drag: null, pointer: null, loading: null};
const LEVEL_AT = [[0.09, 'tier'], [0.2, 'strand'], [0.45, 'family'], [1.15, 'requirement'], [Infinity, 'stage']];
const LEVEL_NAMES = {tier: 'Grades', strand: 'Strands', family: 'Families', requirement: 'Requirements', stage: 'Stages'};
const RANKS = {not_started: 0, practised: 1, proficient: 2, mastered: 3};
const STRAND_SHORT = {pieces: 'Pieces', technique: 'Scales', sight: 'Reading', aural: 'Aural', theory: 'Theory'};
const STRAND_TINT = {pieces: '#d97757', technique: '#00b4b4', sight: '#7aa7ff', aural: '#c084fc', theory: '#e3b341'};
const svgNS = 'http://www.w3.org/2000/svg';

// -- data -----------------------------------------------------------------------------

async function atlasLoad(force) {
  if (atlas.data && !force) return atlas.data;
  if (!atlas.loading) {
    atlas.loading = cmd('atlas').then(data => {
      atlas.data = data;
      atlas.states = data.states || {};
      atlas.byId = new Map(data.nodes.map(n => [n.id, n]));
      atlas.kids = new Map();
      for (const n of data.nodes) if (n.parent) {
        if (!atlas.kids.has(n.parent)) atlas.kids.set(n.parent, []);
        atlas.kids.get(n.parent).push(n);
      }
      return data;
    }).finally(() => { atlas.loading = null; });
  }
  return atlas.loading;
}

async function atlasRefreshStates() {
  if (!atlas.data) return;
  try { atlas.states = (await cmd('atlas')).states || {}; atlasDraw(); } catch (err) {}
}

const stateOf = id => atlas.states[id] || {};
const levelOf = id => stateOf(id).level || 'not_started';

// -- view -----------------------------------------------------------------------------

function atlasLevel(s) { return LEVEL_AT.find(([max]) => s < max)[1]; }

function atlasSize() { const r = $('atlas-svg').getBoundingClientRect(); return {w: r.width || 800, h: r.height || 600}; }

const GUTTER = 120;  // screen px left of the tiers for their titles

function atlasFit(box, pad = 40) {
  const {w, h} = atlasSize();
  const s = Math.min((w - 2 * pad - GUTTER) / box[2], (h - 2 * pad) / box[3]);
  atlas.view = {s, x: box[0] - GUTTER / s - (w / s - GUTTER / s - box[2]) / 2, y: box[1] - (h / s - box[3]) / 2};
  atlasDraw();
}

function atlasHome() {
  const g = atlas.data.geometry;
  atlasFit([0, 0, g.width, Math.min(g.height, g.width * 1.2)]);
  atlas.home = atlas.view;
}

// The Whole map button shows only when it would do something.
function atlasAtHome() {
  const v = atlas.view, h = atlas.home;
  return !!h && Math.abs(v.s / h.s - 1) < 0.01 && Math.abs(v.x - h.x) * v.s < 2 && Math.abs(v.y - h.y) * v.s < 2;
}

function atlasZoomAt(px, py, factor) {
  const v = atlas.view, s = Math.min(4, Math.max(0.02, v.s * factor));
  const wx = v.x + px / v.s, wy = v.y + py / v.s;
  atlas.view = {s, x: wx - px / s, y: wy - py / s};
  atlasDraw();
}

// Zoom one level in onto a cluster, or select a node. A lesson (requirement) or exercise
// (stage) is shown among its family, never zoomed inside: scroll in to see the exercises.
function atlasActivate(id) {
  const n = atlas.byId.get(id);
  if (!n) return;
  if (n.level === 'review' || n.level === 'exam') return atlasSelect(id);
  if (n.level === 'requirement' || n.level === 'stage') {
    atlasShowLesson(n.level === 'stage' ? n.parent : id);
    return atlasSelect(id);
  }
  atlasSelect(id);
  atlasFit(n.box, 30);
}

// A lesson at requirement zoom, its family fitted when it can be; left where it is when it's
// already in view at that zoom, or inside it where you scrolled in yourself.
function atlasShowLesson(id) {
  const n = atlas.byId.get(id), fam = n && atlas.byId.get(n.parent);
  if (!n || !n.box) return;
  const {w, h} = atlasSize(), v = atlas.view;
  if ((atlas.level === 'requirement' || atlas.level === 'stage') && inView(n.box, v, w, h, -40)) return;
  const box = (fam && fam.box) || n.box, pad = 30;
  const s = Math.min(1.1, Math.max(0.5, Math.min((w - 2 * pad - GUTTER) / box[2], (h - 2 * pad) / box[3])));
  const c = box[2] * s <= w - GUTTER && box[3] * s <= h ? box : n.box;  // too big a family: centre the lesson
  atlas.view = {s, x: c[0] + c[2] / 2 - (w + GUTTER) / 2 / s, y: c[1] + c[3] / 2 - h / 2 / s};
  atlasDraw();
}

// After a zoom or pan the node under a still mouse changes, so hover is re-read once drawn.
function atlasDraw() {
  if (atlas.raf) return;
  atlas.raf = requestAnimationFrame(() => {
    atlas.raf = 0;
    atlasRender();
    const p = atlas.pointer;
    if (p && !atlas.drag) {
      const id = atlasHit(p.x, p.y);
      if (id !== atlas.hover) { atlas.hover = id; atlasRender(); }
    }
  });
}

// The clickable node at a screen point. Labels lie over their shapes, so this looks
// through them, but not through anything covering the map (search results, panels).
function atlasHit(x, y) {
  const els = document.elementsFromPoint(x, y);
  if (!els.length || !$('atlas-svg').contains(els[0])) return null;
  const hit = els.find(el => el.classList && el.classList.contains('a-click'));
  return hit ? hit.dataset.id : null;
}

function atlasSetHover(id) {
  if (id !== atlas.hover) { atlas.hover = id; atlasDraw(); }
}

// -- drawing --------------------------------------------------------------------------

const GOLD = '#e3b341', NEUTRAL = '#c9d1d9', BG = '#0a0c12';
const DEPTHS = ['tier', 'strand', 'family', 'requirement', 'stage'];

// A node's colour is its strand's; grades are neutral, Review and Exam gold.
function tintOf(n) {
  if (n.level === 'review' || n.level === 'exam') return GOLD;
  return STRAND_TINT[n.strand || n.id.split('.')[1]] || NEUTRAL;
}

// Progress is how filled-in a dot is: hollow, half (practiced), solid (proficient, mastered).
function fillFor(id, tint) {
  const lv = levelOf(id);
  return lv === 'not_started' ? BG : lv === 'practised' ? `color-mix(in srgb, ${tint} 40%, ${BG})` : tint;
}

// Busier nodes get bigger dots: a radius in screen px from min (nothing inside) to max (36+).
const dotPx = (count, min, max) => Math.min(max, min + Math.sqrt(count || 0) * (max - min) / 6);

// Where a node's dot sits at this zoom, as [cx, cy, r] in world units. A family's dot heads
// its area, leaving the rest for its name underneath.
function dotOf(n, depth, s) {
  const [x, y, bw, bh = bw] = n.box, st = stateOf(n.id);
  switch (n.level) {
    case 'tier': return [atlas.data.geometry.content_width / 2, y + bh / 2, 16 / s];
    case 'strand': return [x + bw / 2, y + bh / 2, dotPx(st.total, 7, 16) / s];
    case 'family': { const r = Math.min(dotPx(st.total, 5, 12) / s, bh * 0.22); return [x + bw / 2, y + r + 4 / s, r]; }
    case 'requirement': return depth === 3 ? [x + bw / 2, y + 12, 10] : [x + bw / 2, y + 9, 7];
    case 'stage': return [x + bw / 2, y + bh / 2, bw * 0.375];
    default: return [x + bw / 2, y + bh / 2, bh / 2];
  }
}

// The box an edge joins: a dot's square, or a Review or Exam shape.
function edgeBox(n, depth, s) {
  if (n.level === 'review' || n.level === 'exam') return n.box;
  const [cx, cy, r] = dotOf(n, depth, s);
  return [cx - r, cy - r, 2 * r, 2 * r];
}

function dotEl(n, [cx, cy, r], cls = '') {
  const tint = tintOf(n), lv = levelOf(n.id);
  return `<circle class="a-node${cls}${lv === 'mastered' ? ' a-gold' : ''}${n.temporary ? ' a-temp' : ''}${route.ids.has(n.id) ? ' a-onroute' : ''}" data-id="${n.id}" cx="${cx}" cy="${cy}" r="${r}" ` +
         `style="stroke:${tint};fill:${fillFor(n.id, tint)}"><title>${esc(n.title)} · ${lv.replace('_', ' ').replace('practised', 'practiced')}</title></circle>`;
}

// An invisible target for hover and clicks around a dot and its name.
const hitRect = (id, x, y, w, h) => `<rect class="a-hit a-click" data-id="${id}" x="${x}" y="${y}" width="${w}" height="${h}"/>`;

function inView(box, v, w, h, margin = 200) {
  const x0 = v.x - margin / v.s, y0 = v.y - margin / v.s, x1 = v.x + (w + margin) / v.s, y1 = v.y + (h + margin) / v.s;
  return box[0] < x1 && box[0] + box[2] > x0 && box[1] < y1 && box[1] + box[3] > y0;
}

function label(x, y, text, px, s, opts = '') {
  return `<text x="${x}" y="${y}" font-size="${(px / s).toFixed(2)}" ${opts}>${esc(text)}</text>`;
}

// A label no wider than `width` (world units): shrinks from maxPx, hidden below minPx.
function fitLabel(x, y, text, maxPx, width, s, opts = '', minPx = 8) {
  const px = Math.min(maxPx, (width * s) / (Math.max(text.length, 1) * 0.56));
  return px < minPx ? '' : label(x, y, text, px, s, opts);
}

// One line that shrinks to fit `width` rather than being cut short, down to minPx.
function shrinkLabel(x, y, text, maxPx, width, s, opts = '', minPx = 8) {
  return label(x, y, text, Math.max(minPx, Math.min(maxPx, (width * s) / (Math.max(text.length, 1) * 0.56))), s, opts);
}

// Words in lines of at most `chars` characters; a longer word keeps a line to itself.
function wrapWords(text, chars) {
  const lines = [];
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const last = lines.length - 1;
    if (last >= 0 && lines[last].length + 1 + word.length <= chars) lines[last] += ' ' + word;
    else lines.push(word);
  }
  return lines;
}

// A name centred under its dot, from its top at y: wrapped to fit `width` (world units) and
// shrunk from maxPx towards minPx to keep it to two lines within `room` (screen px high),
// never cut short. A trailing count ('3/10') is muted. Returns [svg, height, width] (world units).
function nameLabel(cx, y, text, count, maxPx, width, s, opts = '', minPx = 9, room = Infinity) {
  const full = count ? `${text} ${count}` : text;
  let px = maxPx, lines;
  for (;;) {
    lines = wrapWords(full, Math.max(6, Math.floor((width * s) / (px * 0.56))));
    if ((lines.length <= 2 && lines.length * px * 1.2 <= room) || px <= minPx) break;
    px -= 0.5;
  }
  const lh = px * 1.2 / s;
  const spans = lines.map((line, i) => {
    const body = count && i === lines.length - 1 && line.endsWith(count)
      ? esc(line.slice(0, -count.length)) + `<tspan class="a-muted">${esc(count)}</tspan>` : esc(line);
    return `<tspan x="${cx}" dy="${i ? lh : 0}">${body}</tspan>`;
  }).join('');
  return [`<text x="${cx}" y="${y + px / s}" font-size="${(px / s).toFixed(2)}" text-anchor="middle" ${opts}>${spans}</text>`,
          lines.length * lh, Math.max(...lines.map(l => l.length)) * 0.56 * px / s];
}

function isWeakest(n) {
  const p = n.parent && atlas.states[n.parent];
  return p && p.weakest === n.id && (p.ring ?? 1) < 1;
}

// Drawn like a graph of notes: dots coloured by strand, filled by progress, named underneath,
// with no boxes. Hovering a dot lights it and its links and fades the rest.
function atlasRender() {
  const data = atlas.data;
  if (!data) return;
  const v = atlas.view, s = v.s, {w, h} = atlasSize(), geo = data.geometry;
  const level = atlas.level = atlasLevel(s);
  $('atlas-level').textContent = `${LEVEL_NAMES[level]} · ${Math.round(s * 100)}%`;
  $('atlas-home').hidden = atlasAtHome();
  const world = $('atlas-world');
  world.setAttribute('transform', `scale(${s}) translate(${-v.x} ${-v.y})`);
  world.style.setProperty('--halo', `${(3 / s).toFixed(2)}px`);
  const depth = DEPTHS.indexOf(level);
  const out = [];
  const visible = data.nodes.filter(n => n.box && inView(n.box, v, w, h));
  const focus = atlas.hover || atlas.selected;
  const hov = atlas.hover && atlas.byId.get(atlas.hover);
  const lit = new Set();
  if (hov && hov.level !== 'tier') {
    lit.add(hov.id).add(hov.parent);
    for (const [a, b] of data.bundles[level] || []) {
      if (a === hov.id) lit.add(b);
      if (b === hov.id) lit.add(a);
    }
  }
  world.classList.toggle('a-fade', lit.size > 0);
  const group = (id, body) => `<g class="a-g${lit.has(id) ? ' a-lit' : ''}">${body}</g>`;

  // Grades: a faint line between them, the title and count in the margin; a dot each when
  // zoomed right out. Sized to the grade's height on screen, so titles never collide.
  for (const n of visible.filter(n => n.level === 'tier')) {
    const [x, y, bw, bh] = n.box, st = stateOf(n.id), room = bh * s;
    if (depth === 0) out.push(hitRect(n.id, x, y, bw, bh));
    if (y > 0) out.push(`<line class="a-divider" x1="0" y1="${y - 30}" x2="${geo.width}" y2="${y - 30}"/>`);  // mid-gap (layout.TIER_GAP)
    const tx = x - 14 / s, px = Math.min(depth === 0 ? 22 : 16, room - 8);  // in the gutter left of the grade
    if (px >= 9) out.push(shrinkLabel(tx, y + (px + 4) / s, n.title, px, (GUTTER - 24) / s, s, 'text-anchor="end" class="a-tier-title"', 9));
    if (st.total && room >= px + 30) out.push(label(tx, y + (px + 24) / s, `${st.done}/${st.total}`, 12, s, 'text-anchor="end" class="a-muted"'));
    if (depth === 0) out.push(group(n.id, dotEl(n, dotOf(n, depth, s))));
  }
  // Strands: a dot per grade at strand level; below it, just the name in its colour atop the
  // column. Every heading gets the size the tightest one allows, rather than each its own.
  const strands = visible.filter(n => n.level === 'strand' && depth >= 1);
  if (depth === 1) {
    for (const n of strands) {
      const [x, y, bw, bh] = n.box, st = stateOf(n.id), d = dotOf(n, depth, s);
      const full = n.title.split(' · ')[1] || n.title;
      const name = (isWeakest(n) ? '★ ' : '') + (full.length * 0.56 * 12 <= (bw - 16 / s) * s ? full : STRAND_SHORT[n.strand]);
      const [text] = nameLabel(d[0], d[1] + d[2] + 4 / s, name, st.total ? `${st.done}/${st.total}` : '', 15, bw - 16 / s, s,
                               `class="a-strand-title" style="fill:${tintOf(n)}"`);
      out.push(hitRect(n.id, x, y, bw, bh), group(n.id, dotEl(n, d) + text));
    }
  } else if (depth >= 2) {
    const heads = strands.map(n => ({n, full: n.title.split(' · ')[1] || n.title, short: STRAND_SHORT[n.strand], room: n.box[2] - 8 / s}));
    const fit = key => Math.min(13, ...heads.map(h => (h.room * s) / (Math.max(h[key].length, 1) * 0.58)));
    const key = fit('full') >= 10 ? 'full' : fit('short') >= 7 ? 'short' : null;
    if (key) for (const {n, ...h} of heads) out.push(label(n.box[0] + 4 / s, n.box[1] - 6 / s, h[key], fit(key), s, `class="a-strand-title" style="fill:${tintOf(n)}"`));
  }
  // Families: a dot sized by its lessons, the name and count under it; below family level
  // just the name in the strand's colour over its lessons.
  for (const n of visible.filter(n => n.level === 'family' && depth >= 2)) {
    const [x, y, bw, bh] = n.box, st = stateOf(n.id), count = st.total ? `${st.done}/${st.total}` : '';
    if (depth === 2) {
      const d = dotOf(n, depth, s), [cx, cy, r] = d;
      const name = (isWeakest(n) ? '★ ' : '') + n.title + (st.total ? '' : ' (none yet)');
      const room = (y + bh + 14 - (cy + r)) * s - 5;  // down to the next family (layout.FAM_GAP)
      const [text, th, tw] = nameLabel(cx, cy + r + 3 / s, name, count, 12, bw - 4 / s, s, 'class="a-name"', 9, room);
      const hw = Math.max(2 * r, tw) / 2 + 6 / s;
      out.push(hitRect(n.id, cx - hw, cy - r - 4 / s, 2 * hw, 2 * r + th + 12 / s), group(n.id, dotEl(n, d) + text));
    } else {
      out.push(shrinkLabel(x + 8 / s, y + 16 / s, n.title + (count ? ` · ${count}` : ''), 12, bw - 16 / s, s,
                           `class="a-family-title" style="fill:${tintOf(n)}"`));
    }
  }
  // Requirements: a dot with the name under it; at stage zoom a small dot heading a stem
  // that its stages hang from.
  for (const n of visible.filter(n => n.level === 'requirement' && depth >= 3)) {
    const [x, y, bw, bh] = n.box, d = dotOf(n, depth, s), [cx, cy, r] = d;
    if (depth === 3) {
      const px = Math.min(11, bw * s / 7), ty = cy + r + 3;
      const title = px < 6.5 ? '' : `<foreignObject x="${x}" y="${ty}" width="${bw}" height="${Math.max(bh - (ty - y), 20)}"><div class="a-req-title" style="font-size:${(px / s).toFixed(2)}px;overflow:visible">${isWeakest(n) ? '★ ' : ''}${esc(n.title)}</div></foreignObject>`;
      out.push(hitRect(n.id, x, y, bw, bh), group(n.id, dotEl(n, d) + title));
    } else {
      const last = atlas.byId.get((n.stages || []).at(-1));
      const stem = last && last.box ? `<line class="a-stem" x1="${cx}" y1="${cy + r}" x2="${cx}" y2="${last.box[1] + last.box[3] / 2}" style="stroke:${tintOf(n)}"/>` : '';
      const ty = cy + r + 1;
      out.push(group(n.id, stem + dotEl(n, d) + `<foreignObject x="${x + 2}" y="${ty}" width="${bw - 4}" height="${Math.max(y + 34 - ty, 12)}"><div class="a-req-title" style="font-size:${Math.min(5.2, 11 / s).toFixed(2)}px">${esc(n.title)}</div></foreignObject>`));
    }
  }
  // Stages: small dots down their requirement's stem.
  if (depth === 4) {
    for (const n of visible.filter(n => n.level === 'stage')) {
      const d = dotOf(n, depth, s), [cx, cy, r] = d;
      let body = dotEl(n, d, ` a-click a-stage${n.final ? ' a-final' : ''}`);
      if (s > 2.2) body += label(cx + r + 4, cy + 3, n.title, 9, s, 'class="a-muted"');
      if (n.writing && s > 1) body += label(cx + r + 4, cy + 3 + 11 / s, 'writing…', 9, s, 'class="a-writing"');
      out.push(group(n.id, body));
    }
  }
  // Review (hexagon) and Exam (shield) at the foot of each grade: gold outlines, filled by progress.
  for (const n of visible.filter(n => (n.level === 'review' || n.level === 'exam') && depth >= 1)) {
    const [x, y, bw, bh] = n.box, lv = levelOf(n.id), cls = `a-${n.level} a-click${lv === 'mastered' ? ' a-gold' : ''}`;
    const solid = lv === 'proficient' || lv === 'mastered';
    const tag = n.level === 'review' ? 'polygon' : 'path';
    const shape = n.level === 'review'
      ? `<polygon class="${cls}" data-id="${n.id}" points="${x + 14},${y} ${x + bw - 14},${y} ${x + bw},${y + bh / 2} ${x + bw - 14},${y + bh} ${x + 14},${y + bh} ${x},${y + bh / 2}" style="fill:${fillFor(n.id, GOLD)}">`
      : `<path class="${cls}" data-id="${n.id}" d="M${x} ${y} H${x + bw} V${y + bh * 0.55} Q${x + bw} ${y + bh} ${x + bw / 2} ${y + bh} Q${x} ${y + bh} ${x} ${y + bh * 0.55} Z" style="fill:${fillFor(n.id, GOLD)}">`;
    let body = `${shape}<title>${esc(n.title)}</title></${tag}>` +
               fitLabel(x + bw / 2, y + bh / 2 + 4 / s, n.title, 13, bw * 0.86, s, `text-anchor="middle" class="a-gate-title${solid ? ' a-on-solid' : ''}"`, 7);
    const best = stateOf(n.id).best;
    if (best && depth >= 2) body += label(x + bw / 2, y + bh + 16 / s, `best ${best}/150`, 11, s, 'text-anchor="middle" class="a-muted"');
    out.push(group(n.id, body));
  }

  // Edges: the bundles of this level whose ends are near the view, dot to dot; at grade level
  // a plain line down the grades. A link that skips a grade or a column would cut through the
  // one between, so it is drawn only while one of its ends is hovered or selected; so are links
  // between neighbouring columns at strand level, where the columns touch. Lit links take the
  // colour of what's hovered or selected.
  const edges = [];
  const tierIndex = id => data.tiers.findIndex(t => t.id === id.split('.')[0]);
  const colIndex = id => data.geometry.columns.findIndex(c => c.strand === id.split('.')[1]);
  const hotTint = focus && atlas.byId.get(focus) ? tintOf(atlas.byId.get(focus)) : 'var(--accent)';
  if (depth === 0) {
    const tiers = data.nodes.filter(n => n.level === 'tier' && n.box).sort((a, b) => a.box[1] - b.box[1]);
    for (let i = 1; i < tiers.length; i++) {
      const [x1, y1, r1] = dotOf(tiers[i - 1], 0, s), [x2, y2, r2] = dotOf(tiers[i], 0, s);
      edges.push(`<path class="a-edge" d="M${x1} ${y1 + r1} L${x2} ${y2 - r2}" stroke-width="${(1.5 / s).toFixed(2)}"/>`);
    }
  }
  for (const [a, b, count] of depth > 0 ? data.bundles[level] || [] : []) {
    const na = atlas.byId.get(a), nb = atlas.byId.get(b);
    if (!na || !nb || !na.box || !nb.box) continue;
    const near = inView(na.box, v, w, h, 400) || inView(nb.box, v, w, h, 400);
    if (!near) continue;
    const hot = focus && (a === focus || b === focus || atlasAncestors(focus).has(a) || atlasAncestors(focus).has(b));
    const ta = tierIndex(a), tb = tierIndex(b);
    if (!hot && ta >= 0 && tb >= 0 && tb - ta > 1) continue;
    const [ax, ay, aw, ah] = edgeBox(na, depth, s), [bx, by, bw2, bh2] = edgeBox(nb, depth, s);
    const width = (Math.min(1 + Math.log2(count) / 2, 3) * (hot ? 1.6 : 1)) / s;
    let d;
    if (by >= ay + ah - 1) {  // downward: bottom of a to top of b
      const spread = ((hashOf(a + b) % 11) - 5) * Math.min(aw, bw2) / 14;
      const x1 = ax + aw / 2 + spread, y1 = ay + ah, x2 = bx + bw2 / 2 + spread, y2 = by;
      const dy = Math.max(30, Math.abs(y2 - y1) / 2);
      d = `M${x1} ${y1} C${x1} ${y1 + dy} ${x2} ${y2 - dy} ${x2} ${y2}`;
    } else {  // side by side (another column of the same grade): facing side to facing side
      const ca = colIndex(a), cb = colIndex(b);
      if (!hot && (depth === 1 || (ca >= 0 && cb >= 0 && Math.abs(ca - cb) > 1))) continue;
      const right = bx > ax, spread = ((hashOf(a + b) % 7) - 3) / 10;
      const x1 = right ? ax + aw : ax, x2 = right ? bx : bx + bw2;
      const y1 = ay + ah * (0.5 + spread * 0.6), y2 = by + bh2 * (0.5 + spread * 0.6);
      const dx = (right ? 1 : -1) * Math.max(20, Math.abs(x2 - x1) / 2);
      d = `M${x1} ${y1} C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`;
    }
    edges.push(`<path class="a-edge${hot ? ' a-hot' : ''}" d="${d}" stroke-width="${width.toFixed(2)}"${hot ? ` style="stroke:${hotTint}"` : ''}/>`);
  }
  // A goal's temporary nodes: dashed links to what they build on and lead into.
  if (depth >= 3) {
    for (const [a, b] of data.temp_edges || []) {
      const na = atlas.byId.get(a), nb = atlas.byId.get(b);
      if (!na || !nb || !na.box || !nb.box || !(inView(na.box, v, w, h, 400) || inView(nb.box, v, w, h, 400))) continue;
      const [ax, ay, aw, ah] = edgeBox(na, depth, s), [bx, by, bw2] = edgeBox(nb, depth, s);
      edges.push(`<path class="a-edge a-temp-edge" d="M${ax + aw / 2} ${ay + ah} C${ax + aw / 2} ${ay + ah + 60} ${bx + bw2 / 2} ${by - 60} ${bx + bw2 / 2} ${by}" stroke-width="${(1.4 / s).toFixed(2)}"/>`);
    }
  }
  // Review and exam: lines from each strand (its dot at strand level) down the funnel.
  if (depth >= 1) {
    for (const t of visible.filter(n => n.level === 'tier')) {
      const rv = atlas.byId.get(`${t.id}.review`), ex = atlas.byId.get(`${t.id}.exam`);
      if (!rv || !ex) continue;
      for (const st of atlas.kids.get(t.id) || []) {
        if (st.level !== 'strand') continue;
        const [sx, sy, sw, sh] = depth === 1 ? edgeBox(st, depth, s) : st.box;
        edges.push(`<path class="a-edge a-funnel" d="M${sx + sw / 2} ${sy + sh} L${rv.box[0] + rv.box[2] / 2} ${rv.box[1]}" stroke-width="${(1.2 / s).toFixed(2)}"/>`);
      }
      edges.push(`<path class="a-edge a-funnel" d="M${rv.box[0] + rv.box[2] / 2} ${rv.box[1] + rv.box[3]} L${ex.box[0] + ex.box[2] / 2} ${ex.box[1]}" stroke-width="${(2 / s).toFixed(2)}"/>`);
    }
  }
  // Selection ring: round the selected dot, or the dot standing for it at this zoom (an
  // exercise's lesson, a lesson's family); nothing when it's a heading here.
  let sel = atlas.selected && atlas.byId.get(atlas.selected);
  while (sel && DEPTHS.indexOf(sel.level) > depth) sel = atlas.byId.get(sel.parent);
  const ringW = (2.5 / s).toFixed(2);
  if (sel && sel.box && (sel.level === 'review' || sel.level === 'exam')) {
    const [x, y, bw, bh] = sel.box, m = 4 / s;
    out.push(`<rect class="a-selected" x="${x - m}" y="${y - m}" width="${bw + 2 * m}" height="${bh + 2 * m}" rx="${8 / s}" stroke-width="${ringW}"/>`);
  } else if (sel && sel.box && DEPTHS.indexOf(sel.level) === depth) {
    const [cx, cy, r] = dotOf(sel, depth, s);
    out.push(`<circle class="a-selected" cx="${cx}" cy="${cy}" r="${r + 5 / s}" stroke-width="${ringW}"/>`);
  }
  $('atlas-world').innerHTML = edges.join('') + out.join('');
}

function hashOf(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
  return Math.abs(h);
}

const _ancestorCache = new Map();
function atlasAncestors(id) {
  if (_ancestorCache.has(id)) return _ancestorCache.get(id);
  const set = new Set();
  let n = atlas.byId.get(id);
  while (n && n.parent) { set.add(n.parent); n = atlas.byId.get(n.parent); }
  _ancestorCache.set(id, set);
  return set;
}

// -- side panel -----------------------------------------------------------------------

// Lights the side panel's tab for what it shows: 'path', 'place', or null for a skill.
function atlasTab(name) {
  document.querySelectorAll('#atlas-tabs [data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
}

async function atlasSelect(id) {
  path.shown = false;
  atlasTab(null);
  atlas.selected = id;
  tasksMark(true);
  atlasDraw();
  const side = $('atlas-detail');
  side.innerHTML = '<p class="a-muted">Loading…</p>';
  let info;
  try { info = await cmd('node', {id}); } catch (err) { side.textContent = err.message; return; }
  if (atlas.selected !== id) return;
  const n = info.node, st = info.state || {};
  const trail = info.trail.slice(0, -1).map(t => `<a href="#" data-go="${t.id}">${esc(crumb(t))}</a>`).join(' › ');
  const lv = st.level ? st.level.replace('_', ' ').replace('practised', 'practiced') : st.total ? `${st.done} of ${st.total} requirements` : 'not started';
  let html = `<div class="a-trail">${trail}</div><h3>${esc(n.title)}</h3><p class="a-state">${esc(lv)}${st.credited ? ' · credited' : ''}${st.best ? ` · best ${st.best}/150` : ''}</p>`;
  if (info.children.length) {
    html += '<ol class="a-stages">' + info.children.map(c => {
      const l = (c.state && c.state.level) || 'not_started';
      return `<li><a href="#" data-go="${c.id}"><i class="a-dot a-${l}"></i>${esc(c.title)}</a></li>`;
    }).join('') + '</ol>';
  }
  if (n.level === 'stage') {
    const steps = info.lesson ? info.lesson.steps : [];
    html += steps.length
      ? `<p class="a-muted">${steps.length} step${steps.length === 1 ? '' : 's'}: ${steps.map(s => s.type).join(', ')}. Start it from the Route panel ←</p>`
      : '<p class="a-muted">No lesson written for this stage yet.</p>';
  }
  if (n.level === 'exam') {
    html += `<p class="a-muted">Three pieces, scales and arpeggios, sight-reading and aural tests, marked out of 150 by the coach ` +
            `(pass 100, merit 120, distinction 130).</p><button id="atlas-exam">Take the mock exam</button>`;
  }
  if (st.weakest) html += `<p><a href="#" data-go="${st.weakest}">★ Weakest part: ${esc((atlas.byId.get(st.weakest) || {}).title || '')}</a></p>`;
  html += '<div id="atlas-route-note"></div>';
  side.innerHTML = html;
  const ex = $('atlas-exam');
  if (ex) ex.addEventListener('click', () => examStart(n.tier));
  side.querySelectorAll('[data-go]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); atlasActivate(a.dataset.go); }));
  await routeFor(n);
  if (atlas.selected === id) routeNote();
}

// -- the step panel (practice view) ------------------------------------------------------

const step = {node: null, lesson: null, index: 0, title: '', done: {}, spoken: null, at: null};
const crumb = t => t.level === 'strand' ? t.title.split(' · ').pop() : t.title;  // 'Grade 3 · Theory' -> 'Theory'

async function stepOpen(nodeId, info) {
  info = info || await cmd('node', {id: nodeId});
  // The lesson is the stage's requirement ('B♭ major arpeggio · 2 oct · HS'); its stages are the exercises.
  const req = info.trail.length > 1 ? info.trail[info.trail.length - 2] : null;
  Object.assign(step, {node: nodeId, lesson: info.lesson, index: 0, title: info.node.title, done: {},
                       trail: info.trail.map(crumb).join(' › '), req: req && req.level === 'requirement' ? req : null});
  atlasShow(false);
  // A stage is practised in the lesson view: the Practice page pared down to the lesson's
  // exercises on the left, the step panel and the sheet, under the Atlas tab, one page below
  // the map (← Atlas or the browser's Back). An exam's aural tests stay on the Practice page
  // with the exam card.
  if (!(exam.state && exam.state.status !== 'done')) {
    const inLesson = history.state && history.state.lesson;  // another exercise of it: no new page
    document.body.dataset.view = 'lesson';
    if (inLesson) history.replaceState({lesson: nodeId}, '');
    else history.pushState({lesson: nodeId}, '');
    window.dispatchEvent(new CustomEvent('coach:viewchange'));
    lessonNav();
  }
  stepRender();
  try {
    const out = await cmd('stage_open', {node: nodeId});  // its music on the sheet
    if (!out.shown) {  // aural work: nothing to read, so no unrelated score under the questions
      frame.hidden = true;
      $('sheet-notice').textContent = 'Listening work: nothing to read here.';
      $('sheet-notice').hidden = false;
    }
  } catch (err) { statusEl.textContent = err.message; }
}

// What a step says out loud: its text, or for a young learner (who may not read yet) what to do.
function stepSpeech(cur) {
  const young = document.body.dataset.young === '1';
  const list = o => o.length > 1 ? `${o.slice(0, -1).join(', ')}, or ${o[o.length - 1]}?` : (o[0] || '');
  if (cur.type === 'read') return cur.text || '';
  if (cur.type === 'quiz') return `${cur.prompt || ''} ${young && cur.options ? list(cur.options) : ''}`.trim();
  if (!young) return '';
  if (cur.type === 'listen') return 'Listen first. Press Listen.';
  if (cur.type === 'play') return cur.mode === 'rehearse' ? 'Your turn! Press Start, then play along with the beat.' : 'Your turn! Press Start, then find each key.';
  if (cur.type === 'tap') return cur.along ? 'Press Start, then tap any key with the beat.' : 'Listen, then tap the rhythm back on any key.';
  if (cur.type === 'sing') return 'Listen, then sing it back.';
  return '';
}

const HANDS = {right: 'Right hand', left: 'Left hand', both: 'Both hands'};

// A play step's pass mark in words ('get 80% of the notes right', not 'notes 80+').
function stepGoal(cur) {
  if (cur.graded === false) return 'Just practice: this one isn\'t graded.';
  const p = {metric: 'notes', min: 90, ...(cur.pass || {})};
  const aim = {notes: `get ${p.min}% of the notes right`, timing: `play ${p.min}% of the notes in time`,
               overall: `score ${p.min} or more overall`, tempo_stability: `keep the beat steady (${p.min} or more)`}[p.metric]
              || `${esc(p.metric)} ${p.min} or more`;
  const also = [];
  if (p.tempo_min_pct) also.push(`at ${p.tempo_min_pct}% of full speed or faster`);
  if (p.max_wrong != null) also.push(p.max_wrong === 0 ? 'with no wrong keys' : `with no more than ${p.max_wrong} wrong key${p.max_wrong === 1 ? '' : 's'}`);
  return `To pass, play to the end and ${aim}${also.length ? ', ' + also.join(', ') : ''}. It grades itself at the last note.`;
}

// The step's Start / ▶ Listen button turns into Stop while its run goes (coach.html showPractice).
function stepRunning() {
  const b = document.querySelector('#step-panel .sp-act[data-act="start"]');
  if (!b) return;
  if (!b.dataset.label) b.dataset.label = b.textContent;
  b.textContent = running ? '■ Stop' : b.dataset.label;
  b.classList.toggle('stop', running);
}

function stepRender() {
  const panel = $('step-panel');
  // On to another step (or out of the lesson): an example still playing stops, and so does a
  // run, which belongs to the step it was started from.
  const at = step.lesson ? `${step.node}:${step.lesson.steps[step.index]?.id}` : null;
  if (step.at && step.at !== at) {
    cmd('stop_playback').catch(() => {});
    if (running) cmd('stop').catch(() => {});
  }
  clearTimeout(step.hearing);
  step.at = at;
  if (!step.lesson) { panel.hidden = true; return; }
  panel.hidden = false;
  const steps = step.lesson.steps, cur = steps[step.index];
  const dots = steps.map((s, k) => `<button class="sp-dot${k === step.index ? ' on' : ''}${step.done[s.id] === true ? ' ok' : step.done[s.id] === false ? ' no' : ''}" data-k="${k}" title="${esc(s.type)}">${k + 1}</button>`).join('');
  let body = '';
  const sayBtn = '<button class="sp-say" data-act="read" title="Read it to me">🔊</button>';
  if (cur.type === 'read') {
    body = `<p class="sp-text">${esc(cur.text || '')}${sayBtn}</p><button class="sp-act" data-act="done">Got it</button>`;
  } else if (cur.type === 'listen') {
    body = `<p>Listen${cur.hand && cur.hand !== 'both' ? ` (${esc(cur.hand)} hand)` : ''}${cur.tempo_percent && cur.tempo_percent !== 100 ? ` at ${cur.tempo_percent}%` : ''}: the cursor follows the music.</p><button class="sp-act" data-act="start" data-label="▶ Listen">▶ Listen</button>`;
  } else if (cur.type === 'play') {
    const tempo = cur.tempo_percent || 100;
    const how = cur.mode === 'rehearse'
      ? `The music keeps moving${tempo !== 100 ? ` at ${tempo}% speed` : ''}: play along in time.`
      : 'The music waits for you to find each note.';
    body = `<p><b>${HANDS[cur.hand || 'both'] || esc(cur.hand)}</b>${cur.bars ? ` · bars ${esc(cur.bars)}` : ''}</p><p>${how}</p>` +
           `<p class="a-muted">${stepGoal(cur)}</p><button class="sp-act" data-act="start" data-label="Start">Start</button>`;
  } else if (cur.type === 'quiz') {
    body = `<p class="sp-text">${esc(cur.prompt || '')}${sayBtn}</p>` +
           (cur.file ? `<p><button class="sp-act" data-act="hear">▶ Listen</button></p>` : '') +
           `<div class="sp-options">${(cur.options || []).map((o, k) => `<button data-answer="${k}">${esc(o)}</button>`).join('')}` +
           `<button data-act="say" title="Say the answer instead (uses the microphone)">🎤 Say it</button></div>`;
  } else if (cur.type === 'tap') {
    body = cur.along
      ? `<p class="sp-text">Tap any key in time with the music${cur.accent_every ? ', harder on the first beat of each bar' : ''}.</p><button class="sp-act" data-act="start">▶ Start, then tap along</button>`
      : `<p class="sp-text">Listen, then tap the rhythm back on any key.</p><button class="sp-act" data-act="hear">▶ Listen</button> <button class="sp-act" data-act="start">Tap it back</button>`;
    body += '<p class="a-muted">It finishes by itself a couple of seconds after your last tap.</p>';
  } else if (cur.type === 'sing') {
    body = `<p class="sp-text">${cur.score ? 'Sing the notes on the sheet. ▶ plays the tonic to start from.' : 'Listen, then sing it back (any vowel, hum or whistle; any octave).'}</p>` +
           `<button class="sp-act" data-act="hear">▶ ${cur.score ? 'Tonic' : 'Listen'}</button> <button class="sp-act" data-act="sing">🎤 Sing</button>` +
           (cur.keyboard_ok ? ` <button class="sp-act" data-act="keys" title="Play it back on the keyboard instead">🎹 Play it back</button>` : '') +
           `<span id="sp-pitch" class="a-muted"></span>`;
  } else {
    body = `<p class="a-muted">${esc(cur.type)} steps aren't supported on this page yet.</p>`;
  }
  // Written by the generator and not looked at yet: say so, and take a verdict.
  const review = step.lesson.checked === false
    ? `<span class="sp-review" title="Written by Claude and checked automatically (music, quiz answers), but not yet by you">Needs review ` +
      `<button data-review="ok" title="It's right: mark it checked">Looks right</button> <button data-review="bad" title="Say what's wrong; it's noted for rewriting">Something's wrong</button></span>`
    : '';
  const name = step.req ? step.req.title : step.title;
  panel.innerHTML = `<div class="sp-head"><span class="sp-trail" title="${esc(step.trail)}">${esc(name)}</span>${review}<button class="sp-close" title="Close">✕</button></div>` +
                    `<div class="sp-row"><div class="sp-dots">${dots}</div><div class="sp-body">${body}<span id="sp-verdict"></span></div></div>`;
  panel.querySelector('.sp-close').onclick = () => { step.lesson = null; stepRender(); };
  panel.querySelectorAll('.sp-dot').forEach(b => b.onclick = () => { step.index = +b.dataset.k; stepRender(); });
  panel.querySelectorAll('[data-answer]').forEach(b => b.onclick = () => stepAnswer(+b.dataset.answer));
  panel.querySelectorAll('[data-act]').forEach(b => b.onclick = () => stepAct(b.dataset.act));
  panel.querySelectorAll('[data-review]').forEach(b => b.onclick = () => stepReview(b.dataset.review === 'ok'));
  stepRunning();
  if (cur.score && step.shown !== cur.id) { step.shown = cur.id; cmd('step_show', {node: step.node, step: cur.id}).catch(() => {}); }
  // A young learner hears each step once, as it comes up.
  const key = `${step.node}:${cur.id}`;
  if (document.body.dataset.young === '1' && step.spoken !== key && typeof speak === 'function') {
    step.spoken = key;
    speak(stepSpeech(cur), true);
  }
}

async function stepAct(act) {
  const cur = step.lesson.steps[step.index];
  try {
    if (act === 'start' && running) { await cmd('stop'); return; }
    if (act === 'hear') return await stepHear(cur);
    if (act === 'sing') return singStart(cur);
    if (act === 'say') return sayAnswer(cur);
    if (act === 'read') { if (typeof speak === 'function') speak(stepSpeech(cur), true, true); return; }
    if (act === 'keys') { await cmd('step_start', {node: step.node, step: cur.id, port: portSel.value, via: 'keyboard'}); $('sp-verdict').textContent = 'Listening to the keyboard…'; return; }
    if (act === 'done') {
      await cmd('step_done', {node: step.node, step: cur.id});
      step.done[cur.id] = true;
      stepNext();
    } else {
      if (typeof metroUnlock === 'function') metroUnlock();
      await cmd('step_start', {node: step.node, step: cur.id, port: portSel.value});
      if (cur.type === 'listen') { step.done[cur.id] = true; stepRender(); }
      if (cur.type === 'play') $('sp-verdict').textContent = 'Go ahead: it grades itself when you reach the last note.';
      if (cur.type === 'tap') $('sp-verdict').textContent = cur.along ? 'Tap along…' : 'Tap it back…';
    }
  } catch (err) {
    const el = $('sp-verdict');
    if (el) el.textContent = err.message; else statusEl.textContent = err.message;
  }
}

// A short example (a quiz's passage, a phrase to echo): its ▶ button is Stop while it plays.
async function stepHear(cur) {
  const b = document.querySelector('#step-panel .sp-act[data-act="hear"]');
  if (b && b.dataset.playing) { await cmd('stop_playback'); b.textContent = b.dataset.playing; delete b.dataset.playing; return; }
  const out = await cmd('step_play', {node: step.node, step: cur.id});
  if (!b || !out.seconds) return;
  b.dataset.playing = b.textContent;
  b.textContent = '■ Stop';
  clearTimeout(step.hearing);
  step.hearing = setTimeout(() => { if (b.dataset.playing) { b.textContent = b.dataset.playing; delete b.dataset.playing; } },
                            out.seconds * 1000 + 300);
}

async function stepAnswer(k) {
  const cur = step.lesson.steps[step.index];
  try {
    const out = await cmd('quiz_answer', {node: step.node, step: cur.id, answer: k});
    step.done[cur.id] = out.passed;
    stepRender();
    $('sp-verdict').textContent = out.passed ? '✓ Yes, well done!' : `Not quite: it's ${cur.options ? cur.options[out.answer] : 'another one'}${out.explain ? ' – ' + out.explain : ''}`;
    if (document.body.dataset.young === '1' && typeof speak === 'function') {
      speak(out.passed ? 'Yes! Well done.' : `Not quite. It's ${cur.options ? cur.options[out.answer] : 'another one'}.`, true);
    }
    if (out.passed) setTimeout(stepNext, 900);
  } catch (err) { statusEl.textContent = err.message; }
}

async function stepReview(ok) {
  const cur = step.lesson.steps[step.index];
  const note = ok ? '' : prompt(`What's wrong with this lesson (step ${step.index + 1})?`);
  if (!ok && note === null) return;
  try {
    const out = await cmd('lesson_feedback', {node: step.node, step: cur.id, ok, note});
    step.lesson.checked = out.checked;
    stepRender();
    $('sp-verdict').textContent = ok ? 'Marked as checked.' : 'Noted — it will be rewritten.';
  } catch (err) { statusEl.textContent = err.message; }
}

function stepNext() {
  if (step.index < step.lesson.steps.length - 1) step.index++;
  stepRender();
}

// Up from the lesson to the map, with the stage selected. Finished steps are already saved; a
// step stopped halfway isn't graded, so ask before stopping one. fromHistory: the browser's Back
// already left the lesson's history entry, so put it back if the answer is no.
async function stepBack(fromHistory = false) {
  if (running && !confirm('Stop this step and go back to the map?\n\nThe steps you finished are saved. ' +
                          'This one is not graded unless you play it to the end.')) {
    if (fromHistory) history.pushState({lesson: step.node}, '');
    return;
  }
  if (running) { try { await cmd('stop'); } catch (err) { statusEl.textContent = err.message; } }
  const node = step.node;
  step.lesson = null;
  stepRender();
  await atlasShow(true);
  if (node) atlasActivate(node);
}

window.addEventListener('popstate', () => { if (document.body.dataset.view === 'lesson') stepBack(true); });

// Leaving the lesson view by any way (← Roadmap, Back, Home): the Session gets its own sheet back.
let lessonViewWas = document.body.dataset.view;
new MutationObserver(() => {
  const now = document.body.dataset.view;
  if (lessonViewWas === 'lesson' && now !== 'lesson') cmd('stage_close').catch(() => {});
  lessonViewWas = now;
}).observe(document.body, {attributes: true, attributeFilter: ['data-view']});

// The lesson view's left panel: the lesson's name and its exercises (the requirement's stages),
// each with its progress dot; choosing one opens it.
async function lessonNav() {
  const list = $('lesson-stages');
  $('lesson-back').textContent = '← Roadmap';
  $('lesson-name').textContent = step.req ? step.req.title : step.title;
  if (!step.req) { list.innerHTML = ''; return; }
  let info;
  try { info = await cmd('node', {id: step.req.id}); } catch (err) { list.innerHTML = ''; return; }
  list.innerHTML = info.children.map(c => {
    const l = (c.state && c.state.level) || 'not_started';
    return `<li><a href="#" data-stage="${c.id}"${c.id === step.node ? ' class="on" aria-current="step"' : ''}><i class="a-dot a-${l}"></i><span>${esc(c.title)}</span></a></li>`;
  }).join('');
  list.querySelectorAll('[data-stage]').forEach(a => a.addEventListener('click', e => {
    e.preventDefault();
    if (a.dataset.stage === step.node) return;
    if (running && !confirm('Stop this step and open the other exercise?\n\nThis one is not graded unless you play it to the end.')) return;
    (running ? cmd('stop') : Promise.resolve()).catch(() => {}).then(() => stepOpen(a.dataset.stage));
  }));
}
$('lesson-back').addEventListener('click', () => history.state && history.state.lesson ? history.back() : stepBack());

// -- mock exams: the exam card -------------------------------------------------------------
// The server runs the exam (atlas/exam.py); the card shows the sections, what the examiner
// asked for, and a button for the next thing to do. Played tasks record by themselves and the
// examiner moves on when you stop; aural tests open their lesson in the step panel.

const exam = {state: null, placement: null, clock: null, aural: null};
const EXAM_SECTIONS = {pieces: 'Pieces', scales: 'Scales', sight: 'Sight-reading', aural: 'Aural'};

// Placement (atlas/placement.py): where it stands, above the exam it is running.
function placementHtml() {
  const p = exam.placement;
  if (!p) return '';
  const sat = p.exams.map(e => `${esc(e.title)} ${e.passed ? 'passed' : 'not passed'} (${e.total})`).join(' · ');
  if (p.status === 'done') {
    const weak = (p.weak || []).slice(0, 6).map(w => `<li>${esc(w.title)}</li>`).join('');
    return `<div class="ex-place"><b>${esc(p.summary)}</b>${sat ? `<br><span class="a-muted">${sat}</span>` : ''}` +
           (weak ? `<br>Work on these first:<ol>${weak}</ol>` : '') + '</div>';
  }
  const next = !exam.state || exam.state.status === 'done';
  return `<div class="ex-place">Finding your level${sat ? ': ' + sat : ''}.` +
         (next && p.next_title ? ` Next: <b>${esc(p.next_title)}</b>.<div class="ex-row" style="margin-top:6px">` +
           `<button class="ex-go" data-ex="place-go">${p.status === 'paused' ? 'Continue' : 'Sit'} the ${esc(p.next_title)} exam</button>` +
           (p.status === 'running' ? '<button data-ex="place-pause">Later</button>' : '') + '</div>' : '') + '</div>';
}

function examRender() {
  const panel = $('exam-panel'), s = exam.state;
  // Freeplay stays free: between exams nothing shows, only a placement's final result.
  if (!s && (!exam.placement || exam.placement.status !== 'done')) { panel.hidden = true; return; }
  panel.hidden = false;
  // Between exams it's one line above the sheet; the full card is for an exam and its marks.
  panel.classList.toggle('ex-compact', !s && exam.placement.status !== 'done');
  if (!s) {  // placement between exams, or settled
    panel.innerHTML = `<div class="ex-head"><h3>Finding your level</h3></div>` +
                      placementHtml() + `<div class="ex-row"><span style="flex:1"></span><button data-ex="close">Close</button></div>`;
    panel.querySelectorAll('[data-ex]').forEach(b => b.onclick = () => examAct(b.dataset.ex));
    return;
  }
  const t = s.task;
  const chips = Object.entries(EXAM_SECTIONS).filter(([k]) => s.progress[k].total).map(([k, name]) => {
    const p = s.progress[k], on = t && t.section === k, done = p.done === p.total;
    return `<span class="ex-sec${on ? ' on' : ''}${done ? ' done' : ''}">${name} ${p.done}/${p.total}</span>`;
  }).join('');
  let body = '';
  if (s.status === 'done') {
    const r = s.result, sec = r.sections;
    const rows = sec.pieces.map(p => `<tr><td>${esc(p.list || 'Piece')}: ${esc(p.title)}</td><td>${p.mark}/${p.of}</td></tr>`).join('') +
      `<tr><td>Scales and arpeggios</td><td>${sec.scales.mark}/${sec.scales.of}</td></tr>` +
      `<tr><td>Sight-reading</td><td>${sec.sight.mark}/${sec.sight.of}</td></tr>` +
      `<tr><td>Aural tests</td><td>${sec.aural.mark}/${sec.aural.of}</td></tr>` +
      `<tr class="ex-total"><td>Total · ${esc(r.band)}</td><td>${r.total}/${r.of}</td></tr>`;
    body = `<table class="ex-marks">${rows}</table><div class="ex-report">${esc(s.report || '')}</div>` +
           `<div class="ex-row"><button data-ex="close">Close</button></div>`;
  } else if (t) {
    const what = t.kind === 'piece' ? `${esc(t.list || 'Piece')}: ${esc(t.title)}`
      : t.kind === 'scale' ? `${esc(t.title)}${t.hand && t.hand !== 'both' ? ` · ${esc(t.hand)} hand` : ''} · from memory`
      : esc(t.title);
    let act = '';
    if (t.kind === 'aural') {
      act = s.phase === 'answering'
        ? '<button data-ex="open">Show the questions</button> <button class="ex-go" data-ex="finish">Finish this test</button>'
        : '<button class="ex-go" data-ex="next">Begin</button>';
    } else if (t.kind === 'sight' && s.phase !== 'prepared' && s.phase !== 'playing') {
      act = `<button class="ex-go" data-ex="next">Look at the music (${t.prep_sec} s)</button>`;
    } else if (t.kind === 'sight' && s.phase === 'prepared') {
      act = `<span class="ex-clock" id="ex-clock"></span><button class="ex-go" data-ex="next">Play it now</button>`;
    } else if (s.phase === 'playing') {
      act = '<span class="a-muted">Recording… it finishes a few seconds after you stop playing.</span>';
    } else {
      act = '<button class="ex-go" data-ex="next">Begin</button>';
    }
    body = `<p class="ex-examiner">${esc(s.examiner)}</p><p class="ex-task">${what}</p>` +
           `<div class="ex-row">${act}<span style="flex:1"></span><button data-ex="skip" title="Go on to the next task; this one scores nothing">Skip</button>` +
           `<button data-ex="abort" title="Stop this exam (it isn't marked)">Stop exam</button></div>`;
  }
  panel.innerHTML = `<div class="ex-head"><h3>${esc(s.title)}</h3></div>` +
                    `<div class="ex-sections">${chips}</div>${placementHtml()}${body}`;
  panel.querySelectorAll('[data-ex]').forEach(b => b.onclick = () => examAct(b.dataset.ex));
  if (t && t.kind === 'sight' && s.phase === 'prepared') examClock();
  // An aural test that has finished: its questions go away.
  if (exam.aural && (!t || t.node !== exam.aural)) {
    if (step.node === exam.aural) { step.lesson = null; stepRender(); }
    exam.aural = null;
  }
}

function examClock() {
  clearInterval(exam.clock);
  const end = Date.now() + exam.state.task.prep_sec * 1000;
  const tick = () => {
    const el = $('ex-clock');
    if (!el) { clearInterval(exam.clock); return; }
    const left = Math.max(0, Math.ceil((end - Date.now()) / 1000));
    el.textContent = left ? `0:${String(left).padStart(2, '0')}` : 'Time';
    if (!left) clearInterval(exam.clock);
  };
  tick();
  exam.clock = setInterval(tick, 250);
}

async function examAct(act) {
  const t = exam.state && exam.state.task;
  try {
    if (act === 'close') { exam.state = null; exam.placement = null; examRender(); return; }
    if (act === 'place-go' || act === 'place-pause') {
      const out = await cmd(act === 'place-go' ? 'placement_continue' : 'placement_pause');
      exam.state = out.exam || (act === 'place-pause' ? null : exam.state);
      exam.placement = out.placement;
      examRender();
      return;
    }
    if (act === 'abort') {
      if (!confirm('Stop this mock exam? It won\'t be marked.')) return;
      await cmd('exam_abort');
      exam.state = null; examRender(); return;
    }
    if (act === 'skip') { await cmd('exam_skip'); return; }
    if (act === 'finish') { await cmd('exam_next', {finish: true}); return; }
    if (act === 'open') { if (exam.aural) await stepOpen(exam.aural); return; }
    if (act === 'next') {
      if (t && t.kind === 'scale') {  // from memory: the music stays hidden
        frame.hidden = true;
        $('sheet-notice').textContent = 'Scales and arpeggios are played from memory.';
        $('sheet-notice').hidden = false;
      }
      if (typeof metroUnlock === 'function') metroUnlock();
      const out = await cmd('exam_next', {port: portSel.value});
      if (out.aural) { exam.aural = out.aural; await stepOpen(out.aural); }
    }
  } catch (err) { statusEl.textContent = err.message; }
}

async function examStart(tier) {
  try {
    const out = await cmd('exam_start', {tier});
    atlasShow(false);
    exam.state = out.exam;
    examRender();
  } catch (err) { statusEl.textContent = err.message; }
}

// Getting to know you (atlas/welcome.py), the side panel's "Where to start" tab: a few
// questions about you, then some light music checks, one at a time, and the answers pick where
// your path starts. No marks: a check you miss just shows the answer and moves on. A flute
// profile then checks the microphone hears the flute, and the last screen starts Today.
const wl = {qs: null, i: 0, answers: {}, picked: [], audio: null, micChecked: false};
const isFlute = () => document.body.dataset.instrument === 'flute';

async function atlasPlaceForm() {
  path.shown = false;  // a goals update mustn't redraw the Path over this
  atlasTab('place');
  const side = $('atlas-detail');
  let last = null;
  try { const out = await cmd('welcome'); wl.qs = out.questions; last = out.last; } catch (err) { side.textContent = err.message; return; }
  side.innerHTML = `<h3>Getting to know you</h3>` +
    `<p>Hi! A few quick questions so your path starts in the right place: first about you, then a little music. ` +
    `No marks and no pressure; it takes about two minutes.</p>` +
    (isFlute() ? `<p>Have your flute nearby: at the end, the coach checks that it can hear it through the microphone.</p>` : '') +
    (last ? `<p class="a-muted">Last time: ${esc(last.summary)}</p>` : '') +
    `<p><button class="wl-go" id="wl-start">${last ? 'Answer again' : "Let's go"}</button></p>` +
    `<p class="a-muted">Rather show it in a full mock exam? <a href="#" id="wl-mock">Mock exams</a></p>`;
  $('wl-start').onclick = () => { wl.i = 0; wl.answers = {}; wl.picked = []; wl.micChecked = false; welcomeAsk(); };
  $('wl-mock').onclick = e => { e.preventDefault(); atlasMockForm(); };
}

// The questions to ask: no checks for someone brand new who doesn't read music yet, and no
// exam question for someone who's never played.
function welcomeQueue() {
  const a = wl.answers;
  return wl.qs.filter(q => !(q.id === 'exams' && a.played === 0) && !(q.kind === 'check' && a.played === 0 && a.reading === 0));
}

function welcomeAsk() {
  const qs = welcomeQueue(), q = qs[wl.i];
  if (!q) { if (isFlute() && !wl.micChecked) welcomeMic(); else welcomeFinish(); return; }
  const side = $('atlas-detail');
  const opts = q.options.map((o, k) => `<button data-k="${k}"${q.multi && wl.picked.includes(k) ? ' class="on"' : ''}>${esc(o)}</button>`).join('');
  side.innerHTML = `<h3>Getting to know you</h3>` +
    `<div class="wl-bar" title="${wl.i + 1} of ${qs.length}"><i style="width:${Math.round(100 * wl.i / qs.length)}%"></i></div>` +
    (q.kind === 'check' && !qs.slice(0, wl.i).some(x => x.kind === 'check') ? `<p class="a-muted">Now a little music. Guessing is fine!</p>` : '') +
    `<p class="wl-q">${esc(q.prompt)}</p>` +
    (q.staff ? welcomeStaff(q.staff) : '') +
    (q.tones ? `<p><button class="sp-act" id="wl-hear">▶ Play the notes</button></p>` : '') +
    `<div class="wl-options">${opts}</div>` +
    (q.multi ? `<p><button class="wl-go" id="wl-next">Continue</button></p>` : '') +
    (q.kind === 'check' ? `<p><button class="wl-skip" id="wl-skip">I'm not sure</button></p>` : '') +
    `<p class="wl-say" id="wl-say" aria-live="polite"></p>`;
  side.querySelectorAll('.wl-options [data-k]').forEach(b => b.onclick = () => welcomeAnswer(q, +b.dataset.k));
  if (q.tones) { $('wl-hear').onclick = () => welcomeTones(q.tones); welcomeTones(q.tones); }
  if (q.multi) $('wl-next').onclick = () => { wl.answers[q.id] = wl.picked.slice(); wl.picked = []; wl.i++; welcomeAsk(); };
  if (q.kind === 'check') $('wl-skip').onclick = () => welcomeAnswer(q, -1);
}

const WL_CHEERS = ['Nice!', 'Yes!', 'Spot on!', 'You got it!', 'Exactly!', 'Great!'];

function welcomeAnswer(q, k) {
  if (q.multi) {
    wl.picked = wl.picked.includes(k) ? wl.picked.filter(x => x !== k) : [...wl.picked, k];
    welcomeAsk();
    return;
  }
  wl.answers[q.id] = k;
  if (q.kind !== 'check') { wl.i++; welcomeAsk(); return; }
  // A check: say how it went, kindly, show the right answer, and move on.
  const side = $('atlas-detail'), right = k === q.answer;
  side.querySelectorAll('.wl-options button, #wl-skip').forEach(b => b.disabled = true);
  const buttons = side.querySelectorAll('.wl-options [data-k]');
  buttons[q.answer].classList.add('ok');
  if (k >= 0 && !right) buttons[k].classList.add('no');
  $('wl-say').textContent = right ? WL_CHEERS[Math.floor(Math.random() * WL_CHEERS.length)]
    : `${k < 0 ? 'No problem' : 'Not quite'}: it's ${q.options[q.answer]}. You'll meet it on your path!`;
  setTimeout(() => { wl.i++; welcomeAsk(); }, right ? 800 : 2000);
}

// The flute is heard through the microphone, so before finishing: play a long note and see
// Pan hear it. Anyone who can't make a sound yet carries on (Making a sound is the first lesson).
function welcomeMic() {
  const side = $('atlas-detail');
  side.innerHTML = `<h3>Can the coach hear your flute?</h3>` +
    `<p>The coach listens through the microphone. Pick up your flute and play a long, steady note: any note.</p>` +
    `<div class="wl-bar" title="How loud the microphone hears it"><i id="wl-level" style="width:0%"></i></div>` +
    `<p class="wl-q" id="wl-heard" aria-live="polite">Listening…</p>` +
    `<p><button class="wl-go" id="wl-mic-next">Skip for now</button></p>` +
    `<p class="a-muted">Bar not moving? Pick your microphone under Preferences → Microphone &amp; speakers. A headset ` +
    `or USB mic works; the keyboard's audio input doesn't.</p>` +
    `<p class="a-muted">Can't get a note out yet? That's fine: your first lesson, Making a sound, shows you how.</p>`;
  let pitch = null, since = 0, heard = false;
  const stop = () => { flute.probe = null; fluteClose(); };
  $('wl-mic-next').onclick = () => { stop(); wl.micChecked = true; welcomeFinish(); };
  flute.probe = (m, rms) => {
    const bar = $('wl-level');
    if (!bar) { stop(); return; }  // another tab took the panel
    bar.style.width = `${Math.min(100, Math.round(rms * 1500))}%`;
    if (heard) return;
    const now = performance.now();
    if (m === null) {
      pitch = null;
      $('wl-heard').textContent = rms > 0.03 ? 'I hear something, but no clear note yet. Keep the air narrow and steady.' : 'Listening…';
      return;
    }
    if (Math.round(m) !== pitch) { pitch = Math.round(m); since = now; }
    $('wl-heard').textContent = `Hearing ${fluteNoteName(pitch)}… hold it`;
    if (now - since > 700) {
      heard = true;
      $('wl-heard').textContent = `✓ That's a ${fluteNoteName(pitch)}. The coach can hear your flute!`;
      $('wl-mic-next').textContent = 'Continue ▸';
    }
  };
  fluteOpen().catch(err => { stop(); $('wl-heard').textContent = 'The coach needs the microphone: ' + err.message; });
}

async function welcomeFinish() {
  const side = $('atlas-detail');
  side.innerHTML = `<h3>Getting to know you</h3><p>Finding your starting point…</p>`;
  try {
    const out = await cmd('welcome_finish', {answers: wl.answers});
    const checks = out.of ? `<p class="a-muted">Music checks: ${out.correct} of ${out.of}. Anything you missed comes up on your path.</p>` : '';
    side.innerHTML = `<h3>All set! 🎉</h3><p class="wl-q">${esc(out.summary)}</p>${checks}` +
      `<p><button class="wl-go" id="wl-begin">Start today's practice ▸</button> <button class="wl-skip" id="wl-path">See my path</button></p>` +
      `<p class="a-muted">Today's practice is also the first card on Home. A Session is always there too, from Home: play anything you like, nothing is graded.</p>`;
    $('wl-path').onclick = () => pathShow();
    $('wl-begin').onclick = async () => {
      await todayLoad(true);  // planned afresh from the goal just set
      if (today.state && today.state.next !== null && today.state.next !== undefined) todayAct('next');
      else pathShow();
    };
    if (typeof speak === 'function') speak(out.summary, true);
  } catch (err) { side.textContent = err.message; }
}

// A note on a five-line stave (treble: bottom line E4; bass: bottom line G2), with ledger lines.
function welcomeStaff({clef, midi}) {
  const letter = {0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6}[midi % 12];
  const pos = (Math.floor(midi / 12) - 1) * 7 + letter - (clef === 'bass' ? 18 : 30);  // steps above the bottom line
  const gap = 12, bottom = 84, x = 120, y = bottom - pos * gap / 2;
  let lines = '';
  for (let k = 0; k < 5; k++) lines += `<line x1="10" x2="190" y1="${bottom - k * gap}" y2="${bottom - k * gap}"/>`;
  for (let p = -2; p >= pos; p -= 2) lines += `<line x1="${x - 13}" x2="${x + 13}" y1="${bottom - p * gap / 2}" y2="${bottom - p * gap / 2}"/>`;
  for (let p = 10; p <= pos; p += 2) lines += `<line x1="${x - 13}" x2="${x + 13}" y1="${bottom - p * gap / 2}" y2="${bottom - p * gap / 2}"/>`;
  const glyph = clef === 'bass' ? `<text x="14" y="${bottom - 3 * gap + 14}" font-size="40">𝄢</text>`
                                : `<text x="12" y="${bottom + 10}" font-size="64">𝄞</text>`;
  return `<svg class="wl-staff" viewBox="0 0 200 120" role="img" aria-label="A note on the ${clef} stave">` +
         `<g stroke="currentColor" stroke-width="1.2">${lines}</g><g fill="currentColor">${glyph}` +
         `<ellipse cx="${x}" cy="${y}" rx="7.5" ry="5.5" transform="rotate(-20 ${x} ${y})"/></g></svg>`;
}

// Notes one after the other, on the page's own little synth (no keyboard needed).
function welcomeTones(notes) {
  try {
    if (!wl.audio) routeAudio(wl.audio = new AudioContext());
    const ctx = wl.audio;
    let t = ctx.currentTime + 0.05;
    for (const n of notes) {
      const osc = ctx.createOscillator(), g = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.value = 440 * Math.pow(2, (n - 69) / 12);
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.3, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.7);
      osc.connect(g).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.75);
      t += 0.85;
    }
  } catch (err) { statusEl.textContent = 'No sound: ' + err.message; }
}

// Mock exams: placement from a grade you pick, for those who'd rather show it in an exam.
async function atlasMockForm() {
  path.shown = false;  // a goals update mustn't redraw the Path over this form
  atlasTab('place');
  const side = $('atlas-detail');
  let p = null;
  try { p = (await cmd('placement_state')).placement; } catch (err) { /* none */ }
  const tiers = (atlas.data ? atlas.data.tiers : []).map(t => `<option value="${t.id}">${esc(t.title)}</option>`).join('');
  const going = p && (p.status === 'running' || p.status === 'paused');
  side.innerHTML = `<p><a href="#" id="place-back">← Getting to know you</a></p><h3>Mock exams</h3><p class="a-muted">Full mock exams, starting at the grade you think you're at. ` +
    `Each pass moves up a grade until one isn't passed; if the first isn't, it steps down until one is. ` +
    `Grades passed are credited across the Roadmap, and the first grade not passed becomes your goal, its weakest items first.</p>` +
    (going ? `<p>Under way: ${p.exams.length} exam${p.exams.length === 1 ? '' : 's'} sat${p.next_title ? `, next ${esc(p.next_title)}` : ''}.</p>` +
             `<p><button id="place-continue">Continue</button></p><p class="a-muted">Or start again:</p>` : '') +
    `<p><label>Start at <select id="place-tier">${tiers}</select></label> <button id="place-start">Start placement</button></p>`;
  const go = async (name, body) => {
    try {
      const out = await cmd(name, body);
      atlasShow(false);
      exam.state = out.exam;
      exam.placement = out.placement;
      examRender();
    } catch (err) { statusEl.textContent = err.message; }
  };
  $('place-back').onclick = e => { e.preventDefault(); atlasPlaceForm(); };
  $('place-start').onclick = () => go('placement_start', {tier: $('place-tier').value});
  if ($('place-continue')) $('place-continue').onclick = () => go('placement_continue', {});
}

// An exam left unfinished (the page reloaded, or the coach restarted) comes back, and so
// does a placement under way.
Promise.all([cmd('exam_state').catch(() => ({})), cmd('placement_state').catch(() => ({}))]).then(([e, p]) => {
  exam.state = e.exam || null;
  exam.placement = e.exam && p.placement && p.placement.status !== 'done' ? p.placement : null;
  examRender();
});

// -- goals and the Path panel ---------------------------------------------------------------
// A goal (said to the Maestro, typed in the goal box, or set by Claude) is planned by Claude
// Code in the background; the panel lists the active goal's families in order, each with its
// ring, opening to its requirements and stages. Next opens the next unfinished stage.

const path = {state: null, shown: false};

async function pathShow() {
  path.shown = true;
  atlasTab('path');
  atlas.selected = null;
  tasksMark();
  atlasDraw();
  try { path.state = await cmd('goals'); } catch (err) { $('atlas-detail').textContent = err.message; return; }
  pathRender();
}

// Fresh goals for the Route panel (and the Planner tab, if it's showing).
async function goalsLoad() {
  try { path.state = await cmd('goals'); pathRender(); } catch (err) { /* the list keeps what it had */ }
}

function pathRender() {
  tasksRender();
  if (!path.shown) return;
  const st = path.state || {goals: [], path: []}, side = $('atlas-detail');
  const open = st.goals.filter(g => g.status === 'active');
  const planning = st.planning && !st.planning.done
    ? `<p class="p-status${st.planning.error ? ' p-err' : ''}">${st.planning.error ? 'Planning failed: ' + esc(st.planning.error)
        : `Planning “${esc(st.planning.text)}”… (a minute or two${st.planning.song ? ', longer while the song is looked up' : ''})`}</p>` : '';
  let html = `<h3>Planner</h3><div class="p-goalbox"><input id="goal-text" placeholder="A goal: a song, a skill, a grade…" aria-label="New goal">` +
             `<input id="goal-song" placeholder="Song file (optional)" aria-label="Song file" style="flex:0.7">` +
             `<button id="goal-plan">Plan it</button></div>${planning}`;
  if (route.preview) html += `<div class="p-unsaved">Showing the route to <b>${esc(route.preview.title)}</b> (not saved). ${quickSaveBtn()}</div>`;
  const goal = st.goal;
  if (open.length) {
    html += '<h4 class="p-routes-head">Saved routes</h4><div class="p-routes">' + open.map(g => {
      const on = g.id === st.active;
      let row = `<button class="p-route${on ? ' on' : ''}" data-goal="${g.id}" title="Show this route on the left and on the map">${esc(g.title)}</button>`;
      if (on && goal) {
        const reasons = (goal.planner && goal.planner.reasons) || [], sources = (goal.planner && goal.planner.sources) || [];
        const conflicts = (goal.planner && goal.planner.conflicts) || [];
        row += '<div class="p-route-body">' + (st.path.length
          ? `<p class="a-muted">${st.path.length} part${st.path.length === 1 ? '' : 's'} to go.</p>`
          : '<p class="a-muted">Everything on this route is done. Archive it, or set the next goal.</p>') +
          '<button id="path-next">Next ▸</button> <button id="goal-archive" title="Put this goal away; its bridges leave the Roadmap">Archive</button>';
        if (reasons.length || sources.length) {
          row += `<details class="p-reasons"><summary>Why this Path</summary><ul>${reasons.map(r => `<li>${esc(r)}</li>`).join('')}` +
                 conflicts.map(c => `<li>⚠ ${esc(c)}</li>`).join('') + '</ul>' +
                 (sources.length ? `<p>Sources: ${sources.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(new URL(u).hostname.replace(/^www\./, ''))}</a>`).join(', ')}</p>` : '') +
                 '</details>';
        }
        row += '</div>';
      }
      return row;
    }).join('') + '</div>';
  } else {
    html += '<p class="a-muted">No goal yet. Type one above, tell the Maestro, or let a few quick questions find where you start.</p>' +
            '<p><button class="wl-go" id="path-place">Find where I start ▸</button></p>';
  }
  side.innerHTML = html;
  if ($('path-place')) $('path-place').onclick = atlasPlaceForm;
  quickSaveWire(side);
  $('goal-plan').onclick = async () => {
    const text = $('goal-text').value.trim();
    if (!text) return;
    try { await cmd('goal_plan', {text, song: $('goal-song').value.trim() || null}); path.state = await cmd('goals'); pathRender(); }
    catch (err) { statusEl.textContent = err.message; }
  };
  side.querySelectorAll('[data-goal]').forEach(b => b.onclick = async () => {
    try { route.preview = null; path.state = await cmd('goal_activate', {id: b.dataset.goal}); pathRender(); atlasDraw(); }
    catch (err) { statusEl.textContent = err.message; }
  });
  if ($('goal-archive')) $('goal-archive').onclick = async () => {
    if (!confirm('Archive this goal? Its bridges leave the Roadmap.')) return;
    path.state = await cmd('goal_archive', {id: st.active}); pathRender(); atlasLoad(true).then(atlasDraw);
  };
  if ($('path-next')) $('path-next').onclick = pathNext;
}

// -- the Route panel (left) ---------------------------------------------------------------
// One route, inspected: the active goal's Path, or, while a lesson off it is selected, the
// route to that lesson (not saved until Quick save on the right). Every family in order, each
// lesson (requirement) in it a folder of its exercises (stages). A family or lesson shows on
// the map and in the right panel (a lesson also opens or closes); an exercise starts
// practicing: lessons are launched only from here.

const tasks = {closed: new Set()};  // families and lessons folded by hand stay folded across updates
const route = {preview: null, ids: new Set()};  // preview: {target, title, path} from 'route'; ids: outlined on the map

// The route on show: the preview, or the active goal's Path.
function routeShown() {
  const st = path.state || {};
  return route.preview ? route.preview.path : st.goal ? st.path : [];
}

function routeIds(families) {
  const ids = new Set();
  for (const f of families) {
    ids.add(f.family);
    for (const r of f.requirements) { ids.add(r.id); r.stages.forEach(sg => ids.add(sg.id)); }
  }
  return ids;
}

// A lesson (or family) chosen on the map or on the right brings its route up on the left,
// unless it's already on the one there.
async function routeFor(n) {
  if (!['requirement', 'stage', 'family'].includes(n.level)) return;
  const key = n.level === 'stage' ? n.parent : n.id;
  const active = path.state && path.state.goal ? routeIds(path.state.path) : new Set();
  if (active.has(key)) {
    if (route.preview) { route.preview = null; pathRender(); atlasDraw(); }
  } else if (!(route.preview && routeIds(route.preview.path).has(key))) {
    let out;
    try { out = await cmd('route', {id: n.id}); } catch (err) { statusEl.textContent = err.message; return; }
    if (atlas.selected !== n.id) return;
    route.preview = out;
    pathRender();
    atlasDraw();
  }
  tasksMark(true);
}

const quickSaveBtn = () => route.preview
  ? `<button class="p-quick" title="Keep this route as a goal under Saved routes">★ Quick save the route to ${esc(route.preview.title)}</button>` : '';

function quickSaveWire(box) {
  box.querySelectorAll('.p-quick').forEach(b => b.onclick = async () => {
    b.disabled = true;
    try { path.state = await cmd('goal_quick', {id: route.preview.target}); route.preview = null; pathRender(); routeNote(); atlasDraw(); }
    catch (err) { statusEl.textContent = err.message; b.disabled = false; }
  });
}

// Under a lesson's details: Quick save while its route isn't saved, or the goal it's part of.
function routeNote() {
  const box = $('atlas-route-note');
  if (!box) return;
  const st = path.state || {}, n = atlas.byId.get(atlas.selected);
  const key = n && (n.level === 'stage' ? n.parent : n.id);
  box.innerHTML = route.preview ? `<p>${quickSaveBtn()}</p>`
    : st.goal && key && routeIds(st.path).has(key) ? `<p class="a-muted">On your route: ${esc(st.goal.title)}</p>` : '';
  quickSaveWire(box);
}

function tasksRender() {
  const box = $('atlas-task-list'), st = path.state;
  if (!st) { box.innerHTML = '<p class="a-muted">Loading…</p>'; return; }
  const families = routeShown();
  route.ids = routeIds(families);
  if (!route.preview && !st.goal) {
    box.innerHTML = '<p class="a-muted">No route yet. Choose a lesson on the map to see its route, or set a goal in the Planner →</p>';
    return;
  }
  const link = (id, level, title, extra = '', play = false) =>
    `<a href="#" data-zoom="${id}"${play ? ' data-play' : ''}><i class="a-dot a-${level}"></i><span>${esc(title)}${extra}</span></a>`;
  const open = id => tasks.closed.has(id) ? '' : ' open';
  let html = route.preview
    ? `<p class="t-goal">Route to ${esc(route.preview.title)}</p><p class="a-muted t-unsaved">Not saved${st.goal
        ? ` · <a href="#" class="t-back">← ${esc(st.goal.title)}</a>` : ''}</p>`
    : `<p class="t-goal">${esc(st.goal.title || '')}</p>`;
  if (!families.length) html += '<p class="a-muted">Everything on this route is done.</p>';
  html += families.map((f, k) => {
    const ring = f.total ? `<span class="a-muted t-ring">${f.done}/${f.total}</span>` : '';
    const reqs = f.requirements.map(r => `<details class="t-req" data-fold="${esc(r.id)}"${open(r.id)}><summary>` +
      link(r.id, r.level, r.title, (r.recheck ? ' <span class="a-muted">(recheck)</span>' : '') +
        (r.temporary ? ` <span class="a-muted">· ${r.kind === 'drill' || r.kind === 'song' ? r.kind : 'bridge'}</span>` : '')) +
      `</summary><div class="t-stages">${r.stages.map(sg => link(sg.id, sg.level, sg.title,
        sg.lesson ? ' <b class="t-go">▶ Start</b>' : ` · ${r.temporary ? 'writing…' : 'no lesson yet'}`, !!sg.lesson)).join('')}</div></details>`).join('');
    const famLevel = f.total && f.done === f.total ? 'proficient' : f.done ? 'practised' : 'not_started';
    const fam = atlas.byId.has(f.family) ? link(f.family, famLevel, `${k + 1}. ${f.title}`) : `<span>${k + 1}. ${esc(f.title)}</span>`;
    return `<details class="t-fam" data-fold="${esc(f.family)}"${open(f.family)}><summary>${fam}${ring}</summary>${reqs}</details>`;
  }).join('');
  box.innerHTML = html;
  const back = box.querySelector('.t-back');
  if (back) back.onclick = e => { e.preventDefault(); route.preview = null; pathRender(); routeNote(); atlasDraw(); };
  box.querySelectorAll('details').forEach(d => d.ontoggle = () => tasks.closed[d.open ? 'delete' : 'add'](d.dataset.fold));
  box.querySelectorAll('[data-zoom]').forEach(a => a.onclick = e => {
    e.preventDefault();  // in a summary, this also keeps the folder from toggling by itself
    const id = a.dataset.zoom;
    if ('play' in a.dataset) return stepOpen(id);
    if (!atlas.byId.has(id)) { statusEl.textContent = 'That one isn\'t on the map yet.'; return; }
    const folder = a.parentElement.tagName === 'SUMMARY' && a.parentElement.parentElement;
    const lesson = folder && folder.classList.contains('t-req') ? !folder.open : null;
    atlasActivate(id);
    if (lesson !== null) folder.open = lesson;  // after the reveal, so a click can also close it
  });
  tasksMark();
}

// Lights the task open on the map and scrolls the list to it; on a new selection (reveal),
// opens the folders it's in and its own.
function tasksMark(reveal = false) {
  let on = null;
  $('atlas-task-list').querySelectorAll('[data-zoom]').forEach(a => {
    const hit = a.dataset.zoom === atlas.selected;
    a.classList.toggle('on', hit);
    if (hit && !on) on = a;
  });
  if (!on) return;
  for (let d = reveal && on.closest('details'); d; d = d.parentElement.closest('details')) {
    if (!d.open) { d.open = true; tasks.closed.delete(d.dataset.fold); }
  }
  on.scrollIntoView({block: 'nearest'});
}

// Both side panels: drag the grip to resize, « / » or a double-click on the grip to fold one
// down to a rail, the rail to bring it back. Remembered per browser.
(function atlasPanels() {
  const KEY = 'coach.atlasPanels';
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (err) { /* private window */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (err) { /* ignore */ } };
  const fold = (panel, collapsed) => {
    panel.toggleAttribute('data-collapsed', collapsed);
    saved[panel.id] = Object.assign(saved[panel.id] || {}, {collapsed});
    save();
  };
  document.querySelectorAll('#atlas-body .a-panel').forEach(panel => {
    const s = saved[panel.id] || {};
    if (s.width) panel.style.width = s.width + 'px';
    panel.toggleAttribute('data-collapsed', !!s.collapsed);
    panel.querySelector('.a-collapse').onclick = () => fold(panel, true);
    panel.querySelector('.a-rail').onclick = () => fold(panel, false);
  });
  document.querySelectorAll('#atlas-body .a-grip').forEach(grip => {
    const panel = $(grip.dataset.panel), sign = panel.id === 'atlas-tasks' ? 1 : -1;
    grip.ondblclick = () => fold(panel, !panel.hasAttribute('data-collapsed'));
    grip.onpointerdown = e => {
      if (e.button !== 0) return;
      const x0 = e.clientX, w0 = panel.hasAttribute('data-collapsed') ? 34 : panel.getBoundingClientRect().width;
      grip.setPointerCapture(e.pointerId);
      grip.classList.add('a-dragging');
      grip.onpointermove = m => {
        const w = Math.round(w0 + sign * (m.clientX - x0));
        if (w < 120) { panel.setAttribute('data-collapsed', ''); return; }  // dragged shut
        panel.removeAttribute('data-collapsed');
        panel.style.width = Math.min(w, window.innerWidth * 0.45) + 'px';
      };
      grip.onpointerup = grip.onpointercancel = () => {
        grip.onpointermove = grip.onpointerup = grip.onpointercancel = null;
        grip.classList.remove('a-dragging');
        const collapsed = panel.hasAttribute('data-collapsed');
        saved[panel.id] = collapsed ? Object.assign(saved[panel.id] || {}, {collapsed}) : {collapsed, width: parseInt(panel.style.width, 10) || undefined};
        save();
      };
    };
  });
  // The map's size changes with the panels': redraw it to fill the new space.
  new ResizeObserver(() => { if (!$('atlas-view').hidden) atlasDraw(); }).observe($('atlas-map'));
})();

async function pathNext() {
  try {
    const nxt = await cmd('path_next');
    await stepOpen(nxt.stage);
  } catch (err) { statusEl.textContent = err.message; }
}

document.querySelectorAll('#atlas-tabs [data-tab]').forEach(b => b.addEventListener('click', () => {
  if (b.getAttribute('aria-selected') === 'true') return;  // already showing it
  (b.dataset.tab === 'path' ? pathShow : atlasPlaceForm)();
}));

// The server's 'atlas' event: a step's verdict after a graded pass, or the exam's state.
function atlasEvent(msg) {
  if (msg.goals) { path.state = msg.goals; pathRender(); if (msg.goals.planning && msg.goals.planning.done) atlasLoad(true).then(atlasDraw).catch(() => {}); }
  if (msg.refresh) atlasLoad(true).then(() => { atlasDraw(); goalsLoad(); }).catch(() => {});
  if (msg.open) {
    cmd('node', {id: msg.open}).then(info => {  // a stage opens its lesson; anything else is shown on the Atlas
      if (info.node.level === 'stage') stepOpen(msg.open, info);
      else atlasShow(true).then(() => atlasActivate(msg.open));
    }).catch(err => { statusEl.textContent = err.message; });
  }
  if ('exam' in msg) {
    exam.state = msg.exam || (exam.state && exam.state.status === 'done' ? exam.state : null);
    if ('placement' in msg) exam.placement = msg.placement;
    examRender();
  }
  const v = msg.verdict;
  if (v && step.lesson && v.node === step.node) {
    if (v.passed != null) step.done[v.step] = v.passed;  // null: the run ended without a grade
    stepRender();
    const el = $('sp-verdict');
    if (el) el.textContent = v.passed == null ? v.detail || ''
      : `${v.passed ? '✓ Nailed it!' : '↻ Almost, one more go!'}${v.detail ? ' · ' + v.detail : ''}`;
  }
  if (msg.drills) {  // a bar that keeps slipping got a drill, ahead of this on the Path
    const bars = msg.drills.map(d => d.bar).join(' and ');
    const note = msg.drills.length > 1 ? `Bars ${bars} keep slipping: drills for them are on the Roadmap.` : `Bar ${bars} keeps slipping: a drill for it is on the Roadmap.`;
    const el = $('sp-verdict');
    if (el) el.textContent += ' · ' + note; else statusEl.textContent = note;
  }
  if (v) atlasRefreshStates();
  if (v && typeof todayLoad === 'function') todayLoad();  // a part of today's plan may be done now
  if (v && document.body.dataset.view === 'lesson') lessonNav();  // the exercise's dot fills in
}

// -- open / close, input ------------------------------------------------------------------

async function atlasShow(open) {
  if (open) document.body.dataset.view = 'progress';
  else if (document.body.dataset.view === 'progress') document.body.dataset.view = 'practice';
  $('atlas-view').hidden = !open;
  document.body.classList.toggle('atlas-open', open);
  window.dispatchEvent(new CustomEvent('coach:viewchange'));
  if (!open) return;
  try {
    const first = !atlas.data;
    await atlasLoad();
    if (first) { atlasHome(); pathShow(); } else { atlasRefreshStates(); goalsLoad(); }
  } catch (err) {
    $('atlas-detail').innerHTML = `<p>${esc(err.message)}</p><p class="a-muted">` + (document.body.dataset.instrument === 'flute'
      ? 'The flute Roadmap is built from your local flute syllabus: <code>python -m midi_coach.atlas.pan</code>'
      : 'The Roadmap is built from your local syllabus: <code>python -m midi_coach.atlas.build</code>') + `</p>`;
  }
}

(function atlasInput() {
  const svg = $('atlas-svg');
  // Wheel: zoom by how far it scrolled, so a trackpad's many small ticks don't race in;
  // a sideways scroll (deltaY 0) does nothing. Pinch (ctrlKey) sends small deltas, so it's geared up.
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const dy = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? atlasSize().h : 1);
    if (!dy) return;
    const r = svg.getBoundingClientRect();
    const k = e.ctrlKey ? 0.01 : 0.0014;  // 0.0014: one 100-px mouse notch = 1.15x
    atlasZoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-Math.max(-300, Math.min(300, dy)) * k));
  }, {passive: false});
  // Primary button only. The node is taken at press and release from the point itself, since
  // pointer capture sends every event to the svg (e.target is no help there).
  svg.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    atlas.drag = {x: e.clientX, y: e.clientY, moved: false, id: atlasHit(e.clientX, e.clientY)};
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener('pointermove', e => {
    atlas.pointer = {x: e.clientX, y: e.clientY};
    const d = atlas.drag;
    if (d && !(e.buttons & 1)) atlas.drag = null;  // the release was lost (context menu, alt-tab)
    else if (d) {
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
      if (d.moved) {
        atlas.view.x -= dx / atlas.view.s; atlas.view.y -= dy / atlas.view.s;
        d.x = e.clientX; d.y = e.clientY;
        atlasDraw();
      }
      return;
    }
    atlasSetHover(atlasHit(e.clientX, e.clientY));
  });
  svg.addEventListener('pointerup', e => {
    const d = atlas.drag;
    atlas.drag = null;
    if (d && !d.moved && d.id && atlasHit(e.clientX, e.clientY) === d.id) atlasActivate(d.id);
  });
  const endDrag = () => { atlas.drag = null; };
  svg.addEventListener('pointercancel', endDrag);
  svg.addEventListener('lostpointercapture', endDrag);
  svg.addEventListener('pointerleave', () => { if (!atlas.drag) { atlas.pointer = null; atlasSetHover(null); } });
  window.addEventListener('resize', () => { if (!$('atlas-view').hidden) atlasDraw(); });
  document.addEventListener('keydown', e => {
    if ($('atlas-view').hidden || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    if (e.key === 'Escape') window.dispatchEvent(new CustomEvent('coach:navigate', {detail: {view: 'home'}}));
    if (e.key === 'Home' && atlas.data) atlasHome();
  });
  // Out of the Roadmap is back to Home: modes change only there.
  $('atlas-close').addEventListener('click', () => window.dispatchEvent(new CustomEvent('coach:navigate', {detail: {view: 'home'}})));
  $('atlas-home').addEventListener('click', () => atlas.data && atlasHome());

  let timer = null;
  const results = $('atlas-results');
  $('atlas-search').addEventListener('input', e => {
    clearTimeout(timer);
    const q = e.target.value.trim();
    if (!q) { results.hidden = true; return; }
    timer = setTimeout(async () => {
      const out = await cmd('search', {q});
      results.innerHTML = out.results.length
        ? out.results.map(r => `<button data-go="${r.id}">${esc(r.title)}<span class="a-muted"> · ${esc(r.tier)} · ${esc(r.level)}</span></button>`).join('')
        : '<p class="a-muted">Nothing matches.</p>';
      results.hidden = false;
      results.querySelectorAll('[data-go]').forEach(b => b.addEventListener('click', () => {
        results.hidden = true;
        const n = atlas.byId.get(b.dataset.go);
        if (n) { atlasFit((n.level === 'stage' ? atlas.byId.get(n.parent) : n).box, 60); atlasSelect(n.id); }
      }));
    }, 180);
  });
})();


// -- singing: pitch detection in the browser ----------------------------------------------
// YIN (de Cheveigne & Kawahara) on the microphone, every 30 ms over a 2048-sample window;
// a note is the pitch held 120 ms within 40 cents (the same constants as atlas/aural.py).
// Listening ends with Done, after 1.5 s of quiet once something was sung, or at a limit.

const SING = {threshold: 0.15, fmin: 70, fmax: 1100, minNote: 0.12, cents: 40, rmsGate: 0.01, hop: 30, quietEnd: 1.5};
let singing = null;

function yinPitch(buf, sr) {
  const tmax = Math.min(buf.length >> 1, Math.floor(sr / SING.fmin)), tmin = Math.max(2, Math.floor(sr / SING.fmax));
  const n = buf.length - tmax, cmnd = new Float32Array(tmax + 1);
  let running = 0;
  cmnd[0] = 1;
  for (let tau = 1; tau <= tmax; tau++) {
    let acc = 0;
    for (let i = 0; i < n; i++) { const d = buf[i] - buf[i + tau]; acc += d * d; }
    running += acc;
    cmnd[tau] = running ? acc * tau / running : 1;
  }
  let tau = tmin;
  for (; tau < tmax; tau++) {
    if (cmnd[tau] < SING.threshold) { while (tau + 1 < tmax && cmnd[tau + 1] < cmnd[tau]) tau++; break; }
  }
  if (tau >= tmax) return null;
  const a = cmnd[tau - 1], b = cmnd[tau], c = cmnd[tau + 1], den = a - 2 * b + c;
  return sr / (den ? tau + (a - c) / (2 * den) : tau);
}

function notesFromTrack(track) {  // [[t, hz|null]] -> [{midi, start, end, cents}]
  const out = [];
  let run = [];
  const median = xs => { const s = [...xs].sort((p, q) => p - q); return s[s.length >> 1]; };
  const flush = () => {
    if (run.length >= 2 && run[run.length - 1][0] - run[0][0] >= SING.minNote) {
      const m = median(run.map(r => r[1]));
      out.push({midi: Math.round(m), start: run[0][0], end: run[run.length - 1][0], cents: Math.round(100 * (m - Math.round(m)))});
    }
  };
  for (const [t, hz] of track) {
    const m = hz ? 69 + 12 * Math.log2(hz / 440) : null;
    if (m !== null && run.length && Math.abs(m - median(run.map(r => r[1]))) * 100 <= SING.cents) { run.push([t, m]); continue; }
    flush();
    run = m !== null ? [[t, m]] : [];
  }
  flush();
  return out;
}

const NAMES = ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'];
const noteName = m => NAMES[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1);

async function singStart(cur) {
  if (singing) return singStop();
  cmd('stop_playback').catch(() => {});  // the example would be heard as your singing
  let stream;
  try {
    const mic = store.get('mic', '');
    stream = await navigator.mediaDevices.getUserMedia({audio: {deviceId: mic ? {exact: mic} : undefined,
      echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
  } catch (err) {
    $('sp-verdict').textContent = 'No microphone (' + err.message + '). The JUNO-DS audio input carries the keyboard, not your voice.';
    return;
  }
  const ctx = new AudioContext(), analyser = ctx.createAnalyser();
  analyser.fftSize = 2048;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize), t0 = performance.now();
  const limit = 4 + (cur.ref ? cur.ref.length * 1.2 : 10);
  singing = {stream, ctx, track: [], lastVoice: 0, heard: false, step: cur};
  const btn = document.querySelector('#step-panel [data-act="sing"]');
  if (btn) btn.textContent = '■ Done';
  $('sp-verdict').textContent = 'Listening…';
  singing.timer = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let rms = 0;
    for (const x of buf) rms += x * x;
    rms = Math.sqrt(rms / buf.length);
    const t = (performance.now() - t0) / 1000;
    const hz = rms > SING.rmsGate ? yinPitch(buf, ctx.sampleRate) : null;
    singing.track.push([t, hz]);
    if (hz) {
      singing.lastVoice = t; singing.heard = true;
      const m = 69 + 12 * Math.log2(hz / 440), cents = Math.round(100 * (m - Math.round(m)));
      $('sp-pitch').textContent = ` ${noteName(Math.round(m))} ${cents >= 0 ? '+' : ''}${cents}¢`;
    }
    if (t > limit || (singing.heard && t - singing.lastVoice > SING.quietEnd)) singStop();
  }, SING.hop);
}

async function singStop() {
  const s = singing;
  if (!s) return;
  singing = null;
  clearInterval(s.timer);
  s.stream.getTracks().forEach(t => t.stop());
  s.ctx.close();
  const notes = notesFromTrack(s.track);
  $('sp-verdict').textContent = notes.length ? `Heard ${notes.map(n => noteName(n.midi)).join(' ')}` : 'Nothing heard.';
  try {
    const out = await cmd('sing_result', {node: step.node, step: s.step.id, notes});
    step.done[s.step.id] = out.passed;
    stepRender();
    $('sp-verdict').textContent = `${out.passed ? '✓ Nailed it!' : '↻ Almost, one more go!'} · ${out.detail}`;
  } catch (err) { statusEl.textContent = err.message; }
}

// An answer said aloud: recorded, transcribed on the PC (Whisper), then checked like a click.
async function sayAnswer(cur) {
  let stream;
  try {
    const mic = store.get('mic', '');
    stream = await navigator.mediaDevices.getUserMedia({audio: mic ? {deviceId: {exact: mic}} : true});
  }
  catch (err) { $('sp-verdict').textContent = 'No microphone: ' + err.message; return; }
  const rec = new MediaRecorder(stream), chunks = [];
  rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    const blob = new Blob(chunks, {type: rec.mimeType || 'audio/webm'});
    $('sp-verdict').textContent = 'Transcribing…';
    try {
      const res = await fetch('voice/transcribe', {method: 'POST', headers: {'Content-Type': blob.type}, body: blob});
      const {heard, error} = await res.json();
      if (error || !heard) { $('sp-verdict').textContent = error || "I didn't catch that."; return; }
      const out = await cmd('quiz_answer', {node: step.node, step: cur.id, answer: heard});
      step.done[cur.id] = out.passed;
      stepRender();
      $('sp-verdict').textContent = `You said “${heard}” · ${out.passed ? '✓ Right' : `✗ It's ${cur.options ? cur.options[out.answer] : 'not that'}`}`;
      if (out.passed) setTimeout(stepNext, 1200);
    } catch (err) { $('sp-verdict').textContent = err.message; }
  };
  rec.start();
  $('sp-verdict').textContent = 'Say your answer… (3 seconds)';
  setTimeout(() => rec.state !== 'inactive' && rec.stop(), 3000);
}
