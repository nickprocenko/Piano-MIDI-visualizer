// Radio Hands: the page. Plays the station from the app's buffer (Web Audio, so it knows exactly
// which moment of the stream you're hearing), and draws the coach page's falling notes and 3D
// hands (roll.js + hands3d.js, unchanged) at that moment: the song's own notes once the server has
// lined the file up with the radio, else the chords it hears.
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const store = {
    get(k, d) { try { const v = localStorage.getItem('rh.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('rh.' + k, JSON.stringify(v)); } catch (e) {} },
  };
  const post = (url, body) => fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})})
    .then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.statusText); return j; });

  function toast(msg, bad) {
    const t = document.createElement('div');
    t.className = 'toast' + (bad ? ' bad' : '');
    t.textContent = msg;
    $('toasts').appendChild(t);
    setTimeout(() => t.remove(), bad ? 6000 : 3000);
  }
  // Startup splash: stays until the app has answered and the 3D hands are ready (or failed)
  const boot = {state: false, hands: false, t0: performance.now()};
  function bootCheck() {
    const s = $('splash');
    if (boot.state && boot.hands) { s.classList.add('gone'); setTimeout(() => s.remove(), 500); return; }
    $('splash-text').textContent = !boot.state ? 'Connecting to the app…' : 'Loading the 3D hands…';
  }
  setTimeout(() => {
    if (!boot.state && $('splash')) { $('splash-text').textContent = "Can't reach the app. Is its window still open?"; $('splash-retry').hidden = false; }
    else if (!boot.hands && $('splash')) { boot.hands = true; bootCheck(); toast('The 3D hands are slow to load; drawing flat hands for now.', true); }
  }, 12000);
  $('splash-retry').onclick = () => location.reload();

  let state = null;
  let delay = Number(store.get('delay', 12));
  if (![0, 5, 10, 15, 20, 30].includes(delay)) delay = 15;
  $('delay').value = String(delay);

  // -- the player -------------------------------------------------------------------------------
  // The server streams 16-bit stereo PCM from a chosen sample on; each 0.2 s becomes an
  // AudioBuffer scheduled straight after the one before, and every scheduled piece remembers which
  // stream sample it starts with, so position() can say which moment is coming out of the speakers.
  const Player = (() => {
    let ctx = null, gain = null, run = null;
    let volume = Number(store.get('volume', 0.8));
    function ensure() {
      if (!ctx) {
        ctx = new AudioContext({sampleRate: 44100, latencyHint: 'playback'});
        gain = ctx.createGain();
        gain.gain.value = volume;
        gain.connect(ctx.destination);
      }
      return ctx;
    }
    async function start(session, fromSample) {
      stop();
      ensure();
      await ctx.resume();
      const r = {session, abort: new AbortController(), segs: [], sources: new Set(), nextCtx: 0, nextSample: 0, sr: 44100, ended: false};
      run = r;
      let res;
      try {
        res = await fetch(`/api/pcm?session=${session}&from=${Math.max(0, Math.floor(fromSample))}`, {signal: r.abort.signal});
      } catch (e) { if (run === r) run = null; return; }
      if (!res.ok) { if (run === r) run = null; return; }
      r.nextSample = Number(res.headers.get('X-From')) || 0;
      r.sr = Number(res.headers.get('X-Sample-Rate')) || 44100;
      const reader = res.body.getReader();
      const CHUNK = Math.round(r.sr * 0.2) * 4;
      let pend = new Uint8Array(0);
      try {
        while (run === r) {
          const {value, done} = await reader.read();
          if (done) break;
          const joined = new Uint8Array(pend.length + value.length);
          joined.set(pend); joined.set(value, pend.length);
          let at = 0;
          while (joined.length - at >= CHUNK) { schedule(r, joined.subarray(at, at + CHUNK)); at += CHUNK; }
          pend = joined.slice(at);
        }
      } catch (e) { /* aborted */ }
      r.ended = true;
    }
    function schedule(r, bytes) {
      const n = bytes.length >> 2;
      const buf = ctx.createBuffer(2, n, r.sr);
      const pcm = new Int16Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length));
      const L = buf.getChannelData(0), R = buf.getChannelData(1);
      for (let i = 0, j = 0; i < n; i++, j += 2) { L[i] = pcm[j] / 32768; R[i] = pcm[j + 1] / 32768; }
      const now = ctx.currentTime;
      if (r.nextCtx < now + 0.05) r.nextCtx = now + 0.25;  // the start, or after the stream ran dry
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(gain);
      src.start(r.nextCtx);
      r.sources.add(src);
      src.onended = () => r.sources.delete(src);
      r.segs.push({ctx: r.nextCtx, sample: r.nextSample, n});
      r.nextCtx += n / r.sr;
      r.nextSample += n;
      while (r.segs.length > 2 && r.segs[0].ctx + r.segs[0].n / r.sr < now - 3) r.segs.shift();
    }
    // The stream second coming out of the speakers now (null when nothing is playing)
    function position() {
      if (!run || !ctx || !run.segs.length) return null;
      let ct;
      const ts = ctx.getOutputTimestamp ? ctx.getOutputTimestamp() : null;
      if (ts && ts.contextTime > 0) ct = ts.contextTime + (performance.now() - ts.performanceTime) / 1000;
      else ct = ctx.currentTime - (ctx.outputLatency || ctx.baseLatency || 0);
      for (const s of run.segs) {
        if (ct >= s.ctx && ct < s.ctx + s.n / run.sr) return (s.sample + (ct - s.ctx) * run.sr) / run.sr;
      }
      return null;
    }
    function stop() {
      if (!run) return;
      run.abort.abort();
      for (const s of run.sources) { try { s.stop(); } catch (e) {} }
      run = null;
    }
    function setVolume(v) { volume = v; store.set('volume', v); if (gain) gain.gain.value = v; }
    return {start, stop, position, setVolume, get session() { return run && run.session; },
            get volume() { return volume; }, get running() { return !!run; }};
  })();
  $('volume').value = String(Player.volume);
  $('volume').oninput = e => Player.setVolume(Number(e.target.value));

  // Playing: what the user asked for (Listen / a station) until they stop. ?autoplay=1 starts
  // whatever the app is tuned to (the browser must allow sound without a click).
  let wantPlay = new URLSearchParams(location.search).get('autoplay') === '1', waitingFor = null;
  function startPlayback() {
    const t = state && state.tuner;
    if (!t || !t.session) return;
    wantPlay = true;
    const live = t.live;
    if (live < delay - 0.2) { waitingFor = t.session; render(); return; }  // still filling the delay
    waitingFor = null;
    Player.start(t.session, Math.max(t.oldest, live - delay) * t.sr);
    render();
  }
  function stopPlayback() { wantPlay = false; waitingFor = null; Player.stop(); render(); }
  $('play').onclick = () => {
    if (Player.running || waitingFor) { stopPlayback(); post('/api/stop'); }
    else if (state && state.tuner.session) startPlayback();
    else openPicker();
  };
  $('delay').onchange = e => {
    delay = Number(e.target.value);
    store.set('delay', delay);
    if (Player.running || waitingFor) startPlayback();
  };
  $('overlay-btn').onclick = () => {
    if (waitingFor) { const d = delay; delay = 0; startPlayback(); delay = d; }  // play now, live
    else if (state && state.tuner.session) startPlayback();
    else openPicker();
  };

  // -- the state from the server ----------------------------------------------------------------
  const preps = new Map();   // song id -> {notes, bars, timeline, step, duration}
  function connect() {
    const es = new EventSource('/api/events');
    es.onmessage = e => {
      state = JSON.parse(e.data);
      if (!boot.state) { boot.state = true; bootCheck(); offerResume(); }
      setBanner('');
      onState();
    };
    es.onerror = () => { setBanner('Lost the connection to the app. Reconnecting…'); };
  }
  function setBanner(text) { $('banner').hidden = !text; $('banner').textContent = text; }
  function onState() {
    document.title = state.title && Player.running ? `♪ ${state.title} · Radio Hands` : 'Radio Hands';
    const t = state.tuner;
    if (Player.running && Player.session !== t.session) Player.stop();
    if (wantPlay && t.session && !Player.running && (!waitingFor || waitingFor === t.session) && t.live >= delay - 0.2) startPlayback();
    for (const s of [state.song, state.previous]) {
      if (s && s.ready && !preps.has(s.id)) {
        preps.set(s.id, null);
        fetch(`/api/song?id=${s.id}`).then(r => r.ok ? r.json() : null).then(p => {
          if (p) preps.set(s.id, p); else preps.delete(s.id);
        });
      }
    }
    render();
  }

  // -- the header, the song line and the overlay -------------------------------------------------
  const STATUS = {
    looking: ['Looking…', 'wait'], loading: ['Loading…', 'wait'], listening: ['Lining up…', 'wait'],
    synced: ['♪ Notes', 'ok'], not_found: ['Chords', 'off'], no_match: ['Chords', 'bad'], lost: ['Lining up…', 'wait'],
    ended: ['Ended', 'off'], error: ['Error', 'bad'],
  };
  function render() {
    const st = state && state.station;
    const t = state ? state.tuner : {state: 'off'};
    $('st-name').textContent = st ? st.name : 'Choose a station';
    $('st-where').textContent = st ? [st.state, st.country].filter(Boolean).join(', ') || (t.icy_name || '') : '';
    const icon = $('st-icon');
    if (st && st.favicon) { icon.src = st.favicon; icon.hidden = false; icon.onerror = () => { icon.hidden = true; }; } else icon.hidden = true;
    if (st || wantPlay) $('overlay-resume').hidden = true;
    const playing = Player.running;
    $('play').disabled = !st && !state;
    $('play').textContent = playing || waitingFor ? '■ Stop' : (st ? '▶ Listen' : '▶ Choose a station');
    $('play').classList.toggle('stop', !!(playing || waitingFor));
    $('onair').classList.toggle('live', playing && t.state === 'playing');
    const tunerText = {connecting: 'Connecting…', retrying: `Reconnecting: ${t.message || ''}`, playing: '', stopped: '', off: ''}[t.state] || '';
    $('tuner').textContent = tunerText || (playing && t.state === 'playing' && !t.titles && t.live > 20 ? "This station doesn't say what's playing: type it →" : '');
    $('on-air').textContent = state && state.title ? state.title : (st ? (t.state === 'playing' ? '(no title from the station)' : '—') : '—');
    const song = state && state.song;
    const chip = $('song-chip');
    if (song) {
      const [label, kind] = STATUS[song.status] || [song.status, 'off'];
      chip.textContent = label; chip.className = 'chip ' + kind; chip.hidden = false;
      chip.title = song.fit ? `fit ${song.fit.score} · contrast ${song.fit.contrast} · speed ${song.fit.rate} · ${song.fit.heard} s heard` : '';
      let msg = song.message || '';
      if (song.match && song.status !== 'not_found') msg = `${song.match.name}${song.source === 'bitmidi' ? ' (bitmidi)' : ''} · ${msg}`;
      $('song-msg').textContent = msg;
      const sel = $('versions');
      const others = song.others || [];
      if (song.match && others.length) {
        const opts = [song.match, ...others];
        const key = opts.map(o => o.path).join('|');
        if (sel.dataset.key !== key) {
          sel.innerHTML = '';
          for (const o of opts) { const op = document.createElement('option'); op.value = o.path; op.textContent = o.name; sel.appendChild(op); }
          sel.dataset.key = key;
        }
        sel.value = song.match.path; sel.hidden = false;
      } else sel.hidden = true;
    } else { chip.hidden = true; $('song-msg').textContent = ''; $('versions').hidden = true; }
    renderHistory();
    renderSettings();
  }
  $('versions').onchange = e => post('/api/song', {path: e.target.value}).catch(err => toast(err.message, true));
  $('typed').onsubmit = e => {
    e.preventDefault();
    const q = $('typed-q').value.trim();
    if (q) post('/api/song', {query: q}).then(() => { $('typed-q').value = ''; $('typed-q').blur(); }).catch(err => toast(err.message, true));
  };

  function setOverlay(text, button, busy) {
    if ($('overlay-text').textContent !== text) $('overlay-text').textContent = text;
    $('overlay-spin').hidden = !(busy && text);
    const b = $('overlay-btn');
    b.hidden = !button;
    if (button && b.textContent !== button) b.textContent = button;
  }

  function renderHistory() {
    const list = $('history-list');
    const items = (state && state.history) || [];
    const key = items.map(h => h.id + h.status + h.found).join('|');
    if (list.dataset.key === key) return;
    list.dataset.key = key;
    list.innerHTML = '';
    if (!items.length) { list.innerHTML = '<li><small>Songs will be listed here as the station plays them.</small></li>'; return; }
    for (const h of items) {
      const li = document.createElement('li');
      li.className = h.found ? 'found' : '';
      li.innerHTML = '<time></time><span></span><small></small>';
      li.children[0].textContent = h.at;
      li.children[1].textContent = h.title;
      li.children[2].textContent = h.found ? `♪ ${h.found}` : (h.status === 'looking' ? 'looking…' : 'chords (not in the library)');
      list.appendChild(li);
    }
  }
  $('history-btn').onclick = () => {
    const open = $('history').hidden;
    $('history').hidden = !open;
    $('history-btn').setAttribute('aria-expanded', String(open));
  };

  // -- settings ----------------------------------------------------------------------------------
  $('gear').onclick = () => {
    const open = $('settings').hidden;
    $('settings').hidden = !open;
    $('gear').setAttribute('aria-expanded', String(open));
  };
  document.addEventListener('click', e => {
    if (!$('settings').hidden && !$('settings').contains(e.target) && e.target !== $('gear')) {
      $('settings').hidden = true; $('gear').setAttribute('aria-expanded', 'false');
    }
  });
  function renderSettings() {
    if (!state) return;
    $('set-online').checked = state.settings.online;
    $('set-charts').checked = state.settings.charts;
    $('set-lib').textContent = `${state.library.toLocaleString()} song files in the library.`;
  }
  $('set-online').onchange = e => post('/api/settings', {online: e.target.checked});
  $('set-charts').onchange = e => post('/api/settings', {charts: e.target.checked});
  $('set-fingers').checked = coachRoll.fingers();
  $('set-fingers').onchange = e => coachRoll.showFingers(e.target.checked);
  $('set-names').checked = coachRoll.names();
  $('set-names').onchange = e => coachRoll.showNames(e.target.checked);

  // -- the hands ---------------------------------------------------------------------------------
  // Keys the keyboard always spans in chord mode (hidden notes long past, so never drawn), and a
  // far-off note for each hand so they rest on the keys while nothing's playing.
  const RANGE = [[-1e6, 0.1, 36, 'track:keys'], [-1e6, 0.1, 84, 'track:keys']];
  const RESTING = [[1e7, 1, 64, 'right', 3], [1e7, 1, 48, 'left', 3]];
  let shownKey = null;
  function show(key, notes, bars) {
    if (shownKey === key) return;
    shownKey = key;
    coachRoll.score({notes, bars: bars || []});
    coachRoll.parts(['track:keys'], ['right', 'left']);
  }

  function activeSong(t) {
    const list = [state.song, state.previous].filter(Boolean).sort((a, b) => b.started - a.started);
    return list.find(s => t >= s.started - 0.5) || null;
  }
  function midiAt(song, t) {
    const a = song.anchors;
    if (!a.length) return null;
    if (t <= a[0][0]) return a[0][1] + a[0][2] * (t - a[0][0]);
    for (let i = 0; i + 1 < a.length; i++) {
      if (a[i][0] <= t && t <= a[i + 1][0]) return a[i][1] + (a[i + 1][1] - a[i][1]) * (t - a[i][0]) / ((a[i + 1][0] - a[i][0]) || 1);
    }
    const z = a[a.length - 1];
    return z[1] + z[2] * (t - z[0]);
  }
  function beatAt(prep, m) {
    const tl = prep.timeline, step = prep.step;
    if (m <= 0) return tl[0] + m * 2 * ((tl[1] - tl[0]) / step / 2 || 1);
    const i = Math.min(tl.length - 2, Math.floor(m / step));
    return tl[i] + (tl[i + 1] - tl[i]) * (m - i * step) / step;
  }
  function chordAt(t) {
    const segs = state.chords.segs;
    let now = '', next = '';
    for (let i = 0; i < segs.length; i++) {
      if (segs[i][0] <= t && t < segs[i][1]) {
        now = segs[i][2];
        for (let j = i + 1; j < segs.length; j++) if (segs[j][2] && segs[j][2] !== now) { next = segs[j][2]; break; }
        break;
      }
    }
    return [now, next];
  }

  // -- piano / guitar view -----------------------------------------------------------------------
  let view = store.get('view', 'piano');
  const VIEWS = ['piano', 'guitar', 'drums', 'all'];
  function setView(v) {
    if (!VIEWS.includes(v)) v = 'piano';
    view = v; store.set('view', v);
    const on = {roll: v === 'piano' || v === 'all', highway: v === 'guitar' || v === 'all', drumway: v === 'drums' || v === 'all'};
    for (const id of Object.keys(on)) $(id).hidden = !on[id];
    document.querySelector('main').classList.toggle('all', v === 'all');
    for (const b of document.querySelectorAll('#views button')) b.classList.toggle('on', b.dataset.view === v);
    if (v !== 'piano') $('chord').hidden = true;
  }
  for (const b of document.querySelectorAll('#views button')) b.onclick = () => setView(b.dataset.view);
  setView(view);
  // the chords shown on the highway: what the page knows up to the live edge (the delay is the look-ahead)
  // The drum hits to draw, in stream seconds: the song's own MIDI drums when its file is lined up
  // with the radio (known a few seconds ahead), else the ones heard
  function drumHits(t) {
    if (t === null) return {hits: [], source: 'heard'};
    const song = activeSong(t), prep = song && preps.get(song.id);
    if (song && prep && prep.drums && prep.drums.length && song.anchors.length && song.good_from !== null && t >= song.good_from - 1 && t <= song.good_until) {
      const mNow = midiAt(song, t), rate = song.anchors[song.anchors.length - 1][2], d = prep.drums;
      let a = 0, b = d.length;
      while (a < b) { const mid = (a + b) >> 1; if (d[mid][0] < mNow - 0.3 * rate) a = mid + 1; else b = mid; }
      const hits = [];
      for (let i = a; i < d.length && d[i][0] < mNow + 6 * rate; i++) hits.push([t + (d[i][0] - mNow) / rate, d[i][1]]);
      return {hits, source: 'file'};
    }
    return {hits: state.drums ? state.drums.hits : [], source: 'heard'};
  }
  function drawDrums(t, now) {
    const {hits, source} = drumHits(t);
    window.drumHighway.draw($('drumway'), t === null ? 0 : t, hits, source, now);
  }
  function drawGuitar(t, now) {
    const idle = t === null;
    window.guitarHighway.draw($('highway'), idle ? 0 : t, idle ? [] : state.chords.segs, state.tuner.live, now);
  }

  let shownM = null, lastNow = 0, lastSong = null, chordNotes = [], chordsSeen = null;
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.2, (now - lastNow) / 1000);
    lastNow = now;
    if (!state) return;
    const t = Player.position();
    const tuner = state.tuner;
    if (view === 'guitar' || view === 'all') drawGuitar(t, now);
    if (view === 'drums' || view === 'all') drawDrums(t, now);
    if (t === null) {
      show('idle', RANGE.concat(RESTING));
      coachRoll.frameAt(0, now);
      $('chord').hidden = true;
      if (!state.station) setOverlay('Choose a station to start.', 'Choose a station');
      else if (waitingFor) setOverlay(`Starting in ${Math.max(1, Math.ceil(delay - tuner.live))} s: getting ahead of the radio so the hands are ready on time.`, 'Play now (live)', true);
      else if (wantPlay) setOverlay(tuner.state === 'playing' ? 'Starting…' : (tuner.message || 'Connecting…'), '', true);
      else setOverlay('', '▶ Listen');
      return;
    }
    // Notes when the song's file is lined up with the radio at this moment
    const song = activeSong(t);
    const prep = song && preps.get(song.id);
    let m = null;
    if (song && prep && song.anchors.length && song.good_from !== null && t >= song.good_from - 1 && t <= song.good_until) {
      m = midiAt(song, t);
      if (m > prep.duration + 1) m = null;
    }
    const [cNow, cNext] = chordAt(t);
    $('chord').hidden = !cNow || view !== 'piano';
    if (cNow) {
      $('chord-now').textContent = cNow;
      $('chord-next').textContent = cNext;
      $('chord-src').textContent = m !== null ? '' : ({chart: 'from the chart', file: "the file's chords", heard: 'as heard'}[state.chords.source] || '');
    }
    if (m !== null) {
      // ease small corrections (a new anchor) instead of jumping
      const rate = song.anchors[song.anchors.length - 1][2];
      if (shownM === null || lastSong !== song.id || Math.abs(m - (shownM + dt * rate)) > 1.0) shownM = m;
      else shownM = shownM + dt * rate + (m - shownM - dt * rate) * Math.min(1, dt / 0.25);
      lastSong = song.id;
      show('song:' + song.id, prep.notes.filter(n => n[3] === 'right' || n[3] === 'left'), prep.bars);
      coachRoll.frameAt(beatAt(prep, shownM), now);
      setOverlay('', '');
      return;
    }
    shownM = null;
    // Chords: the notes are placed at stream seconds × bps
    // The chords are revised as more radio is heard, so each new set goes to the piano as an
    // update: the hands carry on from where they are. Only a new station or song starts them over.
    const key = 'chords:' + tuner.session;
    if (shownKey !== key) { show(key, RANGE.concat(RESTING)); chordNotes = []; chordsSeen = null; }
    if (chordsSeen !== state.chords) {
      chordsSeen = state.chords;
      chordNotes = state.chords.notes;
      coachRoll.update({notes: RANGE.concat(chordNotes.length ? chordNotes : RESTING)});
    }
    const notes = chordNotes;
    coachRoll.frameAt(t * state.chords.bps, now);
    let msg = '';
    if (song && (song.status === 'listening' || song.status === 'lost' || song.status === 'loading') && !notes.length) msg = song.message;
    else if (!state.title && !cNow) msg = '';
    setOverlay(msg, '', true);
  }

  // -- the station picker ------------------------------------------------------------------------
  function openPicker() { $('picker').hidden = false; loadFilters(); $('f-name').focus(); renderSaved(); search(); }
  function closePicker() { $('picker').hidden = true; }
  $('station').onclick = openPicker;
  $('picker-close').onclick = closePicker;
  $('picker').onclick = e => { if (e.target === $('picker')) closePicker(); };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePicker(); });
  for (const b of document.querySelectorAll('.sheet nav button')) {
    b.onclick = () => {
      for (const x of document.querySelectorAll('.sheet nav button')) x.classList.toggle('on', x === b);
      for (const p of document.querySelectorAll('[data-pane]')) p.hidden = p.dataset.pane !== b.dataset.tab;
      renderSaved();
    };
  }

  let filtersLoaded = false;
  async function loadFilters() {
    if (filtersLoaded) return;
    filtersLoaded = true;
    const sel = $('f-country');
    const region = (navigator.language.split('-')[1] || '').toUpperCase();
    const saved = store.get('country', region || '');
    try {
      const list = await (await fetch('/api/countries')).json();
      for (const c of list) { const o = document.createElement('option'); o.value = c.code; o.textContent = c.name; o.dataset.name = c.name; sel.appendChild(o); }
    } catch (e) {}
    sel.value = saved;
    $('f-state').value = '';
    await loadStates(store.get('state', ''));
    search();
  }
  async function loadStates(chosen) {
    const sel = $('f-state');
    sel.innerHTML = '<option value="">Any province / state</option>';
    const opt = $('f-country').selectedOptions[0];
    if (!opt || !opt.value) return;
    try {
      const list = await (await fetch(`/api/states?country=${encodeURIComponent(opt.dataset.name)}`)).json();
      for (const s of list) { const o = document.createElement('option'); o.value = s.name; o.textContent = `${s.name} (${s.stations})`; sel.appendChild(o); }
    } catch (e) {}
    sel.value = chosen || '';
  }
  $('f-country').onchange = async () => { store.set('country', $('f-country').value); store.set('state', ''); await loadStates(''); search(); };
  $('f-state').onchange = () => { store.set('state', $('f-state').value); search(); };
  let searchTimer = 0, searchSeq = 0;
  $('f-name').onkeydown = e => { if (e.key === 'Enter') { const li = $('results').querySelector('li:not(.empty)'); if (li) li.click(); } };
  $('f-name').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(search, 300); };
  $('f-tag').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(search, 400); };
  async function search() {
    const seq = ++searchSeq;
    const ul = $('results');
    const params = new URLSearchParams({q: $('f-name').value.trim(), country: $('f-country').value, state: $('f-state').value, tag: $('f-tag').value.trim()});
    ul.innerHTML = '<li class="empty"><span class="spin"></span>Searching…</li>';
    try {
      const r = await fetch('/api/stations?' + params);
      const list = await r.json();
      if (seq !== searchSeq) return;
      if (!r.ok) throw new Error(list.error);
      fillStations(ul, list, 'No stations found. Try fewer filters.');
    } catch (e) {
      if (seq === searchSeq) ul.innerHTML = `<li class="empty">${e.message || "Couldn't search for stations."}</li>`;
    }
  }
  const favs = () => store.get('favs', []);
  function isFav(s) { return favs().some(f => f.url === s.url); }
  function toggleFav(s) {
    const list = favs();
    const i = list.findIndex(f => f.url === s.url);
    if (i >= 0) list.splice(i, 1); else list.unshift(s);
    store.set('favs', list.slice(0, 60));
  }
  function remember(s) {
    const list = store.get('recent', []).filter(r => r.url !== s.url);
    list.unshift(s);
    store.set('recent', list.slice(0, 20));
  }
  function renderSaved() {
    fillStations($('favs'), favs(), 'Star a station (☆) to keep it here.');
    fillStations($('recent'), store.get('recent', []), 'Stations you play will be listed here.');
  }
  function fillStations(ul, list, empty) {
    ul.innerHTML = '';
    if (!list.length) { ul.innerHTML = `<li class="empty">${empty}</li>`; return; }
    const current = state && state.station && state.station.url;
    for (const s of list) {
      const li = document.createElement('li');
      li.className = s.url === current ? 'on' : '';
      const img = s.favicon ? Object.assign(document.createElement('img'), {src: s.favicon, alt: '', loading: 'lazy'}) : null;
      if (img) img.onerror = () => img.replaceWith(Object.assign(document.createElement('span'), {className: 'ph'}));
      li.appendChild(img || Object.assign(document.createElement('span'), {className: 'ph'}));
      const meta = document.createElement('span');
      meta.className = 'meta';
      meta.innerHTML = '<b></b><small></small>';
      meta.children[0].textContent = s.name;
      meta.children[1].textContent = [[s.state, s.countrycode || s.country].filter(Boolean).join(', '), (s.tags || '').split(',').slice(0, 3).join(', ')].filter(Boolean).join(' · ');
      li.appendChild(meta);
      const q = document.createElement('span');
      q.className = 'q';
      q.textContent = [s.codec, s.bitrate ? s.bitrate + 'k' : '', s.hls ? 'HLS' : ''].filter(Boolean).join(' ');
      li.appendChild(q);
      const fav = document.createElement('button');
      fav.className = 'fav' + (isFav(s) ? ' on' : '');
      fav.textContent = isFav(s) ? '★' : '☆';
      fav.title = 'Favourite';
      fav.onclick = e => { e.stopPropagation(); toggleFav(s); fav.classList.toggle('on'); fav.textContent = fav.classList.contains('on') ? '★' : '☆'; };
      li.appendChild(fav);
      li.onclick = () => tune(s);
      ul.appendChild(li);
    }
  }
  async function tune(s) {
    closePicker();
    remember(s);
    // the click is the user's go-ahead for sound: make the audio context now
    wantPlay = true;
    Player.stop();
    try {
      const r = await post('/api/tune', s);
      waitingFor = r.session;
    } catch (e) { toast(e.message || "Couldn't tune in to that station.", true); wantPlay = false; }
    render();
  }
  $('link-form').onsubmit = e => {
    e.preventDefault();
    const url = $('link-url').value.trim();
    if (url) tune({url, name: $('link-name').value.trim() || url, uuid: ''});
  };

  // -- go ----------------------------------------------------------------------------------------
  let handsMode = 'loading';
  coachRoll.handsLoaded().then(mode => {
    handsMode = mode;
    if (mode !== '3d') { console.warn('3D hands unavailable; drawing flat hands'); toast('3D hands unavailable; drawing flat hands.', true); }
  }).catch(() => { handsMode = '2d'; }).finally(() => { boot.hands = true; bootCheck(); });

  // -- resume the last station, and keyboard shortcuts -------------------------------------------
  function offerResume() {
    if (state.station || wantPlay) return;
    const last = store.get('recent', [])[0];
    if (!last) return;
    const b = $('overlay-resume');
    b.textContent = `↺ Resume ${last.name}`;
    b.hidden = false;
    b.onclick = () => { b.hidden = true; tune(last); };
  }
  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) && e.target.type !== 'range' && e.target.type !== 'checkbox') return;
    if (!$('picker').hidden) return;
    const k = e.key.toLowerCase();
    const vol = d => { const v = Math.min(1, Math.max(0, Player.volume + d)); Player.setVolume(v); $('volume').value = String(v); toast(`Volume ${Math.round(v * 100)}%`); };
    if (k === ' ' || k === 'k') { e.preventDefault(); if (document.activeElement) document.activeElement.blur(); $('play').click(); }
    else if (k === 's') { e.preventDefault(); openPicker(); }
    else if (k === 'h') $('history-btn').click();
    else if (k >= '1' && k <= '4') setView(VIEWS[Number(k) - 1]);
    else if (k === 'g') setView(view === 'guitar' ? 'piano' : 'guitar');
    else if (k === 'm') { if (Player.volume > 0) { premute = Player.volume; vol(-Player.volume); } else vol(premute || 0.8); }
    else if (k === 'arrowup') { e.preventDefault(); vol(0.05); }
    else if (k === 'arrowdown') { e.preventDefault(); vol(-0.05); }
    else if (k === 'f') { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(() => {}); }
  });
  let premute = 0;
  // ?debug=1: the page reports how it's doing to the app's log (for checking it headless)
  if (new URLSearchParams(location.search).get('debug') === '1') {
    const errors = [];
    window.addEventListener('error', e => errors.push(String(e.message)));
    window.addEventListener('unhandledrejection', e => errors.push(String(e.reason && e.reason.stack || e.reason)));
    setInterval(() => {
      const t = Player.position();
      post('/api/log', {hands: handsMode, running: Player.running, position: t, button: $('play').textContent,
                        shown: shownKey, overlay: $('overlay-text').textContent, errors: errors.splice(0)}).catch(() => {});
    }, 2000);
  }
  connect();
  requestAnimationFrame(frame);
})();
