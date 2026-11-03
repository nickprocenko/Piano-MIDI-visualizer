// Main menu (who is practicing) and the top dash bar. Loaded after atlas.js, which owns the Atlas view.
(function () {
  const menuEl = $('mainmenu');
  const SEEN = 'coach.menu-seen';  // per browser tab, so a reload goes straight back to practice
  let view = {active: 'default', profiles: [], busy: false};
  let editing = false;

  const initial = p => (p.name.trim()[0] || '?').toUpperCase();
  const INSTRUMENTS = [{id: 'piano', name: 'Piano', glyph: '🎹'}, {id: 'flute', name: 'Flute', glyph: '🎶'}];
  const instName = id => (INSTRUMENTS.find(i => i.id === id) || INSTRUMENTS[0]).name;

  function renderChip() {
    const p = view.profiles.find(x => x.id === view.active) || {name: 'Profile'};
    $('chip-name').textContent = p.name;
    $('chip-avatar').textContent = initial(p);
    document.body.dataset.instrument = p.instrument || 'piano';  // flute: the microphone, and the flute Roadmap
    document.body.dataset.young = p.young ? '1' : '';  // a child: steps read aloud, in big print
    $('home-atlas').textContent = 'Open the Roadmap';
    renderInstruments(p);
  }

  // Home's instrument switcher: the ones this profile learns, then "+ <name>" for the rest.
  function renderInstruments(p) {
    const box = $('home-inst');
    if (!p.id) { box.innerHTML = ''; return; }
    const learnt = p.instruments || [p.instrument || 'piano'];
    box.innerHTML = '';
    for (const inst of INSTRUMENTS) {
      const b = document.createElement('button');
      const has = learnt.includes(inst.id), current = inst.id === (p.instrument || 'piano');
      b.dataset.instrument = inst.id;
      b.setAttribute('aria-pressed', current ? 'true' : 'false');
      if (!has) b.className = 'new';
      b.innerHTML = `<span aria-hidden="true">${has ? inst.glyph : '+'}</span>${esc(has ? inst.name : 'Learn ' + inst.name.toLowerCase())}`;
      b.title = current ? `You're learning ${inst.name.toLowerCase()} now`
              : has ? `Switch to ${inst.name.toLowerCase()}: its own Roadmap, input and Maestro`
              : `Start learning ${inst.name.toLowerCase()} too. It gets its own Roadmap; your ${instName(p.instrument).toLowerCase()} progress stays.`;
      box.appendChild(b);
    }
  }

  $('home-inst').addEventListener('click', e => {
    const b = e.target.closest('button[data-instrument]');
    const p = view.profiles.find(x => x.id === view.active);
    if (!b || !p || b.dataset.instrument === p.instrument) return;
    const to = b.dataset.instrument;
    if (!(p.instruments || []).includes(to) &&
        !confirm(`Start learning ${instName(to).toLowerCase()} on "${p.name}"? It gets its own Roadmap ${to === 'flute' ? '(the microphone hears you play)' : '(the keyboard over MIDI)'}; your ${instName(p.instrument).toLowerCase()} progress stays.`)) return;
    change('profile_instrument', {id: p.id, instrument: to});
  });

  function renderMenu() {
    const list = $('mm-list');
    list.innerHTML = '';
    for (const p of view.profiles) {
      const card = document.createElement('button');
      card.className = 'mm-card' + (p.id === view.active ? ' current' : '');
      card.dataset.id = p.id;
      card.innerHTML = `<span class="avatar">${esc(initial(p))}</span><span class="mm-name">${esc(p.name)}</span>` +
                       `<span class="mm-inst">${(p.instruments || [p.instrument]).map(instName).join(' · ')}${p.young ? ' · young learner' : ''}</span>`;
      const tools = document.createElement('span');
      tools.className = 'mm-tools';
      tools.innerHTML = '<span data-do="rename" title="Rename">✎</span>' +
                        `<span data-do="young" title="${p.young ? 'Not a young learner any more' : 'Young learner: simple words, steps read aloud, starts at First steps'}">☺</span>` +
                        (p.id === 'default' ? '' : '<span data-do="delete" title="Remove (its data stays on disk)">✕</span>');
      card.appendChild(tools);
      list.appendChild(card);
    }
    menuEl.classList.toggle('editing', editing);
    $('mm-edit').textContent = editing ? 'Done' : 'Edit';
    renderChip();
  }

  function message(text) { $('mm-msg').textContent = text || ''; }

  async function load() {
    try { view = await cmd('profiles'); } catch (err) { message(err.message); }
    renderMenu();
  }

  function enter() {
    try { sessionStorage.setItem(SEEN, '1'); } catch (e) {}
    menuEl.hidden = true;
  }

  async function change(name, body) {
    message('');
    try {
      view = await cmd(name, body);
    } catch (err) {
      message(err.message);
      if (menuEl.hidden) alert(err.message);  // from Home's instrument switcher
      return false;
    }
    try { sessionStorage.setItem(SEEN, '1'); } catch (e) {}
    location.reload();  // everything on the page belongs to the profile: start it fresh
    return true;
  }

  function open() {
    editing = false;
    message('');
    menuEl.hidden = false;
    load();
    const current = menuEl.querySelector('.mm-card.current');
    if (current) current.focus();
  }

  $('mm-list').addEventListener('click', async e => {
    const card = e.target.closest('.mm-card');
    if (!card) return;
    const id = card.dataset.id;
    const act = e.target.dataset && e.target.dataset.do;
    const p = view.profiles.find(x => x.id === id);
    if (act === 'rename') {
      const name = prompt('Rename profile', p.name);
      if (name === null) return;
      try { view = await cmd('profile_rename', {id, name}); message(''); } catch (err) { message(err.message); }
      renderMenu();
    } else if (act === 'young') {
      const on = !p.young;
      if (confirm(on ? `Make "${p.name}" a young learner's profile? The Maestro will use simple words, lesson steps are read aloud in big print, and a piano profile with no goal starts at First steps.`
                     : `"${p.name}" is no longer a young learner: the usual Maestro and step panel.`)) {
        change('profile_young', {id, young: on});
      }
    } else if (act === 'delete') {
      if (confirm(`Remove the profile "${p.name}"? Its files stay in your MidiCoach folder, but it won't be listed.`)) change('profile_delete', {id});
    } else if (editing) {
      return;
    } else if (id === view.active) {
      enter();
    } else {
      change('profile_select', {id});
    }
  });

  $('mm-new').addEventListener('submit', e => {
    e.preventDefault();
    const name = $('mm-name').value.trim();
    if (name) change('profile_new', {name, instrument: $('mm-instrument').value, young: $('mm-young').checked});
  });
  $('mm-edit').addEventListener('click', () => { editing = !editing; renderMenu(); });
  $('mm-continue').addEventListener('click', enter);
  $('dash-brand').addEventListener('click', () => go('home'));
  $('profile-chip').addEventListener('click', open);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !menuEl.hidden) enter(); });

  // -- the dash bar ----------------------------------------------------------------------

  // The bar has Home, Ask Maestro and the name of the mode you're in: to change modes you go
  // back to Home, and leaving a mode stops whatever it was running.
  const tabs = [...document.querySelectorAll('#dash .dtab')];
  const WHERE = {practice: 'Session', explore: 'Explore', record: 'Record a new idea', progress: 'Roadmap', youtube: 'YouTube'};
  function mark(which) {
    tabs.forEach(t => {
      if (t.dataset.dash === which) t.setAttribute('aria-current', 'page');
      else t.removeAttribute('aria-current');
    });
    $('dash-where').textContent = WHERE[which] || '';
  }
  // The view each place opens in (Explore, Songs and Lessons are the search on the Session's page).
  const VIEW = {home: 'home', practice: 'practice', explore: 'practice', songs: 'practice', lessons: 'practice',
                record: 'record', progress: 'progress', place: 'progress', youtube: 'youtube'};

  // A Session plays the piece; recording is Record's own mode, so a Session opens on its last play mode.
  function sessionMode() {
    if (mode !== 'record') return;
    const last = store.get('mode', 'learn');
    setMode(last === 'record' ? 'learn' : last);
  }

  // Explore is the song and lesson search. Coming from Home or the Atlas you're choosing a new
  // piece, so it fills the page; from a Session it opens beside the sheet, so you can look for the
  // next piece while this one stays on the stand. ⇤ / ⤢ switch between the two.
  function explore() {
    const full = document.body.dataset.view !== 'practice';
    atlasShow(false);
    document.body.dataset.view = 'practice';
    sessionMode();
    showLibrary(true);
    libraryFull(full);
    mark(full ? 'explore' : 'practice');
    $('lib-search').focus();
  }

  async function go(which) {
    const from = document.body.dataset.view === 'lesson' ? 'progress' : document.body.dataset.view;
    if (running && VIEW[which] && VIEW[which] !== from) cmd('stop').catch(() => {});
    if (which !== 'explore' && which !== 'songs' && which !== 'lessons') libraryFull(false);
    if (which === 'home') {
      atlasShow(false);
      document.body.dataset.view = 'home';
      mark(which);
      window.dispatchEvent(new CustomEvent('coach:viewchange'));  // Today ticks off what you just did
      return;
    }
    if (which === 'practice') {
      atlasShow(false);
      document.body.dataset.view = 'practice';
      showLibrary(false);
      sessionMode();
      mark(which);
      return;
    }
    if (which === 'record') {
      atlasShow(false);
      document.body.dataset.view = 'record';
      showLibrary(false);
      if (vid.ready) vid.player.pauseVideo();  // the Session's video stays set up, out of sight
      setMode('record');
      mark(which);
      $('go').focus();
      return;
    }
    if (which === 'explore') {
      explore();
      return;
    }
    if (which === 'progress' || which === 'place') {  // place: the map with Where to start open
      if (document.body.dataset.view === 'lesson') {  // up from the lesson to the map, as ← Roadmap does
        if (history.state && history.state.lesson) history.back(); else stepBack();
        return;
      }
      document.body.dataset.view = 'progress';
      await atlasShow(true);
      mark('progress');
      (which === 'place' ? atlasPlaceForm : pathShow)();
      return;
    }
    if (which === 'youtube') {
      atlasShow(false);
      document.body.dataset.view = 'youtube';
      mark(which);
      youtubeShow();
      return;
    }
    if (which === 'songs' || which === 'lessons') {
      setTab(which);
      explore();
      return;
    }
  }
  tabs.forEach(t => t.addEventListener('click', () => go(t.dataset.dash)));
  window.addEventListener('coach:navigate', e => go(e.detail.view));
  // A lesson is part of the Atlas: its label stays Roadmap.
  window.addEventListener('coach:viewchange', () => {
    const v = document.body.dataset.view;
    mark(v === 'lesson' ? 'progress' : v === 'practice' && document.body.classList.contains('lib-full') ? 'explore' : v);
  });
  $('pick-piece').addEventListener('click', () => go('explore'));
  $('home-practice').addEventListener('click', () => {
    const title = $('title').textContent.trim();
    go(title && title !== 'no score yet' ? 'practice' : 'explore');
  });
  $('home-explore').addEventListener('click', () => go('explore'));
  $('home-record').addEventListener('click', () => go('record'));
  $('home-progress').addEventListener('click', () => go('progress'));
  $('home-youtube').addEventListener('click', () => go('youtube'));
  $('home-ask').addEventListener('click', () => {
    go('practice');
    if (!$('ask').disabled) $('ask').focus();
  });
  // The bar's Ask Maestro: where the ask box is on screen (a Session, Record, a lesson) it just
  // focuses it, so nothing running stops; elsewhere it opens the Session first, as Home's does.
  $('dash-ask').addEventListener('click', () => {
    if (!$('ask').offsetParent) go('practice');
    if (!$('ask').disabled) $('ask').focus();
  });

  const syncHomePiece = () => {
    const title = $('title').textContent.trim();
    const hasPiece = title && title !== 'no score yet';
    $('home-piece').textContent = hasPiece
      ? `Continue with ${title}`
      : 'Choose a song or lesson to begin.';
    $('home-practice').querySelector('.home-card-action').textContent =
      hasPiece ? 'Open the Session →' : 'Browse songs & lessons →';
  };
  new MutationObserver(syncHomePiece).observe($('title'), {childList: true, characterData: true, subtree: true});
  syncHomePiece();

  mark('home');
  load();
  let seen = false;
  try { seen = sessionStorage.getItem(SEEN) === '1'; } catch (e) {}
  if (seen) menuEl.hidden = true;
})();
