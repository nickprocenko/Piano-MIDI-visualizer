// Preferences beside File (Ctrl+,): the connections, the microphone and speakers, the Maestro's
// voice, how the sheet is drawn, the song folders and the keyboard shortcuts. Most controls
// mirror ones in the page's own menus (Playing, Parts, Sheet, Maestro), so a change here is
// remembered and acted on exactly as if it had been made there. Loaded after file.js.
(function () {
  const dlg = $('prefs-dlg');
  const panes = [...dlg.querySelectorAll('section[data-pane]')];
  const tabs = [...dlg.querySelectorAll('#prefs-nav [data-pane]')];
  let pane = store.get('prefsPane', 'connections');

  $('prefs-btn').addEventListener('click', () => openPrefs());
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key === ',') { e.preventDefault(); openPrefs(); }
  });
  dlg.addEventListener('close', () => { stopMeter(); fluteCalibrate(false); $('prefs-btn').setAttribute('aria-expanded', 'false'); });
  tabs.forEach(t => t.addEventListener('click', () => showPane(t.dataset.pane)));
  $('prefs-nav').addEventListener('keydown', e => {
    const i = tabs.indexOf(document.activeElement);
    if (i < 0 || !['ArrowDown', 'ArrowUp'].includes(e.key)) return;
    e.preventDefault();
    const next = tabs[(i + (e.key === 'ArrowDown' ? 1 : tabs.length - 1)) % tabs.length];
    next.focus();
    showPane(next.dataset.pane);
  });

  async function openPrefs(at) {  // at: a section to show, e.g. 'audio'
    if (at) pane = at;
    syncMirrors();
    if (!dlg.open) dlg.showModal();
    $('prefs-btn').setAttribute('aria-expanded', 'true');
    showPane(pane);
    tabs.find(t => t.dataset.pane === pane).focus();
    await loadPorts();
    syncMirrors();
  }
  window.openPreferences = openPrefs;

  function showPane(name) {
    if (!panes.some(p => p.dataset.pane === name)) name = 'connections';
    pane = name;
    store.set('prefsPane', name);
    panes.forEach(p => { p.hidden = p.dataset.pane !== name; });
    tabs.forEach(t => t.setAttribute('aria-selected', t.dataset.pane === name));
    syncMirrors();
    if (name === 'audio') listDevices().then(startMeter, err => { $('pref-mic-msg').textContent = err.message; });
    else stopMeter();
    fluteCalibrate(name === 'audiomidi' && dlg.open);  // flute.js: the microphone's notes, live
    if (name === 'library') showFolders();
  }

  // -- Mirrored controls --------------------------------------------------------------------
  // [copy here, the page's own control]. The copy is refreshed from the original whenever
  // it's shown; a change to the copy is set on the original and its own events fired.

  const mirrors = [
    [$('conn-port'), portSel], [$('conn-out'), outSel],
    [$('pref-style'), $('style')], [$('pref-talk-greet'), $('talk-greet')], [$('pref-talk-passes'), $('talk-passes')],
    [$('pref-talk-signoff'), $('talk-signoff')], [$('pref-voice'), $('voice')], [$('pref-voice-name'), $('voice-name')],
    [$('pref-voice-vol'), $('voice-vol')],
    [$('pref-dynamics'), $('dynamics')], [$('pref-layout'), $('layout')], [$('pref-zoom'), $('zoom')],
  ];

  function syncMirrors() {
    const live = connEl.classList.contains('live');
    $('conn-server').classList.toggle('live', live);
    $('conn-server-text').textContent = live ? 'Coach server: connected' : 'Coach server: ' + connEl.textContent;
    for (const [copy, original] of mirrors) {
      if (original.type === 'checkbox') { copy.checked = original.checked; continue; }
      if (original.tagName === 'SELECT') {
        copy.innerHTML = original.innerHTML;  // options and groups (the voices are grouped)
        if (!original.options.length) copy.add(new Option('none found', ''));
        copy.disabled = !original.options.length;
      }
      copy.value = original.value;
    }
    $('pref-zoom-val').textContent = $('zoom').value + '%';
    $('pref-voice-vol-val').textContent = $('voice-vol').value + '%';
    $('pref-voice-row').hidden = $('voice-wrap').style.display === 'none';
    $('pref-show').value = document.body.dataset.show || 'sheet';
  }
  for (const [copy, original] of mirrors) {
    for (const type of ['input', 'change']) {
      copy.addEventListener(type, () => {
        if (original.type === 'checkbox') original.checked = copy.checked; else original.value = copy.value;
        original.dispatchEvent(new Event(type));
        if (type === 'input') syncMirrors();  // the % beside a slider
      });
    }
  }
  $('pref-show').addEventListener('change', e => setView(e.target.value));
  $('pref-voice-test').addEventListener('click', () => speak('This is my voice.', true, true));
  new MutationObserver(() => { if (dlg.open) syncMirrors(); }).observe(connEl, {childList: true, attributes: true});

  $('conn-refresh').addEventListener('click', async () => {
    $('conn-refresh').disabled = true;
    await loadPorts();
    syncMirrors();
    $('conn-refresh').disabled = false;
  });

  // -- Microphone and speakers --------------------------------------------------------------
  // One microphone for everything that listens: talking to the Maestro, singing and spoken
  // answers in lessons, the flute. The speakers carry the page's own sounds. Windows only
  // tells a page the devices' names once it has been allowed to use the microphone.

  const micPick = $('pref-mic'), spkPick = $('pref-speaker');
  let known = null;  // microphone ids seen so far, to notice one being plugged in

  async function devices() {
    if (!navigator.mediaDevices?.enumerateDevices) return {mics: [], speakers: [], named: false};
    const all = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.deviceId !== 'communications');
    const mics = all.filter(d => d.kind === 'audioinput'), speakers = all.filter(d => d.kind === 'audiooutput');
    return {mics, speakers, named: mics.some(d => d.label)};
  }

  function fill(sel, list, saved, fallback) {
    sel.innerHTML = '';
    if (!list.some(d => d.deviceId === 'default')) sel.add(new Option(fallback, ''));
    for (const d of list) sel.add(new Option(d.label || fallback, d.deviceId));
    const ids = [...sel.options].map(o => o.value);
    sel.value = ids.includes(saved) ? saved : ids.includes('default') ? 'default' : '';
  }

  async function listDevices() {
    const {mics, speakers, named} = await devices();
    $('pref-mic-allow').hidden = named || !mics.length;
    micPick.disabled = !named;
    spkPick.disabled = !named || !('setSinkId' in HTMLMediaElement.prototype);
    if (!named) {
      micPick.innerHTML = spkPick.innerHTML = '';
      micPick.add(new Option(mics.length ? 'Allow the microphone to see the list' : 'No microphone found', ''));
      spkPick.add(new Option('Windows default', ''));
      micNote();
      return;
    }
    fill(micPick, mics, store.get('mic', ''), 'Windows default');
    fill(spkPick, speakers, store.get('speaker', ''), 'Windows default');
    micNote();
  }

  function micNote() {
    const label = micPick.selectedOptions[0]?.text || '';
    $('pref-mic-note').textContent = /juno/i.test(label)
      ? 'This is the JUNO-DS audio input: it carries the keyboard’s sound, not your voice. Pick a headset or USB microphone.'
      : '';
  }

  $('pref-mic-allow').addEventListener('click', async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({audio: true});
      s.getTracks().forEach(t => t.stop());
      $('pref-mic-msg').textContent = '';
    } catch (err) { $('pref-mic-msg').textContent = 'The microphone was not allowed: ' + err.message; }
    await listDevices();
    startMeter();
    loadMics().catch(() => {});  // the Talk button's list gets the names too
  });

  micPick.addEventListener('change', () => {
    store.set('mic', micPick.value);
    micNote();
    loadMics().catch(() => {});
    window.dispatchEvent(new CustomEvent('coach:mic'));  // the flute listens on the new one
    startMeter();
  });
  spkPick.addEventListener('change', () => { setSpeaker(spkPick.value); testTone(); });
  $('pref-speaker-test').addEventListener('click', testTone);

  function testTone() {
    const ctx = new AudioContext();
    routeAudio(ctx).then(() => {
      let t = ctx.currentTime + 0.05;
      for (const hz of [523.25, 659.25, 783.99]) {
        const osc = ctx.createOscillator(), g = ctx.createGain();
        osc.type = 'triangle';
        osc.frequency.value = hz;
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
        osc.connect(g).connect(ctx.destination);
        osc.start(t);
        osc.stop(t + 0.4);
        t += 0.18;
      }
      setTimeout(() => ctx.close(), 1200);
    });
  }

  // A level meter while Audio is showing, so you can see the chosen microphone hears you.
  let meter = null;
  async function startMeter() {
    stopMeter();
    if (!dlg.open || pane !== 'audio' || micPick.disabled) return;
    const want = micPick.value;
    const m = meter = {};
    try {
      m.stream = await navigator.mediaDevices.getUserMedia({audio: want ? {deviceId: {exact: want}} : true});
    } catch (err) {
      $('pref-mic-msg').textContent = 'Can’t open this microphone: ' + err.message;
      return;
    }
    if (meter !== m) return m.stream.getTracks().forEach(t => t.stop());  // closed or changed meanwhile
    $('pref-mic-msg').textContent = '';
    m.ctx = new AudioContext();
    const analyser = m.ctx.createAnalyser();
    analyser.fftSize = 512;
    m.ctx.createMediaStreamSource(m.stream).connect(analyser);
    const data = new Uint8Array(analyser.fftSize), bar = $('pref-level').firstChild;
    m.timer = setInterval(() => {
      analyser.getByteTimeDomainData(data);
      let peak = 0;
      for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
      bar.style.width = Math.min(100, peak / 0.6) + '%';
    }, 60);
  }

  function stopMeter() {
    const m = meter;
    meter = null;
    $('pref-level').firstChild.style.width = '0';
    if (!m) return;
    clearInterval(m.timer);
    m.stream?.getTracks().forEach(t => t.stop());
    m.ctx?.close();
  }

  // Plugging a microphone in (or out) updates the lists at once, and says so.
  async function noticeDevices() {
    const {mics, named} = await devices();
    const added = known ? mics.filter(d => !known.has(d.deviceId) && d.deviceId !== 'default') : [];
    known = named ? new Set(mics.map(d => d.deviceId)) : null;  // unnamed ids are blank, so nothing to compare
    if (added.length) {
      statusEl.textContent = `New microphone: ${added[0].label}. Choose it in Preferences → Audio.`;
      $('pref-mic-msg').textContent = `Plugged in: ${added[0].label}`;
    }
    loadMics().catch(() => {});
    if (dlg.open && pane === 'audio') { await listDevices(); if (!meter) startMeter(); }
  }
  navigator.mediaDevices?.addEventListener?.('devicechange', noticeDevices);
  noticeDevices().catch(() => {});

  // -- Library --------------------------------------------------------------------------------

  async function showFolders() {
    try {
      const {folders} = await cmd('song_sources');
      $('pref-folders').textContent = folders.length
        ? folders.map(f => f.path + (f.found ? '' : ' (not found)')).join('\n')
        : 'No folders chosen yet.';
    } catch (err) { $('pref-folders').textContent = err.message; }
  }
  $('pref-folders-btn').addEventListener('click', async () => {
    await openSongFolders();
    $('folders-dlg').addEventListener('close', showFolders, {once: true});
  });
})();
