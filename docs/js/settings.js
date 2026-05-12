// Persistent settings + preset management + desktop export

const KEY = 'pmv-web-app';
const PRESETS_KEY = 'pmv-web-app-presets';

const DEFAULTS = {
  // Note appearance
  noteColor: '#00e5ff',
  noteColorMode: 'solid',
  noteInnerColor: '#a0f5ff',
  noteInnerBlend: 35,
  noteBrightness: 100,
  noteGlow: 35,
  noteInnerOpacity: 85,
  noteHeadOpacity: 90,
  speed: 420,
  noteWidth: 16,
  noteEdgeRoundness: 6,
  // Particle effects
  effectGlow: true,
  effectGlowStrength: 115,
  effectHighlight: true,
  effectHighlightStrength: 95,
  effectSparks: true,
  effectSparksAmount: 150,
  effectSmoke: true,
  effectSmokeAmount: 140,
  effectPressMist: true,
  effectPressMistAmount: 120,
  effectMoonDust: true,
  effectSteam: true,
  effectHaloPulse: true,
  // Fluid
  fluidEnabled: true,
  fluidIntensity: 95,
  fluidColor: '#4bc0ff',
  fluidColorMode: 'solid',
  fluidSource: 'base',
  fluidRepulsion: 50,
  fluidRadius: 1.2,
  fluidTightness: 65,
  fluidSpeed: 10,
  fluidBloom: true,
  fluidBloomIntensity: 0.8,
  fluidSunrays: true,
  fluidSunraysWeight: 0.85,
  densityDissipation: 2.2,
  velocityDissipation: 0.7,
  curl: 46,
  // UI
  showKeyboard: true,
  keyboardHeight: 80,
};

export class Settings {
  constructor () {
    this._data = { ...DEFAULTS };
    this._load();
  }

  get (key) { return this._data[key]; }

  set (key, value) {
    this._data[key] = value;
    this._save();
  }

  all () { return { ...this._data }; }

  _load () {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) Object.assign(this._data, JSON.parse(raw));
    } catch {}
  }

  _save () {
    try { localStorage.setItem(KEY, JSON.stringify(this._data)); } catch {}
  }

  // ── Presets ──────────────────────────────────────────────────────────────

  getPresets () {
    try { return JSON.parse(localStorage.getItem(PRESETS_KEY) || '[]'); }
    catch { return []; }
  }

  savePreset (name) {
    const presets = this.getPresets();
    const idx = presets.findIndex(p => p.name === name);
    const entry = { name, settings: this.all() };
    if (idx >= 0) presets[idx] = entry;
    else presets.push(entry);
    localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
    return presets;
  }

  loadPreset (name) {
    const p = this.getPresets().find(p => p.name === name);
    if (!p) return false;
    Object.assign(this._data, p.settings);
    this._save();
    return true;
  }

  deletePreset (name) {
    const presets = this.getPresets().filter(p => p.name !== name);
    localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
    return presets;
  }

  // ── Desktop export ────────────────────────────────────────────────────────

  buildDesktopPatch () {
    const d = this._data;
    const hexToRgb = hex => {
      const n = parseInt(hex.slice(1), 16);
      return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
    };
    const [cr, cg, cb] = hexToRgb(d.noteColor);
    const [ir, ig, ib] = hexToRgb(d.noteInnerColor);
    return {
      color_r: cr, color_g: cg, color_b: cb,
      interior_r: ir, interior_g: ig, interior_b: ib,
      inner_blend_percent:          d.noteInnerBlend,
      glow_strength_percent:        Math.round(d.noteGlow * 1.8),
      effect_glow_enabled:          d.effectGlow ? 1 : 0,
      effect_highlight_enabled:     d.effectHighlight ? 1 : 0,
      effect_sparks_enabled:        d.effectSparks ? 1 : 0,
      effect_smoke_enabled:         d.effectSmoke ? 1 : 0,
      effect_press_smoke_enabled:   d.effectPressMist ? 1 : 0,
      effect_moon_dust_enabled:     d.effectMoonDust ? 1 : 0,
      effect_steam_smoke_enabled:   d.effectSteam ? 1 : 0,
      effect_halo_pulse_enabled:    d.effectHaloPulse ? 1 : 0,
      highlight_strength_percent:   d.effectHighlightStrength,
      spark_amount_percent:         d.effectSparksAmount,
      smoke_amount_percent:         d.effectSmokeAmount,
      press_smoke_amount_percent:   d.effectPressMistAmount,
      fluid_intensity:              d.fluidIntensity,
      fluid_curl:                   Math.round(d.curl * 2),
      fluid_density_dissipation:    Math.min(100, Math.round(d.densityDissipation * 25)),
      fluid_velocity_dissipation:   Math.min(40,  Math.round(d.velocityDissipation * 10)),
      effect_fluid_enabled:         d.fluidEnabled ? 0.5 : 0,
    };
  }
}
