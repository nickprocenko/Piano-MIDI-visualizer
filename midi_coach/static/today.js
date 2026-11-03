// Today (atlas/today.py): the Home page's one-button session, and the same list beside a lesson.
// Loaded after atlas.js (stepOpen, atlasEvent) and coach.html's script (cmd, esc, loadPiece).
//
// The plan comes from cmd('today'): a warm-up, a review, the Path's next stop and a piece for
// fun, as many as fit the time you said you have. A part opens its lesson, or for fun its piece
// in a Session. The list is fetched again after each verdict and on the way back to Home, so
// parts tick off as you go; when they're all done, Keep going adds the next stop on the Path.
"use strict";

const today = {state: null, busy: false};

async function todayLoad(fresh = false) {
  try { today.state = await cmd('today', fresh ? {fresh: true} : {}); }
  catch (err) { today.state = {error: err.message, parts: []}; }
  todayRender();
}

const todayMinutes = m => `${Math.round(m)} minute${Math.round(m) === 1 ? '' : 's'}`;

function todayPart(p, k, cur) {
  const mark = p.done ? '✓' : k + 1;
  const where = [p.detail, p.where].filter(Boolean).map(esc).join(' · ');
  return `<li><button class="td-part${p.done ? ' done' : ''}${k === cur ? ' on' : ''}" data-part="${k}">` +
         `<span class="td-mark" aria-hidden="true">${mark}</span>` +
         `<span class="td-text"><span class="td-label">${esc(p.label)}</span> <b>${esc(p.title)}</b>` +
         (where ? `<span class="td-where">${where}</span>` : '') + `</span>` +
         `<span class="td-min">${p.done ? 'done' : '~' + p.minutes + ' min'}</span></button></li>`;
}

function todayRender() {
  todayRenderHome();
  todayRenderLesson();
}

function todayRenderHome() {
  const s = today.state, card = $('today-card');
  if (!s) return;
  const parts = s.parts || [];
  const done = Math.min(1, (s.practiced_min || 0) / (s.minutes || 15));
  $('today-fill').style.width = `${Math.round(done * 100)}%`;
  const go = $('today-go');
  card.classList.toggle('td-all', !!s.all_done);
  if (s.error && !parts.length) {
    $('today-title').textContent = 'Today';
    $('today-sub').textContent = s.error;
    go.textContent = 'Open the Roadmap ▸';
    go.dataset.act = 'atlas';
  } else if (!s.goal) {  // a new profile: a few questions set the goal, then Today has a plan
    const inst = document.body.dataset.instrument;
    const named = {flute: 'the flute', sax: 'the saxophone', voice: 'singing'}[inst];
    $('today-title').textContent = named ? `New to ${named}? Start here` : 'New here? Start here';
    $('today-sub').textContent = 'A few quick questions (about two minutes) find where you start, then Today plans your practice.' +
      (inst === 'voice' ? ' Have your microphone ready.' : named ? ` Have your ${named.slice(4)} and microphone ready.` : '');
    go.textContent = 'Find where I start ▸';
    go.dataset.act = 'place';
  } else if (!parts.length) {
    $('today-title').textContent = 'Today';
    $('today-sub').textContent = `Nothing on your Path has a lesson ready yet. Open the Roadmap to see what's there.`;
    go.textContent = 'Open the Roadmap ▸';
    go.dataset.act = 'atlas';
  } else if (s.all_done) {
    $('today-title').textContent = 'Today\'s practice is done 🎉';
    $('today-sub').textContent = `${todayMinutes(s.practiced_min)} practiced today. Come back tomorrow, or keep going.`;
    go.textContent = 'Keep going ▸';
    go.dataset.act = 'more';
  } else {
    const started = parts.some(p => p.done) || s.practiced_min >= 1;
    $('today-title').textContent = started ? 'Pick up where you left off' : `Today's practice · about ${s.minutes} minutes`;
    $('today-sub').textContent = `${todayMinutes(s.practiced_min)} of ${s.minutes} practiced today` +
      (s.goal ? ` · toward ${s.goal}` : '');
    go.textContent = started ? 'Continue ▸' : 'Start ▸';
    go.dataset.act = 'next';
  }
  $('today-parts').innerHTML = parts.map((p, k) => todayPart(p, k, s.next)).join('');
  $('today-parts').querySelectorAll('[data-part]').forEach(b => b.onclick = () => todayOpen(+b.dataset.part));
}

// Beside a lesson: today's list, the part you're on lit, and what's next once it's done.
function todayRenderLesson() {
  const box = $('lesson-today'), s = today.state;
  const parts = (s && s.parts) || [];
  if (!parts.length) { box.hidden = true; return; }
  box.hidden = false;
  const reqId = step.req ? step.req.id : null;
  const here = parts.findIndex(p => p.stage === step.node || (reqId && p.requirement === reqId));
  let foot = '';
  if (s.all_done) {
    foot = `<p class="td-cheer">All done for today 🎉 ${esc(todayMinutes(s.practiced_min))} practiced.</p>` +
           `<button class="td-next" data-act="more">Keep going ▸</button>`;
  } else if (here >= 0 && parts[here].done && s.next !== null) {
    foot = `<p class="td-cheer">✓ ${esc(parts[here].label)} done!</p>` +
           `<button class="td-next" data-act="next">Next: ${esc(parts[s.next].title)} ▸</button>`;
  }
  box.innerHTML = `<h3>Today <span class="a-muted">${esc(todayMinutes(s.practiced_min))} of ${s.minutes}</span></h3>` +
                  `<ol class="td-parts">${parts.map((p, k) => todayPart(p, k, here)).join('')}</ol>${foot}`;
  box.querySelectorAll('[data-part]').forEach(b => b.onclick = () => todayOpen(+b.dataset.part));
  box.querySelectorAll('[data-act]').forEach(b => b.onclick = () => todayAct(b.dataset.act));
}

async function todayOpen(k) {
  const p = today.state && today.state.parts[k];
  if (!p) return;
  if (typeof running !== 'undefined' && running && !confirm('Stop this step and go to the other part of today?\n\nThis one is not graded unless you play it to the end.')) return;
  try {
    if (typeof running !== 'undefined' && running) await cmd('stop');
    if (p.kind === 'fun') {
      window.dispatchEvent(new CustomEvent('coach:navigate', {detail: {view: 'practice'}}));
      await loadPiece(p.file);
      statusEl.textContent = `For fun: ${p.title}. Pick a mode and play it however you like.`;
    } else {
      await stepOpen(p.stage);
    }
  } catch (err) { statusEl.textContent = err.message; }
}

async function todayAct(act) {
  if (today.busy) return;
  today.busy = true;
  try {
    if (act === 'atlas' || act === 'place') {  // place: the map with Where to start open
      window.dispatchEvent(new CustomEvent('coach:navigate', {detail: {view: act === 'place' ? 'place' : 'progress'}}));
      return;
    }
    if (act === 'replan') { await todayLoad(true); return; }
    if (act === 'more') {
      const before = (today.state.parts || []).length;
      today.state = await cmd('today_more');
      todayRender();
      if (today.state.error) { statusEl.textContent = today.state.error; return; }
      if (today.state.parts.length > before) await todayOpen(before);
      return;
    }
    if (today.state && today.state.next !== null && today.state.next !== undefined) await todayOpen(today.state.next);
  } catch (err) { statusEl.textContent = err.message; }
  finally { today.busy = false; }
}

$('today-go').addEventListener('click', () => todayAct($('today-go').dataset.act || 'next'));
$('today-replan').addEventListener('click', () => todayAct('replan'));
// On Home, Today folds to a strip beside the cards; the strip opens it again. Remembered.
function todayFold(folded) {
  $('home-main').classList.toggle('td-folded', folded);
  const b = $('today-fold');
  b.setAttribute('aria-expanded', String(!folded));
  b.title = folded ? 'Show Today' : 'Hide Today';
  b.firstElementChild.textContent = folded ? '›' : '‹';
  store.set('todayFolded', folded ? '1' : '');
}
$('today-fold').addEventListener('click', e => { e.stopPropagation(); todayFold(!$('home-main').classList.contains('td-folded')); });
$('today-card').addEventListener('click', () => { if ($('home-main').classList.contains('td-folded')) todayFold(false); });
todayFold(store.get('todayFolded', '') === '1');
// Back on Home (a take for fun may have finished there), or another lesson open: fresh ticks.
window.addEventListener('coach:viewchange', () => {
  const v = document.body.dataset.view;
  if (v === 'home') todayLoad();
  else if (v === 'lesson') todayRenderLesson();
});
todayLoad();
