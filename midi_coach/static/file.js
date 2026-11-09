// File menu beside Home: open a file from the computer, save a copy of the sheet, download it,
// choose the song folders.
// The song folders dialog lives here too; Preferences (prefs.js) opens it. Loaded after profiles.js.
(function () {
  const btn = $('file-btn'), list = $('file-menu');
  const items = () => [...list.querySelectorAll('button:not(:disabled)')];
  const hasScore = () => { const t = $('title').textContent.trim(); return !!t && t !== 'no score yet'; };
  const navigate = view => window.dispatchEvent(new CustomEvent('coach:navigate', {detail: {view}}));

  function show(open) {
    list.hidden = !open;
    btn.setAttribute('aria-expanded', open);
    if (!open) return;
    list.querySelectorAll('.needs-score').forEach(b => { b.disabled = !hasScore(); });
    items()[0]?.focus();
  }

  btn.addEventListener('click', () => show(list.hidden));
  document.addEventListener('click', e => { if (!list.hidden && !$('file-wrap').contains(e.target)) show(false); });
  window.addEventListener('blur', () => show(false));  // a click on the sheet's iframe
  list.addEventListener('keydown', e => {
    const all = items(), i = all.indexOf(document.activeElement);
    if (e.key === 'Escape') { show(false); btn.focus(); }
    else if (e.key === 'ArrowDown') all[(i + 1) % all.length].focus();
    else if (e.key === 'ArrowUp') all[(i - 1 + all.length) % all.length].focus();
    else return;
    e.preventDefault();
  });
  list.addEventListener('click', e => {
    const item = e.target.closest('[data-file]');
    if (!item || item.disabled) return;
    show(false);
    ACTIONS[item.dataset.file]();
  });
  document.addEventListener('keydown', e => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    const key = e.key.toLowerCase();
    if (key === 'o' && !e.shiftKey) { e.preventDefault(); ACTIONS.open(); }
    else if (key === 's' && e.shiftKey && hasScore()) { e.preventDefault(); ACTIONS['save-as'](); }
  });

  const ACTIONS = {
    open: () => $('file-pick').click(),
    'save-as': openSaveAs,
    download: () => {
      const a = document.createElement('a');
      a.href = 'file';
      a.download = '';
      a.click();
    },
    folders: () => openFolders(),
    profile: () => $('profile-chip').click(),
  };

  // -- Open ------------------------------------------------------------------------------

  $('file-pick').addEventListener('change', async e => {
    const file = e.target.files[0];
    e.target.value = '';  // the same file can be picked again
    if (!file) return;
    statusEl.textContent = `Opening ${file.name}…`;
    try {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(',', 2)[1] || '');
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
      });
      await cmd('open_file', {name: file.name, data});  // the sheet arrives over the event stream
      navigate('practice');
      loadLessons();
    } catch (err) { statusEl.textContent = err.message; }
  });

  // -- Save as ---------------------------------------------------------------------------

  const NEW = '\u0000new';
  const saveDlg = $('save-as-dlg');

  async function openSaveAs() {
    if (!hasScore()) return;
    $('save-as-msg').textContent = '';
    $('save-as-name').value = $('title').textContent.trim();
    let standard = [];
    try { ({standard} = await cmd('lessons')); } catch (e) {}
    const current = lib.items.find(x => x.path === lib.current);
    const cats = [...new Set([...standard, ...lib.categories.filter(c => c !== 'Unsorted'), 'Unsorted'])];
    const sel = $('save-as-cat');
    sel.innerHTML = '';
    cats.forEach(c => sel.add(new Option(c, c)));
    sel.add(new Option('New category…', NEW));
    sel.value = current ? current.category : (standard[0] || 'Unsorted');
    newCategory();
    saveDlg.showModal();
    $('save-as-name').select();
  }

  function newCategory() {
    const on = $('save-as-cat').value === NEW;
    $('save-as-new-wrap').hidden = !on;
    $('save-as-new').required = on;
    if (on) $('save-as-new').focus();
  }
  $('save-as-cat').addEventListener('change', newCategory);

  saveDlg.querySelector('form').addEventListener('submit', async e => {
    if (e.submitter?.value !== 'save') return;
    e.preventDefault();  // stays open if the save fails
    const title = $('save-as-name').value.trim();
    const category = $('save-as-cat').value === NEW ? $('save-as-new').value.trim() : $('save-as-cat').value;
    $('save-as-go').disabled = true;
    try {
      const out = await cmd('save_as', {title, category});
      saveDlg.close();
      await cmd('load', {lesson: out.path}).catch(() => {});  // carry on with the copy, as Save as does (not mid-run)
      loadLessons();
      statusEl.textContent = `Saved “${title}” in ${out.category}.`;
    } catch (err) {
      $('save-as-msg').textContent = err.message;
    } finally {
      $('save-as-go').disabled = false;
    }
  });

  // -- Song folders ----------------------------------------------------------------------
  // The folders the Songs search reads (config.json search_folders, shared with the desktop
  // visualizer). Each change is saved at once; Done just closes.

  const foldersDlg = $('folders-dlg');
  let chosen = [];

  function showFolders(src) {
    chosen = src.folders.map(f => f.path);
    const ul = $('folders-list');
    ul.innerHTML = '';
    for (const f of src.folders) {
      const li = document.createElement('li');
      li.innerHTML = `<span>${esc(f.path)}${f.found ? '' : ' <em>not found</em>'}</span>`;
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.textContent = 'Remove';
      rm.title = 'Stop searching this folder (its files stay where they are)';
      rm.addEventListener('click', () => saveFolders({folders: chosen.filter(p => p !== f.path)}));
      li.appendChild(rm);
      ul.appendChild(li);
    }
    if (!src.folders.length) ul.innerHTML = '<li class="none">No folders chosen yet. Add the folder where you keep MIDI files.</li>';
    $('folders-always').textContent = 'Always searched too: ' + src.always.join(' · ');
    $('folders-online').checked = src.online;
    $('folders-watch').checked = src.watch_downloads;
    $('folders-watch-hint').textContent = `New MIDI or MusicXML files in ${src.downloads_folder} are copied into your library. Files added to the folders above are noticed by themselves.`;
    $('folders-downloads').textContent = `Songs you pick there are saved in ${src.downloads}`;
    lib.online = src.online;
  }

  async function saveFolders(change) {
    $('folders-msg').textContent = '';
    try {
      showFolders(await cmd('set_song_sources', change));
      searchSongs();  // new counts, and the songs in a new folder
      renderLibrary();
      return true;
    } catch (err) {
      $('folders-msg').textContent = err.message;
      return false;
    }
  }

  async function openFolders() {
    $('folders-msg').textContent = '';
    $('folders-path').value = '';
    try { showFolders(await cmd('song_sources')); } catch (err) { $('folders-msg').textContent = err.message; }
    foldersDlg.showModal();
  }
  window.openSongFolders = openFolders;

  async function addFolder() {
    const path = $('folders-path').value.trim();
    if (!path) return $('folders-path').focus();
    if (await saveFolders({folders: [...chosen, path]})) $('folders-path').value = '';
  }
  $('folders-add').addEventListener('click', addFolder);
  $('folders-path').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addFolder(); } });
  $('folders-browse').addEventListener('click', async () => {
    const b = $('folders-browse');
    b.disabled = true;
    $('folders-msg').textContent = '';
    try {
      const {folder} = await cmd('pick_folder');  // Windows' own picker opens (it may be behind this window)
      if (folder) { $('folders-path').value = folder; await addFolder(); }
    } catch (err) { $('folders-msg').textContent = err.message; }
    b.disabled = false;
  });
  $('folders-online').addEventListener('change', e => saveFolders({online: e.target.checked}));
  $('folders-watch').addEventListener('change', e => saveFolders({watch_downloads: e.target.checked}));
  $('folders-rescan').addEventListener('click', async () => {
    const b = $('folders-rescan');
    b.disabled = true;
    $('folders-msg').textContent = '';
    try {
      const {total} = await cmd('rescan');
      $('folders-msg').textContent = `${total.toLocaleString()} songs in your library.`;
      searchSongs();
    } catch (err) { $('folders-msg').textContent = err.message; }
    b.disabled = false;
  });
})();
