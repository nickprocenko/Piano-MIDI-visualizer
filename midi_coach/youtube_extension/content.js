// Piano Coach for YouTube: runs inside youtube.com, for videos that only play there.
//
// The same as the coach page's video panel (midi_coach/static/video.js), with YouTube's own
// <video> as the clock: every few seconds it reads the song open in the coach and its sync
// (cmd/synced, through background.js); while this tab plays that song's video, the beat under
// it goes to cmd/synced_cursor and the coach's sheet and the visualizer's strip follow. The
// taps and the loop are the coach's, so they're shared with the video panel.
//
// A small box in the top-right corner holds the controls: use this video for the song,
// Tap to sync (T taps; once synced, T on a downbeat fixes drift), and Loop bars. T is taken
// from YouTube (theater mode) only while the box is following a song. Ads pause the sheet.

const PC = {pollMs: 3000, tickMs: 100, driftBeats: 0.08, idleSec: 4, loopLeadSec: 1, seekQuietMs: 600};
const pc = {info: null, state: 'offline', sent: null, tapping: null, idle: 0, seekAt: 0};

function send(cmd, body) {
  return new Promise(resolve => {
    try {
      chrome.runtime.sendMessage({cmd, body}, out => resolve(chrome.runtime.lastError || !out ? {offline: true} : out));
    } catch (e) {  // the extension was reloaded: this copy of the script is cut off until the tab reloads
      resolve({offline: true});
    }
  });
}

// -- YouTube's page --------------------------------------------------------------------------

const videoEl = () => document.querySelector('#movie_player video, video.html5-main-video') || document.querySelector('video');
const adShowing = () => !!document.querySelector('.html5-video-player.ad-showing');

function pageVideoId() {
  const url = new URL(location.href);
  return url.searchParams.get('v') || (url.pathname.match(/^\/(?:shorts|live|embed)\/([\w-]{11})/) || [])[1] || null;
}

const matched = () => !!(pc.info && pc.info.video && pc.info.video.id === pageVideoId());
const playing = v => !!v && !v.paused && !v.ended && v.readyState > 2 && !adShowing();

// -- the map from video time to beat (as in video.js) ------------------------------------------

function beatAt(t) {
  const k = pc.info ? pc.info.knots : [];
  if (!k.length) return [0, 0, -1];
  if (t <= k[0][0]) return [k[0][1], 0, -1];
  const n = k.length - 1;
  if (t >= k[n][0]) return [k[n][1], 0, n];
  let lo = 0, hi = n;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (k[mid][0] <= t) lo = mid; else hi = mid; }
  const slope = (k[hi][1] - k[lo][1]) / (k[hi][0] - k[lo][0]);
  return [k[lo][1] + slope * (t - k[lo][0]), slope, lo];
}

function loopSpan() {
  const info = pc.info, loop = info && info.loop;
  if (!loop || !loop.on || !info.knots.length) return null;
  const i = info.bars.findIndex(b => b.number === loop.from), j = info.bars.findIndex(b => b.number === loop.to);
  return i < 0 || j < 0 ? null : [info.knots[i][0], info.knots[j + 1][0]];
}

function tick(force) {
  const v = videoEl();
  if (!v || !matched()) return;
  if (adShowing()) {  // the <video> is playing the ad, with the ad's own time: park the cursor once
    const s = pc.sent;
    if (s && s.bps) {
      pc.sent = {...s, beat: s.beat + s.bps * (performance.now() - s.at) / 1000, bps: 0, at: performance.now()};
      send('synced_cursor', {beat: pc.sent.beat, bps: 0});
    }
    return;
  }
  const on = playing(v);
  const span = on && !pc.tapping && loopSpan();
  if (span && performance.now() - pc.seekAt > PC.seekQuietMs
      && (v.currentTime >= span[1] || v.currentTime < span[0] - PC.loopLeadSec - 0.5)) {
    pc.seekAt = performance.now();
    v.currentTime = Math.max(0, span[0] - PC.loopLeadSec);
  }
  const [beat, slope, seg] = beatAt(v.currentTime);
  const bps = on ? slope * v.playbackRate : 0;
  const s = pc.sent, now = performance.now();
  if (!force && s && s.seg === seg && Math.abs(s.bps - bps) < 1e-4
      && Math.abs(s.beat + s.bps * (now - s.at) / 1000 - beat) < PC.driftBeats) return;
  pc.sent = {beat, bps, seg, at: now};
  send('synced_cursor', {beat, bps});  // refused while a practice run owns the cursor
}

// -- the box ----------------------------------------------------------------------------------

const host = document.createElement('div');
host.id = 'piano-coach-box';
const root = host.attachShadow({mode: 'open'});
root.innerHTML = `
<style>
  :host { all: initial; }
  .box { position: fixed; top: 72px; right: 16px; z-index: 2147483000; width: 300px; padding: 10px 12px;
         background: #12151e; color: #e6e9f2; border: 1px solid rgba(0,180,180,.5); border-radius: 8px;
         box-shadow: 0 6px 24px rgba(0,0,0,.45); font: 13px/1.45 'Segoe UI', Roboto, Arial, sans-serif; }
  .box.min { width: auto; padding: 6px 10px; }
  .box.min .body { display: none; }
  .head { display: flex; align-items: center; gap: 8px; }
  .head b { color: #00b4b4; font-weight: 600; white-space: nowrap; }
  .song { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #8d93a8; }
  .box.min .song { display: none; }
  .body { margin-top: 8px; display: flex; flex-direction: column; gap: 8px; }
  .row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; color: #8d93a8; }
  .row[hidden], button[hidden] { display: none; }
  label { display: inline-flex; align-items: center; gap: 5px; }
  button { padding: 4px 10px; border: 1px solid rgba(255,255,255,.18); border-radius: 5px; background: transparent;
           color: #e6e9f2; font: inherit; cursor: pointer; }
  button:hover { border-color: #00b4b4; }
  button:disabled { opacity: .4; cursor: default; }
  #min { padding: 0 7px; color: #8d93a8; }
  #use { border-color: #00b4b4; color: #00b4b4; font-weight: 600; }
  #sync.tapping { border-color: #00b4b4; background: rgba(0,180,180,.15); color: #00b4b4; font-weight: 600; }
  #sync.hit { background: rgba(0,180,180,.45); }
  input[type=number] { width: 48px; padding: 3px 5px; background: #0a0c12; color: #e6e9f2;
                       border: 1px solid rgba(255,255,255,.15); border-radius: 4px; font: inherit; }
  #msg b { color: #e6e9f2; font-weight: 600; }
</style>
<div class="box" id="box">
  <div class="head"><b>𝄞 Piano Coach</b><span class="song" id="song"></span><button id="min" title="Shrink / grow">–</button></div>
  <div class="body">
    <div id="msg"></div>
    <button id="use" hidden></button>
    <div class="row" id="sync-row" hidden>
      <button id="sync" title="Line the video up with the sheet: tap on the first beat of each bar">Tap to sync</button>
      <label>from bar <input id="bar" type="number" min="0" value="1"></label>
      <button id="done" hidden>Done</button>
      <button id="clear" title="Forget the taps for this video">Forget taps</button>
    </div>
    <div class="row" id="loop-row" hidden>
      <label title="Repeat these bars (a second before the first bar, for a run-up)"><input type="checkbox" id="loop"> Loop bars</label>
      <input id="from" type="number" min="0" aria-label="Loop from bar"> – <input id="to" type="number" min="0" aria-label="Loop to bar">
    </div>
  </div>
</div>`;
const $ = id => root.getElementById(id);
const esc = t => String(t).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
const typing = () => /^(INPUT|SELECT|TEXTAREA)$/.test((root.activeElement || {}).tagName || '');

function barList(numbers) {
  const out = [];
  for (const n of numbers) {
    const last = out[out.length - 1];
    if (last && n === last[1] + 1) last[1] = n; else out.push([n, n]);
  }
  return out.map(([a, b]) => a === b ? `${a}` : `${a}–${b}`).join(', ');
}

function note(html) { $('msg').innerHTML = html; }

function describe() {
  const info = pc.info;
  if (!info.taps) {
    return note('Not synced yet, so the sheet assumes bar 1 starts when the video does. Press <b>Tap to sync</b>, '
      + 'then tap <b>T</b> on the first beat of each bar for 4 to 8 bars.');
  }
  const bpm = info.bpm ? ` · about <b>${Math.round(info.bpm)} BPM</b>` : '';
  note(`Synced on bar${info.tapped.length > 1 ? 's' : ''} ${barList(info.tapped)}${bpm}. `
    + 'The sheet follows this video. If it drifts, press <b>T</b> on the first beat of any bar.');
}

function render() {
  const info = pc.info, id = pageVideoId(), on = pc.state === 'ok' && matched();
  $('box').style.display = id ? '' : 'none';  // only on a video's page
  $('song').textContent = info ? info.title : '';
  $('sync-row').hidden = $('loop-row').hidden = !on;
  $('use').hidden = !(pc.state === 'ok' && id && !matched());
  if (pc.state === 'offline') return note('The Piano Coach isn’t running. Start it, and this box connects by itself.');
  if (pc.state === 'nosong') return note('Pick a song in the Piano Coach, then come back to its video here.');
  if (!matched()) {
    $('use').textContent = 'Use this video for this song';
    return note(info.video
      ? `<b>${esc(info.title)}</b> is synced to another video. Using this one forgets those taps.`
      : `Play along with <b>${esc(info.title)}</b> here: the sheet will follow this video.`);
  }
  if (pc.tapping) return;  // the tapping line stays
  if (adShowing()) return note('An ad is playing: the sheet waits for the song.');
  describe();
}

function setInfo(out) {
  if (out.offline) { pc.state = 'offline'; pc.info = null; return render(); }
  if (out.error) { pc.state = 'nosong'; pc.info = null; return render(); }
  const changed = !pc.info || pc.info.path !== out.path;
  pc.state = 'ok';
  pc.info = out;
  if (!typing()) {
    const loop = out.loop || {};
    const bars = out.bars.map(b => b.number);
    $('loop').checked = !!loop.on;
    $('from').value = loop.from ?? out.first_bar;
    $('to').value = loop.to ?? (bars.length ? bars[bars.length - 1] : '');
    if (changed && !pc.tapping) $('bar').value = out.first_bar;
  }
  $('clear').disabled = !out.taps;
  render();
}

async function poll() {
  if (pc.tapping) return;  // the taps are saved when tapping ends
  const before = pc.info && JSON.stringify([pc.info.knots, pc.info.loop]);
  setInfo(await send('synced'));
  if (pc.info && JSON.stringify([pc.info.knots, pc.info.loop]) !== before) pc.sent = null;
  tick(true);
}

// -- tapping (as in video.js) -----------------------------------------------------------------

function startTapping() {
  const v = videoEl();
  if (!v || !matched()) return;
  const bar = Number($('bar').value);
  pc.tapping = {bar: Number.isFinite(bar) ? bar : pc.info.first_bar, taps: []};
  $('sync').classList.add('tapping');
  $('sync').textContent = 'Tap (T)';
  $('done').hidden = false;
  if (v.paused) v.play();
  note(`Tap <b>T</b> (or the button) on the first beat of <b>bar ${pc.tapping.bar}</b>, then on the first beat `
    + 'of every bar after it. A few bars is enough; Done saves them.');
}

function tap() {
  const v = videoEl();
  if (!v || !matched()) return;
  if (!pc.tapping) {
    if (pc.info.taps && playing(v)) return nudge(v.currentTime);
    startTapping();
    if (!playing(v)) return;
  }
  if (!playing(v)) return note('Play the video, then tap on the first beat of each bar.');
  const t = pc.tapping;
  t.taps.push(v.currentTime);
  $('sync').classList.add('hit');
  setTimeout(() => $('sync').classList.remove('hit'), 120);
  note(`<b>${t.taps.length}</b> tapped from bar ${t.bar}. Keep going, or press Done.`);
  clearTimeout(pc.idle);
  pc.idle = setTimeout(() => stopTapping(true), PC.idleSec * 1000);
}

async function stopTapping(save) {
  clearTimeout(pc.idle);
  const t = pc.tapping;
  pc.tapping = null;
  $('sync').classList.remove('tapping', 'hit');
  $('sync').textContent = 'Tap to sync';
  $('done').hidden = true;
  if (save && t && t.taps.length) {
    setInfo(await send('synced', {taps: t.taps, bar: t.bar}));
    pc.sent = null;
  }
  render();
}

async function nudge(at) {
  const out = await send('synced', {nudge: at});
  setInfo(out);
  pc.sent = null;
  if (out.nudged !== undefined) note(`Bar <b>${out.nudged}</b> now starts there. ` + $('msg').innerHTML);
}

// -- wiring -----------------------------------------------------------------------------------

$('min').addEventListener('click', () => {
  const min = $('box').classList.toggle('min');
  $('min').textContent = min ? '+' : '–';
});
$('use').addEventListener('click', async () => {
  const title = document.title.replace(/\s*-\s*YouTube( Music)?$/, '').replace(/^\(\d+\)\s*/, '');
  setInfo(await send('synced', {link: pageVideoId(), title}));
  pc.sent = null;
  tick(true);
});
$('sync').addEventListener('click', () => pc.tapping ? tap() : startTapping());
$('done').addEventListener('click', () => stopTapping(true));
$('clear').addEventListener('click', async () => {
  if (!confirm('Forget the taps for this video? You can tap again any time.')) return;
  setInfo(await send('synced', {clear: true}));
  pc.sent = null;
});
['loop', 'from', 'to'].forEach(id => $(id).addEventListener('change', async () => {
  const num = box => $(box).value === '' ? null : Number($(box).value);
  setInfo(await send('synced', {loop: {from: num('from'), to: num('to'), on: $('loop').checked}}));
  pc.sent = null;
}));
// Keys typed in the box stay in the box (YouTube would take them as shortcuts).
root.addEventListener('keydown', e => e.stopPropagation());
window.addEventListener('keydown', e => {
  if (e.key.toLowerCase() !== 't' || e.repeat || e.ctrlKey || e.altKey || e.metaKey || !matched()) return;
  const el = e.composedPath()[0] || e.target;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) || el.isContentEditable) return;  // search box, comments
  e.preventDefault();
  e.stopImmediatePropagation();
  tap();
}, true);
// Media events don't bubble, but a listener on the capture side hears them from any <video>.
['play', 'pause', 'seeked', 'ratechange', 'ended'].forEach(type => document.addEventListener(type, () => {
  render();
  tick(true);
}, true));
document.addEventListener('yt-navigate-finish', () => { stopTapping(false); pc.sent = null; render(); tick(true); });

document.documentElement.appendChild(host);
setInterval(() => tick(false), PC.tickMs);
setInterval(poll, PC.pollMs);
poll();
