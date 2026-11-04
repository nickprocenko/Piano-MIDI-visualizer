// The flute through the microphone, for the coach page (loaded after coach.html's script,
// sharing its globals: $, cmd, store, speaking, talking, showAnswer, showNpc, stopSpeaking).
// The alto saxophone and the voice are heard the same way: the profile view (profiles.js puts
// it in window.coachInstrument) gives each one's pitch range, YIN threshold and how far a note
// may waver, and the sax's transposition: its music is written 9 semitones above how it
// sounds, so every pitch heard is moved up 9 (the notes, the tuner and the welcome's check all
// read written pitch) and the page's examples are moved down 9 to sound right.
//
// Notes: while a run listens on the microphone (input 'Microphone (flute)'), the pitch is
// tracked with YIN (de Cheveigne & Kawahara, as the sing-back steps in atlas.js) on 1024-sample
// windows every 512 samples, from an AudioWorklet so it keeps time with the tab in the
// background. A note starts when a pitch in the flute's range holds for 3 frames (~30 ms),
// ends when the sound stops or another pitch holds, and is re-started by a tongued dip in
// level on the same pitch. Each note is posted to cmd/mic_note as a note-on / note-off with
// how long ago it began, and the server grades it exactly like a key on the keyboard.
// Preferences → Audio to MIDI changes the window, the gate and the timings (saved in
// localStorage as coach.audioMidi) and shows what goes in and what comes out.
//
// Hands-free: with the box ticked, speech heard while you're not playing (loud, but not a
// steady flute pitch) is transcribed on the PC (Whisper, free) and, when it starts with
// "Maestro", sent to the Maestro as if typed: "Maestro, start Learn mode at sixty percent".
// "Maestro" alone gets a "Yes?" and the next thing you say counts.
//
// Both pause while the Maestro is speaking or you hold Talk, so neither hears the other.
//
// Examples: a flute profile hears a lesson's examples from this page (a 'sound' event), not
// from the MIDI output, and while one sounds the microphone ignores what it hears (the page's
// own sound, through the speakers), as it does the Maestro's voice.

const MIC_PORT = 'Microphone (flute)';
const FLUTE = {fmin: 240, fmax: 2400, threshold: 0.12, rmsGate: 0.012, holdFrames: 3, endFrames: 4, change: 0.6,
               dip: 0.35, rise: 0.6};
const VAD = {startMs: 40, beforeMs: 90, end: 0.75, maxSec: 8, minSec: 0.35, fluteShare: 0.55, rate: 16000};
// What changes per instrument (instruments.py): FLUTE's limits, and the transposition.
const MIC_SOUND = {flute: {partials: [[1, 1], [2, .15]], cents: 8},  // the examples' tone: harmonics, vibrato depth
                   sax: {partials: [[1, 1], [2, .5], [3, .32], [4, .18], [5, .1]], cents: 6},
                   voice: {partials: [[1, 1], [2, .3], [3, .12]], cents: 18},
                   fiddle: {partials: [[1, 1], [2, .5], [3, .35], [4, .2], [5, .12]], cents: 12},
                   guitar: {partials: [[1, 1], [2, .45], [3, .25], [4, .12]], cents: 0},
                   bass: {partials: [[1, 1], [2, .6], [3, .2]], cents: 0}};
const micInstrument = () => window.coachInstrument || {id: 'flute', name: 'Flute', transpose: 0, mic: null};
const micTranspose = () => micInstrument().transpose || 0;
const micName = () => {
  const id = micInstrument().id;
  return id === 'voice' ? 'your voice' : `your ${{sax: 'saxophone', guitar: 'guitar', bass: 'bass', fiddle: 'fiddle'}[id] || 'flute'}`;
};
// Preferences → Audio to MIDI. size/hop in samples; gateDb is FLUTE.rmsGate in dBFS (-38 = 0.012);
// strict is the YIN threshold; startMs/endMs become holdFrames/endFrames; latencyMs is extra
// input delay (audio interface, Bluetooth) added to every note's ago_ms.
const AUDIO_MIDI = {size: 1024, hop: 512, gateDb: -38, strict: 0.12, startMs: 30, endMs: 45, latencyMs: 0};
const WAKE = /^\W*(?:(?:hey|ok|okay|hi)\W+)?(?:maestro|my stro|mystro|mistro|maestra|mastro|maestros|my astro)\b\W*(.*)$/i;
const FLUTE_NAMES = ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'];
const fluteNoteName = m => FLUTE_NAMES[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1);

const flute = {
  stream: null, ctx: null, node: null, src: null, sr: 48000, opening: null,
  size: 1024, hop: 512, latencyMs: 0, clarity: 0,  // from AUDIO_MIDI and the saved settings
  monitor: null,     // Preferences → Audio to MIDI: {frame(info), midi(event)}; tracks notes without sending them
  run: false,        // a run is listening on the microphone: send notes
  taps: false,       // ...and it's a tapping step (no score): a clap counts as a tap
  env: 0, lastClap: 0,
  handsFree: false,  // listen for "Maestro, ..."
  probe: null,       // the welcome's microphone check: called with (pitch or null, level) each frame
  note: null, cand: null, quiet: 0, peak: 0, dipped: false, // note tracker
  speech: null, awaitUntil: 0, busy: false,                 // hands-free
  queue: Promise.resolve(),
};
const example = {ctx: null, out: null, until: 0};  // the page's example playing, and until when (performance.now)

// -- the microphone -------------------------------------------------------------------------

const WORKLET = `
class Frames extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = options.processorOptions || {};
    this.size = o.size || 1024; this.hop = o.hop || 512;
    this.buf = new Float32Array(this.size); this.fill = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.buf[this.fill++] = ch[i];
      if (this.fill === this.size) {
        this.port.postMessage(this.buf.slice(0));
        this.buf.copyWithin(0, this.hop); this.fill = this.size - this.hop;
      }
    }
    return true;
  }
}
registerProcessor('flute-frames', Frames);`;

function audioMidiSettings() {
  let saved = {};
  try { saved = JSON.parse(store.get('audioMidi', '{}')) || {}; } catch (e) {}
  const mic = micInstrument().mic || {};
  const out = {...AUDIO_MIDI, ...(mic.threshold ? {strict: mic.threshold} : {}), ...saved};  // the instrument's strictness unless you set one
  if (mic.size && out.size < mic.size) {  // a guitar's or a bass's low notes need a longer window: the same overlap, longer
    const overlap = Math.max(1, Math.round(out.size / out.hop));
    out.size = mic.size;
    out.hop = mic.size / overlap;
  }
  return out;
}

const hopMs = () => flute.hop / flute.sr * 1000;
const framesFor = ms => Math.max(1, Math.round(ms / hopMs()));

function fluteApply() {  // the saved settings onto FLUTE and flute (the frame counts depend on the sample rate)
  const s = audioMidiSettings();
  flute.size = s.size;
  flute.hop = Math.min(s.hop, s.size);
  flute.latencyMs = s.latencyMs;
  FLUTE.rmsGate = Math.pow(10, s.gateDb / 20);
  FLUTE.threshold = s.strict;
  const mic = micInstrument().mic;
  if (mic) Object.assign(FLUTE, {fmin: mic.fmin, fmax: mic.fmax, change: mic.change});
  FLUTE.holdFrames = framesFor(s.startMs);
  FLUTE.endFrames = framesFor(s.endMs);
}
fluteApply();

function fluteConnect() {  // a frames node for the current window and hop, fed by the microphone
  if (flute.node) { flute.src.disconnect(); flute.node.port.onmessage = null; flute.node.disconnect(); }
  flute.node = new AudioWorkletNode(flute.ctx, 'flute-frames', {processorOptions: {size: flute.size, hop: flute.hop}});
  flute.node.port.onmessage = e => fluteFrame(e.data);
  flute.src.connect(flute.node);
}

async function fluteOpen() {
  if (flute.ctx) return;
  if (flute.opening) return flute.opening;
  flute.opening = (async () => {
    const mic = store.get('mic', '');
    // No echo cancellation or noise suppression: both treat a held flute note as noise.
    flute.stream = await navigator.mediaDevices.getUserMedia({audio: {deviceId: mic ? {exact: mic} : undefined,
      echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
    flute.ctx = new AudioContext();
    flute.sr = flute.ctx.sampleRate;
    fluteApply();
    await flute.ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], {type: 'application/javascript'})));
    flute.src = flute.ctx.createMediaStreamSource(flute.stream);
    fluteConnect();
  })();
  try { await flute.opening; } finally { flute.opening = null; }
}

// New settings from Preferences: saved, applied, and the window rebuilt if it changed.
function fluteSettings(changes) {
  const s = {...audioMidiSettings(), ...changes};
  const keep = {};
  for (const k of Object.keys(AUDIO_MIDI)) if (s[k] !== AUDIO_MIDI[k]) keep[k] = s[k];
  store.set('audioMidi', JSON.stringify(keep));
  const size = flute.size, hop = flute.hop;
  fluteApply();
  if (flute.ctx && flute.node && (flute.size !== size || flute.hop !== hop)) {
    fluteEnd();
    flute.cand = flute.speech = null;
    flute.recent = [];
    fluteConnect();
  }
}

function fluteClose() {
  if (flute.run || flute.handsFree || flute.probe || flute.monitor || !flute.ctx) return;
  fluteEnd();
  flute.stream.getTracks().forEach(t => t.stop());
  flute.ctx.close();
  flute.stream = flute.ctx = flute.node = flute.src = null;
  fluteTuner(null);
}

// Another microphone picked in Preferences while listening: carry on with the new one.
window.addEventListener('coach:mic', async () => {
  if (!flute.ctx) return;
  fluteEnd();
  flute.stream.getTracks().forEach(t => t.stop());
  flute.ctx.close();
  flute.stream = flute.ctx = flute.node = flute.src = null;
  try { await fluteOpen(); } catch (err) { $('heard').textContent = 'The flute needs the microphone: ' + err.message; }
});

// -- pitch ------------------------------------------------------------------------------------

function flutePitch(buf, sr) {  // YIN; null when there's no clear pitch in the flute's range
  const tmax = Math.min(buf.length >> 1, Math.floor(sr / FLUTE.fmin)), tmin = Math.max(2, Math.floor(sr / FLUTE.fmax));
  const n = buf.length - tmax, cmnd = new Float32Array(tmax + 1);
  let running = 0;
  cmnd[0] = 1;
  for (let tau = 1; tau <= tmax; tau++) {
    let acc = 0;
    for (let i = 0; i < n; i++) { const d = buf[i] - buf[i + tau]; acc += d * d; }
    running += acc;
    cmnd[tau] = running ? acc * tau / running : 1;
  }
  let tau = tmin, best = 1;
  for (; tau < tmax; tau++) {
    if (cmnd[tau] < FLUTE.threshold) { while (tau + 1 < tmax && cmnd[tau + 1] < cmnd[tau]) tau++; break; }
    best = Math.min(best, cmnd[tau]);
  }
  flute.clarity = Math.max(0, 1 - (tau < tmax ? cmnd[tau] : best));  // shown in Preferences → Audio to MIDI
  if (tau >= tmax) return null;
  const a = cmnd[tau - 1], b = cmnd[tau], c = cmnd[tau + 1], den = a - 2 * b + c;
  return sr / (den ? tau + (a - c) / (2 * den) : tau);
}

function fluteFrame(buf) {
  const now = performance.now();
  let rms = 0;
  for (const x of buf) rms += x * x;
  rms = Math.sqrt(rms / buf.length);
  const paused = (typeof speaking !== 'undefined' && speaking) || (typeof talking !== 'undefined' && talking);
  if (paused) { fluteEnd(); flute.speech = null; flute.monitor?.frame({paused: true, rms, now}); return; }
  const own = now < example.until;  // the page's example: not the flute (claps still count for tapping along)
  if (own) { fluteEnd(); flute.cand = flute.speech = null; }
  flute.clarity = 0;
  const hz = rms > FLUTE.rmsGate ? flutePitch(buf, flute.sr) : null;
  const m = hz ? 69 + 12 * Math.log2(hz / 440) + micTranspose() : null;  // written pitch (a sax's is 9 above what sounds)
  if ((flute.run || flute.monitor) && !own) fluteTrack(m, rms, now);
  if (flute.run && flute.taps) fluteClap(m, rms, now);
  flute.env = 0.9 * flute.env + 0.1 * rms;
  if (flute.handsFree && !own) fluteListen(buf, rms, m, now);
  if (flute.probe) flute.probe(m, rms);
  flute.monitor?.frame({rms, hz, m, clarity: flute.clarity, note: flute.note ? flute.note.pitch : null, now});
  fluteTuner(m);
}

// -- notes ------------------------------------------------------------------------------------

// To the server only while a run listens (live); the Audio to MIDI test just shows them.
function fluteSend(body, live) {  // in order: an off must reach the server before the next on
  flute.monitor?.midi({...body, live, now: performance.now()});
  if (!live) return;
  flute.queue = flute.queue.then(() => cmd('mic_note', body)).catch(() => {});
}

function fluteOn(m, at, rms) {
  const pitch = Math.round(m);
  flute.note = {pitch, at, live: flute.run};
  flute.peak = rms;
  flute.dipped = false;
  const velocity = Math.round(Math.max(30, Math.min(120, 40 + 400 * rms)));
  // A frame is heard half a window after it starts; the note began holdFrames before that.
  const ago = performance.now() - at + flute.size / 2 / flute.sr * 1000 + flute.latencyMs;
  fluteSend({on: pitch, velocity, ago_ms: Math.round(ago)}, flute.note.live);
}

function fluteEnd() {
  if (!flute.note) return;
  const ago = flute.quiet * hopMs() + flute.latencyMs;
  fluteSend({off: flute.note.pitch, ago_ms: Math.round(ago)}, flute.note.live);
  flute.note = null;
}

function fluteTrack(m, rms, now) {
  const note = flute.note;
  if (m === null) {
    flute.cand = null;
    if (note && ++flute.quiet >= FLUTE.endFrames) fluteEnd();
    return;
  }
  flute.quiet = 0;
  const c = flute.cand;
  if (c && Math.abs(m - c.m) < 0.5) { c.n++; c.m = (c.m * (c.n - 1) + m) / c.n; } else flute.cand = {m, n: 1, at: now};
  const cand = flute.cand;
  if (!note) {
    if (cand.n >= FLUTE.holdFrames) fluteOn(cand.m, cand.at, rms);
    return;
  }
  if (Math.abs(cand.m - note.pitch) >= FLUTE.change && cand.n >= FLUTE.holdFrames) {  // slurred to a new note
    fluteEnd();
    fluteOn(cand.m, cand.at, rms);
    return;
  }
  // Tongued again on the same pitch: the level dips, then comes back.
  flute.peak = Math.max(rms, flute.peak * 0.995);
  if (rms < flute.peak * FLUTE.dip) flute.dipped = true;
  else if (flute.dipped && rms > flute.peak * FLUTE.rise) { fluteEnd(); fluteOn(m, now, rms); }
}

// Aural tapping steps: a clap (a sudden burst with no pitch) is a tap, sent as a short note.
function fluteClap(m, rms, now) {
  if (m !== null || flute.note || now - flute.lastClap < 120) return;
  if (rms > FLUTE.rmsGate * 4 && rms > flute.env * 4) {
    flute.lastClap = now;
    fluteSend({on: 60, velocity: 90, ago_ms: 10 + flute.latencyMs}, true);
    fluteSend({off: 60, ago_ms: flute.latencyMs}, true);
  }
}

// -- examples -----------------------------------------------------------------------------------

// {notes: [[start s, length s, pitch, velocity], ...]} plays them on a soft tone like the
// instrument's (MIC_SOUND: a few harmonics, a slow vibrato), a transposing instrument's written
// pitches moved to how they sound; {stop: true} stops them. Each new one stops the last.
function fluteExample(msg) {
  if (example.out) {
    const out = example.out;
    out.gain.setTargetAtTime(0, example.ctx.currentTime, 0.02);
    setTimeout(() => out.disconnect(), 200);
    example.out = null;
    example.until = Math.min(example.until, performance.now() + 250);  // the room's echo dies away
  }
  if (msg.stop || !msg.notes || !msg.notes.length) return;
  try {
    if (!example.ctx) routeAudio(example.ctx = new AudioContext());
    const ctx = example.ctx;
    ctx.resume();
    const out = example.out = ctx.createGain(), lfo = ctx.createOscillator(), depth = ctx.createGain();
    const sound = MIC_SOUND[micInstrument().id] || MIC_SOUND.flute, shift = micTranspose();
    out.gain.value = 0.25;
    out.connect(ctx.destination);
    lfo.frequency.value = 5;
    depth.gain.value = sound.cents;
    lfo.connect(depth);
    const t0 = ctx.currentTime + 0.08;
    let end = 0;
    for (const [at, len, pitch, velocity] of msg.notes) {
      const t = t0 + at, d = Math.max(0.08, len), hz = 440 * Math.pow(2, (pitch - shift - 69) / 12);
      const env = ctx.createGain();
      env.gain.setValueAtTime(0, t);
      env.gain.linearRampToValueAtTime(0.4 + 0.6 * velocity / 127, t + 0.04);
      env.gain.setTargetAtTime(0, t + d - 0.02, 0.03);
      env.connect(out);
      for (const [k, level] of sound.partials) {
        const osc = ctx.createOscillator(), g = ctx.createGain();
        osc.frequency.value = k * hz;
        g.gain.value = level;
        depth.connect(osc.detune);
        osc.connect(g);
        g.connect(env);
        osc.start(t);
        osc.stop(t + d + 0.2);
      }
      end = Math.max(end, at + d);
    }
    lfo.start(t0);
    lfo.stop(t0 + end + 0.2);
    example.until = performance.now() + (t0 - ctx.currentTime + end + 0.3) * 1000;
  } catch (err) { $('heard').textContent = 'No sound: ' + err.message; }
}

// -- the tuner ----------------------------------------------------------------------------------

function fluteTuner(m) {
  try { fingeringMonitor(flute.ctx ? m : null); } catch (_) {}
  let el = $('flute-tuner');
  if (!el) {
    el = document.createElement('span');
    el.id = 'flute-tuner';
    el.title = 'What the microphone hears: the note, and how many cents sharp (+) or flat (−)';
    $('last').after(el);
  }
  if (!flute.ctx) { el.textContent = ''; return; }
  if (m === null) { el.textContent = flute.run ? '🎤 …' : ''; return; }
  const near = Math.round(m), cents = Math.round(100 * (m - near));
  el.textContent = `🎤 ${fluteNoteName(near)} ${cents >= 0 ? '+' : '−'}${Math.abs(cents)}¢`;
  el.className = Math.abs(cents) <= 15 ? 'in-tune' : '';
}

// -- the fingering monitor ------------------------------------------------------------------------
// While a run listens (a flute or a sax, Sheet ▸ Fingering ▸ Monitor): the fingering of the note the
// music is waiting for (the server's 'pending' marks, Learn mode) beside the note the microphone
// hears, green when they match and red when not. The heard note stays a moment after the sound stops.

const fingMon = {marks: new Map(), expected: null, heard: null, heardAt: 0, shown: ''};
const FING_HOLD_MS = 1500;

function fingeringMarks(msg) {
  if (msg.reset) fingMon.marks.clear();
  for (const mk of msg.marks || []) {
    const key = `${mk.beat}|${mk.pitch}`;
    if (mk.status === 'pending') fingMon.marks.set(key, mk); else fingMon.marks.delete(key);
  }
  let first = null;
  for (const mk of fingMon.marks.values()) {
    if (!first || mk.beat < first.beat - 1e-3 || (Math.abs(mk.beat - first.beat) < 1e-3 && mk.pitch > first.pitch)) first = mk;
  }
  const next = first ? first.pitch : null;
  if (next !== fingMon.expected) { fingMon.previous = fingMon.expected; fingMon.expected = next; }
  fingeringMonitor();
}

function fingeringMonitor(m) {
  const now = performance.now();
  if (m !== undefined && m !== null) { fingMon.heard = Math.round(m); fingMon.heardAt = now; }
  else if (fingMon.heard !== null && now - fingMon.heardAt > FING_HOLD_MS) fingMon.heard = null;
  const inst = typeof fingeredInstrument === 'function' ? fingeredInstrument() : null;
  const on = !!inst && flute.run && !flute.taps && $('fing-monitor-on')?.checked;
  const sig = on ? `${inst}|${fingMon.expected}|${fingMon.heard}` : '';
  if (sig === fingMon.shown) return;
  fingMon.shown = sig;
  let el = $('fing-monitor');
  if (!el) {
    el = document.createElement('div');
    el.id = 'fing-monitor';
    el.setAttribute('aria-live', 'polite');
    document.body.appendChild(el);
  }
  el.hidden = !on;
  if (!on) { el.innerHTML = ''; return; }
  const card = (label, note, cls) => {
    const svg = note === null ? '' : Fingering.svg(inst, note, {height: 140});
    return `<figure class="${cls}">${svg || '<div class="fm-empty">…</div>'}` +
           `<figcaption>${note === null ? '—' : esc(Fingering.name(note).replace(/\d+$/, ''))}<small>${label}</small></figcaption></figure>`;
  };
  const exp = fingMon.expected, heard = fingMon.heard;
  // The note just played, still sounding as the music moves on, isn't a wrong one.
  const verdict = exp === null || heard === null ? '' : heard === exp ? 'right' : heard === fingMon.previous ? '' : 'wrong';
  el.innerHTML = card('Play', exp, '') + card('Heard', heard, verdict);
}

// -- hands-free: "Maestro, ..." -------------------------------------------------------------------

function fluteListen(buf, rms, m, now) {
  const s = flute.speech;
  const loud = rms > FLUTE.rmsGate * 2;
  if (!s) {
    if (flute.busy || flute.note) return;  // playing, or still answering the last thing said
    flute.loudFrames = loud ? (flute.loudFrames || 0) + 1 : 0;
    flute.recent = (flute.recent || []).concat([buf]).slice(-framesFor(VAD.beforeMs));  // a little before the start
    if (flute.loudFrames >= framesFor(VAD.startMs)) flute.speech = {frames: flute.recent.slice(), pitched: 0, total: 0, lastLoud: now, at: now};
    return;
  }
  s.frames.push(buf);
  s.total++;
  if (m !== null) s.pitched++;
  if (loud) s.lastLoud = now;
  const long = (now - s.at) / 1000;
  if ((now - s.lastLoud) / 1000 > VAD.end || long > VAD.maxSec) {
    flute.speech = null;
    flute.loudFrames = 0;
    if (long < VAD.minSec || s.pitched / Math.max(1, s.total) > VAD.fluteShare) return;  // a cough, or the flute
    fluteHeard(s.frames);
  }
}

function fluteWav(frames) {  // overlapping frames (each one hop on from the last) -> 16 kHz mono 16-bit WAV
  const pcm = [frames[0]].concat(frames.slice(1).map(f => f.subarray(f.length - flute.hop)));
  const total = pcm.reduce((a, f) => a + f.length, 0), step = flute.sr / VAD.rate;
  const out = new Int16Array(Math.floor(total / step));
  let k = 0, pos = 0;
  const flat = new Float32Array(total);
  for (const f of pcm) { flat.set(f, pos); pos += f.length; }
  for (let i = 0; i < out.length; i++, k += step) out[i] = Math.max(-1, Math.min(1, flat[Math.floor(k)])) * 32767;
  const head = new DataView(new ArrayBuffer(44));
  const text = (o, t) => [...t].forEach((ch, i) => head.setUint8(o + i, ch.charCodeAt(0)));
  text(0, 'RIFF'); head.setUint32(4, 36 + out.length * 2, true); text(8, 'WAVEfmt ');
  head.setUint32(16, 16, true); head.setUint16(20, 1, true); head.setUint16(22, 1, true);
  head.setUint32(24, VAD.rate, true); head.setUint32(28, VAD.rate * 2, true); head.setUint16(32, 2, true); head.setUint16(34, 16, true);
  text(36, 'data'); head.setUint32(40, out.length * 2, true);
  return new Blob([head, out], {type: 'audio/wav'});
}

async function fluteHeard(frames) {
  flute.busy = true;
  try {
    const res = await fetch('voice/transcribe', {method: 'POST', headers: {'Content-Type': 'audio/wav'}, body: fluteWav(frames)});
    const heard = ((await res.json()).heard || '').trim();
    if (!heard) return;
    const wake = heard.match(WAKE);
    const waiting = performance.now() < flute.awaitUntil;
    if (!wake && !waiting) return;  // not for the Maestro
    const text = wake ? wake[1].trim() : heard;
    if (!text) {  // "Maestro" alone
      flute.awaitUntil = performance.now() + 8000;
      if (mpOpen()) mpLine({who: 'Maestro', kind: 'pending', text: 'Yes?'}); else showNpc('Yes?', 'Maestro');
      return;
    }
    flute.awaitUntil = 0;
    stopSpeaking();
    mpThinking();
    const out = await fetch('cmd/chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})});
    showAnswer(await out.json());
  } catch (err) {
    $('heard').textContent = 'Hands-free: ' + err.message;
  } finally {
    flute.busy = false;
  }
}

async function fluteHandsFree(on) {
  flute.handsFree = on;
  store.set('handsfree', on ? '1' : '');
  if (!on) return fluteClose();
  try {
    await fluteOpen();
    $('heard').textContent = 'Hands-free: say “Maestro, …” and what you want.';
  } catch (err) {
    flute.handsFree = false;
    $('handsfree').checked = false;
    $('heard').textContent = 'Hands-free needs the microphone: ' + err.message;
  }
}

// -- Preferences → Audio to MIDI -----------------------------------------------------------------
// While the pane shows, the microphone stays open and every frame goes to the graph (level,
// gate, pitch, the note being held) and every note-on / note-off to the list below it. They
// reach the coach only if a run is listening at the time; otherwise it's a test.

const cal = {ready: false, frames: [], events: [], since: 0, raf: 0, noise: null};
const CAL_SPAN = 4000;  // ms of history in the graph
const CAL_LOW = 55, CAL_HIGH = 100;  // the graph's pitch range (the flute is 58-98)
const dbOf = rms => 20 * Math.log10(Math.max(rms, 1e-5));

function calInit() {
  if (cal.ready) return;
  cal.ready = true;
  for (const n of [512, 1024, 2048, 4096]) $('am-size').add(new Option(`${n} samples`, n));
  const set = (id, f) => $(id).addEventListener('input', e => { fluteSettings(f(+e.target.value)); calShow(); });
  $('am-size').addEventListener('change', e => {
    const s = audioMidiSettings(), size = +e.target.value;
    fluteSettings({size, hop: size / Math.round(s.size / s.hop)});
    calShow();
  });
  $('am-hop').addEventListener('change', e => { fluteSettings({hop: audioMidiSettings().size / +e.target.value}); calShow(); });
  set('am-gate', v => ({gateDb: v}));
  set('am-strict', v => ({strict: +(1 - v / 100).toFixed(2)}));
  set('am-start', v => ({startMs: v}));
  set('am-end', v => ({endMs: v}));
  set('am-latency', v => ({latencyMs: v}));
  $('am-reset').addEventListener('click', () => { store.set('audioMidi', '{}'); fluteSettings({}); calShow(); });
  $('am-noise').addEventListener('click', () => {
    $('am-noise').disabled = true;
    $('am-msg').textContent = 'Listening to the room: stay quiet for 2 seconds…';
    cal.noise = [];
    setTimeout(() => {
      const levels = (cal.noise || []).sort((a, b) => a - b);
      cal.noise = null;
      $('am-noise').disabled = false;
      if (!levels.length) { $('am-msg').textContent = 'Nothing was heard: is the microphone open?'; return; }
      const floor = dbOf(levels[Math.floor(levels.length * 0.9)]);
      const gateDb = Math.max(-75, Math.min(-20, Math.round(floor + 8)));
      fluteSettings({gateDb});
      calShow();
      $('am-msg').textContent = `Room noise about ${Math.round(floor)} dB, so the gate is now ${gateDb} dB: quieter sounds are ignored.`;
    }, 2000);
  });
}

function calShow() {  // the controls and the numbers beside them, from the saved settings
  const s = audioMidiSettings(), ms = n => (n / flute.sr * 1000).toFixed(1) + ' ms', sr = flute.sr;
  $('am-size').value = s.size;
  $('am-hop').value = Math.round(s.size / s.hop);
  $('am-gate').value = s.gateDb;
  $('am-strict').value = Math.round(100 * (1 - s.strict));
  $('am-start').value = s.startMs;
  $('am-end').value = s.endMs;
  $('am-latency').value = s.latencyMs;
  $('am-size-val').textContent = ms(s.size);
  $('am-hop-val').textContent = ms(flute.hop);
  $('am-gate-val').textContent = s.gateDb + ' dB';
  $('am-strict-val').textContent = Math.round(100 * (1 - s.strict)) + '%';
  $('am-start-val').textContent = `${s.startMs} ms (${FLUTE.holdFrames} frame${FLUTE.holdFrames > 1 ? 's' : ''})`;
  $('am-end-val').textContent = `${s.endMs} ms (${FLUTE.endFrames} frame${FLUTE.endFrames > 1 ? 's' : ''})`;
  $('am-latency-val').textContent = s.latencyMs + ' ms';
  const lowest = Math.max(FLUTE.fmin, sr / (flute.size / 2));
  const track = flute.stream?.getAudioTracks()[0]?.getSettings?.() || {};
  const reported = [track.latency ? `microphone ${Math.round(track.latency * 1000)} ms` : '',
                    flute.ctx?.baseLatency ? `audio engine ${Math.round(flute.ctx.baseLatency * 1000)} ms` : ''].filter(Boolean);
  $('am-info').textContent = [
    `${sr} Hz, ${s.size}-sample window (${ms(s.size)}), a new frame every ${ms(flute.hop)}.`,
    `Lowest pitch it can hear: ${Math.round(lowest)} Hz (${fluteNoteName(Math.ceil(69 + 12 * Math.log2(lowest / 440)) + micTranspose())}), highest ${FLUTE.fmax} Hz.`,
    `A note is recognized about ${Math.round(s.size / 2 / sr * 1000 + (FLUTE.holdFrames - 1) * hopMs())} ms after it starts; ` +
      `that delay${s.latencyMs ? ' plus the extra latency' : ''} is taken off its time, so it's graded on time.`,
    reported.length ? `Reported by Windows: ${reported.join(', ')}.` : '',
  ].filter(Boolean).join('\n');
}

function calFrame(f) {
  cal.frames.push(f);
  while (cal.frames.length && f.now - cal.frames[0].now > CAL_SPAN) cal.frames.shift();
  if (cal.noise && !f.paused) cal.noise.push(f.rms);
  const out = [`Level ${Math.round(dbOf(f.rms))} dB`];
  if (f.paused) out.push('paused while the Maestro speaks or you hold Talk');
  else if (f.rms <= FLUTE.rmsGate) out.push('below the gate');
  else if (!f.hz) out.push(`no clear pitch (clarity ${Math.round(100 * f.clarity)}%)`);
  else {
    const near = Math.round(f.m), cents = Math.round(100 * (f.m - near));
    out.push(`${f.hz.toFixed(1)} Hz`, `${fluteNoteName(near)} ${cents >= 0 ? '+' : '−'}${Math.abs(cents)}¢`,
             `clarity ${Math.round(100 * f.clarity)}%`);
  }
  out.push(f.note === null || f.note === undefined ? 'no note' : `holding ${fluteNoteName(f.note)} (${f.note})`);
  $('am-now').textContent = out.join(' · ');
}

function calMidi(e) {
  const at = e.now - e.ago_ms;
  e.at = at;
  if (e.on !== undefined) cal.events.push(e);
  else {
    const on = [...cal.events].reverse().find(x => x.on === e.off && !x.ended);
    if (on) { on.ended = true; e.held = Math.round(at - on.at); }
    cal.events.push(e);
  }
  cal.events = cal.events.slice(-40);
  const t = x => ((x.at - cal.since) / 1000).toFixed(2).padStart(7) + ' s';
  const rows = cal.events.slice(-12).reverse().map(x => {
    const pitch = x.on !== undefined ? x.on : x.off;
    const what = x.on !== undefined
      ? `on   ${(fluteNoteName(pitch) + ' (' + pitch + ')').padEnd(10)} vel ${String(x.velocity).padStart(3)}   heard ${x.ago_ms} ms late`
      : `off  ${(fluteNoteName(pitch) + ' (' + pitch + ')').padEnd(10)} ${x.held !== undefined ? 'held ' + x.held + ' ms' : ''}`;
    return `${t(x)}  ${what.padEnd(48)} ${x.live ? '→ coach' : 'test'}`;
  });
  $('am-log').textContent = rows.join('\n');
}

function calDraw() {
  cal.raf = requestAnimationFrame(calDraw);
  const cv = $('am-graph'), dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = cv.clientHeight;
  if (!w) return;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  const g = cv.getContext('2d'), css = getComputedStyle(document.documentElement);
  const color = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const now = performance.now(), x = t => w - (now - t) / CAL_SPAN * w, bar = Math.max(1, hopMs() / CAL_SPAN * w);
  const yDb = db => h * (1 - (Math.max(-80, Math.min(0, db)) + 80) / 80);
  const yPitch = m => h * (1 - (m - CAL_LOW) / (CAL_HIGH - CAL_LOW));
  g.fillStyle = 'rgba(255,255,255,.14)';  // level
  for (const f of cal.frames) { const y = yDb(dbOf(f.rms)); g.fillRect(x(f.now) - bar, y, bar, h - y); }
  g.strokeStyle = color('--miss', '#e66');  // the gate
  g.setLineDash([4, 4]);
  g.beginPath(); g.moveTo(0, yDb(dbOf(FLUTE.rmsGate))); g.lineTo(w, yDb(dbOf(FLUTE.rmsGate))); g.stroke();
  g.setLineDash([]);
  g.fillStyle = color('--hit', '#4c8');  // notes held
  for (const f of cal.frames) if (f.note !== null && f.note !== undefined) g.fillRect(x(f.now) - bar, yPitch(f.note) - 2, bar, 4);
  g.fillStyle = color('--accent', '#0bb');  // the pitch heard
  for (const f of cal.frames) if (f.m !== null && f.m !== undefined) g.fillRect(x(f.now) - 1, yPitch(f.m) - 1, 2, 2);
  g.strokeStyle = color('--hit', '#4c8');  // note-ons
  for (const e of cal.events) if (e.on !== undefined && now - e.at < CAL_SPAN) {
    g.beginPath(); g.moveTo(x(e.at), 0); g.lineTo(x(e.at), h); g.stroke();
  }
  g.fillStyle = color('--muted', '#999');
  g.font = '10px Segoe UI, Arial, sans-serif';
  g.fillText(`gate ${Math.round(dbOf(FLUTE.rmsGate))} dB`, 4, Math.max(10, yDb(dbOf(FLUTE.rmsGate)) - 3));
  for (const m of [60, 72, 84, 96]) g.fillText(fluteNoteName(m), w - 22, yPitch(m) + 3);
}

// Called by prefs.js: on while the Audio to MIDI pane shows.
async function fluteCalibrate(on) {
  if (!on) {
    if (!flute.monitor) return;
    flute.monitor = null;
    cancelAnimationFrame(cal.raf);
    cal.noise = null;
    if (flute.note && !flute.note.live) fluteEnd();
    fluteClose();
    return;
  }
  calInit();
  calShow();
  if (flute.monitor) return;
  cal.frames = [];
  cal.events = [];
  cal.since = performance.now();
  $('am-log').textContent = 'Play a few notes: each note-on and note-off shows here.';
  $('am-now').textContent = 'Opening the microphone…';
  $('am-msg').textContent = '';
  flute.monitor = {frame: calFrame, midi: calMidi};
  cal.raf = requestAnimationFrame(calDraw);
  try {
    await fluteOpen();
    calShow();  // now with the real sample rate
  } catch (err) {
    flute.monitor = null;
    cancelAnimationFrame(cal.raf);
    $('am-now').textContent = '';
    $('am-msg').textContent = 'Can’t open the microphone: ' + err.message;
  }
}

// -- wiring --------------------------------------------------------------------------------------

// Called by showPractice with every practice update: listen while a run uses the microphone.
async function flutePractice(p) {
  const want = !!(p.running && p.port === MIC_PORT && !(p.settings && p.settings.mode === 'listen'));
  const s = p.settings || {};
  flute.taps = want && s.mode === 'free' && !s.reference;  // free play with no score: an aural tapping step
  if (want === flute.run) return;
  flute.run = want;
  if (!want) { fluteEnd(); fluteClose(); return; }
  try { await fluteOpen(); } catch (err) {
    flute.run = false;
    $('heard').textContent = `The coach needs the microphone to hear ${micName()}: ` + err.message;
  }
}

(() => {
  const box = document.createElement('label');
  box.className = 'handsfree';
  box.title = 'Keep the microphone open and act on anything that starts with “Maestro” (both hands stay on your instrument). ' +
              'Speech is transcribed on this PC; only what follows “Maestro” goes to the Maestro.';
  box.innerHTML = '<input type="checkbox" id="handsfree"> Hands-free';
  $('ai-spend').before(box);
  $('handsfree').addEventListener('change', e => fluteHandsFree(e.target.checked));
  if (store.get('handsfree', '')) { $('handsfree').checked = true; fluteHandsFree(true); }
})();

window.addEventListener('coach:instrument', fluteApply);  // the profile's instrument: its limits
