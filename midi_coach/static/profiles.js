// Main menu (who is practicing) and the top dash bar. Loaded after atlas.js, which owns the Atlas view.
(function () {
  const menuEl = $('mainmenu');
  const SEEN = 'coach.menu-seen';  // per browser tab, so a reload goes straight back to practice
  let view = {active: 'default', profiles: [], busy: false};
  let editing = false;

  const initial = p => (p.name.trim()[0] || '?').toUpperCase();

  function renderChip() {
    const p = view.profiles.find(x => x.id === view.active) || {name: 'Profile'};
    $('chip-name').textContent = p.name;
    $('chip-avatar').textContent = initial(p);
  }

  function renderMenu() {
    const list = $('mm-list');
    list.innerHTML = '';
    for (const p of view.profiles) {
      const card = document.createElement('button');
      card.className = 'mm-card' + (p.id === view.active ? ' current' : '');
      card.dataset.id = p.id;
      card.innerHTML = `<span class="avatar">${esc(initial(p))}</span><span class="mm-name">${esc(p.name)}</span>`;
      const tools = document.createElement('span');
      tools.className = 'mm-tools';
      tools.innerHTML = '<span data-do="rename" title="Rename">✎</span>' + (p.id === 'default' ? '' : '<span data-do="delete" title="Remove (its data stays on disk)">✕</span>');
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
    } catch (err) { message(err.message); return false; }
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
    if (name) change('profile_new', {name});
  });
  $('mm-edit').addEventListener('click', () => { editing = !editing; renderMenu(); });
  $('mm-continue').addEventListener('click', enter);
  $('dash-brand').addEventListener('click', open);
  $('profile-chip').addEventListener('click', open);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !menuEl.hidden) enter(); });

  // -- the dash bar ----------------------------------------------------------------------

  const tabs = [...document.querySelectorAll('#dash .dtab')];
  function mark(which) { tabs.forEach(t => t.setAttribute('aria-selected', t.dataset.dash === which)); }
  const practiceTab = () => (lib.tab === 'lessons' ? 'lessons' : 'songs');

  async function go(which) {
    if (which === 'songs' || which === 'lessons') {
      atlasShow(false);
      setTab(which);
      showLibrary(true);
      mark(which);
      return;
    }
    await atlasShow(true);
    mark(which);
    if (which === 'path') pathShow();
    if (which === 'level') atlasPlaceForm();
  }
  tabs.forEach(t => t.addEventListener('click', () => go(t.dataset.dash)));

  // Leaving the Atlas by its own button or Esc returns the selection to Songs / Lessons.
  new MutationObserver(() => { if ($('atlas-view').hidden) mark(practiceTab()); else if (!tabs.some(t => t.getAttribute('aria-selected') === 'true' && ['atlas', 'path', 'level'].includes(t.dataset.dash))) mark('atlas'); })
    .observe($('atlas-view'), {attributes: true, attributeFilter: ['hidden']});
  document.querySelectorAll('#library .tabs button').forEach(b => b.addEventListener('click', () => mark(b.dataset.tab)));

  mark(practiceTab());
  load();
  let seen = false;
  try { seen = sessionStorage.getItem(SEEN) === '1'; } catch (e) {}
  if (seen) menuEl.hidden = true;
})();
