// The Roadmap view and the step panel of the coach page (loaded after coach.html's script,
// whose helpers - $, cmd, esc, store, statusEl, portSel - it uses).
//
// The tree comes from cmd('atlas'). The map shows one level at a time, with no zoom: your
// route, the whole course, or one grade's board with a family's lessons in a drawer. Choosing
// an exercise shows it in the side panel; "Practice" (or the Route panel) opens its lesson
// above the sheet music.
"use strict";

const atlas = {data: null, byId: new Map(), kids: new Map(), states: {}, stamp: 0, mode: null, tier: null, family: null,
               selected: null, raf: 0, loading: null, viewEl: null, viewKey: '', origin: null, reveal: false};
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
      atlas.stamp++;
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
  try { atlas.states = (await cmd('atlas')).states || {}; atlas.stamp++; atlasDraw(); } catch (err) {}
}

const stateOf = id => atlas.states[id] || {};
const levelOf = id => stateOf(id).level || 'not_started';

// -- views ----------------------------------------------------------------------------
// The map shows one level at a time and never zooms: your route (the active goal's Path, or
// the route to a lesson chosen off it) as a road of stops; the whole course as a road of grade
// medals; or one grade as a board, a lane per strand of family badges, a family's lessons in a
// drawer. Moving between them grows out of (or shrinks back into) what was clicked.

const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const GOLD = '#e3b341', NEUTRAL = '#c9d1d9';

// Strand and node glyphs on a 24-unit grid, stroked.
const GLYPH = {
  pieces: '<path d="M9 17V6l10-2v11"/><circle cx="7" cy="17" r="2.4"/><circle cx="17" cy="15" r="2.4"/>',
  technique: '<path d="M3 19h4v-4h4v-4h4V7h4V3"/>',
  sight: '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.6"/>',
  aural: '<path d="M7 9a5 5 0 0 1 10 0c0 3-3 3.5-3 6.5a2.5 2.5 0 0 1-5 0"/><path d="M10 9.5a2 2 0 0 1 4 0"/>',
  theory: '<path d="M3 5.5c3-1.3 6-1.3 9 .5 3-1.8 6-1.8 9-.5V19c-3-1.3-6-1.3-9 .5-3-1.8-6-1.8-9-.5z"/><path d="M12 6v13.5"/>',
  review: '<path d="M4 12a8 8 0 0 1 13.7-5.6L20 9"/><path d="M20 4v5h-5"/><path d="M20 12a8 8 0 0 1-13.7 5.6L4 15"/><path d="M4 20v-5h5"/>',
  exam: '<path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8-4.3-4.1 5.9-.9z"/>',
  bridge: '<path d="M2 17h20"/><path d="M5 17v-3a7 7 0 0 1 14 0v3"/><path d="M9 17v-4.5M15 17v-4.5"/>',
  goal: '<path d="M5 21V4"/><path d="M5 4h12l-2.5 4L17 12H5"/>',
};
const glyph = (k, size, color) => `<svg class="a-glyph" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="${color}" ` +
  `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${GLYPH[k] || GLYPH.goal}</svg>`;

// A node's colour is its strand's; grades are neutral, Review, Exam and goal bridges gold.
function tintOf(n) {
  if (!n) return NEUTRAL;
  if (n.level === 'review' || n.level === 'exam' || (n.temporary && !n.strand)) return GOLD;
  return STRAND_TINT[n.strand || (n.id || '').split('.')[1]] || NEUTRAL;
}

const reqsOf = id => (atlas.kids.get(id) || []).filter(k => k.level === 'requirement');
const stagesOf = id => (atlas.kids.get(id) || []).filter(k => k.level === 'stage');
const rankOf = id => RANKS[levelOf(id)] || 0;

// How far along a node is, 0..1: a cluster's ring, a lesson's share of exercises proficient.
function fracOf(n) {
  if (!n) return 0;
  if (['tier', 'strand', 'family'].includes(n.level)) return stateOf(n.id).ring || 0;
  if (n.level === 'review' || n.level === 'exam' || n.level === 'stage') return rankOf(n.id) >= 2 ? 1 : rankOf(n.id) ? 0.4 : 0;
  if (rankOf(n.id) >= 2) return 1;
  const stages = stagesOf(n.id);
  const done = stages.filter(s => rankOf(s.id) >= 2).length;
  return stages.length ? Math.max(done / stages.length, rankOf(n.id) ? 0.12 : 0) : rankOf(n.id) ? 0.4 : 0;
}

// Gold once every lesson inside is mastered.
function masteredOf(n) {
  if (!n) return false;
  if (n.level === 'requirement' || n.level === 'stage' || n.level === 'review' || n.level === 'exam') return levelOf(n.id) === 'mastered';
  const reqs = n.level === 'family' ? reqsOf(n.id) : [];
  return n.level === 'family' ? reqs.length > 0 && reqs.every(r => levelOf(r.id) === 'mastered') : (stateOf(n.id).ring || 0) >= 1;
}

// -- rings: a ring that grew since you last looked sweeps up from where it was ----------

const seen = {map: null, key: '', timer: 0};
function seenMap() {
  const key = 'coach.atlasSeen.' + (document.body.dataset.instrument || 'piano');
  if (seen.key !== key) {
    seen.key = key;
    try { seen.map = JSON.parse(localStorage.getItem(key)) || {}; } catch (err) { seen.map = {}; }
  }
  return seen.map;
}
function seenSave() {
  clearTimeout(seen.timer);
  seen.timer = setTimeout(() => { try { localStorage.setItem(seen.key, JSON.stringify(seen.map)); } catch (err) { /* private window */ } }, 400);
}

// An icon: a progress ring round a face (a rounded square for a family, a circle otherwise)
// holding a glyph or a short label. kind: 'badge' | 'medal' | 'stop' | 'gate'.
function iconHtml(id, f, tint, size, {kind = 'badge', glyphKey = null, label = '', mastered = false, next = false, dashed = false} = {}) {
  const map = seenMap(), prev = map[id];
  const from = prev != null && prev < f - 0.001 && !reduceMotion() ? prev : f;
  const done = f >= 1;
  const ringCol = mastered ? GOLD : tint;
  const face = label
    ? `<span class="a-label">${esc(label)}</span>`
    : glyph(glyphKey, Math.round(size * 0.36), done ? 'var(--bg)' : tint);
  return `<span class="a-ico a-${kind}${done ? ' a-done' : ''}${mastered ? ' a-mastered-ico' : ''}${next ? ' a-next' : ''}${dashed ? ' a-dashed' : ''}" ` +
         `style="--tint:${tint};--ring:${ringCol};--size:${size}px">` +
         (next ? '<span class="a-pulse"></span>' : '') +
         `<svg class="a-ring" viewBox="0 0 40 40" aria-hidden="true"><circle class="a-ring-bg" cx="20" cy="20" r="18"/>` +
         `<circle class="a-ring-fg" cx="20" cy="20" r="18" pathLength="100" data-ring="${esc(id)}" data-to="${f}" data-from="${from}" ` +
         `style="stroke-dasharray:${(from * 100).toFixed(1)} 100"/></svg>` +
         `<span class="a-face">${face}</span>` +
         (mastered ? '<span class="a-crown" aria-hidden="true"></span><span class="a-glint" aria-hidden="true">✦</span>' : '') +
         `</span>`;
}

// After a view is drawn: sweep the rings that grew, burst the ones that just filled, remember all.
function ringsSweep(root) {
  const map = seenMap();
  const grew = [];
  root.querySelectorAll('.a-ring-fg[data-ring]').forEach(c => {
    const to = +c.dataset.to, from = +c.dataset.from;
    map[c.dataset.ring] = to;
    if (to > from) grew.push([c, from, to]);
  });
  seenSave();
  if (!grew.length) return;
  setTimeout(() => grew.forEach(([c, from, to], i) => {
    c.style.transitionDelay = `${Math.min(i, 12) * 90}ms`;
    c.style.strokeDasharray = `${(to * 100).toFixed(1)} 100`;
    if (to >= 1 && from < 1) setTimeout(() => c.closest('.a-ico')?.classList.add('a-burst'), 1100 + Math.min(i, 12) * 90);
  }), 350);
}

// -- state of the map ------------------------------------------------------------------

const TIER_SHORT = t => { const m = /(\d+)/.exec(t.title); return m ? m[1] : t.title.split(/\s+/).filter(w => w.length > 2).map(w => w[0].toUpperCase()).join('').slice(0, 2); };
const tiersSorted = () => [...atlas.data.tiers].sort((a, b) => a.order - b.order);

function familyOf(n) {
  while (n && n.level !== 'family' && n.parent) n = atlas.byId.get(n.parent);
  return n && n.level === 'family' ? n : null;
}

// The route's stops in order (one per lesson), and the next one.
function routeStops() {
  const out = [];
  for (const f of routeShown()) for (const r of f.requirements) out.push({...r, family: f.family, famTitle: f.title});
  return out;
}
const nextStopId = () => (routeStops()[0] || {}).id || null;

// Where the map is: atlas.mode 'route' | 'course' | 'grade', atlas.tier, atlas.family (drawer).
function atlasGo(mode, tier = null, family = null) {
  atlas.mode = mode;
  if (mode === 'grade') atlas.tier = tier;
  atlas.family = mode === 'grade' ? family : null;
  atlasDraw();
}

function atlasHome() { atlas.origin = null; atlasGo('course'); }

// Clicking a node shows it: on the route when it's there and the route is showing, else on
// its grade's board, its family's drawer open; and it's selected for the side panel.
function atlasActivate(id, from = null) {
  const n = atlas.byId.get(id);
  if (!n) return;
  atlas.origin = from ? originOf(from) : null;
  if (!(atlas.mode === 'route' && route.ids.has(id))) {
    const fam = n.level === 'tier' || n.level === 'strand' || n.level === 'review' || n.level === 'exam' ? null : familyOf(n);
    atlasGo('grade', n.tier || n.id.split('.')[0], fam && fam.id);
  }
  atlas.reveal = true;
  return atlasSelect(id);
}

// The point (in the map's own pixels) a transition grows from.
function originOf(el) {
  const m = $('atlas-map').getBoundingClientRect(), r = el.getBoundingClientRect();
  return [r.left + r.width / 2 - m.left, r.top + r.height / 2 - m.top];
}

function atlasSize() { const r = $('atlas-map').getBoundingClientRect(); return {w: r.width || 800, h: r.height || 600}; }

function atlasDraw() {
  if (atlas.raf) return;
  atlas.raf = requestAnimationFrame(() => { atlas.raf = 0; atlasRender(); });
}

function isWeakest(n) {
  const p = n.parent && atlas.states[n.parent];
  return p && p.weakest === n.id && (p.ring || 0) > 0 && p.ring < 1;  // only once something there has started
}

// -- drawing ---------------------------------------------------------------------------

const DEPTH = {route: 0, course: 0, grade: 1};

function atlasRender() {
  if (!atlas.data) return;
  if (!atlas.mode) atlas.mode = 'course';
  if (atlas.mode === 'route' && !routeShown().length && !(path.state && path.state.goal)) atlas.mode = 'course';
  if (atlas.mode === 'grade' && !atlas.byId.has(atlas.tier)) atlas.mode = 'course';
  crumbsRender();
  const name = atlas.mode + (atlas.mode === 'grade' ? ':' + atlas.tier : '');
  const {w} = atlasSize();
  const key = `${name}|${atlas.stamp}|${[...route.ids].join(',')}|${atlas.mode === 'grade' ? '' : Math.round(w / 40)}`;
  const stage = $('atlas-stage');
  let el = atlas.viewEl && atlas.viewEl.isConnected ? atlas.viewEl : null;
  if (!el || atlas.viewKey !== key) {
    const same = el && el.dataset.view === name;
    const fresh = same ? el : document.createElement('div');
    const top = same ? el.scrollTop : 0;
    fresh.className = `av av-${atlas.mode}`;
    fresh.dataset.view = name;
    fresh.dataset.hov = '';
    fresh.innerHTML = atlas.mode === 'route' ? routeHtml(w) : atlas.mode === 'course' ? courseHtml(w) : boardHtml(atlas.tier);
    if (!same) {
      const deeper = el ? DEPTH[atlas.mode] - DEPTH[(el.dataset.view || '').split(':')[0]] : 0;
      viewSwap(stage, el, fresh, deeper);
    } else fresh.scrollTop = top;
    wireView(fresh);
    ringsSweep(fresh);
    atlas.viewEl = fresh;
    atlas.viewKey = key;
  }
  drawerRender();
  markSelection();
}

// The old view grows past you (going in) or shrinks away (going out) while the new one comes
// from the clicked point; sideways (route <-> course) it slides.
function viewSwap(stage, old, fresh, deeper) {
  stage.append(fresh);
  if (!old) return;
  if (reduceMotion()) { old.remove(); return; }
  const {w, h} = atlasSize(), [ox, oy] = atlas.origin || [w / 2, h / 3];
  const how = deeper > 0 ? 'in' : deeper < 0 ? 'out' : 'side';
  old.style.transformOrigin = `${ox}px ${oy + old.scrollTop}px`;
  fresh.style.transformOrigin = `${ox}px ${oy}px`;
  fresh.classList.add(`av-enter-${how}`);
  old.classList.add(`av-leave-${how}`);
  old.style.pointerEvents = 'none';
  requestAnimationFrame(() => requestAnimationFrame(() => fresh.classList.remove(`av-enter-${how}`)));
  setTimeout(() => old.remove(), 520);
  atlas.origin = null;
}

// Clicks inside a view: a node (data-go) is shown or opened, an action (data-act) done.
function wireView(el) {
  el.onclick = e => {
    const t = e.target.closest('[data-go],[data-act]');
    if (!t || !el.contains(t)) return;
    e.preventDefault();
    if (t.dataset.act) return viewAction(t.dataset.act, t);
    const n = atlas.byId.get(t.dataset.go);
    if (!n) return;
    if (n.level === 'tier') { atlas.origin = originOf(t); atlasGo('grade', n.id); return atlasSelect(n.id); }
    if (n.level === 'family' && atlas.mode === 'grade') { atlasGo('grade', atlas.tier, n.id); return atlasSelect(n.id); }
    atlasActivate(n.id, t);
  };
  // Links follow the pointer (or focus) over the view as a whole, so a rebuild under a still
  // pointer, or leaving into the drawer, never leaves the board dimmed.
  const hover = id => { if ((id || '') !== el.dataset.hov) { el.dataset.hov = id || ''; linksShow(el, id); } };
  el.onpointerover = e => { const t = e.target.closest('[data-links]'); hover(t && el.contains(t) ? t.dataset.go : null); };
  el.onpointerleave = () => hover(null);
  el.onfocusin = e => { const t = e.target.closest('[data-links]'); hover(t ? t.dataset.go : null); };
  el.onfocusout = () => hover(null);
}

function viewAction(act, t) {
  if (act === 'route') { atlas.origin = null; atlasGo('route'); }
  else if (act === 'course') atlasHome();
  else if (act === 'next') pathNext();
  else if (act === 'planner') pathShow();
  else if (act === 'place') atlasPlaceForm();
  else if (act === 'start') stepOpen(t.dataset.stage);
  else if (act === 'tier') { const id = t.dataset.tier; atlasGo('grade', id); atlasSelect(id); }
}

// Breadcrumbs in the top bar: Your route | Whole course › Grade 2 › Scales, hands together.
function crumbsRender() {
  const box = $('atlas-level');
  const hasRoute = routeShown().length || (path.state && path.state.goal);
  const tier = atlas.mode === 'grade' && atlas.byId.get(atlas.tier), fam = atlas.family && atlas.byId.get(atlas.family);
  let html = `<span class="a-switch"><button data-crumb="route"${atlas.mode === 'route' ? ' class="on"' : ''}${hasRoute ? '' : ' disabled title="Set a goal in the Planner to get a route"'}>Your route</button>` +
             `<button data-crumb="course"${atlas.mode !== 'route' ? ' class="on"' : ''} title="Every grade (Home)">Whole course</button></span>`;
  if (tier) html += `<span class="a-sep">›</span><button data-crumb="tier"${fam ? '' : ' class="here"'}>${esc(tier.title)}</button>`;
  if (fam) html += `<span class="a-sep">›</span><button class="here" data-crumb="fam">${esc(fam.title)}</button>`;
  box.innerHTML = html;
  box.querySelectorAll('[data-crumb]').forEach(b => b.onclick = () => {
    const c = b.dataset.crumb;
    if (c === 'route') atlasGo('route');
    else if (c === 'course') atlasHome();
    else if (c === 'tier') { atlasGo('grade', atlas.tier); atlasSelect(atlas.tier); }
  });
}

// Esc: close the drawer, then out to the whole course, then Home.
function atlasBack() {
  if (atlas.family) { atlasGo('grade', atlas.tier); return true; }
  if (atlas.mode === 'grade') { atlasHome(); return true; }
  return false;
}

// Selected things get a ring; on a new selection it's scrolled into view.
function markSelection() {
  const sel = atlas.selected, n = sel && atlas.byId.get(sel);
  const ids = new Set(sel ? [sel] : []);
  if (n && n.level === 'stage') ids.add(n.parent);
  let first = null;
  document.querySelectorAll('#atlas-map [data-go]').forEach(el => {
    const on = ids.has(el.dataset.go) || (atlas.mode === 'route' && n && n.level === 'family' && el.dataset.family === sel);
    el.classList.toggle('a-sel', on);
    if (on && !first && !el.closest('.av-leave-in,.av-leave-out,.av-leave-side')) first = el;
  });
  if (atlas.reveal && first) first.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: reduceMotion() ? 'auto' : 'smooth'});
  atlas.reveal = false;
}

// A road through points, row by row, turning round at the ends (a serpentine).
function roadPath(pts, w, turn = 60) {
  let d = `M${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
    if (Math.abs(y0 - y1) < 1) d += ` L${x1} ${y1}`;
    else { const side = x0 > w / 2 ? 1 : -1, bx = x0 + side * turn; d += ` C${bx} ${y0} ${bx} ${y1} ${x1} ${y1}`; }
  }
  return d;
}

// Points for n items in rows that snake left-right-left, across width w.
function snake(n, w, {pad = 90, gap = 170, rowH = 170, top = 120} = {}) {
  const per = Math.max(2, Math.min(7, Math.floor((w - 2 * pad) / gap) + 1));
  const dx = per > 1 ? (w - 2 * pad) / (per - 1) : 0;
  const pts = [];
  for (let i = 0; i < n; i++) {
    const r = Math.floor(i / per), c = i % per;
    pts.push([pad + (r % 2 ? per - 1 - c : c) * dx, top + r * rowH]);
  }
  return {pts, height: top + Math.ceil(n / per) * rowH};
}

// A floating "you are here" pin over a point.
const pinHtml = (x, y) => `<span class="a-pin" style="left:${x}px;top:${y}px" aria-hidden="true"></span>`;

// Your route: the stops still to do, the goal at the end of the road.
function routeHtml(w) {
  const st = path.state || {}, stops = routeStops();
  const preview = route.preview;
  const title = preview ? preview.title : st.goal ? st.goal.title : '';
  if (!stops.length && !title) {
    return `<div class="ar-empty"><span class="a-big-glyph">${glyph('goal', 48, 'var(--accent)')}</span><h2>No route yet</h2>` +
           `<p>Set a goal in the Planner and its lessons line up here as a road, the next one first.</p>` +
           `<p><button data-act="planner">Set a goal</button> <button data-act="place">Find where I start</button> <button data-act="course">See the whole course</button></p></div>`;
  }
  const next = stops[0];
  const firstLesson = next && (next.stages || []).find(sg => sg.lesson);
  const play = !preview && st.goal ? '<button class="a-play" data-act="next">▶ Play the next stop</button>'
    : firstLesson ? `<button class="a-play" data-act="start" data-stage="${esc(firstLesson.id)}">▶ Start the first stop</button>` : '';
  let html = `<div class="av-head"><div><div class="av-eyebrow">${preview ? 'Route to a lesson · not saved' : 'Your route'}</div><h2>${esc(title)}</h2>` +
             `<p class="a-muted">${stops.length ? `${stops.length} lesson${stops.length === 1 ? '' : 's'} to go` : 'Everything on this route is done.'}</p></div>` +
             `<div class="av-actions">${play}</div></div>`;
  const all = stops.concat([{id: '__goal', title, goal: true}]);
  const {pts, height} = snake(all.length, w, {top: 150});
  html += `<div class="ar-road" style="height:${height}px">`;
  html += `<svg class="ar-svg" width="${w}" height="${height}" aria-hidden="true"><path class="ar-bed" d="${roadPath(pts, w)}"/>` +
          `<path class="ar-lane" d="${roadPath(pts, w)}"/></svg>`;
  all.forEach((s, i) => {
    const [x, y] = pts[i];
    if (s.goal) {
      html += `<div class="ar-stop ar-goal" style="left:${x - 75}px;top:${y - 34}px">` +
              iconHtml('goal:' + title, 0, GOLD, 72, {kind: 'medal', glyphKey: 'goal'}) +
              `<span class="ar-title">${esc(title)}</span><span class="ar-cap">Goal</span></div>`;
      return;
    }
    const n = atlas.byId.get(s.id) || {id: s.id, level: 'requirement'};
    const tint = s.temporary ? GOLD : tintOf(atlas.byId.get(s.family) || n);
    const strand = (atlas.byId.get(s.family) || n).strand || 'goal';
    const f = (s.stages || []).length ? (s.stages.filter(sg => RANKS[sg.level] >= 2).length / s.stages.length) : fracOf(n);
    const isNext = i === 0;
    const cap = s.temporary ? (s.kind === 'drill' || s.kind === 'song' ? s.kind : 'bridge') : s.famTitle;
    html += `<button class="ar-stop${isNext ? ' ar-next' : ''}" data-go="${esc(s.id)}" data-family="${esc(s.family)}" style="left:${x - 75}px;top:${y - 30}px;--bob:${-(hashOf(s.id) % 4000)}ms" title="${esc(s.title)}">` +
            (isNext ? '<span class="ar-tag">Next stop</span>' : '') +
            iconHtml(s.id, f, tint, isNext ? 64 : 54, {kind: 'stop', glyphKey: s.temporary ? 'bridge' : strand, next: isNext, dashed: s.temporary, mastered: levelOf(s.id) === 'mastered'}) +
            `<span class="ar-title">${esc(s.title)}${s.recheck ? ' <span class="a-muted">(recheck)</span>' : ''}</span>` +
            `<span class="ar-cap" style="color:${tint}">${esc(cap || '')}</span></button>`;
  });
  return html + pinHtml(pts[0][0], pts[0][1] - (stops.length ? 78 : 60)) + '</div>';
}

// The whole course: a road of grade medals, the one you're in marked.
function courseHtml(w) {
  const tiers = tiersSorted();
  const next = nextStopId(), nextNode = next && atlas.byId.get(next);
  const here = (nextNode && nextNode.tier) || (tiers.find(t => (stateOf(t.id).ring || 0) < 1) || tiers[tiers.length - 1]).id;
  const total = tiers.reduce((a, t) => a + (stateOf(t.id).total || 0), 0), done = tiers.reduce((a, t) => a + (stateOf(t.id).done || 0), 0);
  let html = `<div class="av-head"><div><div class="av-eyebrow">${esc(atlas.data.name || 'Roadmap')}</div><h2>Whole course</h2>` +
             `<p class="a-muted">${done} of ${total} lessons proficient · choose a grade to open it</p></div></div>`;
  const {pts, height} = snake(tiers.length, w, {gap: 150, rowH: 180, top: 150});
  html += `<div class="ar-road" style="height:${height}px"><svg class="ar-svg" width="${w}" height="${height}" aria-hidden="true">` +
          `<path class="ar-bed" d="${roadPath(pts, w)}"/><path class="ar-lane" d="${roadPath(pts, w)}"/></svg>`;
  let pin = null;
  tiers.forEach((t, i) => {
    const [x, y] = pts[i], st = stateOf(t.id), f = st.ring || 0, isHere = t.id === here;
    if (isHere) pin = [x, y - 82];
    html += `<button class="ar-stop ar-tier${isHere ? ' ar-next' : ''}" data-go="${esc(t.id)}" style="left:${x - 75}px;top:${y - 40}px;--bob:${-(hashOf(t.id) % 4000)}ms">` +
            iconHtml(t.id, f, isHere ? 'var(--accent)' : NEUTRAL, isHere ? 84 : 76, {kind: 'medal', label: TIER_SHORT(t), mastered: f >= 1, next: isHere}) +
            `<span class="ar-title">${esc(t.title)}</span><span class="ar-cap">${st.total ? (f >= 1 ? 'Done' : `${st.done}/${st.total}`) : ''}</span></button>`;
  });
  return html + (pin ? pinHtml(pin[0], pin[1]) : '') + '</div>';
}

// One grade: a lane per strand (and one for a goal's bridges), family badges down each lane in
// the order the layout gives them; Review and the mock exam at the end.
function boardHtml(tierId) {
  const tier = atlas.byId.get(tierId), st = stateOf(tierId);
  const tiers = tiersSorted(), k = tiers.findIndex(t => t.id === tierId);
  const order = Object.fromEntries((atlas.data.strands || []).map((s, i) => [s.id, i]));
  const kids = atlas.kids.get(tierId) || [];
  const lanes = kids.filter(c => c.level === 'strand').sort((a, b) => (order[a.strand] ?? 9) - (order[b.strand] ?? 9));
  const goals = kids.find(c => c.level === 'family' && c.temporary);
  const nextFam = (familyOf(atlas.byId.get(nextStopId())) || {}).id;
  const byY = (a, b) => ((a.box || [0, 0])[1] - (b.box || [0, 0])[1]) || ((a.box || [0])[0] - (b.box || [0])[0]);
  const badge = n => {
    const s = stateOf(n.id), f = fracOf(n), tint = tintOf(n);
    const count = s.total ? `${s.done}/${s.total}` : 'none yet';
    return `<button class="ab-badge${route.ids.has(n.id) ? ' a-onroute' : ''}" data-go="${esc(n.id)}" data-links style="--bob:${-(hashOf(n.id) % 4000)}ms" title="${esc(n.title)}">` +
           iconHtml(n.id, f, tint, 62, {kind: 'badge', glyphKey: n.temporary ? 'bridge' : n.strand, mastered: masteredOf(n), next: n.id === nextFam}) +
           `<span class="ab-name">${isWeakest(n) ? '<span class="a-star" title="Weakest here">★</span> ' : ''}${esc(n.title)}</span>` +
           `<span class="ab-count">${count}</span></button>`;
  };
  const prev = tiers[k - 1], next = tiers[k + 1];
  let html = `<div class="av-head ab-head">` +
             `<span class="ab-medal">${iconHtml(tierId, st.ring || 0, 'var(--accent)', 58, {kind: 'medal', label: TIER_SHORT(tier), mastered: (st.ring || 0) >= 1})}</span>` +
             `<div><div class="av-eyebrow">${esc(atlas.data.name || 'Roadmap')}</div><h2>${esc(tier.title)}</h2>` +
             `<p class="a-muted">${st.total ? `${st.done} of ${st.total} lessons proficient` : ''}</p></div>` +
             `<div class="av-actions">${prev ? `<button data-act="tier" data-tier="${esc(prev.id)}" title="${esc(prev.title)}">‹ ${esc(prev.title)}</button>` : ''}` +
             `${next ? `<button data-act="tier" data-tier="${esc(next.id)}" title="${esc(next.title)}">${esc(next.title)} ›</button>` : ''}</div></div>`;
  html += `<div class="ab-wrap"><svg class="ab-links" aria-hidden="true"></svg><div class="ab-lanes" style="--lanes:${lanes.length + (goals ? 1 : 0)}">`;
  for (const lane of lanes) {
    const fams = (atlas.kids.get(lane.id) || []).filter(c => c.level === 'family').sort(byY);
    const ls = stateOf(lane.id), tint = tintOf(lane);
    html += `<section class="ab-lane" style="--tint:${tint}"><button class="ab-lane-head" data-go="${esc(lane.id)}" title="${esc(lane.title)}">` +
            `${glyph(lane.strand, 18, tint)}<span>${esc(lane.title.split(' · ').pop())}</span>` +
            `<span class="ab-count">${ls.total ? `${ls.done}/${ls.total}` : ''}</span></button>${fams.map(badge).join('')}</section>`;
  }
  if (goals) html += `<section class="ab-lane ab-goals" style="--tint:${GOLD}"><div class="ab-lane-head">${glyph('bridge', 18, GOLD)}<span>${esc(goals.title)}</span></div>${badge(goals)}</section>`;
  html += '</div></div>';
  const gates = ['review', 'exam'].map(g => atlas.byId.get(`${tierId}.${g}`)).filter(Boolean);
  if (gates.length) {
    html += '<div class="ab-gates">' + gates.map(g => {
      const best = stateOf(g.id).best;
      return `<button class="ab-gate" data-go="${esc(g.id)}" style="--bob:${-(hashOf(g.id) % 4000)}ms">` +
             iconHtml(g.id, fracOf(g), GOLD, 58, {kind: 'gate', glyphKey: g.level, mastered: levelOf(g.id) === 'mastered'}) +
             `<span class="ab-name">${esc(g.title)}</span><span class="ab-count">${best ? `best ${best}/150` : g.level === 'review' ? 'Weakest lessons first' : 'Marked out of 150'}</span></button>`;
    }).join('<span class="ab-gate-arrow" aria-hidden="true">→</span>') + '</div>';
  }
  return html;
}

// Pointing at a family draws what it builds on (in) and what builds on it (out), within the grade.
function linksShow(view, id) {
  const svg = view.querySelector('.ab-links'), wrap = view.querySelector('.ab-wrap');
  if (!svg || !wrap) return;
  view.querySelectorAll('.a-pre,.a-post').forEach(e => e.classList.remove('a-pre', 'a-post'));
  const pairs = id ? (atlas.data.bundles.family || []).filter(([a, b]) => a === id || b === id) : [];
  wrap.classList.toggle('a-dim', pairs.length > 0);
  if (!pairs.length) { svg.innerHTML = ''; return; }
  const box = wrap.getBoundingClientRect();
  svg.setAttribute('width', wrap.scrollWidth); svg.setAttribute('height', wrap.scrollHeight);
  const at = gid => {
    const el = view.querySelector(`.ab-badge[data-go="${CSS.escape(gid)}"] .a-ico`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {el: el.closest('.ab-badge'), x: r.left + r.width / 2 - box.left, y: r.top + r.height / 2 - box.top, r: r.width / 2};
  };
  const me = at(id);
  if (!me) return;
  me.el.classList.add('a-pre');
  let out = '';
  for (const [a, b] of pairs) {
    const A = at(a), B = at(b);
    if (!A || !B) continue;
    (a === id ? B : A).el.classList.add(a === id ? 'a-post' : 'a-pre');
    const dx = B.x - A.x, dy = B.y - A.y, len = Math.hypot(dx, dy) || 1;
    const x1 = A.x + dx / len * (A.r + 4), y1 = A.y + dy / len * (A.r + 4), x2 = B.x - dx / len * (B.r + 8), y2 = B.y - dy / len * (B.r + 8);
    const bend = Math.abs(dx) < 10 ? 50 : 0;
    out += `<path class="ab-link" d="M${x1} ${y1} C${x1 + bend} ${y1 + dy / 3} ${x2 + bend} ${y2 - dy / 3} ${x2} ${y2}" marker-end="url(#ab-arrow)"/>`;
  }
  svg.innerHTML = `<defs><marker id="ab-arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">` +
                  `<path d="M0 0L10 5L0 10z" fill="var(--text)"/></marker></defs>${out}`;
}

// The drawer: a family's lessons, each a card with a bar of its exercises.
function drawerRender() {
  const dr = $('atlas-drawer');
  const fam = atlas.mode === 'grade' && atlas.family && atlas.byId.get(atlas.family);
  if (!fam) { dr.classList.remove('open'); dr.dataset.fam = ''; return; }
  const key = `${fam.id}|${atlas.stamp}|${[...route.ids].length}`;
  if (dr.dataset.key !== key) {
    const tint = tintOf(fam), next = nextStopId();
    const reqs = reqsOf(fam.id);
    dr.innerHTML = `<div class="ad-head">${iconHtml('d:' + fam.id, fracOf(fam), tint, 44, {kind: 'badge', glyphKey: fam.temporary ? 'bridge' : fam.strand, mastered: masteredOf(fam)})}` +
      `<div><h3>${esc(fam.title)}</h3><p class="a-muted">${reqs.length} lesson${reqs.length === 1 ? '' : 's'}</p></div>` +
      `<button class="ad-close" title="Close (Esc)" aria-label="Close">✕</button></div>` +
      (reqs.length ? '' : '<p class="a-muted">No lessons here yet.</p>') +
      reqs.map(r => {
        const stages = stagesOf(r.id), lv = levelOf(r.id);
        const pips = stages.map(sg => `<button class="ad-pip ad-${levelOf(sg.id)}${sg.final ? ' ad-final' : ''}" data-go="${esc(sg.id)}" ` +
          `title="${esc(sg.title)} · ${levelOf(sg.id).replace('_', ' ').replace('practised', 'practiced')}${sg.writing ? ' · writing…' : ''}"></button>`).join('');
        return `<div class="ad-card${r.id === next ? ' ad-next' : ''}${lv === 'mastered' ? ' ad-gold' : ''}${route.ids.has(r.id) ? ' a-onroute' : ''}" data-go="${esc(r.id)}" style="--tint:${r.temporary ? GOLD : tint}">` +
          (r.id === next ? '<span class="ad-tag">Next stop</span>' : '') +
          `<span class="ad-title">${isWeakest(r) ? '<span class="a-star">★</span> ' : ''}${esc(r.title)}</span>` +
          `<span class="ad-pips">${pips}</span>` +
          `<span class="a-muted ad-count">${stages.filter(sg => rankOf(sg.id) >= 2).length}/${stages.length} exercises · ${lv.replace('_', ' ').replace('practised', 'practiced')}</span></div>`;
      }).join('');
    dr.dataset.key = key;
    dr.querySelector('.ad-close').onclick = () => atlasGo('grade', atlas.tier);
    dr.onclick = e => {
      const t = e.target.closest('[data-go]');
      if (t && dr.contains(t)) { e.stopPropagation(); atlas.reveal = false; atlasSelect(t.dataset.go); }
    };
    ringsSweep(dr);
  }
  if (!dr.classList.contains('open')) requestAnimationFrame(() => dr.classList.add('open'));
}

// Notes drifting up behind the map, slowly: the map is never quite still.
function ambientInit() {
  const box = $('atlas-ambient');
  if (!box || box.childElementCount) return;
  const marks = ['♪', '♫', '♩', '♬', '𝄞'];
  box.innerHTML = Array.from({length: 16}, (_, i) => {
    const h = hashOf('amb' + i);
    return `<span style="left:${h % 97}%;font-size:${14 + h % 22}px;animation-duration:${22 + h % 20}s;animation-delay:-${h % 30}s;` +
           `--drift:${(h % 60) - 30}px">${marks[h % marks.length]}</span>`;
  }).join('');
}

function hashOf(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
  return Math.abs(h);
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
  songMode(false);
  try {
    const out = await cmd('stage_open', {node: nodeId});  // its music on the sheet
    $('lesson-song').hidden = !out.song;
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

// Fingering charts (docs/fingering.js): a woodwind's new notes on a lesson's read step, and the
// diagram a 'Which note is this?' quiz asks about (its title left off, so it doesn't give the answer away).
function fingeringSvg(instrument, note, height, title) {
  if (typeof Fingering === 'undefined' || !Fingering.has(instrument)) return '';
  return Fingering.svg(instrument, note, {height, ...(title === undefined ? {} : {title})});
}
function fingeringCharts(f) {
  if (!f || !Array.isArray(f.notes)) return '';
  const cells = f.notes.map(n => {
    const svg = fingeringSvg(f.instrument, n, 110);
    return svg ? `<figure>${svg}<figcaption>${esc(Fingering.name(n).replace(/\d+$/, ''))}</figcaption></figure>` : '';
  }).join('');
  return cells ? `<div class="fing-charts" title="Blue: left hand. Red: right hand. Filled: press the key.">${cells}</div>` : '';
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
    body = `<p class="sp-text">${esc(cur.text || '')}${sayBtn}</p>${fingeringCharts(cur.fingerings)}<button class="sp-act" data-act="done">Got it</button>`;
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
           (cur.fingering ? `<div class="fing-quiz">${fingeringSvg(cur.fingering.instrument, cur.fingering.note, 120, '')}</div>` : '') +
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
  if (lessonViewWas === 'lesson' && now !== 'lesson') { cmd('stage_close').catch(() => {}); songMode(false); }
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

// See in the song: the goal's song on the sheet in the lesson view, the lesson's bars marked
// with the Bars range (a section's own bars, a bridge's from the planner, else the start).
// Runs there aren't graded against the lesson. Back to exercise puts the lesson's music back.
function songMode(on) {
  document.body.classList.toggle('in-song', on);
}

async function sheetLoaded(version) {  // the score that replaced `version` is drawn
  for (let i = 0; i < 80 && !(scoreVersion !== version && scoreReady); i++) await new Promise(r => setTimeout(r, 100));
}

async function songOpen() {
  const was = scoreVersion;
  let out;
  try { out = await cmd('stage_song', {node: step.node}); } catch (err) { statusEl.textContent = err.message; return; }
  songMode(true);
  $('lesson-song-note').textContent = `“${out.title}”: ${out.why}.`;
  await sheetLoaded(was);
  const [first, last] = (out.bars.split(',')[0] || '').split('-').map(n => n.trim());
  $('from').value = first || '';
  $('to').value = first ? last || first : '';
  $('to').dispatchEvent(new Event('change'));
  if (first) jumpToBar(Number(first));
}

async function songBack() {
  if (running) { try { await cmd('stop'); } catch (err) {} }
  $('from').value = $('to').value = '';
  $('to').dispatchEvent(new Event('change'));
  songMode(false);
  try { await cmd('stage_open', {node: step.node}); } catch (err) { statusEl.textContent = err.message; }
}

// To the Session with the song: the server keeps it as the Session's sheet (stage_close puts it
// up as the lesson view closes), the marked bars stay chosen, and the map keeps this lesson.
async function songToSession() {
  if (running && !(await askSwitch('practice'))) return;
  try { await cmd('stage_song', {node: step.node, keep: true}); } catch (err) { statusEl.textContent = err.message; return; }
  store.set('atlasLastLesson', step.node);
  window.coachGo('practice', {unguarded: true});
}

$('lesson-song-btn').addEventListener('click', songOpen);
$('lesson-song-back').addEventListener('click', songBack);
$('lesson-song-session').addEventListener('click', songToSession);

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
// your path starts. No marks: a check you miss just shows the answer and moves on. A profile on
// the microphone (flute, sax, voice, fiddle, guitar, bass) then checks the microphone hears it,
// and the last screen starts Today.
const wl = {qs: null, i: 0, answers: {}, picked: [], audio: null, micChecked: false};
const isMic = () => ['flute', 'sax', 'voice', 'fiddle', 'guitar', 'bass'].includes(document.body.dataset.instrument);
const isVoice = () => document.body.dataset.instrument === 'voice';
const instWord = () => ({flute: 'flute', sax: 'saxophone', fiddle: 'fiddle', guitar: 'guitar', bass: 'bass'})[document.body.dataset.instrument]
  || 'instrument';

async function atlasPlaceForm() {
  path.shown = false;  // a goals update mustn't redraw the Path over this
  atlasTab('place');
  const side = $('atlas-detail');
  let last = null;
  try { const out = await cmd('welcome'); wl.qs = out.questions; last = out.last; } catch (err) { side.textContent = err.message; return; }
  side.innerHTML = `<h3>Getting to know you</h3>` +
    `<p>Hi! A few quick questions so your path starts in the right place: first about you, then a little music. ` +
    `No marks and no pressure; it takes about two minutes.</p>` +
    (isVoice() ? `<p>At the end, the coach checks that it can hear you sing through the microphone.</p>`
      : isMic() ? `<p>Have your ${instWord()} nearby: at the end, the coach checks that it can hear it through the microphone.</p>` : '') +
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
  if (!q) { if (isMic() && !wl.micChecked) welcomeMic(); else welcomeFinish(); return; }
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

// The flute, sax and voice are heard through the microphone, so before finishing: play (or
// sing) a long note and see the coach hear it. Anyone who can't make a sound yet carries on
// (the first lesson shows how). A sax's note is named in written pitch, as flute.js hears it.
function welcomeMic() {
  const side = $('atlas-detail');
  const voice = isVoice(), yours = voice ? 'you' : `your ${instWord()}`;
  side.innerHTML = `<h3>Can the coach hear ${voice ? 'you sing' : yours}?</h3>` +
    (voice ? `<p>The coach listens through the microphone. Sing a long, steady note on "ah": any comfortable note.</p>`
      : `<p>The coach listens through the microphone. Pick up your ${instWord()} and play a long, steady note: any note.</p>`) +
    `<div class="wl-bar" title="How loud the microphone hears it"><i id="wl-level" style="width:0%"></i></div>` +
    `<p class="wl-q" id="wl-heard" aria-live="polite">Listening…</p>` +
    `<p><button class="wl-go" id="wl-mic-next">Skip for now</button></p>` +
    `<p class="a-muted">Bar not moving? Pick your microphone under Preferences → Microphone &amp; speakers. A headset ` +
    `or USB mic works; the keyboard's audio input doesn't.</p>` +
    (voice ? `<p class="a-muted">Not sure what to sing? Hum a note you'd use to say "mmm, yes". Your first lesson, Finding your voice, starts there.</p>`
      : `<p class="a-muted">Can't get a note out yet? That's fine: your first lesson, Making a sound, shows you how.</p>`);
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
      $('wl-heard').textContent = rms > 0.03 ? `I hear something, but no clear note yet. ${voice ? 'Hold one steady "ah".' : 'Keep the air steady.'}` : 'Listening…';
      return;
    }
    if (Math.round(m) !== pitch) { pitch = Math.round(m); since = now; }
    $('wl-heard').textContent = `Hearing ${fluteNoteName(pitch)}… hold it`;
    if (now - since > 700) {
      heard = true;
      $('wl-heard').textContent = `✓ That's a ${fluteNoteName(pitch)}. The coach can hear ${yours}!`;
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
    ambientInit();
    if (first) {  // opens on your route when there is one, else on the whole course
      atlas.mode = 'course';
      atlasDraw();
      await pathShow();
      if (path.state && path.state.goal && atlas.mode === 'course' && !atlas.selected) atlasGo('route');
    } else { atlasRefreshStates(); goalsLoad(); }
  } catch (err) {
    const build = {flute: 'The flute Roadmap is built from your local flute syllabus: <code>python -m midi_coach.atlas.pan</code>',
                   sax: 'The saxophone Roadmap is built from your local saxophone syllabus: <code>python -m midi_coach.atlas.sax</code>',
                   voice: 'The vocal Roadmap is built with <code>python -m midi_coach.atlas.voice</code>',
                   fiddle: 'The fiddle Roadmap is built with <code>python -m midi_coach.atlas.fiddle</code>',
                   guitar: 'The guitar Roadmap is built with <code>python -m midi_coach.atlas.guitar</code>',
                   bass: 'The bass Roadmap is built with <code>python -m midi_coach.atlas.bass</code>'};
    $('atlas-detail').innerHTML = `<p>${esc(err.message)}</p><p class="a-muted">` + (build[document.body.dataset.instrument]
      || 'The Roadmap is built from your local syllabus: <code>python -m midi_coach.atlas.build</code>') + `</p>`;
  }
}

(function atlasInput() {
  window.addEventListener('resize', () => { if (!$('atlas-view').hidden) atlasDraw(); });
  document.addEventListener('keydown', e => {
    if ($('atlas-view').hidden || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    if (e.key === 'Escape' && !atlasBack()) window.dispatchEvent(new CustomEvent('coach:navigate', {detail: {view: 'home'}}));
    if (e.key === 'Home' && atlas.data) atlasHome();
  });
  // Out of the Roadmap is back to Home: modes change only there.
  $('atlas-close').addEventListener('click', () => window.dispatchEvent(new CustomEvent('coach:navigate', {detail: {view: 'home'}})));

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
        if (n) atlasActivate(n.id);
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
