// Canvas 2D particle effects: sparks, smoke, mist, moon dust, steam

export class ParticleSystem {
  constructor () {
    this._particles = [];
  }

  // Call when a note is pressed (cx = note centre-x, y = keyboard top)
  noteOn (cx, y, color, halfWidth, s) {
    if (s.effectSparks)   this._spawnSparks(cx, y, halfWidth * 2, color, s.effectSparksAmount);
    if (s.effectPressMist) this._spawnMist(cx, y, halfWidth * 2, color, s.effectPressMistAmount);
  }

  // Call when a note is released
  noteOff (cx, y, color, halfWidth, s) {
    if (s.effectSmoke) this._spawnSmoke(cx, y, halfWidth * 2, color, s.effectSmokeAmount, false);
    if (s.effectSteam) this._spawnSmoke(cx, y, halfWidth * 2, color, 80, true);
  }

  // Spawn a single moon-dust particle; call from app.js each frame for active trails
  spawnMoonDust (x, y, color) {
    const life = 0.8 + Math.random() * 1.5;
    this._particles.push({
      type: 'moonDust', x, y, color,
      vx: (Math.random() - 0.5) * 22,
      vy: -(3 + Math.random() * 12),
      life, maxLife: life,
      size: 0.7 + Math.random() * 1.8,
    });
  }

  update (dt) {
    this._particles = this._particles.filter(p => {
      p.life -= dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      if (p.type === 'spark') {
        p.vy += 900 * dt;                         // gravity
        p.vx *= Math.max(0, 1 - 3 * dt);         // drag
      } else if (p.type !== 'moonDust') {
        p.vy -= 25 * dt;                          // upward drift
        p.vx += Math.sin(p.phase) * 18 * dt;     // curl
        p.phase += dt * 2;
        p.radius += dt * (p.type === 'steam' ? 22 : 10);
      }
      return p.life > 0;
    });
  }

  draw (ctx, s) {
    for (const p of this._particles) {
      const ratio = Math.max(0, p.life / p.maxLife);
      ctx.fillStyle = p.color;
      if (p.type === 'spark') {
        ctx.globalAlpha = ratio * 0.9;
        ctx.beginPath();
        ctx.arc(p.x, p.y, Math.max(0.3, p.size * ratio), 0, Math.PI * 2);
        ctx.fill();
      } else if (p.type === 'smoke' || p.type === 'steam' || p.type === 'mist') {
        const a = p.type === 'mist' ? 0.22 : p.type === 'steam' ? 0.15 : 0.28;
        ctx.globalAlpha = ratio * a;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
      } else if (p.type === 'moonDust') {
        ctx.globalAlpha = Math.sin(ratio * Math.PI) * 0.75;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
  }

  _spawnSparks (cx, y, width, color, amountPct) {
    const count = Math.round((amountPct / 100) * 14);
    for (let i = 0; i < count; i++) {
      const angle = -Math.PI / 2 + (Math.random() - 0.5) * 1.4;
      const speed = 180 + Math.random() * 450;
      this._particles.push({
        type: 'spark', color,
        x: cx + (Math.random() - 0.5) * width,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 0.25 + Math.random() * 0.55, maxLife: 0.8,
        size: 1.2 + Math.random() * 2.2,
      });
    }
  }

  _spawnSmoke (cx, y, width, color, amountPct, isSteam) {
    const count = Math.round((amountPct / 100) * (isSteam ? 3 : 7));
    for (let i = 0; i < count; i++) {
      const life = isSteam ? (1.8 + Math.random() * 2) : (0.7 + Math.random() * 1.3);
      this._particles.push({
        type: isSteam ? 'steam' : 'smoke', color,
        x: cx + (Math.random() - 0.5) * width * 1.5,
        y: y + Math.random() * 8,
        vx: (Math.random() - 0.5) * 25,
        vy: -(8 + Math.random() * 18),
        life, maxLife: life,
        radius: (isSteam ? 9 : 5) + Math.random() * 4,
        phase: Math.random() * Math.PI * 2,
      });
    }
  }

  _spawnMist (cx, y, width, color, amountPct) {
    const count = Math.round((amountPct / 100) * 10);
    for (let i = 0; i < count; i++) {
      const life = 0.35 + Math.random() * 0.55;
      this._particles.push({
        type: 'mist', color,
        x: cx + (Math.random() - 0.5) * width * 2.2,
        y: y + Math.random() * 12,
        vx: (Math.random() - 0.5) * 22,
        vy: -(4 + Math.random() * 14),
        life, maxLife: life,
        radius: 6 + Math.random() * 10,
        phase: Math.random() * Math.PI * 2,
      });
    }
  }
}
