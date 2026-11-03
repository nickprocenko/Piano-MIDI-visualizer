// The YouTube tab: play along with a song's video on youtube.com. Loaded after video.js
// (videoShow) and coach.html's script (cmd, esc); profiles.js opens it with youtubeShow().
//
// Videos that only play on youtube.com go through the Piano Coach for YouTube extension
// (youtube_extension/), which follows the song open in the coach. This tab says whether the
// extension is talking to the coach (cmd('youtube')), walks through loading it, and lists every
// song synced to a video, each a click from playing along again. While the tab is open it asks
// again every few seconds, so the light turns green as soon as a YouTube tab opens.
"use strict";

const YT_POLL_MS = 3000;
const ytv = {timer: 0, listKey: null, setupShown: false};

const ytWatch = id => `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;
const ytThumb = id => `https://i.ytimg.com/vi/${encodeURIComponent(id)}/mqdefault.jpg`;
const ytSearch = q => `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}`;
const ytName = title => title.replace(/_/g, ' ');

function ytAgo(sec) {
  if (sec < 90) return 'just now';
  if (sec < 90 * 60) return `${Math.round(sec / 60)} minutes ago`;
  if (sec < 36 * 3600) return `${Math.round(sec / 3600)} hours ago`;
  return `${Math.round(sec / 86400)} days ago`;
}

function ytMsg(text) { $('ytv-msg').textContent = text || ''; }

function ytStatus(ext) {
  let state = ext.state, head, detail;
  if (state === 'live') {
    head = 'Connected';
    detail = 'A YouTube tab is open and talking to the coach. Play this song’s video there and the sheet follows it.';
  } else if (state === 'installed') {
    head = 'Installed';
    detail = `Last heard from ${ytAgo(ext.seen)}. Open youtube.com in Chrome or Edge and it connects by itself.`;
  } else {
    head = 'Not set up yet';
    detail = 'Some videos only play on youtube.com. Load the extension once (below) and the sheet follows them there too.';
  }
  if (state !== 'unknown' && ext.outdated) {
    state = 'outdated';
    head = 'Reload the extension';
    detail = `The copy in your browser is ${ext.version ? `version ${esc(ext.version)}` : 'an older version'}; `
      + `the one in the coach is ${esc(ext.latest)}. On the extensions page press its reload button (↻), then reload the YouTube tab.`;
  }
  $('ytv-status').className = `ytv-card ytv-status ${state}`;
  $('ytv-state').textContent = head;
  $('ytv-state-detail').innerHTML = detail;
  if (!ytv.setupShown) {  // open the steps once when they're needed, then leave them as the user sets them
    ytv.setupShown = true;
    $('ytv-setup').open = state === 'unknown' || state === 'outdated';
  }
}

function ytSong(song) {
  const v = song && song.video;
  $('ytv-title').textContent = song ? ytName(song.title) : 'No song open';
  $('ytv-thumb').hidden = !v;
  if (v) $('ytv-thumb').style.backgroundImage = `url("${ytThumb(v.id)}")`;
  $('ytv-open').hidden = !v;
  if (v) $('ytv-open').href = ytWatch(v.id);
  $('ytv-find').hidden = !song;
  if (song) $('ytv-find').href = ytSearch(ytName(song.title));
  $('ytv-find').textContent = v ? 'Find another video ↗' : 'Find it on YouTube ↗';
  $('ytv-find').classList.toggle('primary', !!song && !v);
  $('ytv-here').hidden = !song;
  $('ytv-pick').textContent = song ? 'Choose another song' : 'Choose a song';
  let detail;
  if (!song) detail = 'The extension follows whichever song is open in the coach, so open one first.';
  else if (!v) detail = 'No video chosen yet. Find it on YouTube, then press <b>Use this video for this song</b> in the Piano Coach box there.';
  else if (!song.taps) {
    detail = `Video: <b>${esc(v.title || v.id)}</b>. Not synced yet: in the Piano Coach box on YouTube press <b>Tap to sync</b>, `
      + 'then tap <b>T</b> on the first beat of each bar for 4 to 8 bars.';
  } else {
    const bpm = song.bpm ? `, about <b>${Math.round(song.bpm)} BPM</b>` : '';
    detail = `Video: <b>${esc(v.title || v.id)}</b>. Synced on bar${song.tapped.length > 1 ? 's' : ''} ${barList(song.tapped)}${bpm}.`;
  }
  $('ytv-detail').innerHTML = detail;
}

// Open a synced song in the coach (the extension follows the song open here).
async function ytLoad(path) {
  ytMsg('');
  try {
    await cmd('load', {lesson: path});
    return true;
  } catch (err) {
    ytMsg(err.message);
    return false;
  }
}

async function ytPlayHere(path) {
  if (path && !await ytLoad(path)) return;
  window.dispatchEvent(new CustomEvent('coach:navigate', {detail: {view: 'practice'}}));
  if ($('video-panel').hidden) videoShow(true);
}

function ytList(videos) {
  const key = JSON.stringify(videos);
  if (key === ytv.listKey) return;  // unchanged: keep the rows (and keyboard focus) as they are
  ytv.listKey = key;
  const list = $('ytv-list');
  list.replaceChildren();
  $('ytv-empty').hidden = videos.length > 0;
  for (const e of videos) {
    const li = document.createElement('li');
    li.className = 'ytv-row' + (e.current ? ' on' : '');
    const synced = e.taps ? `synced on ${e.taps} bar${e.taps > 1 ? 's' : ''}` : 'not synced yet';
    const sub = e.missing ? 'The song’s file has moved or been deleted' : `${e.video.title || e.video.id} · ${synced}`;
    li.innerHTML = `<img alt="" loading="lazy" src="${esc(ytThumb(e.video.id))}">
      <div><span class="ytv-name">${esc(ytName(e.title))}</span><span class="ytv-sub">${esc(sub)}</span></div>
      <a class="ytv-btn" target="_blank" rel="noopener" href="${esc(ytWatch(e.video.id))}"
         title="Open this song in the coach and its video on YouTube">Play along ↗</a>
      <button class="ytv-btn" title="Open this song in a Session with its video above the sheet">Play here</button>`;
    const [link, here] = li.querySelectorAll('.ytv-btn');
    if (e.missing) {
      link.removeAttribute('href');
      link.setAttribute('aria-disabled', 'true');
      link.style.opacity = here.style.opacity = '.4';
      here.disabled = true;
    } else {
      link.addEventListener('click', () => { if (!e.current) ytLoad(e.path).then(ytRefresh); });  // the tab opens either way
      here.addEventListener('click', () => ytPlayHere(e.current ? null : e.path));
    }
    list.appendChild(li);
  }
}

async function ytRefresh() {
  try {
    const out = await cmd('youtube');
    $('ytv-folder').textContent = out.folder;
    ytStatus(out.extension);
    ytSong(out.song);
    ytList(out.videos);
  } catch (err) {
    $('ytv-state').textContent = 'Can’t reach the coach';
    $('ytv-state-detail').textContent = err.message;
  }
}

function youtubeShow() {
  clearInterval(ytv.timer);
  ytRefresh();
  ytv.timer = setInterval(() => {
    if (document.body.dataset.view !== 'youtube') return clearInterval(ytv.timer);
    ytRefresh();
  }, YT_POLL_MS);
}

if (/\bEdg\//.test(navigator.userAgent)) $('ytv-ext-url').textContent = 'edge://extensions';
$('ytv-here').addEventListener('click', () => ytPlayHere(null));
$('ytv-pick').addEventListener('click', () => window.dispatchEvent(new CustomEvent('coach:navigate', {detail: {view: 'explore'}})));
$('ytv-reveal').addEventListener('click', async () => {
  try { await cmd('youtube', {reveal: true}); } catch (err) { ytMsg(err.message); }
});
document.querySelectorAll('#youtube-view [data-copy]').forEach(b => b.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($(b.dataset.copy).textContent);
    b.textContent = 'Copied';
  } catch (e) {
    b.textContent = 'Select and copy it';
  }
  setTimeout(() => { b.textContent = 'Copy'; }, 1500);
}));
