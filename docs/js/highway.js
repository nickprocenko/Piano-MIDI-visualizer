// Note trail (highway) renderer — extended for inner colour, glow/highlight effects

export class Highway {
  constructor () {
    this._trails = new Map();
    this._finished = [];
  }

  // innerColor: hex string for interior gradient; innerBlend: 0-1
  noteOn (note, velocity, x, width, color, innerColor, innerBlend) {
    this._trails.set(note, {
      note, x, width, color,
      innerColor: innerColor || color,
      innerBlend: innerBlend ?? 0,
      topY: 0,
      bottomY: 0,
      released: false,
      velocity,
    });
  }

  noteOff (note) {
    const trail = this._trails.get(note);
    if (!trail) return;
    trail.released = true;
    this._finished.push(trail);
    this._trails.delete(note);
  }

  update (dt, speed, canvasHeight, keyboardHeight) {
    const dy = speed * dt;
    const limit = canvasHeight - keyboardHeight;

    for (const t of this._trails.values()) {
      t.topY = Math.min(t.topY + dy, limit);
    }

    this._finished = this._finished.filter(t => {
      t.topY    += dy;
      t.bottomY += dy;
      return t.bottomY < limit;
    });
  }

  draw (ctx, canvasHeight, keyboardHeight, appearance = {}, time = 0) {
    const base = canvasHeight - keyboardHeight;
    for (const t of this._finished) this._drawTrail(ctx, t, base, appearance, time);
    for (const t of this._trails.values()) this._drawTrail(ctx, t, base, appearance, time);
  }

  recolor (getColor) {
    for (const t of this._trails.values()) t.color = getColor(t.note);
    for (const t of this._finished) t.color = getColor(t.note);
  }

  * activeTrails () {
    for (const t of this._trails.values()) yield t;
  }

  get activeCount () { return this._trails.size; }

  _drawTrail (ctx, t, base, appearance, time) {
    const h = t.topY - (t.released ? t.bottomY : 0);
    if (h <= 0) return;
    const yTop = base - t.topY;

    const glowEnabled  = appearance.effectGlow !== false;
    const glowStr      = this._clamp01((appearance.effectGlowStrength ?? 100) / 100);
    const innerOpacity = this._clamp01(appearance.innerOpacity ?? 0.85);
    const headOpacity  = this._clamp01(appearance.headOpacity  ?? 0.9);
    const edgeR        = Math.min(t.width / 2, appearance.edgeRoundness ?? 6);
    const hlEnabled    = appearance.effectHighlight !== false;
    const hlStr        = this._clamp01((appearance.effectHighlightStrength ?? 95) / 170);
    const haloPulse    = (appearance.effectHaloPulse && glowEnabled)
      ? (1 + 0.35 * Math.sin(time * 5))
      : 1;

    // Outer glow layers
    if (glowEnabled && glowStr > 0) {
      const outerW = t.width * (1.2 + glowStr * 1.2);
      ctx.globalAlpha = (0.08 + glowStr * 0.28) * haloPulse;
      ctx.fillStyle = t.color;
      ctx.fillRect(t.x - (outerW - t.width) / 2, yTop, outerW, h);

      const midW = t.width * (1.0 + glowStr * 0.6);
      ctx.globalAlpha = (0.12 + glowStr * 0.3) * haloPulse;
      ctx.fillRect(t.x - (midW - t.width) / 2, yTop, midW, h);
    }

    // Note body — solid or inner-colour gradient
    ctx.globalAlpha = innerOpacity;
    const blend = this._clamp01(t.innerBlend ?? 0);
    if (blend > 0 && t.innerColor && t.innerColor !== t.color) {
      const grad = ctx.createLinearGradient(t.x, 0, t.x + t.width, 0);
      const mid = blend * 0.35;
      grad.addColorStop(0,       t.color);
      grad.addColorStop(0.5 - mid, t.innerColor);
      grad.addColorStop(0.5 + mid, t.innerColor);
      grad.addColorStop(1,       t.color);
      ctx.fillStyle = grad;
    } else {
      ctx.fillStyle = t.color;
    }
    this._roundedRect(ctx, t.x, yTop, t.width, h, edgeR);
    ctx.fill();

    // Specular highlight — left-edge streak
    if (hlEnabled && hlStr > 0) {
      ctx.globalAlpha = hlStr * 0.55;
      ctx.fillStyle = '#ffffff';
      const hlW = Math.max(1, t.width * 0.07);
      ctx.fillRect(t.x + Math.ceil(edgeR / 2), yTop + edgeR, hlW, Math.max(0, h - edgeR * 2));
    }

    // Head (bright top edge where the note is "arriving")
    if (headOpacity > 0) {
      ctx.globalAlpha = headOpacity;
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(t.x, yTop, t.width, Math.min(3, h));
    }

    ctx.globalAlpha = 1.0;
  }

  _roundedRect (ctx, x, y, w, h, r) {
    if (r <= 0) { ctx.beginPath(); ctx.rect(x, y, w, h); return; }
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h);
    ctx.lineTo(x, y + h);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  _clamp01 (v) { return Math.max(0, Math.min(1, v)); }
}
