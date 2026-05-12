// Web MIDI API wrapper with QWERTY keyboard fallback

const QWERTY_MAP = {
  'a': 60, 's': 62, 'd': 64, 'f': 65, 'g': 67, 'h': 69, 'j': 71,
  'k': 72, 'l': 74, ';': 76, "'": 77,
  'w': 61, 'e': 63, 't': 66, 'y': 68, 'u': 70, 'o': 73, 'p': 75,
};

export class MidiInput {
  constructor () {
    this._noteOnCallbacks  = [];
    this._noteOffCallbacks = [];
    this._connectedCallbacks = [];
    this._midiAccess = null;
    this._activeInput = null;
    this._keyboardDown = new Set();
    this._setupKeyboard();
  }

  get connected () { return this._midiAccess !== null; }
  get inputs () {
    if (!this._midiAccess) return [];
    return [...this._midiAccess.inputs.values()];
  }

  async requestAccess () {
    if (!navigator.requestMIDIAccess) return false;
    try {
      this._midiAccess = await navigator.requestMIDIAccess({ sysex: false });
      this._midiAccess.onstatechange = () => this._onStateChange();
      this._connectAll();
      this._connectedCallbacks.forEach(fn => fn(true));
      return true;
    } catch {
      return false;
    }
  }

  selectInput (id) {
    if (!this._midiAccess) return;
    this._disconnectAll();
    if (id === null) { this._activeInput = null; return; }
    const input = this._midiAccess.inputs.get(id);
    if (!input) return;
    this._activeInput = input;
    input.onmidimessage = e => this._onMidi(e);
  }

  onNoteOn  (fn) { this._noteOnCallbacks.push(fn); }
  onNoteOff (fn) { this._noteOffCallbacks.push(fn); }
  onConnect (fn) { this._connectedCallbacks.push(fn); }

  _onMidi (e) {
    const [status, note, velocity] = e.data;
    const cmd = status & 0xf0;
    if (cmd === 0x90 && velocity > 0) {
      this._noteOnCallbacks.forEach(fn => fn(note, velocity));
    } else if (cmd === 0x80 || (cmd === 0x90 && velocity === 0)) {
      this._noteOffCallbacks.forEach(fn => fn(note));
    }
  }

  _connectAll () {
    if (!this._midiAccess) return;
    for (const input of this._midiAccess.inputs.values()) {
      input.onmidimessage = e => this._onMidi(e);
    }
  }

  _disconnectAll () {
    if (!this._midiAccess) return;
    for (const input of this._midiAccess.inputs.values()) {
      input.onmidimessage = null;
    }
    this._activeInput = null;
  }

  _onStateChange () {
    this._connectAll();
    this._connectedCallbacks.forEach(fn => fn(true));
  }

  _setupKeyboard () {
    window.addEventListener('keydown', e => {
      if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
      if (document.activeElement && document.activeElement.tagName === 'INPUT') return;
      const note = QWERTY_MAP[e.key.toLowerCase()];
      if (note == null || this._keyboardDown.has(note)) return;
      this._keyboardDown.add(note);
      this._noteOnCallbacks.forEach(fn => fn(note, 80));
    });
    window.addEventListener('keyup', e => {
      const note = QWERTY_MAP[e.key.toLowerCase()];
      if (note == null) return;
      this._keyboardDown.delete(note);
      this._noteOffCallbacks.forEach(fn => fn(note));
    });
  }
}
