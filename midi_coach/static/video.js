// Play along with a recording, for the coach page (loaded after coach.html's script, sharing
// its globals: $, cmd, store, esc, running, scoreVersion).
//
// The YouTube player (IFrame Player API) plays the video. synced.py knows how its time lines
// up with the score and sends it as knots [video seconds, beat] at every bar line. While the
// panel is open, the beat under the video is posted to cmd/synced_cursor with the speed it's
// moving at; the server sends the cursor to this page's sheet and the visualizer's strip,
// which glide on between posts. A new post goes out at each bar line, on play / pause / seek /
// speed change, and when the glide has drifted from the video. Nothing is posted during a
// practice run, which owns the cursor.
//
// The page can't hear the video, so the user lines it up: Tap to sync, then T (or the
// button) on the first beat of each bar for a few bars; the taps are saved when Done is
// pressed or tapping stops for a few seconds. Once synced, T while the video plays puts the
// nearest bar line at that moment, to fix a stretch that drifts.

const VIDEO = {tickMs: 100, driftBeats: 0.08, idleSec: 4, jumpSec: 0.25, lean: 0.2, loopLeadSec: 1, seekQuietMs: 600};
const vid = {
  api: null, player: null, ready: false, loadedId: null, info: null,
  clock: {base: 0, at: 0, last: null, rate: 1, playing: false},
  sent: null, timer: 0, tapping: null, idle: 0, seekAt: 0,
};

function videoNote(html) { $('video-note').innerHTML = html; }

function videoApi() {
  if (!vid.api) vid.api = new Promise((resolve, reject) => {
    window.onYouTubeIframeAPIReady = () => resolve(window.YT);
    const s = document.createElement('script');
    s.src = 'https://www.youtube.com/iframe_api';
    s.onerror = () => { vid.api = null; reject(new Error('Could not reach YouTube. Is the internet on?')); };
    document.head.appendChild(s);
  });
  return vid.api;
}

// -- the video's clock ------------------------------------------------------------------------
// getCurrentTime() changes in steps a few times a second; between steps the time is counted
// on from the last one, and each new step pulls it gently back (a seek resets it).

function videoNow() {
  const c = vid.clock, now = performance.now();
  const guess = c.playing ? c.base + (now - c.at) / 1000 * c.rate : c.base;
  const t = vid.player.getCurrentTime() || 0;
  if (t === c.last) return guess;
  c.last = t;
  c.base = !c.playing || Math.abs(t - guess) > VIDEO.jumpSec ? t : guess + (t - guess) * VIDEO.lean;
  c.at = now;
  return c.base;
}

function resetClock() {
  const c = vid.clock;
  c.base = c.last = vid.player.getCurrentTime() || 0;
  c.at = performance.now();
  c.rate = vid.player.getPlaybackRate() || 1;
  c.playing = vid.player.getPlayerState() === YT.PlayerState.PLAYING;
}

// [beat, beats per video second, which bar's stretch] at a video time
function videoBeat(t) {
  const k = vid.info ? vid.info.knots : [];
  if (!k.length) return [0, 0, -1];
  if (t <= k[0][0]) return [k[0][1], 0, -1];  // before bar 1: the cursor waits there
  const n = k.length - 1;
  if (t >= k[n][0]) return [k[n][1], 0, n];
  let lo = 0, hi = n;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (k[mid][0] <= t) lo = mid; else hi = mid; }
  const slope = (k[hi][1] - k[lo][1]) / (k[hi][0] - k[lo][0]);
  return [k[lo][1] + slope * (t - k[lo][0]), slope, lo];
}

// [start, end] of the loop in video seconds, or null when it's off. The knots are one per bar
// line and then the end, so bar i starts at knots[i] and ends at knots[i + 1].
function videoLoopSpan() {
  const info = vid.info, loop = info && info.loop;
  if (!loop || !loop.on || !info.knots.length) return null;
  const i = info.bars.findIndex(b => b.number === loop.from), j = info.bars.findIndex(b => b.number === loop.to);
  return i < 0 || j < 0 ? null : [info.knots[i][0], info.knots[j + 1][0]];
}

function videoTick(force) {
  if (!vid.ready || !vid.info || !vid.info.video || running || $('video-panel').hidden) return;
  const span = vid.clock.playing && !vid.tapping && videoLoopSpan();
  if (span && performance.now() - vid.seekAt > VIDEO.seekQuietMs) {
    const t = videoNow();
    if (t >= span[1] || t < span[0] - VIDEO.loopLeadSec - 0.5) {  // past the end, or not there yet
      vid.seekAt = performance.now();
      vid.player.seekTo(Math.max(0, span[0] - VIDEO.loopLeadSec), true);
    }
  }
  const [beat, slope, seg] = videoBeat(videoNow());
  const bps = vid.clock.playing ? slope * vid.clock.rate : 0;
  const s = vid.sent, now = performance.now();
  if (!force && s && s.seg === seg && Math.abs(s.bps - bps) < 1e-4
      && Math.abs(s.beat + s.bps * (now - s.at) / 1000 - beat) < VIDEO.driftBeats) return;
  vid.sent = {beat, bps, seg, at: now};
  cmd('synced_cursor', {beat, bps}).catch(() => {});  // a run that just started owns the cursor
}

// -- the panel ----------------------------------------------------------------------------

function barList(numbers) {
  const out = [];
  for (const n of numbers) {
    const last = out[out.length - 1];
    if (last && n === last[1] + 1) last[1] = n; else out.push([n, n]);
  }
  return out.map(([a, b]) => a === b ? `${a}` : `${a}–${b}`).join(', ');
}

function videoDescribe() {
  const info = vid.info;
  if (!info) return videoNote('');
  if (!info.video) return videoNote('Choose a video of this song: paste its link, or find it on YouTube.');
  if (!info.taps) {
    return videoNote('Not synced yet, so the sheet assumes bar 1 starts when the video does. Press <b>Tap to sync</b>, '
      + 'then tap <b>T</b> on the first beat of each bar for 4 to 8 bars.');
  }
  const bpm = info.bpm ? ` · the recording is about <b>${Math.round(info.bpm)} BPM</b>` : '';
  videoNote(`Synced on bar${info.tapped.length > 1 ? 's' : ''} ${barList(info.tapped)}${bpm}. `
    + 'If the sheet drifts, press <b>T</b> on the first beat of any bar while the video plays.');
}

function videoSpeeds() {
  const sel = $('video-speed');
  const rates = (vid.ready && vid.player.getAvailablePlaybackRates()) || [1];
  const now = vid.ready ? vid.player.getPlaybackRate() : 1;
  const bpm = vid.info && vid.info.bpm;
  sel.innerHTML = '';
  for (const r of rates) sel.add(new Option(`${Math.round(r * 100)}%` + (bpm ? ` · ${Math.round(bpm * r)} BPM` : ''), r));
  sel.value = now;
}

function videoSetInfo(info) {
  vid.info = info;
  vid.sent = null;
  if (!vid.tapping) $('video-bar').value = info.first_bar;
  $('video-clear').disabled = !info.taps;
  $('video-sync').disabled = !info.video;
  const loop = info.loop || {};
  const bars = info.bars.map(b => b.number);
  $('video-loop').checked = !!loop.on;
  $('video-from').value = loop.from ?? info.first_bar;
  $('video-to').value = loop.to ?? (bars.length ? bars[bars.length - 1] : '');
  $('video-yt').hidden = !info.video;
  if (info.video) $('video-yt').href = 'https://www.youtube.com/watch?v=' + info.video.id;
  videoDescribe();
  videoSpeeds();
  videoLoad();
}

async function videoLoad() {
  const id = vid.info && vid.info.video && vid.info.video.id;
  $('yt-empty').hidden = !!id;
  if (!id) {
    if (vid.ready) vid.player.stopVideo();
    vid.loadedId = null;
    return;
  }
  if (id === vid.loadedId) return;
  let YT;
  try { YT = await videoApi(); } catch (err) { return videoNote(esc(err.message)); }
  if (vid.ready) { vid.loadedId = id; vid.player.cueVideoById(id); return; }
  if (vid.player) return;  // still starting: onReady cues whatever is current then
  vid.player = new YT.Player('yt-player', {
    videoId: id,
    playerVars: {playsinline: 1, rel: 0, origin: location.origin},
    events: {
      onReady: () => {
        vid.ready = true;
        vid.loadedId = id;
        resetClock();
        videoSpeeds();
        if (vid.info && vid.info.video && vid.info.video.id !== id) videoLoad();
        clearInterval(vid.timer);
        vid.timer = setInterval(() => videoTick(false), VIDEO.tickMs);
      },
      onStateChange: () => {
        resetClock();
        videoTick(true);
        // Keys pressed in the player go to YouTube: take the focus back so T reaches this page.
        if (document.activeElement === vid.player.getIframe()) $('video-sync').focus();
      },
      onPlaybackRateChange: () => { resetClock(); $('video-speed').value = vid.clock.rate; videoTick(true); },
      onError: e => videoNote([101, 150].includes(e.data)
        ? 'This video only plays on YouTube itself. Press <b>Open on YouTube</b>: with the Music Hub extension '
          + 'installed, the sheet follows it there, with the same taps and loop. Or choose another video.'
        : 'YouTube could not play this video. Choose another one.'),
    },
  });
}

async function videoRefresh() {
  if (!scoreVersion) { vid.info = null; return videoNote('Pick a song first.'); }
  try { videoSetInfo(await cmd('synced')); } catch (err) { videoNote(esc(err.message)); }
}

function videoShow(open) {
  $('video-panel').hidden = !open;
  $('video-btn').setAttribute('aria-pressed', String(open));
  store.set('video', open ? '1' : '');
  if (open) return videoRefresh();
  videoStopTapping(false);
  if (vid.ready) vid.player.pauseVideo();
  if (vid.sent && vid.sent.bps && !running) cmd('synced_cursor', {beat: videoBeat(videoNow())[0], bps: 0}).catch(() => {});
  vid.sent = null;
}

// The coach page calls this when another song is loaded.
function videoScoreChanged() {
  videoStopTapping(false);
  if ($('video-panel').hidden) { vid.info = null; return; }
  if (vid.ready) vid.player.pauseVideo();
  videoRefresh();
}

// -- tapping ------------------------------------------------------------------------------

function videoStartTapping() {
  if (!vid.ready || !vid.info || !vid.info.video) return videoNote('Choose a video first.');
  const bar = Number($('video-bar').value);
  vid.tapping = {bar: Number.isFinite(bar) ? bar : vid.info.first_bar, taps: []};
  $('video-sync').classList.add('tapping');
  $('video-sync').textContent = 'Tap (T)';
  $('video-done').hidden = false;
  if (!vid.clock.playing) vid.player.playVideo();
  videoNote(`Tap <b>T</b> (or the button) on the first beat of <b>bar ${vid.tapping.bar}</b>, then on the first beat `
    + 'of every bar after it. A few bars is enough; Done saves them.');
}

function videoTap() {
  if (!vid.ready) return;
  if (!vid.tapping) {
    if (vid.info && vid.info.taps && vid.clock.playing) return videoNudge();
    videoStartTapping();
    if (!vid.tapping || !vid.clock.playing) return;
  }
  if (!vid.clock.playing) return videoNote('Play the video, then tap on the first beat of each bar.');
  const t = vid.tapping;
  t.taps.push(videoNow());
  const btn = $('video-sync');
  btn.classList.add('hit');
  setTimeout(() => btn.classList.remove('hit'), 120);
  videoNote(`<b>${t.taps.length}</b> tapped from bar ${t.bar}. Keep going, or press Done.`);
  clearTimeout(vid.idle);
  vid.idle = setTimeout(() => videoStopTapping(true), VIDEO.idleSec * 1000);
}

async function videoStopTapping(save) {
  clearTimeout(vid.idle);
  const t = vid.tapping;
  vid.tapping = null;
  $('video-sync').classList.remove('tapping', 'hit');
  $('video-sync').textContent = 'Tap to sync';
  $('video-done').hidden = true;
  if (!save || !t || !t.taps.length) return videoDescribe();
  try { videoSetInfo(await cmd('synced', {taps: t.taps, bar: t.bar})); } catch (err) { videoNote(esc(err.message)); }
}

async function videoNudge() {
  try {
    const out = await cmd('synced', {nudge: videoNow()});
    videoSetInfo(out);
    if (out.nudged !== undefined) videoNote(`Bar <b>${out.nudged}</b> now starts there. ` + $('video-note').innerHTML);
  } catch (err) { videoNote(esc(err.message)); }
}

async function videoChoose(link, title) {
  $('video-results').hidden = true;
  try { videoSetInfo(await cmd('synced', {link, title})); } catch (err) { videoNote(esc(err.message)); }
}

async function videoFind() {
  const box = $('video-results');
  box.hidden = false;
  box.textContent = 'Searching YouTube…';
  try {
    const {results} = await cmd('synced', {search: ''});
    box.innerHTML = '';
    if (!results.length) { box.textContent = 'Nothing found. Paste a link instead.'; return; }
    for (const r of results) {
      const b = document.createElement('button');
      b.textContent = r.title || r.url;
      b.addEventListener('click', () => videoChoose(r.video_id, r.title));
      box.appendChild(b);
    }
  } catch (err) { box.textContent = err.message; }
}

$('video-btn').addEventListener('click', () => videoShow($('video-panel').hidden));
$('video-use').addEventListener('click', () => videoChoose($('video-link').value));
$('video-link').addEventListener('keydown', e => { if (e.key === 'Enter') videoChoose($('video-link').value); });
$('video-find').addEventListener('click', videoFind);
$('video-sync').addEventListener('click', () => vid.tapping ? videoTap() : videoStartTapping());
$('video-done').addEventListener('click', () => videoStopTapping(true));
$('video-clear').addEventListener('click', async () => {
  if (!confirm('Forget the taps for this video? You can tap again any time.')) return;
  try { videoSetInfo(await cmd('synced', {clear: true})); } catch (err) { videoNote(esc(err.message)); }
});
['video-loop', 'video-from', 'video-to'].forEach(id => $(id).addEventListener('change', async () => {
  const num = box => $(box).value === '' ? null : Number($(box).value);
  try {
    videoSetInfo(await cmd('synced', {loop: {from: num('video-from'), to: num('video-to'), on: $('video-loop').checked}}));
  } catch (err) { videoNote(esc(err.message)); }
}));
$('video-speed').addEventListener('change', e => { if (vid.ready) vid.player.setPlaybackRate(Number(e.target.value)); });
document.addEventListener('keydown', e => {
  if (e.key.toLowerCase() !== 't' || e.repeat || e.ctrlKey || e.altKey || e.metaKey || $('video-panel').hidden
      || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
  e.preventDefault();
  videoTap();
});
if (store.get('video', '')) videoShow(true);
