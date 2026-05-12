import { FluidSimulation } from './fluid.js';
import { MidiInput } from './midi.js';
import { noteCenterX, noteWidth, drawKeyboard, noteAtPoint } from './piano.js';
import { Highway } from './highway.js';
import { ParticleSystem } from './particles.js';
import { Settings } from './settings.js';

// Keyboard occupies the center 2/3 of the viewport
const KB_FRACTION = 2 / 3;
const SIM_DT = 1 / 60;
const MAX_STEPS = 8;
const MAX_DYE_TIGHTNESS_REDUCTION = 0.75;
const MIN_DYE_RADIUS = 0.002;
// Raw URL for the bloom dither texture that lives in the other repo
const DITHER_URL = 'https://raw.githubusercontent.com/nickprocenko/webgl-fluid-simulation/master/LDR_LLL1_0.png';

const fluidCanvas   = document.getElementById('fluid-canvas');
const highwayCanvas = document.getElementById('highway-canvas');
const pianoCanvas   = document.getElementById('piano-canvas');
const hCtx = highwayCanvas.getContext('2d');
const pCtx = pianoCanvas.getContext('2d');

const settings  = new Settings();
const highway   = new Highway();
const particles = new ParticleSystem();
const midi      = new MidiInput();

let fluid          = null;
let lastTime       = performance.now();
let simAccumulator = 0;
let time           = 0;
let noteColorMap   = {};
const pointerToNote  = new Map();
const noteTouchCount = new Map();

// ── Layout helpers ─────────────────────────────────────────────────────────────

function getLayout () {
  const dpr = window.devicePixelRatio || 1;
  const W   = fluidCanvas.width;
  const H   = fluidCanvas.height;
  const kbH = settings.get('keyboardHeight') * dpr;
  const kbW = Math.floor(W * KB_FRACTION);
  const kbX = Math.floor((W - kbW) / 2);  // left edge of the keyboard zone
  return { W, H, kbH, kbW, kbX, dpr };
}

function resize () {
  const dpr = window.devicePixelRatio || 1;
  const vv  = window.visualViewport;
  const W   = window.innerWidth;
  const H   = vv ? vv.height : window.innerHeight;
  for (const c of [fluidCanvas, highwayCanvas, pianoCanvas]) {
    c.width        = Math.floor(W * dpr);
    c.height       = Math.floor(H * dpr);
    c.style.width  = W + 'px';
    c.style.height = H + 'px';
  }
  if (fluid) fluid.resize();
  updateKeyboardPointerEvents();
}

function updateKeyboardPointerEvents () {
  pianoCanvas.style.pointerEvents = settings.get('showKeyboard') ? 'auto' : 'none';
}

window.addEventListener('resize', resize);
if (window.visualViewport) window.visualViewport.addEventListener('resize', resize);

// ── Fluid init ───────────────────────────────────────────────────────────────

function initFluid () {
  try {
    fluid = new FluidSimulation(fluidCanvas, {
      SIM_RESOLUTION:      128,
      DYE_RESOLUTION:      512,
      DENSITY_DISSIPATION: settings.get('densityDissipation'),
      VELOCITY_DISSIPATION:settings.get('velocityDissipation'),
      PRESSURE:            0.8,
      PRESSURE_ITERATIONS: 20,
      CURL:                settings.get('curl'),
      BLOOM:               settings.get('fluidBloom'),
      BLOOM_INTENSITY:     settings.get('fluidBloomIntensity'),
      SUNRAYS:             settings.get('fluidSunrays'),
      SUNRAYS_WEIGHT:      settings.get('fluidSunraysWeight'),
      ditherTextureUrl:    DITHER_URL,
    });
  } catch (e) {
    console.warn('WebGL fluid init failed:', e);
    fluid = null;
  }
}

// ── MIDI ────────────────────────────────────────────────────────────────────

const midiDot = document.getElementById('midi-dot');
midi.onConnect(() => {
  midiDot.classList.add('connected');
  const list = document.getElementById('midi-inputs-list');
  if (list) list.innerHTML = midi.inputs.map(i => `<div>${i.name}</div>`).join('') || 'No MIDI devices found';
});
document.getElementById('midi-btn').addEventListener('click', async () => {
  const ok = await midi.requestAccess();
  if (!ok) alert('Web MIDI not available — use keyboard (A–L keys)');
});

// ── Note events ────────────────────────────────────────────────────────────

function handleNoteOn (note, velocity) {
  const { W, H, kbH, kbW, kbX } = getLayout();
  const base  = H - kbH;
  const color = getNoteColor(note);
  const nw    = noteWidth(note, kbW) * (settings.get('noteWidth') / 16);
  const cx    = noteCenterX(note, kbW) + kbX;
  const x     = cx - nw / 2;
  noteColorMap[note] = color;
  highway.noteOn(note, velocity, x, nw, color,
    settings.get('noteInnerColor'),
    settings.get('noteInnerBlend') / 100);
  particles.noteOn(cx, base, color, nw / 2, getEffectSettings());
}

function handleNoteOff (note) {
  for (const t of highway.activeTrails()) {
    if (t.note === note) {
      const { H, kbH } = getLayout();
      particles.noteOff(t.x + t.width / 2, H - kbH, t.color, t.width / 2, getEffectSettings());
      break;
    }
  }
  highway.noteOff(note);
  delete noteColorMap[note];
}

midi.onNoteOn(handleNoteOn);
midi.onNoteOff(handleNoteOff);

// ── On-screen piano: tap + drag glide ───────────────────────────────────────

function getPointerNote (e) {
  if (!settings.get('showKeyboard')) return null;
  const rect = pianoCanvas.getBoundingClientRect();
  if (!rect.width) return null;
  const { W, kbW, kbX, kbH } = getLayout();
  const scaleX = pianoCanvas.width / rect.width;
  const scaleY = pianoCanvas.height / rect.height;
  const rawX = (e.clientX - rect.left) * scaleX;
  const rawY = (e.clientY - rect.top) * scaleY;
  // Keyboard sits at the bottom of the full-height canvas
  const yInKb = rawY - (pianoCanvas.height - kbH);
  return noteAtPoint(rawX - kbX, yInKb, kbW, kbH);
}

function releasePointerNote (pid) {
  const note = pointerToNote.get(pid);
  if (note == null) return;
  pointerToNote.delete(pid);
  const count = (noteTouchCount.get(note) ?? 1) - 1;
  if (count <= 0) { noteTouchCount.delete(note); handleNoteOff(note); }
  else noteTouchCount.set(note, count);
}

function setPointerNote (pid, note) {
  const prev = pointerToNote.get(pid);
  if (prev === note) return;
  releasePointerNote(pid);
  if (note == null) return;
  pointerToNote.set(pid, note);
  const count = noteTouchCount.get(note) ?? 0;
  if (count === 0) handleNoteOn(note, 100);
  noteTouchCount.set(note, count + 1);
}

function releaseAll () { for (const pid of [...pointerToNote.keys()]) releasePointerNote(pid); }

pianoCanvas.addEventListener('pointerdown', e => {
  const note = getPointerNote(e);
  if (note == null) return;
  try { pianoCanvas.setPointerCapture(e.pointerId); } catch {}
  setPointerNote(e.pointerId, note);
  e.preventDefault();
});
pianoCanvas.addEventListener('pointermove', e => {
  if (!pointerToNote.has(e.pointerId)) return;
  setPointerNote(e.pointerId, getPointerNote(e));
  e.preventDefault();
});
pianoCanvas.addEventListener('pointerup',     e => { releasePointerNote(e.pointerId); e.preventDefault(); });
pianoCanvas.addEventListener('pointercancel', e => { releasePointerNote(e.pointerId); e.preventDefault(); });
window.addEventListener('blur', releaseAll);

// ── Settings panel wiring ───────────────────────────────────────────────────

const panel = document.getElementById('settings-panel');
document.getElementById('settings-btn').addEventListener('click',  () => panel.classList.toggle('open'));
document.getElementById('settings-close').addEventListener('click', () => panel.classList.remove('open'));

// wire(elementId, settingsKey, transformFromSlider, transformToSlider)
function wire (id, key, fromEl, toEl) {
  const el = document.getElementById(id);
  if (!el) return;
  const isCheck = el.type === 'checkbox';
  const stored  = settings.get(key);
  if (isCheck) el.checked = !!stored;
  else         el.value   = toEl ? toEl(stored) : stored;
  const span = document.getElementById(id + '-val');
  if (span) span.textContent = el.value;
  el.addEventListener('input', () => {
    const raw = isCheck ? el.checked : el.value;
    const val = fromEl ? fromEl(raw) : (isCheck ? raw : (+raw || raw));
    settings.set(key, val);
    if (span) span.textContent = el.value;
    onSettingChange(key, val);
  });
}

function onSettingChange (key, val) {
  if (['noteColor','noteColorMode','noteBrightness','noteInnerColor','noteInnerBlend'].includes(key))
    refreshColors();
  if (key === 'keyboardHeight') resize();
  if (key === 'showKeyboard') { if (!val) releaseAll(); updateKeyboardPointerEvents(); }
  if (fluid) {
    if (key === 'densityDissipation')  fluid.updateConfig({ DENSITY_DISSIPATION:  val });
    if (key === 'velocityDissipation') fluid.updateConfig({ VELOCITY_DISSIPATION: val });
    if (key === 'curl')                fluid.updateConfig({ CURL:                 val });
    if (key === 'fluidBloom')          fluid.updateConfig({ BLOOM:                val });
    if (key === 'fluidBloomIntensity') fluid.updateConfig({ BLOOM_INTENSITY:      val });
    if (key === 'fluidSunrays')        fluid.updateConfig({ SUNRAYS:              val });
    if (key === 'fluidSunraysWeight')  fluid.updateConfig({ SUNRAYS_WEIGHT:       val });
  }
}

// Note appearance
wire('note-color',         'noteColor');
wire('note-color-mode',    'noteColorMode');
wire('note-inner-color',   'noteInnerColor');
wire('note-inner-blend',   'noteInnerBlend',   v => +v);
wire('note-brightness',    'noteBrightness',   v => +v);
wire('note-glow',          'noteGlow',         v => +v);
wire('note-inner-opacity', 'noteInnerOpacity', v => +v);
wire('note-head-opacity',  'noteHeadOpacity',  v => +v);
wire('speed',              'speed',            v => +v);
wire('note-width',         'noteWidth',        v => +v);
wire('note-edge-roundness','noteEdgeRoundness',v => +v);
// Particle effects
wire('effect-glow',              'effectGlow');
wire('effect-glow-strength',     'effectGlowStrength',     v => +v);
wire('effect-highlight',         'effectHighlight');
wire('effect-highlight-strength','effectHighlightStrength', v => +v);
wire('effect-sparks',            'effectSparks');
wire('effect-sparks-amount',     'effectSparksAmount',     v => +v);
wire('effect-smoke',             'effectSmoke');
wire('effect-smoke-amount',      'effectSmokeAmount',      v => +v);
wire('effect-press-mist',        'effectPressMist');
wire('effect-press-mist-amount', 'effectPressMistAmount',  v => +v);
wire('effect-moon-dust',         'effectMoonDust');
wire('effect-steam',             'effectSteam');
wire('effect-halo-pulse',        'effectHaloPulse');
// Fluid
wire('fluid-enabled',       'fluidEnabled');
wire('fluid-intensity',     'fluidIntensity',    v => +v);
wire('fluid-color',         'fluidColor');
wire('fluid-color-mode',    'fluidColorMode');
wire('fluid-source',        'fluidSource');
wire('fluid-repulsion',     'fluidRepulsion',    v => +v);
wire('fluid-radius',        'fluidRadius',       v => +v / 10, v => Math.round(v * 10));
wire('fluid-tightness',     'fluidTightness',    v => +v);
wire('fluid-speed',         'fluidSpeed',        v => +v);
wire('fluid-bloom',         'fluidBloom');
wire('fluid-bloom-intensity','fluidBloomIntensity',v => +v / 100, v => Math.round(v * 100));
wire('fluid-sunrays',       'fluidSunrays');
wire('fluid-sunrays-weight','fluidSunraysWeight',v => +v / 100, v => Math.round(v * 100));
wire('density-dissipation', 'densityDissipation',v => +v / 10, v => Math.round(v * 10));
wire('velocity-dissipation','velocityDissipation',v => +v / 10, v => Math.round(v * 10));
wire('curl',                'curl',              v => +v);
// Keyboard
wire('show-keyboard',  'showKeyboard');
wire('keyboard-height','keyboardHeight', v => +v);

// Presets
const presetNameEl = document.getElementById('preset-name');
const presetListEl = document.getElementById('preset-list');

function renderPresets () {
  presetListEl.innerHTML = settings.getPresets().map(p => `
    <div class="preset-item">
      <span class="preset-name-label">${p.name}</span>
      <button class="preset-load" data-name="${p.name}">Load</button>
      <button class="preset-del"  data-name="${p.name}">✕</button>
    </div>`).join('');
}

document.getElementById('preset-save').addEventListener('click', () => {
  const name = presetNameEl.value.trim();
  if (name) { settings.savePreset(name); renderPresets(); }
});

presetListEl.addEventListener('click', e => {
  const name = e.target.dataset.name;
  if (!name) return;
  if (e.target.classList.contains('preset-load')) {
    if (settings.loadPreset(name)) location.reload();
  } else if (e.target.classList.contains('preset-del')) {
    settings.deletePreset(name);
    renderPresets();
  }
});

document.getElementById('export-btn').addEventListener('click', () => {
  const json = JSON.stringify({ note_style: settings.buildDesktopPatch() }, null, 2);
  const btn  = document.getElementById('export-btn');
  navigator.clipboard.writeText(json)
    .then(() => { btn.textContent = 'Copied!'; setTimeout(() => { btn.textContent = 'Copy Desktop Config'; }, 1500); })
    .catch(() => prompt('Copy this:', json));
});

renderPresets();

// ── Main loop ───────────────────────────────────────────────────────────────

function frame (now) {
  requestAnimationFrame(frame);
  const dt = Math.min((now - lastTime) / 1000, 0.05);
  lastTime = now;
  time    += dt;

  const { W, H, kbH, kbW, kbX, dpr } = getLayout();
  const base    = H - kbH;
  const fluidOn = settings.get('fluidEnabled');
  const intensity = settings.get('fluidIntensity') / 100;

  // ─ Fluid sim ─
  if (fluid && fluidOn) {
    const fluidRadius = settings.get('fluidRadius');
    const tightness   = settings.get('fluidTightness') / 100;
    const dyeScale    = 1 - tightness * MAX_DYE_TIGHTNESS_REDUCTION;
    const fluidMode   = settings.get('fluidColorMode');
    const source      = settings.get('fluidSource');
    const repulsion   = settings.get('fluidRepulsion') / 100;
    const velY        = -intensity * 0.002;

    simAccumulator += dt * (settings.get('fluidSpeed') / 10);
    let steps = 0;
    while (simAccumulator >= SIM_DT && steps < MAX_STEPS) {
      for (const t of highway.activeTrails()) {
        const normX  = (t.x + t.width / 2) / W;
        const velRad = Math.max(0.005, (t.width / W) * fluidRadius);
        const dyeRad = Math.max(MIN_DYE_RADIUS, velRad * dyeScale);
        const [r, g, b] = getFluidColor(t.note, fluidMode);
        const s = intensity * SIM_DT;
        if (source === 'head' || source === 'both')
          fluid.addSplat(normX, (base - t.topY) / H, 0, velY, r*s, g*s, b*s, velRad, dyeRad);
        if (source === 'base' || source === 'both')
          fluid.addSplat(normX, base / H,             0, velY, r*s, g*s, b*s, velRad, dyeRad);
        // Trail repulsion: outward velocity splats at the trail edges
        if (repulsion > 0) {
          const hW   = t.width / 2 / W;
          const mg   = hW * 0.8;
          const push = repulsion * 0.0015;
          const midY = (base - t.topY * 0.5) / H;
          fluid.addSplat(normX - hW - mg, midY, -push, 0, 0, 0, 0, 0.018, 0.001);
          fluid.addSplat(normX + hW + mg, midY,  push, 0, 0, 0, 0, 0.018, 0.001);
        }
      }
      fluid.step(SIM_DT);
      simAccumulator -= SIM_DT;
      steps++;
    }
    fluid.render();
  } else if (fluid) {
    const gl = fluid.gl;
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  // ─ Moon dust (spawned here so we have canvas coordinates) ─
  const fx = getEffectSettings();
  if (fx.effectMoonDust) {
    for (const t of highway.activeTrails()) {
      if (t.topY > 0 && Math.random() < dt * 10)
        particles.spawnMoonDust(t.x + t.width / 2, base - Math.random() * t.topY, t.color);
    }
  }

  particles.update(dt);

  // ─ Highway + particles ─
  highway.update(dt, settings.get('speed') * dpr, H, kbH);
  hCtx.clearRect(0, 0, W, H);
  highway.draw(hCtx, H, kbH, getAppearance(), time);
  particles.draw(hCtx, fx);

  // ─ Keyboard ─
  if (settings.get('showKeyboard')) {
    pCtx.clearRect(0, 0, pianoCanvas.width, pianoCanvas.height);
    const activeSet = new Set([...highway.activeTrails()].map(t => t.note));
    pCtx.save();
    pCtx.translate(kbX, 0);
    drawKeyboard(pCtx, activeSet, kbH, noteColorMap, kbW);
    pCtx.restore();
  } else {
    pCtx.clearRect(0, 0, pianoCanvas.width, pianoCanvas.height);
  }
}

// ── Colour helpers ───────────────────────────────────────────────────────────

function hexToRgb (hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16 & 0xff) / 255, (n >> 8 & 0xff) / 255, (n & 0xff) / 255];
}

function rgbToHex (r, g, b) {
  const clamp = v => Math.max(0, Math.min(255, Math.round(v * 255)));
  return '#' + [clamp(r), clamp(g), clamp(b)].map(v => v.toString(16).padStart(2, '0')).join('');
}

function getNoteColor (note) {
  const bri = settings.get('noteBrightness') / 100;
  const [r, g, b] = getModeRgb(note, settings.get('noteColorMode'), 'noteColor');
  return rgbToHex(r * bri, g * bri, b * bri);
}

function getFluidColor (note, mode) {
  if (mode === 'perNote') return noteToRainbow(note);
  return hexToRgb(settings.get('fluidColor'));
}

function getModeRgb (note, mode, solidKey) {
  if (mode === 'rainbow') return noteToRainbow(note);
  const t = (note % 12) / 12;
  if (mode === 'fire')   return gradRgb(t, [[1,.25,.05],[1,.58,.08],[1,.92,.28]]);
  if (mode === 'water')  return gradRgb(t, [[.05,.35,.95],[.06,.75,1],[.45,.95,1]]);
  if (mode === 'sunset') return gradRgb(t, [[.98,.26,.46],[1,.45,.2],[.98,.82,.3]]);
  if (mode === 'neon')   return gradRgb(t, [[.2,1,.75],[.45,.72,1],[1,.28,.92]]);
  return hexToRgb(settings.get(solidKey));
}

function noteToRainbow (note) { return hslToRgb((note % 12) / 12, 0.95, 0.62); }

function gradRgb (t, stops) {
  t = Math.max(0, Math.min(1, t));
  const seg = 1 / (stops.length - 1);
  const i   = Math.min(stops.length - 2, Math.floor(t / seg));
  const lt  = (t - i * seg) / seg;
  const a   = stops[i], b = stops[i + 1];
  return [a[0]+(b[0]-a[0])*lt, a[1]+(b[1]-a[1])*lt, a[2]+(b[2]-a[2])*lt];
}

function hslToRgb (h, s, l) {
  const q = l < 0.5 ? l*(1+s) : l+s-l*s, p = 2*l-q;
  return [hue(p,q,h+1/3), hue(p,q,h), hue(p,q,h-1/3)];
}

function hue (p, q, t) {
  if (t<0) t+=1; if (t>1) t-=1;
  if (t<1/6) return p+(q-p)*6*t;
  if (t<1/2) return q;
  if (t<2/3) return p+(q-p)*(2/3-t)*6;
  return p;
}

function refreshColors () {
  highway.recolor(getNoteColor);
  noteColorMap = {};
  for (const t of highway.activeTrails()) noteColorMap[t.note] = t.color;
}

// ── Appearance ──────────────────────────────────────────────────────────────

function getAppearance () {
  return {
    effectGlow:              settings.get('effectGlow'),
    effectGlowStrength:      settings.get('effectGlowStrength'),
    effectHighlight:         settings.get('effectHighlight'),
    effectHighlightStrength: settings.get('effectHighlightStrength'),
    effectHaloPulse:         settings.get('effectHaloPulse'),
    edgeRoundness:           settings.get('noteEdgeRoundness'),
    innerOpacity:            settings.get('noteInnerOpacity') / 100,
    headOpacity:             settings.get('noteHeadOpacity')  / 100,
  };
}

function getEffectSettings () {
  return {
    effectSparks:       settings.get('effectSparks'),
    effectSparksAmount: settings.get('effectSparksAmount'),
    effectSmoke:        settings.get('effectSmoke'),
    effectSmokeAmount:  settings.get('effectSmokeAmount'),
    effectPressMist:    settings.get('effectPressMist'),
    effectPressMistAmount: settings.get('effectPressMistAmount'),
    effectMoonDust:     settings.get('effectMoonDust'),
    effectSteam:        settings.get('effectSteam'),
  };
}

// ── Boot ────────────────────────────────────────────────────────────────────

resize();
initFluid();
requestAnimationFrame(frame);
midi.requestAccess().catch(() => {});
