'use strict';

// ─── Configuration (injected by the server or set manually) ──────────────────
const CONFIG = window.__CONFIG__ || {
  theme: 'default',
  noteSpeed: 4,
  wsUrl: `ws://${location.host}`,
};

// ─── Theme colour maps ────────────────────────────────────────────────────────
const THEMES = {
  default: { background: '#111111', noteColor: '#4fc3f7', pianoWhite: '#ffffff', pianoBlack: '#222222' },
  neon:    { background: '#0a0a0a', noteColor: '#39ff14', pianoWhite: '#e0e0e0', pianoBlack: '#111111' },
  minimal: { background: '#fafafa', noteColor: '#1565c0', pianoWhite: '#ffffff', pianoBlack: '#212121' },
};

// ─── Constants ────────────────────────────────────────────────────────────────
const MIDI_NOTE_COUNT = 88;   // standard piano range (A0 – C8)
const MIDI_NOTE_OFFSET = 21;  // MIDI number of A0
const BLACK_KEY_PATTERN = [false, true, false, true, false, false, true, false, true, false, true, false];

// ─── State ────────────────────────────────────────────────────────────────────
const activeNotes = new Map();  // midiNote -> { startY }
const fallingNotes = [];        // { midiNote, x, y, width, height, color }

// ─── Canvas setup ─────────────────────────────────────────────────────────────
const canvas = document.getElementById('visualizer');
const ctx = canvas.getContext('2d');

// Cached key layout – rebuilt whenever the canvas is resized.
let keyLayout = [];
let keyMap = new Map();  // midiNote -> key layout object

function buildKeyLayout() {
  keyLayout = getKeyLayout();
  keyMap = new Map(keyLayout.map(k => [k.midiNote, k]));
}

function resize() {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  buildKeyLayout();
}
window.addEventListener('resize', resize);
resize();

// ─── Layout helpers ───────────────────────────────────────────────────────────
function getKeyLayout() {
  const whiteKeyCount = Array.from({ length: MIDI_NOTE_COUNT }, (_, i) => {
    const noteIndex = (i + MIDI_NOTE_OFFSET) % 12;
    return !BLACK_KEY_PATTERN[noteIndex];
  }).filter(Boolean).length;

  const whiteKeyWidth = canvas.width / whiteKeyCount;
  const pianoHeight = canvas.height * 0.15;

  let whiteIndex = 0;
  return Array.from({ length: MIDI_NOTE_COUNT }, (_, i) => {
    const midiNote = i + MIDI_NOTE_OFFSET;
    const noteIndex = midiNote % 12;
    const isBlack = BLACK_KEY_PATTERN[noteIndex];

    if (isBlack) {
      const x = whiteIndex * whiteKeyWidth - whiteKeyWidth * 0.3;
      return { midiNote, isBlack, x, width: whiteKeyWidth * 0.6, pianoHeight };
    } else {
      const x = whiteIndex * whiteKeyWidth;
      whiteIndex++;
      return { midiNote, isBlack, x, width: whiteKeyWidth, pianoHeight };
    }
  });
}

// ─── Draw ─────────────────────────────────────────────────────────────────────
function draw() {
  const theme = THEMES[CONFIG.theme] || THEMES.default;
  const pianoHeight = canvas.height * 0.15;
  const rollHeight = canvas.height - pianoHeight;

  // Background
  ctx.fillStyle = theme.background;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Advance and draw falling notes
  for (const note of fallingNotes) {
    note.y += CONFIG.noteSpeed;
  }
  // Remove notes that have scrolled off screen
  while (fallingNotes.length && fallingNotes[0].y > rollHeight) {
    fallingNotes.shift();
  }
  for (const note of fallingNotes) {
    ctx.fillStyle = note.color;
    ctx.fillRect(note.x, note.y, note.width - 2, note.height);
  }

  // Active (held) notes – grow downward from the top of the piano
  for (const [midiNote] of activeNotes) {
    const key = keyMap.get(midiNote);
    if (!key) continue;
    ctx.fillStyle = theme.noteColor;
    ctx.fillRect(key.x + 1, 0, key.width - 2, rollHeight);
  }

  // Piano keys
  for (const key of keyLayout) {
    if (!key.isBlack) {
      ctx.fillStyle = activeNotes.has(key.midiNote) ? theme.noteColor : theme.pianoWhite;
      ctx.fillRect(key.x, rollHeight, key.width - 1, pianoHeight);
      ctx.strokeStyle = '#555';
      ctx.strokeRect(key.x, rollHeight, key.width - 1, pianoHeight);
    }
  }
  for (const key of keyLayout) {
    if (key.isBlack) {
      ctx.fillStyle = activeNotes.has(key.midiNote) ? theme.noteColor : theme.pianoBlack;
      ctx.fillRect(key.x, rollHeight, key.width, pianoHeight * 0.6);
    }
  }

  requestAnimationFrame(draw);
}

// ─── Note events ──────────────────────────────────────────────────────────────
function noteOn(midiNote) {
  const theme = THEMES[CONFIG.theme] || THEMES.default;
  const key = keyMap.get(midiNote);
  if (!key) return;
  activeNotes.set(midiNote, { startY: 0 });
  // Spawn a new falling note block
  fallingNotes.push({
    midiNote,
    x: key.x + 1,
    y: 0,
    width: key.width,
    height: 0,
    color: theme.noteColor,
  });
}

function noteOff(midiNote) {
  activeNotes.delete(midiNote);
}

// ─── WebSocket connection ─────────────────────────────────────────────────────
function connect() {
  const ws = new WebSocket(CONFIG.wsUrl);

  ws.addEventListener('message', (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'noteOn')  noteOn(msg.note);
      if (msg.type === 'noteOff') noteOff(msg.note);
      if (msg.type === 'config')  Object.assign(CONFIG, msg.data);
    } catch (e) {
      console.error('Failed to parse message:', e);
    }
  });

  ws.addEventListener('close', () => {
    console.log('WebSocket closed – reconnecting in 2 sec…');
    setTimeout(connect, 2000);
  });

  ws.addEventListener('error', (e) => {
    console.error('WebSocket error:', e);
  });
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
connect();
requestAnimationFrame(draw);
