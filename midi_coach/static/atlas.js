// The Atlas view and the step panel of the coach page (loaded after coach.html's script,
// whose helpers - $, cmd, esc, store, statusEl, portSel - it uses).
//
// The tree comes from cmd('atlas') with a fixed position for every node (atlas/layout.py),
// so this only draws: the zoom decides which level is shown (tier -> strand -> family ->
// requirement -> stage), only what's in view is drawn, and edges are the bundles of that
// level. Clicking zooms one level in; clicking a stage opens it in the side panel, and
// "Practise" opens its lesson above the sheet music.
"use strict";

const atlas = {data: null, byId: new Map(), kids: new Map(), states: {}, view: {x: 0, y: 0, s: 0.05},
               level: 'tier', hover: null, selected: null, raf: 0, drag: null, loading: null};
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
}

function atlasZoomAt(px, py, factor) {
  const v = atlas.view, s = Math.min(4, Math.max(0.02, v.s * factor));
  const wx = v.x + px / v.s, wy = v.y + py / v.s;
  atlas.view = {s, x: wx - px / s, y: wy - py / s};
  atlasDraw();
}

// Zoom one level in onto a node (clusters), or select it (stages, review, exam).
function atlasActivate(id) {
  const n = atlas.byId.get(id);
  if (!n) return;
  if (n.level === 'review' || n.level === 'exam') return atlasSelect(id);
  if (n.level === 'stage') {
    if (atlas.level !== 'stage') atlasFit(atlas.byId.get(n.parent).box, 60);
    return atlasSelect(id);
  }
  atlasSelect(id);
  atlasFit(n.box, n.level === 'requirement' ? 60 : 30);
}

function atlasDraw() {
  if (atlas.raf) return;
  atlas.raf = requestAnimationFrame(() => { atlas.raf = 0; atlasRender(); });
}

// -- drawing --------------------------------------------------------------------------

function fillFor(id) {
  const lv = levelOf(id);
  return lv === 'not_started' ? 'transparent' : lv === 'practised' ? 'rgba(0,180,180,.28)' : 'var(--accent)';
}

function ringArc(cx, cy, r, frac, s) {
  const c = 2 * Math.PI * r;
  return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,.15)" stroke-width="${3 / s}"/>` +
         `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--accent)" stroke-width="${3 / s}" ` +
         `stroke-dasharray="${(frac * c).toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"/>`;
}

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

function isWeakest(n) {
  const p = n.parent && atlas.states[n.parent];
  return p && p.weakest === n.id && (p.ring ?? 1) < 1;
}

function atlasRender() {
  const data = atlas.data;
  if (!data) return;
  const v = atlas.view, s = v.s, {w, h} = atlasSize();
  const level = atlas.level = atlasLevel(s);
  $('atlas-level').textContent = `${LEVEL_NAMES[level]} · ${Math.round(s * 100)}%`;
  $('atlas-world').setAttribute('transform', `scale(${s}) translate(${-v.x} ${-v.y})`);
  const depth = ['tier', 'strand', 'family', 'requirement', 'stage'].indexOf(level);
  const out = [];
  const visible = data.nodes.filter(n => n.box && inView(n.box, v, w, h));
  const focus = atlas.hover || atlas.selected;

  // Tier bands (always), with their title and ring.
  for (const n of visible.filter(n => n.level === 'tier')) {
    const [x, y, bw, bh] = n.box, st = stateOf(n.id);
    out.push(`<rect class="a-tier${depth === 0 ? ' a-click' : ''}" data-id="${n.id}" x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${12 / s}"/>`);
    const tx = x - 14 / s, px = depth === 0 ? 22 : 16;  // in the gutter left of the band
    out.push(label(tx, y + (px + 6) / s, n.title, px, s, 'text-anchor="end" class="a-tier-title"'));
    if (st.total) out.push(ringArc(tx - 14 / s, y + (px + 34) / s, 11 / s, st.ring || 0, s),
                           label(tx - 32 / s, y + (px + 39) / s, `${st.done}/${st.total}`, 12, s, 'text-anchor="end" class="a-muted"'));
  }
  // Strands: a tinted column per tier; headed at every level from strand down.
  for (const n of visible.filter(n => n.level === 'strand' && depth >= 1)) {
    const [x, y, bw, bh] = n.box, st = stateOf(n.id), tint = STRAND_TINT[n.strand];
    out.push(`<rect class="a-strand${depth === 1 ? ' a-click' : ''}" data-id="${n.id}" x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${8 / s}" style="--tint:${tint}"/>`);
    const star = depth === 1 && isWeakest(n) ? '★ ' : '';
    const full = star + (n.title.split(' · ')[1] || n.title), short = star + STRAND_SHORT[n.strand];
    if (depth === 1) {
      out.push(fitLabel(x + 8 / s, y + 22 / s, full, 18, bw - 40 / s, s, `class="a-strand-title" style="fill:${tint}"`, 9) ||
               fitLabel(x + 8 / s, y + 22 / s, short, 14, bw - 36 / s, s, `class="a-strand-title" style="fill:${tint}"`, 7));
      if (st.total) out.push(ringArc(x + bw - 22 / s, y + 18 / s, 9 / s, st.ring || 0, s));
    } else {
      out.push(fitLabel(x + 4 / s, y - 6 / s, full, 13, bw, s, `class="a-strand-title" style="fill:${tint}"`, 7) ||
               fitLabel(x + 4 / s, y - 6 / s, short, 13, bw, s, `class="a-strand-title" style="fill:${tint}"`, 6));
    }
  }
  // Families: pills (with ring) at family level, framed boxes below it.
  for (const n of visible.filter(n => n.level === 'family' && depth >= 2)) {
    const [x, y, bw, bh] = n.box, st = stateOf(n.id);
    if (depth === 2) {
      out.push(`<rect class="a-family a-click${n.temporary ? ' a-temp' : ''}" data-id="${n.id}" x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${Math.min(bh / 2, 18 / s)}"/>`);
      const title = (isWeakest(n) ? '★ ' : '') + n.title + (st.total ? '' : ' (none yet)');
      out.push(fitLabel(x + 12 / s, y + 20 / s, title, 14, bw - 64 / s, s, 'class="a-family-title"', 7));
      if (st.total) {
        out.push(ringArc(x + bw - 20 / s, y + 16 / s, 8 / s, st.ring || 0, s));
        out.push(label(x + bw - 34 / s, y + 20 / s, `${st.done}/${st.total}`, 11, s, 'text-anchor="end" class="a-muted"'));
      }
    } else {
      out.push(`<rect class="a-family-frame${n.temporary ? ' a-temp' : ''}" x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${10 / s}"/>`);
      out.push(fitLabel(x + 8 / s, y + 16 / s, n.title + (st.total ? ` · ${st.done}/${st.total}` : ''), 12, bw - 16 / s, s, 'class="a-family-title"', 6));
    }
  }
  // Requirements: rounded squares filled by level; at stage zoom an outline holding its stages.
  for (const n of visible.filter(n => n.level === 'requirement' && depth >= 3)) {
    const [x, y, bw, bh] = n.box;
    const mastered = levelOf(n.id) === 'mastered';
    if (depth === 3) {
      const sq = Math.min(bw, 70);
      out.push(`<rect class="a-req a-click${mastered ? ' a-gold' : ''}${n.temporary ? ' a-temp' : ''}" data-id="${n.id}" x="${x + (bw - sq) / 2}" y="${y}" width="${sq}" height="${Math.min(bh, 34)}" rx="${6 / s}" style="fill:${fillFor(n.id)}"/>`);
      const px = Math.min(11, bw * s / 7);
      if (px >= 6.5) out.push(`<foreignObject x="${x}" y="${y + 36}" width="${bw}" height="${Math.max(bh - 36, 20)}"><div class="a-req-title" style="font-size:${(px / s).toFixed(2)}px">${isWeakest(n) ? '★ ' : ''}${esc(n.title)}</div></foreignObject>`);
    } else {
      out.push(`<rect class="a-req-frame${mastered ? ' a-gold' : ''}${n.temporary ? ' a-temp' : ''}" data-id="${n.id}" x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${6 / s}"/>`);
      out.push(`<foreignObject x="${x + 2}" y="${y + 2}" width="${bw - 4}" height="30"><div class="a-req-title" style="font-size:${Math.min(5.2, 11 / s).toFixed(2)}px">${esc(n.title)}</div></foreignObject>`);
    }
  }
  // Stages: circles filled by level, gold ring when mastered.
  if (depth === 4) {
    for (const n of visible.filter(n => n.level === 'stage')) {
      const [x, y, d] = n.box, r = d / 2, cx = x + r, cy = y + r, lv = levelOf(n.id);
      out.push(`<circle class="a-stage a-click${lv === 'mastered' ? ' a-gold' : ''}${n.final ? ' a-final' : ''}${n.temporary ? ' a-temp' : ''}" data-id="${n.id}" cx="${cx}" cy="${cy}" r="${r}" style="fill:${fillFor(n.id)}"><title>${esc(n.title)} · ${lv.replace('_', ' ')}</title></circle>`);
      if (s > 2.2) out.push(label(cx + r + 4, cy + 3, n.title, 9, s, 'class="a-muted"'));
      if (n.writing && s > 1) out.push(label(cx + r + 4, cy + 3 + 11 / s, 'writing…', 9, s, 'class="a-writing"'));
    }
  }
  // Review (hexagon) and Exam (shield) at the foot of each tier.
  for (const n of visible.filter(n => (n.level === 'review' || n.level === 'exam') && depth >= 1)) {
    const [x, y, bw, bh] = n.box, lv = levelOf(n.id), cls = `a-${n.level} a-click${lv === 'mastered' ? ' a-gold' : ''}`;
    const shape = n.level === 'review'
      ? `<polygon class="${cls}" data-id="${n.id}" points="${x + 14},${y} ${x + bw - 14},${y} ${x + bw},${y + bh / 2} ${x + bw - 14},${y + bh} ${x + 14},${y + bh} ${x},${y + bh / 2}" style="fill:${fillFor(n.id)}"/>`
      : `<path class="${cls}" data-id="${n.id}" d="M${x} ${y} H${x + bw} V${y + bh * 0.55} Q${x + bw} ${y + bh} ${x + bw / 2} ${y + bh} Q${x} ${y + bh} ${x} ${y + bh * 0.55} Z" style="fill:${fillFor(n.id)}"/>`;
    out.push(shape.replace('/>', `><title>${esc(n.title)}</title></${n.level === 'review' ? 'polygon' : 'path'}>`), fitLabel(x + bw / 2, y + bh / 2 + 4 / s, n.title, 13, bw * 0.86, s, 'text-anchor="middle" class="a-gate-title"', 7));
    const best = stateOf(n.id).best;
    if (best && depth >= 2) out.push(label(x + bw / 2, y + bh + 16 / s, `best ${best}/150`, 11, s, 'text-anchor="middle" class="a-muted"'));
  }

  // Edges: the bundles of this level whose ends are near the view.
  const edges = [];
  for (const [a, b, count] of data.bundles[level] || []) {
    const na = atlas.byId.get(a), nb = atlas.byId.get(b);
    if (!na || !nb || !na.box || !nb.box) continue;
    const near = inView(na.box, v, w, h, 400) || inView(nb.box, v, w, h, 400);
    if (!near) continue;
    const hot = focus && (a === focus || b === focus || atlasAncestors(focus).has(a) || atlasAncestors(focus).has(b));
    const [ax, ay, aw, ah] = na.box, [bx, by, bw2] = nb.box;
    const spread = ((hashOf(a + b) % 11) - 5) * Math.min(aw, bw2) / 14;
    const x1 = ax + aw / 2 + spread, y1 = ay + ah, x2 = bx + bw2 / 2 + spread, y2 = by;
    const dy = Math.max(30, Math.abs(y2 - y1) / 2);
    const width = (Math.min(1 + Math.log2(count) / 2, 3) * (hot ? 1.6 : 1)) / s;
    edges.push(`<path class="a-edge${hot ? ' a-hot' : ''}" d="M${x1} ${y1} C${x1} ${y1 + dy} ${x2} ${y2 - dy} ${x2} ${y2}" stroke-width="${width.toFixed(2)}"/>`);
  }
  // A goal's temporary nodes: dashed links to what they build on and lead into.
  if (depth >= 3) {
    for (const [a, b] of data.temp_edges || []) {
      const na = atlas.byId.get(a), nb = atlas.byId.get(b);
      if (!na || !nb || !na.box || !nb.box || !(inView(na.box, v, w, h, 400) || inView(nb.box, v, w, h, 400))) continue;
      const [ax, ay, aw, ah] = na.box, [bx, by, bw2] = nb.box;
      edges.push(`<path class="a-edge a-temp-edge" d="M${ax + aw / 2} ${ay + ah} C${ax + aw / 2} ${ay + ah + 60} ${bx + bw2 / 2} ${by - 60} ${bx + bw2 / 2} ${by}" stroke-width="${(1.4 / s).toFixed(2)}"/>`);
    }
  }
  // Review and exam: lines from each strand down the funnel.
  if (depth >= 1) {
    for (const t of visible.filter(n => n.level === 'tier')) {
      const rv = atlas.byId.get(`${t.id}.review`), ex = atlas.byId.get(`${t.id}.exam`);
      if (!rv || !ex) continue;
      for (const st of atlas.kids.get(t.id) || []) {
        if (st.level !== 'strand') continue;
        const [sx, sy, sw, sh] = st.box;
        edges.push(`<path class="a-edge a-funnel" d="M${sx + sw / 2} ${sy + sh} L${rv.box[0] + rv.box[2] / 2} ${rv.box[1]}" stroke-width="${(1.2 / s).toFixed(2)}"/>`);
      }
      edges.push(`<path class="a-edge a-funnel" d="M${rv.box[0] + rv.box[2] / 2} ${rv.box[1] + rv.box[3]} L${ex.box[0] + ex.box[2] / 2} ${ex.box[1]}" stroke-width="${(2 / s).toFixed(2)}"/>`);
    }
  }
  // Selection ring.
  const sel = atlas.selected && atlas.byId.get(atlas.selected);
  if (sel && sel.box) {
    const [x, y, bw, bh] = sel.box, m = 4 / s;
    out.push(`<rect class="a-selected" x="${x - m}" y="${y - m}" width="${bw + 2 * m}" height="${bh + 2 * m}" rx="${8 / s}" stroke-width="${(2.5 / s).toFixed(2)}"/>`);
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

async function atlasSelect(id) {
  path.shown = false;
  atlas.selected = id;
  atlasDraw();
  const side = $('atlas-detail');
  side.innerHTML = '<p class="a-muted">Loading…</p>';
  let info;
  try { info = await cmd('node', {id}); } catch (err) { side.textContent = err.message; return; }
  if (atlas.selected !== id) return;
  const n = info.node, st = info.state || {};
  const trail = info.trail.slice(0, -1).map(t => `<a href="#" data-go="${t.id}">${esc(crumb(t))}</a>`).join(' › ');
  const lv = st.level ? st.level.replace('_', ' ') : st.total ? `${st.done} of ${st.total} requirements` : 'not started';
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
      ? `<p class="a-muted">${steps.length} step${steps.length === 1 ? '' : 's'}: ${steps.map(s => s.type).join(', ')}</p><button id="atlas-practise">Practise this stage</button>`
      : '<p class="a-muted">No lesson written for this stage yet.</p>';
  }
  if (n.level === 'exam') {
    html += `<p class="a-muted">Three pieces, scales and arpeggios, sight-reading and aural tests, marked out of 150 by the coach ` +
            `(pass 100, merit 120, distinction 130). A mock, not an exam board's exam.</p><button id="atlas-exam">Take the mock exam</button>`;
  }
  if (st.weakest) html += `<p><a href="#" data-go="${st.weakest}">★ Weakest part: ${esc((atlas.byId.get(st.weakest) || {}).title || '')}</a></p>`;
  side.innerHTML = html;
  const ex = $('atlas-exam');
  if (ex) ex.addEventListener('click', () => examStart(n.tier));
  side.querySelectorAll('[data-go]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); atlasActivate(a.dataset.go); }));
  const go = $('atlas-practise');
  if (go) go.addEventListener('click', () => stepOpen(id, info));
}

// -- the step panel (practice view) ------------------------------------------------------

const step = {node: null, lesson: null, index: 0, title: '', done: {}};
const crumb = t => t.level === 'strand' ? t.title.split(' · ').pop() : t.title;  // 'Grade 3 · Theory' -> 'Theory'

async function stepOpen(nodeId, info) {
  info = info || await cmd('node', {id: nodeId});
  Object.assign(step, {node: nodeId, lesson: info.lesson, index: 0, title: info.node.title, done: {},
                       trail: info.trail.map(crumb).join(' › ')});
  atlasShow(false);
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

function stepRender() {
  const panel = $('step-panel');
  if (!step.lesson) { panel.hidden = true; return; }
  panel.hidden = false;
  const steps = step.lesson.steps, cur = steps[step.index];
  const dots = steps.map((s, k) => `<button class="sp-dot${k === step.index ? ' on' : ''}${step.done[s.id] === true ? ' ok' : step.done[s.id] === false ? ' no' : ''}" data-k="${k}" title="${esc(s.type)}">${k + 1}</button>`).join('');
  let body = '';
  if (cur.type === 'read') {
    body = `<p class="sp-text">${esc(cur.text || '')}</p><button class="sp-act" data-act="done">Got it</button>`;
  } else if (cur.type === 'listen') {
    body = `<p>Listen${cur.hand && cur.hand !== 'both' ? ` (${esc(cur.hand)} hand)` : ''}${cur.tempo_percent && cur.tempo_percent !== 100 ? ` at ${cur.tempo_percent}%` : ''}.</p><button class="sp-act" data-act="start">▶ Listen</button>`;
  } else if (cur.type === 'play') {
    const p = cur.pass || {metric: 'notes', min: 90};
    const how = `${cur.mode === 'rehearse' ? 'Rehearse' : 'Learn'} · ${esc(cur.hand || 'both')} hand${cur.hand === 'both' ? 's' : ''}${cur.bars ? ` · bars ${esc(cur.bars)}` : ''} · ${cur.tempo_percent || 100}%`;
    body = `<p>${how}</p><p class="a-muted">Pass mark: ${esc(p.metric)} ≥ ${p.min}${p.tempo_min_pct ? `, tempo ≥ ${p.tempo_min_pct}%` : ''}${p.max_wrong != null ? `, at most ${p.max_wrong} wrong` : ''}</p><button class="sp-act" data-act="start">Start this step</button>`;
  } else if (cur.type === 'quiz') {
    body = `<p class="sp-text">${esc(cur.prompt || '')}</p>` +
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
  panel.innerHTML = `<div class="sp-head"><span class="sp-trail">${esc(step.trail)}</span>${review}<button class="sp-close" title="Close">✕</button></div>` +
                    `<div class="sp-row"><div class="sp-dots">${dots}</div><div class="sp-body">${body}<span id="sp-verdict"></span></div></div>`;
  panel.querySelector('.sp-close').onclick = () => { step.lesson = null; stepRender(); };
  panel.querySelectorAll('.sp-dot').forEach(b => b.onclick = () => { step.index = +b.dataset.k; stepRender(); });
  panel.querySelectorAll('[data-answer]').forEach(b => b.onclick = () => stepAnswer(+b.dataset.answer));
  panel.querySelectorAll('[data-act]').forEach(b => b.onclick = () => stepAct(b.dataset.act));
  panel.querySelectorAll('[data-review]').forEach(b => b.onclick = () => stepReview(b.dataset.review === 'ok'));
  if (cur.score && step.shown !== cur.id) { step.shown = cur.id; cmd('step_show', {node: step.node, step: cur.id}).catch(() => {}); }
}

async function stepAct(act) {
  const cur = step.lesson.steps[step.index];
  try {
    if (act === 'hear') { await cmd('step_play', {node: step.node, step: cur.id}); return; }
    if (act === 'sing') return singStart(cur);
    if (act === 'say') return sayAnswer(cur);
    if (act === 'keys') { await cmd('step_start', {node: step.node, step: cur.id, port: portSel.value, via: 'keyboard'}); $('sp-verdict').textContent = 'Listening to the keyboard…'; return; }
    if (act === 'done') {
      await cmd('step_done', {node: step.node, step: cur.id});
      step.done[cur.id] = true;
      stepNext();
    } else {
      if (typeof metroUnlock === 'function') metroUnlock();
      await cmd('step_start', {node: step.node, step: cur.id, port: portSel.value});
      if (cur.type === 'listen') { step.done[cur.id] = true; stepRender(); }
      if (cur.type === 'tap') $('sp-verdict').textContent = cur.along ? 'Tap along…' : 'Tap it back…';
    }
  } catch (err) { statusEl.textContent = err.message; }
}

async function stepAnswer(k) {
  const cur = step.lesson.steps[step.index];
  try {
    const out = await cmd('quiz_answer', {node: step.node, step: cur.id, answer: k});
    step.done[cur.id] = out.passed;
    stepRender();
    $('sp-verdict').textContent = out.passed ? '✓ Right' : `✗ It's ${cur.options ? cur.options[out.answer] : 'not that'}${out.explain ? ' – ' + out.explain : ''}`;
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
  if (!s && !exam.placement) { panel.hidden = true; return; }
  panel.hidden = false;
  if (!s) {  // placement between exams, or settled
    panel.innerHTML = `<div class="ex-head"><h3>Finding your level</h3><span class="ex-mock">Mock exams, marked by the coach — not by an exam board</span></div>` +
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
  panel.innerHTML = `<div class="ex-head"><h3>${esc(s.title)}</h3><span class="ex-mock">A mock exam, marked by the coach — not by an exam board</span></div>` +
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

// Find my level: placement from a grade you pick (the Atlas bar's button).
async function atlasPlaceForm() {
  const side = $('atlas-detail');
  let p = null;
  try { p = (await cmd('placement_state')).placement; } catch (err) { /* none */ }
  const tiers = (atlas.data ? atlas.data.tiers : []).map(t => `<option value="${t.id}">${esc(t.title)}</option>`).join('');
  const going = p && (p.status === 'running' || p.status === 'paused');
  side.innerHTML = `<h3>Find my level</h3><p class="a-muted">Full mock exams, starting at the grade you think you're at. ` +
    `Each pass moves up a grade until one isn't passed; if the first isn't, it steps down until one is. ` +
    `Grades passed are credited across the Atlas, and the first grade not passed becomes your goal, its weakest items first.</p>` +
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
  $('place-start').onclick = () => go('placement_start', {tier: $('place-tier').value});
  if ($('place-continue')) $('place-continue').onclick = () => go('placement_continue', {});
}
$('atlas-place').addEventListener('click', atlasPlaceForm);

// An exam left unfinished (the page reloaded, or the coach restarted) comes back, and so
// does a placement under way.
Promise.all([cmd('exam_state').catch(() => ({})), cmd('placement_state').catch(() => ({}))]).then(([e, p]) => {
  exam.state = e.exam || null;
  exam.placement = p.placement && p.placement.status !== 'done' ? p.placement : null;
  examRender();
});

// -- goals and the Path panel ---------------------------------------------------------------
// A goal (said to the Maestro, typed in the goal box, or set by Claude) is planned by Claude
// Code in the background; the panel lists the active goal's families in order, each with its
// ring, opening to its requirements and stages. Next opens the next unfinished stage.

const path = {state: null, shown: false};

async function pathShow() {
  path.shown = true;
  atlas.selected = null;
  atlasDraw();
  try { path.state = await cmd('goals'); } catch (err) { $('atlas-detail').textContent = err.message; return; }
  pathRender();
}

function pathRender() {
  if (!path.shown) return;
  const st = path.state || {goals: [], path: []}, side = $('atlas-detail');
  const open = st.goals.filter(g => g.status === 'active');
  const planning = st.planning && !st.planning.done
    ? `<p class="p-status${st.planning.error ? ' p-err' : ''}">${st.planning.error ? 'Planning failed: ' + esc(st.planning.error)
        : `Planning “${esc(st.planning.text)}”… (a minute or two${st.planning.song ? ', longer while the song is looked up' : ''})`}</p>` : '';
  let html = `<h3>Path</h3><div class="p-goalbox"><input id="goal-text" placeholder="A goal: a song, a skill, a grade…" aria-label="New goal">` +
             `<input id="goal-song" placeholder="Song file (optional)" aria-label="Song file" style="flex:0.7">` +
             `<button id="goal-plan">Plan it</button></div>${planning}`;
  if (open.length) {
    html += `<p><label>Goal <select id="goal-pick">${open.map(g => `<option value="${g.id}"${g.id === st.active ? ' selected' : ''}>${esc(g.title)}</option>`).join('')}</select></label>` +
            (st.active ? ` <button id="goal-archive" title="Put this goal away; its bridges leave the Atlas">Archive</button>` : '') + '</p>';
  }
  const goal = st.goal;
  if (goal) {
    const reasons = (goal.planner && goal.planner.reasons) || [], sources = (goal.planner && goal.planner.sources) || [];
    const conflicts = (goal.planner && goal.planner.conflicts) || [];
    html += `<button id="path-next">Next ▸</button>`;
    if (reasons.length || sources.length) {
      html += `<details class="p-reasons"><summary>Why this Path</summary><ul>${reasons.map(r => `<li>${esc(r)}</li>`).join('')}` +
              conflicts.map(c => `<li>⚠ ${esc(c)}</li>`).join('') + '</ul>' +
              (sources.length ? `<p>Sources: ${sources.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(new URL(u).hostname.replace(/^www\./, ''))}</a>`).join(', ')}</p>` : '') +
              '</details>';
    }
    if (!st.path.length) html += '<p class="a-muted">Everything on this Path is done. Archive the goal, or set the next one.</p>';
    html += st.path.map((f, k) => {
      const ring = f.total ? ` <span class="a-muted">${f.done}/${f.total}</span>` : '';
      const reqs = f.requirements.map(r => `<div class="p-req"><i class="a-dot a-${r.level}"></i><a href="#" data-go="${r.id}">${esc(r.title)}</a>` +
        `${r.recheck ? ' <span class="a-muted">(recheck)</span>' : ''}${r.temporary ? ' <span class="a-muted">· bridge</span>' : ''}` +
        `<div class="p-stages">${r.stages.map(sg => sg.lesson
          ? `<div><i class="a-dot a-${sg.level}"></i><a href="#" data-stage="${sg.id}">${esc(sg.title)}</a></div>`
          : `<div class="p-none"><i class="a-dot a-${sg.level}"></i>${esc(sg.title)} · ${r.temporary ? 'writing…' : 'no lesson yet'}</div>`).join('')}</div></div>`).join('');
      return `<details class="p-fam"${k === 0 ? ' open' : ''}><summary><span>${k + 1}. ${esc(f.title)}</span>${ring}</summary>${reqs}</details>`;
    }).join('');
  } else if (!open.length) {
    html += '<p class="a-muted">No goal yet. Type one above, tell the Maestro, or use Find my level to start from a grade.</p>';
  }
  side.innerHTML = html;
  $('goal-plan').onclick = async () => {
    const text = $('goal-text').value.trim();
    if (!text) return;
    try { await cmd('goal_plan', {text, song: $('goal-song').value.trim() || null}); path.state = await cmd('goals'); pathRender(); }
    catch (err) { statusEl.textContent = err.message; }
  };
  if ($('goal-pick')) $('goal-pick').onchange = async e => { path.state = await cmd('goal_activate', {id: e.target.value}); pathRender(); };
  if ($('goal-archive')) $('goal-archive').onclick = async () => {
    if (!confirm('Archive this goal? Its bridges leave the Atlas.')) return;
    path.state = await cmd('goal_archive', {id: st.active}); pathRender(); atlasLoad(true).then(atlasDraw);
  };
  if ($('path-next')) $('path-next').onclick = pathNext;
  side.querySelectorAll('[data-go]').forEach(a => a.onclick = e => { e.preventDefault(); path.shown = false; atlasActivate(a.dataset.go); });
  side.querySelectorAll('[data-stage]').forEach(a => a.onclick = e => { e.preventDefault(); stepOpen(a.dataset.stage); });
}

async function pathNext() {
  try {
    const nxt = await cmd('path_next');
    await stepOpen(nxt.stage);
  } catch (err) { statusEl.textContent = err.message; }
}

$('atlas-path').addEventListener('click', pathShow);

// The server's 'atlas' event: a step's verdict after a graded pass, or the exam's state.
function atlasEvent(msg) {
  if (msg.goals) { path.state = msg.goals; pathRender(); if (msg.goals.planning && msg.goals.planning.done) atlasLoad(true).then(atlasDraw).catch(() => {}); }
  if (msg.refresh) atlasLoad(true).then(() => { atlasDraw(); if (path.shown) pathShow(); }).catch(() => {});
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
    step.done[v.step] = v.passed;
    stepRender();
    const el = $('sp-verdict');
    if (el) el.textContent = `${v.passed ? '✓ Passed' : '✗ Not yet'}${v.detail ? ' · ' + v.detail : ''}`;
  }
  if (v) atlasRefreshStates();
}

// -- open / close, input ------------------------------------------------------------------

async function atlasShow(open) {
  $('atlas-view').hidden = !open;
  document.body.classList.toggle('atlas-open', open);
  if (!open) return;
  try {
    const first = !atlas.data;
    await atlasLoad();
    if (first) { atlasHome(); pathShow(); } else atlasRefreshStates();
  } catch (err) {
    $('atlas-detail').innerHTML = `<p>${esc(err.message)}</p><p class="a-muted">The Atlas is built from your local syllabus: <code>python -m midi_coach.atlas.build</code></p>`;
  }
}

(function atlasInput() {
  const svg = $('atlas-svg');
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    atlasZoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.15 : 1 / 1.15);
  }, {passive: false});
  svg.addEventListener('pointerdown', e => {
    atlas.drag = {x: e.clientX, y: e.clientY, moved: false};
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener('pointermove', e => {
    const d = atlas.drag;
    if (d) {
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
      if (d.moved) {
        atlas.view.x -= dx / atlas.view.s; atlas.view.y -= dy / atlas.view.s;
        d.x = e.clientX; d.y = e.clientY;
        atlasDraw();
      }
      return;
    }
    const id = e.target.closest && e.target.closest('[data-id]') && e.target.closest('[data-id]').dataset.id;
    if (id !== atlas.hover) { atlas.hover = id || null; atlasDraw(); }
  });
  svg.addEventListener('pointerup', e => {
    const d = atlas.drag;
    atlas.drag = null;
    if (d && !d.moved) {
      const hit = e.target.closest && e.target.closest('[data-id]');
      if (hit) atlasActivate(hit.dataset.id);
    }
  });
  window.addEventListener('resize', () => { if (!$('atlas-view').hidden) atlasDraw(); });
  document.addEventListener('keydown', e => {
    if ($('atlas-view').hidden || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    if (e.key === 'Escape') atlasShow(false);
    if (e.key === 'Home' && atlas.data) atlasHome();
  });
  $('atlas-close').addEventListener('click', () => atlasShow(false));
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
    $('sp-verdict').textContent = `${out.passed ? '✓ Passed' : '✗ Not yet'} · ${out.detail}`;
  } catch (err) { statusEl.textContent = err.message; }
}

// An answer said aloud: recorded, transcribed on the PC (Whisper), then checked like a click.
async function sayAnswer(cur) {
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); }
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
