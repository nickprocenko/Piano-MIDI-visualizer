// Drum view: hits fall down a highway to pads at the strike line. Lanes, left to right: crash,
// hi-hat, snare, tom; the kick is a bar across all of them. The hits are the song's own MIDI
// drums when its file is lined up with the radio, else what the audio detector heard (kick, snare
// and hi-hat only), so a hit is known as far ahead as the delay allows.
"use strict";
(() => {
  // lane numbers as radio_hands/drums.py: 0 crash, 1 hat, 2 snare, 3 tom, 4 kick
  const LANES = [
    {id: 0, name: 'Crash', color: '#f6e05e'}, {id: 1, name: 'Hi-hat', color: '#4cc9f0'},
    {id: 2, name: 'Snare', color: '#ff6b6b'}, {id: 3, name: 'Tom', color: '#5ad19a'},
  ];
  const KICK = {name: 'Kick', color: '#ffb347'};
  const WINDOW = 5, K = 4, PMIN = 1 / (1 + K);
  const flash = new Map();  // key -> the time a pad was last hit

  function draw(canvas, t, hits, source, now) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const bg = ctx.createLinearGradient(0, 0, 0, h);
    bg.addColorStop(0, '#07080d'); bg.addColorStop(1, '#10121b');
    ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

    const y0 = h * 0.02, y1 = h * 0.8, cx = w / 2;
    const nearW = Math.min(w * 0.7, 640), farW = nearW * 0.2;
    const frac = dt => { const p = 1 / (1 + K * Math.max(0, dt) / WINDOW); return (p - PMIN) / (1 - PMIN); };
    const yAt = f => y0 + (y1 - y0) * f;
    const widthAt = f => farW + (nearW - farW) * f;
    const laneX = (i, f) => cx + (i - 1.5) * widthAt(f) / 4;     // 4 lanes
    const scale = f => 0.3 + 0.7 * f;

    // lanes, edges, the seconds going by
    for (let i = 0; i < 4; i++) {
      ctx.strokeStyle = LANES[i].color + '44'; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(laneX(i, 0), yAt(0)); ctx.lineTo(laneX(i, 1), yAt(1)); ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(255,255,255,.1)'; ctx.lineWidth = 1;
    for (const s of [-0.5, 3.5]) { ctx.beginPath(); ctx.moveTo(cx + (s - 1.5) * farW / 4, yAt(0)); ctx.lineTo(cx + (s - 1.5) * nearW / 4, yAt(1)); ctx.stroke(); }
    for (let s = Math.ceil(t * 2) / 2; s < t + WINDOW; s += 0.5) {
      const f = frac(s - t);
      ctx.strokeStyle = `rgba(255,255,255,${0.03 + 0.08 * f})`;
      ctx.beginPath(); ctx.moveTo(laneX(-0.5, f), yAt(f)); ctx.lineTo(laneX(3.5, f), yAt(f)); ctx.stroke();
    }

    // hits, far ones first
    const list = hits.filter(x => x[0] > t - 0.2 && x[0] < t + WINDOW).sort((a, b) => b[0] - a[0]);
    for (const [at, lane] of list) {
      const dt = at - t, f = frac(dt), y = yAt(f), k = scale(f);
      const past = dt < 0;
      if (past) { flash.set(lane, now); }
      ctx.globalAlpha = past ? Math.max(0, 1 + dt / 0.2) : 1;
      if (lane === 4) {  // the kick: a bar across the road
        ctx.fillStyle = KICK.color;
        const hgt = 5 + 14 * k;
        ctx.beginPath(); ctx.roundRect(laneX(-0.5, f), y - hgt / 2, laneX(3.5, f) - laneX(-0.5, f), hgt, hgt / 2); ctx.fill();
      } else {
        const L = LANES[lane], x = laneX(lane, f), r = (widthAt(f) / 4) * 0.34;
        ctx.fillStyle = L.color;
        ctx.beginPath(); ctx.ellipse(x, y, r * 1.15, r * 0.62, 0, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,.7)'; ctx.lineWidth = 1 + k; ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    // the pads at the strike line, lit as they're hit
    const f = 1, y = yAt(1);
    ctx.strokeStyle = 'rgba(0,224,224,.9)'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(laneX(-0.6, f), y); ctx.lineTo(laneX(3.6, f), y); ctx.stroke();
    const lit = lane => Math.max(0, 1 - (now - (flash.get(lane) || -1e9)) / 180);
    const kl = lit(4);
    ctx.fillStyle = KICK.color + (kl > 0 ? 'ff' : '33');
    ctx.globalAlpha = 0.25 + 0.75 * kl;
    ctx.beginPath(); ctx.roundRect(laneX(-0.5, f), y + 10, laneX(3.5, f) - laneX(-0.5, f), 22, 11); ctx.fill();
    ctx.globalAlpha = 1;
    for (let i = 0; i < 4; i++) {
      const x = laneX(i, f), r = (widthAt(f) / 4) * 0.34, l = lit(i);
      ctx.globalAlpha = 0.25 + 0.75 * l;
      ctx.fillStyle = LANES[i].color;
      ctx.beginPath(); ctx.ellipse(x, y + 4, r * 1.15, r * 0.62, 0, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillStyle = '#8d93a8'; ctx.font = '600 11px "Segoe UI", Arial, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillText(LANES[i].name, x, y + r * 0.62 + 12);
    }
    ctx.fillStyle = '#8d93a8'; ctx.font = '600 11px "Segoe UI", Arial, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText('Kick', cx, y + 36);
    ctx.textAlign = 'left'; ctx.fillText(source === 'file' ? "the song's own drums" : 'drums as heard (kick, snare, hi-hat)', 14, h - 20);
  }

  window.drumHighway = {draw};
})();
