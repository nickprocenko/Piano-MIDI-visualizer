/*
 * MusicFX site script — shared layout, product cards, cart and hero animation.
 * Depends on catalog.js (window.MusicFX). No build step, no dependencies.
 */
(function () {
  const MFX = window.MusicFX;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const money = (n) => (n === 0 ? "Free" : "$" + n.toLocaleString("en-US"));
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------------------------------------------------------------- layout
  const NAV = [
    { href: "shop.html", label: "Shop", page: "shop" },
    { href: "shop.html?inst=keys", label: "Keys", page: "keys" },
    { href: "shop.html?inst=drums", label: "Drums", page: "drums" },
    { href: "shop.html?inst=guitar", label: "Guitar", page: "guitar" },
    { href: "software.html", label: "Software & Apps", page: "software" },
    { href: "index.html#faq", label: "FAQ", page: "faq" },
  ];

  const LOGO_SVG = `
    <svg class="logo-mark" viewBox="0 0 32 32" aria-hidden="true">
      <defs><linearGradient id="lg" x1="0" x2="1"><stop offset="0" stop-color="#00d2c8"/><stop offset=".6" stop-color="#ff3d9a"/><stop offset="1" stop-color="#ffb547"/></linearGradient></defs>
      <rect x="2" y="2" width="28" height="28" rx="8" fill="#171722" stroke="#2a2a3a"/>
      <rect x="7" y="16" width="3.2" height="9" rx="1.2" fill="url(#lg)"/>
      <rect x="12.2" y="9" width="3.2" height="16" rx="1.2" fill="url(#lg)"/>
      <rect x="17.4" y="13" width="3.2" height="12" rx="1.2" fill="url(#lg)"/>
      <rect x="22.6" y="6" width="3.2" height="19" rx="1.2" fill="url(#lg)"/>
    </svg>`;

  function renderChrome() {
    let page = document.body.dataset.page;
    if (page === "shop") page = new URLSearchParams(location.search).get("inst") || "shop";
    const header = document.createElement("header");
    header.className = "site-header";
    header.innerHTML = `
      <div class="container nav">
        <a class="logo" href="index.html" aria-label="MusicFX home">${LOGO_SVG}<span>Music<b>FX</b></span></a>
        <button class="menu-toggle" aria-label="Open menu" aria-expanded="false" aria-controls="nav-links">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
        </button>
        <ul class="nav-links" id="nav-links">
          ${NAV.map((n) => `<li><a href="${n.href}"${n.page === page ? ' aria-current="page"' : ""}>${n.label}</a></li>`).join("")}
        </ul>
        <button class="cart-btn" type="button" data-open-cart aria-label="Open cart">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6h15l-1.5 9h-12z"/><path d="M6 6 5 3H2"/><circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/></svg>
          <span class="cart-count" data-cart-count data-empty="true">0</span>
        </button>
      </div>`;
    document.body.prepend(header);

    const toggle = $(".menu-toggle", header);
    const links = $(".nav-links", header);
    toggle.addEventListener("click", () => {
      const open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    links.addEventListener("click", (e) => { if (e.target.closest("a")) links.classList.remove("open"); });

    const footer = document.createElement("footer");
    footer.className = "site-footer";
    footer.innerHTML = `
      <div class="container">
        <div class="footer-grid">
          <div>
            <a class="logo" href="index.html">${LOGO_SVG}<span>Music<b>FX</b></span></a>
            <p style="margin-top:14px;max-width:300px">Lights, visuals and practice tools for keys, drums and guitar — all in one app.</p>
          </div>
          <div><h4>Shop</h4><ul>
            <li><a href="shop.html?inst=keys">Keys</a></li>
            <li><a href="shop.html?inst=drums">Drums</a></li>
            <li><a href="shop.html?inst=guitar">Guitar</a></li>
            <li><a href="shop.html?cat=bundle">Complete Kits</a></li>
          </ul></div>
          <div><h4>Software</h4><ul>
            <li><a href="../">Launch the app</a></li>
            <li><a href="software.html#instruments">Instrument modes</a></li>
            <li><a href="software.html#coach">Practice Coach</a></li>
            <li><a href="software.html#stream">Streaming Tools</a></li>
          </ul></div>
          <div><h4>Support</h4><ul>
            <li><a href="shop.html#size-guide">Size Guide</a></li>
            <li><a href="index.html#faq">FAQ</a></li>
            <li><a href="https://github.com/nickprocenko/Piano-MIDI-visualizer">GitHub</a></li>
          </ul></div>
        </div>
        <div class="footer-bottom">
          <span>© ${new Date().getFullYear()} MusicFX. All rights reserved.</span>
          <span>Prices shown are previews and may change before launch.</span>
        </div>
      </div>`;
    document.body.append(footer);

    const shell = document.createElement("div");
    shell.innerHTML = `
      <div class="cart-overlay" data-close-cart></div>
      <aside class="cart-drawer" role="dialog" aria-modal="true" aria-labelledby="cart-title" aria-hidden="true">
        <div class="cart-head">
          <h2 id="cart-title">Your cart</h2>
          <button class="icon-btn" type="button" data-close-cart aria-label="Close cart">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6 6 18"/></svg>
          </button>
        </div>
        <div class="cart-items" data-cart-items></div>
        <div class="cart-foot">
          <div class="cart-row"><span class="muted">Subtotal</span><span class="cart-total" data-cart-total>$0</span></div>
          <div class="cart-row muted" style="font-size:.85rem"><span>Shipping & tax calculated at checkout</span></div>
          <button class="btn btn-primary btn-block" type="button" data-checkout>Checkout</button>
        </div>
      </aside>
      <div class="toast" role="status" aria-live="polite"></div>`;
    document.body.append(...shell.children);

    document.addEventListener("click", (e) => {
      if (e.target.closest("[data-open-cart]")) openCart();
      if (e.target.closest("[data-close-cart]")) closeCart();
      if (e.target.closest("[data-checkout]")) {
        // TODO: hand the cart to the payment provider (Stripe Checkout / Shopify Buy Button).
        toast(cart.items.length ? "Checkout opens at launch — join the list to be first in line." : "Your cart is empty.");
      }
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeCart(); });
  }

  let toastTimer;
  function toast(msg) {
    const el = $(".toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2800);
  }

  // ---------------------------------------------------------------- cart
  const CART_KEY = "musicfx.cart.v2";
  const cart = {
    items: load(),
    add(id, size) {
      const s = size ?? null;
      const line = this.items.find((i) => i.id === id && String(i.size) === String(s));
      if (line) line.qty += 1;
      else this.items.push({ id, size: s, qty: 1 });
      this.save();
    },
    setQty(index, qty) {
      if (qty <= 0) this.items.splice(index, 1);
      else this.items[index].qty = qty;
      this.save();
    },
    total() { return this.items.reduce((sum, i) => sum + MFX.priceOf(MFX.byId[i.id], i.size) * i.qty, 0); },
    count() { return this.items.reduce((n, i) => n + i.qty, 0); },
    save() {
      try { localStorage.setItem(CART_KEY, JSON.stringify(this.items)); } catch (_) { /* storage blocked: cart lives for this page only */ }
      renderCart();
    },
  };
  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(CART_KEY) || "[]");
      return Array.isArray(raw) ? raw.filter((i) => MFX.byId[i.id] && i.qty > 0) : [];
    } catch (_) { return []; }
  }

  const sizeLong = (p, size) => (p.sizeKind ? MFX.sizeOption(p.sizeKind, size)?.long || "" : "");

  function renderCart() {
    const count = cart.count();
    $$("[data-cart-count]").forEach((el) => { el.textContent = count; el.dataset.empty = String(count === 0); });
    const list = $("[data-cart-items]");
    if (!list) return;
    if (!cart.items.length) {
      list.innerHTML = `<p class="cart-empty">Your cart is empty.<br><a href="shop.html">Browse the shop →</a></p>`;
    } else {
      list.innerHTML = cart.items.map((i, idx) => {
        const p = MFX.byId[i.id];
        const unit = MFX.priceOf(p, i.size);
        const meta = [sizeLong(p, i.size) || p.tagline, p.category === "bundle" ? "kit" : "", p.status === "preorder" ? "pre-order" : ""].filter(Boolean).join(" · ");
        return `
          <div class="cart-item">
            <div>
              <div class="cart-item-name">${esc(p.name)}</div>
              <div class="cart-item-meta">${esc(meta)}</div>
            </div>
            <div class="cart-item-price">${money(unit * i.qty)}</div>
            <div class="qty" aria-label="Quantity">
              <button type="button" data-qty="${idx}" data-delta="-1" aria-label="Decrease">−</button>
              <span>${i.qty}</span>
              <button type="button" data-qty="${idx}" data-delta="1" aria-label="Increase">+</button>
            </div>
            <button class="cart-remove" type="button" data-remove="${idx}">Remove</button>
          </div>`;
      }).join("");
    }
    $("[data-cart-total]").textContent = money(cart.total());
  }

  function openCart() {
    $(".cart-drawer")?.classList.add("open");
    $(".cart-drawer")?.setAttribute("aria-hidden", "false");
    $(".cart-overlay")?.classList.add("open");
  }
  function closeCart() {
    $(".cart-drawer")?.classList.remove("open");
    $(".cart-drawer")?.setAttribute("aria-hidden", "true");
    $(".cart-overlay")?.classList.remove("open");
  }

  document.addEventListener("click", (e) => {
    const q = e.target.closest("[data-qty]");
    if (q) {
      const idx = Number(q.dataset.qty);
      cart.setQty(idx, cart.items[idx].qty + Number(q.dataset.delta));
    }
    const r = e.target.closest("[data-remove]");
    if (r) cart.setQty(Number(r.dataset.remove), 0);
  });

  // ---------------------------------------------------------------- art
  // Inline illustrations so the shop works before real photos exist.
  const HUES = ["#00d2c8", "#2ab7ff", "#7a6bff", "#ff3d9a", "#ff6a5c", "#ffb547"];
  const DEFS = `<defs><filter id="glow" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="bigglow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6"/></filter></defs>`;

  function keyboardSVG(y, w, x = 20) {
    const white = 14, ww = w / white;
    let s = `<rect x="${x}" y="${y}" width="${w}" height="46" rx="4" fill="#e9e8f0"/>`;
    for (let i = 1; i < white; i++) s += `<line x1="${x + i * ww}" y1="${y}" x2="${x + i * ww}" y2="${y + 46}" stroke="#b9b8c6" stroke-width="1"/>`;
    [0, 1, 3, 4, 5, 7, 8, 10, 11, 12].forEach((i) => { s += `<rect x="${x + (i + 1) * ww - ww * 0.3}" y="${y}" width="${ww * 0.6}" height="28" rx="2" fill="#16161e"/>`; });
    return s;
  }
  function stripSVG(y, w, n, x = 20) {
    let s = `<rect x="${x - 4}" y="${y - 7}" width="${w + 8}" height="14" rx="7" fill="#22222f" stroke="#33334a"/>`;
    for (let i = 0; i < n; i++) {
      const c = HUES[Math.floor((i / n) * HUES.length)];
      const on = [2, 3, 7, 11, 12, 16, 20, 21, 25].includes(i % 28);
      s += `<circle cx="${x + 4 + (i * (w - 8)) / (n - 1)}" cy="${y}" r="2.6" fill="${on ? c : "#3a3a50"}"${on ? ` filter="url(#glow)"` : ""}/>`;
    }
    return s;
  }
  function hubSVG(cx, cy, scale = 1, label = "MusicFX", led = "#00d2c8") {
    const w = 96 * scale, h = 58 * scale, x = cx - w / 2, y = cy - h / 2;
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${12 * scale}" fill="#1f1f2c" stroke="#3a3a52" stroke-width="1.5"/>
      <rect x="${x + 12 * scale}" y="${y + 12 * scale}" width="${34 * scale}" height="${6 * scale}" rx="3" fill="#2d2d40"/>
      <text x="${x + 12 * scale}" y="${y + h - 14 * scale}" fill="#9a99ad" font-family="Space Grotesk, sans-serif" font-size="${10 * scale}" font-weight="700">${label}</text>
      <circle cx="${x + w - 18 * scale}" cy="${y + 18 * scale}" r="${5 * scale}" fill="${led}" filter="url(#glow)"/>
      <rect x="${x + w - 30 * scale}" y="${y + h - 20 * scale}" width="${18 * scale}" height="${7 * scale}" rx="2" fill="#0b0b10"/>`;
  }
  // Front-on drum with a glowing ring inside the shell.
  function drumSVG(cx, cy, r, color, lit = true) {
    return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="#15151f" stroke="#3a3a52" stroke-width="${Math.max(2, r * 0.08)}"/>
      ${lit ? `<circle cx="${cx}" cy="${cy}" r="${r * 0.84}" fill="none" stroke="${color}" stroke-width="${r * 0.18}" opacity=".55" filter="url(#bigglow)"/>` : ""}
      <circle cx="${cx}" cy="${cy}" r="${r * 0.84}" fill="${lit ? color : "none"}" fill-opacity=".08" stroke="${lit ? color : "#3a3a50"}" stroke-width="${Math.max(1.5, r * 0.05)}" stroke-dasharray="${r * 0.04} ${r * 0.06}"/>
      <circle cx="${cx}" cy="${cy}" r="${r * 0.6}" fill="#e9e8f0" fill-opacity=".05"/>`;
  }
  function drumKitSVG() {
    return drumSVG(160, 118, 52, "#ff3d9a") + drumSVG(104, 62, 26, "#00d2c8") + drumSVG(160, 46, 22, "#7a6bff", false) +
      drumSVG(216, 62, 26, "#ffb547") + drumSVG(58, 132, 30, "#2ab7ff") + drumSVG(262, 132, 32, "#ff6a5c");
  }
  // Guitar neck seen from the player's side, LEDs along the top edge.
  function neckSVG(x, y, w, frets = 12, lit = [1, 3, 5, 7, 9]) {
    const fw = w / frets;
    let s = `<path d="M${x - 46} ${y - 8} l40 -6 l6 52 l-40 6z" fill="#2a2030" stroke="#3a3a52"/>`;
    s += `<rect x="${x}" y="${y}" width="${w}" height="38" rx="3" fill="#3b2a22"/>`;
    for (let i = 1; i <= frets; i++) s += `<rect x="${x + i * fw - 1}" y="${y}" width="2" height="38" fill="#c9c6d6"/>`;
    [3, 5, 7, 9].forEach((f) => { if (f <= frets) s += `<circle cx="${x + (f - 0.5) * fw}" cy="${y + 19}" r="2.6" fill="#e9e3d6" opacity=".8"/>`; });
    for (let i = 0; i < 6; i++) s += `<line x1="${x - 4}" y1="${y + 4 + i * 6}" x2="${x + w}" y2="${y + 4 + i * 6}" stroke="#d9d6e3" stroke-width="${0.6 + i * 0.18}" opacity=".85"/>`;
    s += `<rect x="${x}" y="${y - 7}" width="${w}" height="6" rx="3" fill="#22222f" stroke="#33334a"/>`;
    for (let i = 0; i < frets; i++) {
      const on = lit.includes(i), c = HUES[i % HUES.length];
      s += `<circle cx="${x + (i + 0.5) * fw}" cy="${y - 4}" r="2.4" fill="${on ? c : "#3a3a50"}"${on ? ' filter="url(#glow)"' : ""}/>`;
    }
    return s;
  }

  function productArt(p) {
    const W = 320, H = 180;
    let body = "";
    const id = p.id;
    if (id === "kit-complete" || id === "kit-stage") {
      body = stripSVG(70, 200, 28, 30) + keyboardSVG(84, 200, 30) + hubSVG(272, 104, 0.62);
      if (id === "kit-stage") body = `<rect x="30" y="30" width="200" height="8" rx="4" fill="#ff3d9a" opacity=".85" filter="url(#glow)"/>` + body;
    } else if (id === "strip") body = stripSVG(62, 260, 36, 30) + keyboardSVG(78, 260, 30);
    else if (id === "kit-drums") body = drumKitSVG();
    else if (id === "drum-ring") body = drumSVG(160, 90, 68, "#ff3d9a");
    else if (id === "kit-guitar") body = neckSVG(70, 74, 200, 10) + hubSVG(270, 140, 0.5, "Guitar", "#ff3d9a");
    else if (id === "fret-strip") body = neckSVG(60, 72, 240, 12, [0, 2, 4, 6, 8, 11]);
    else if (id === "ambient-bar") {
      body = `<rect x="30" y="84" width="260" height="12" rx="6" fill="#22222f" stroke="#33334a"/>` +
        Array.from({ length: 36 }, (_, i) => `<circle cx="${38 + i * 7.1}" cy="90" r="2.2" fill="hsl(${300 + i * 2},100%,62%)" filter="url(#glow)"/>`).join("");
    } else if (id === "hub") body = hubSVG(160, 90, 1.5);
    else if (id === "hub-pro") body = hubSVG(160, 84, 1.5, "Hub Pro") + `<text x="160" y="160" text-anchor="middle" fill="#ffb547" font-family="Inter, sans-serif" font-size="11" font-weight="600">+ USB MIDI HOST</text>`;
    else if (id === "drum-hub") {
      body = hubSVG(160, 84, 1.7, "Drum Hub", "#ff3d9a") + Array.from({ length: 8 }, (_, i) => `<circle cx="${104 + i * 16}" cy="152" r="4" fill="#0b0b10" stroke="#3a3a52"/>`).join("");
    } else if (id === "guitar-hub") {
      body = `<rect x="122" y="40" width="76" height="100" rx="18" fill="#1f1f2c" stroke="#3a3a52" stroke-width="1.5"/><rect x="146" y="30" width="28" height="16" rx="4" fill="#2d2d40"/>
        <text x="160" y="104" text-anchor="middle" fill="#9a99ad" font-family="Space Grotesk, sans-serif" font-size="11" font-weight="700">Guitar</text>
        <circle cx="160" cy="72" r="7" fill="#ff3d9a" filter="url(#glow)"/><rect x="150" y="122" width="20" height="6" rx="2" fill="#0b0b10"/>`;
    } else if (id === "hit-sensor") {
      body = `<path d="M70 120 h180" stroke="#3a3a52" stroke-width="10" stroke-linecap="round"/><rect x="132" y="82" width="56" height="34" rx="8" fill="#1f1f2c" stroke="#3a3a52"/>
        <circle cx="160" cy="99" r="9" fill="#ffb547" filter="url(#glow)"/><path d="M188 99 C 230 99, 230 60, 270 60" stroke="#3a3a52" stroke-width="4" fill="none"/>`;
    } else if (id === "psu" || id === "psu-8a") {
      body = `<rect x="110" y="56" width="62" height="70" rx="10" fill="#1f1f2c" stroke="#3a3a52" stroke-width="1.5"/><rect x="128" y="74" width="8" height="18" rx="2" fill="#555"/><rect x="146" y="74" width="8" height="18" rx="2" fill="#555"/><text x="141" y="114" text-anchor="middle" fill="#9a99ad" font-family="Inter, sans-serif" font-size="10" font-weight="700">${id === "psu" ? "4 A" : "8 A"}</text><path d="M172 104 C 220 104, 200 140, 250 130" stroke="#3a3a52" stroke-width="5" fill="none"/><circle cx="252" cy="130" r="6" fill="#00d2c8"/>`;
    } else if (id === "ext-cable") {
      body = `<path d="M60 120 C 120 30, 200 160, 260 70" stroke="#3a3a52" stroke-width="6" fill="none"/><rect x="44" y="112" width="24" height="16" rx="3" fill="#00d2c8"/><rect x="252" y="62" width="24" height="16" rx="3" fill="#ff3d9a"/>`;
    } else if (p.category === "software") {
      body = `<rect x="40" y="26" width="240" height="132" rx="10" fill="#0b0b10" stroke="#3a3a52"/><rect x="40" y="26" width="240" height="18" rx="10" fill="#1f1f2c"/>
        <circle cx="54" cy="35" r="3" fill="#ff6a5c"/><circle cx="64" cy="35" r="3" fill="#ffb547"/><circle cx="74" cy="35" r="3" fill="#00d2c8"/>` +
        (id === "sw-coach"
          ? [30, 52, 40, 70, 58, 84, 76].map((h, i) => `<rect x="${70 + i * 28}" y="${146 - h}" width="16" height="${h}" rx="3" fill="${h > 60 ? "#00d2c8" : "#ff3d9a"}" opacity=".9"/>`).join("")
          : `<g transform="translate(58 60) scale(.42)">${keyboardSVG(40, 160, 0)}</g><g transform="translate(140 52) scale(.3)">${drumKitSVG()}</g><g transform="translate(118 116) scale(.5)">${neckSVG(60, 20, 240, 12)}</g>`);
    }
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(p.name)} illustration">${DEFS}${body}</svg>`;
  }

  const INSTRUMENT_ART = {
    keys: () => stripSVG(66, 260, 36, 30) + keyboardSVG(82, 260, 30),
    drums: drumKitSVG,
    guitar: () => neckSVG(64, 72, 236, 12, [0, 2, 4, 6, 8, 11]),
  };
  function renderInstrumentArt() {
    $$("[data-art]").forEach((el) => {
      const f = INSTRUMENT_ART[el.dataset.art];
      if (f) el.innerHTML = `<svg viewBox="0 0 320 180" aria-hidden="true">${DEFS}${f()}</svg>`;
    });
  }

  // ---------------------------------------------------------------- product cards
  const CAT_LABEL = Object.fromEntries(MFX.CATEGORIES.map((c) => [c.id, c.label]));
  const INST_LABEL = { keys: "Keys", drums: "Drums", guitar: "Guitar", all: "All instruments" };

  /** Group bundle parts for display: "5× DrumRing (10", 12", 14", 16", 22")". */
  function includesText(p, size) {
    const groups = [];
    MFX.partsOf(p, size).forEach((x) => {
      let g = groups.find((y) => y.id === x.id);
      if (!g) groups.push((g = { id: x.id, qty: 0, sizes: [] }));
      g.qty += x.qty;
      if (x.size != null) g.sizes.push(MFX.sizeOption(MFX.byId[x.id].sizeKind, x.size).label);
    });
    return groups.map((g) => `${g.qty > 1 ? `${g.qty}× ` : ""}<b>${esc(MFX.byId[g.id].name)}</b>${g.sizes.length ? ` (${esc(g.sizes.join(", "))})` : ""}`).join(", ");
  }

  function productCard(p, size) {
    const s = MFX.sizeFor(p, size);
    const price = MFX.priceOf(p, s);
    const parts = MFX.partsPriceOf(p, s);
    const soon = p.status === "coming-soon", pre = p.status === "preorder";
    const badge = soon ? `<span class="product-badge soon">Coming soon</span>`
      : p.free ? `<span class="product-badge free">Free</span>`
      : p.badge ? `<span class="product-badge${pre ? " pre" : ""}">${esc(p.badge)}</span>`
      : pre ? `<span class="product-badge pre">Pre-order</span>` : "";

    const kind = p.sizeKind && MFX.SIZE_KINDS[p.sizeKind];
    const action = p.free ? `<a class="btn btn-ghost btn-sm" href="${esc(p.href)}">Get it free</a>`
      : soon ? `<button class="btn btn-ghost btn-sm" type="button" data-notify>Notify me</button>`
      : `<button class="btn btn-primary btn-sm" type="button" data-add>${pre ? "Pre-order" : "Add to cart"}</button>`;
    const priceHTML = p.free ? `<div class="price">Free</div>`
      : `<div class="price">${soon ? "~" : ""}${money(price)}${parts > price ? `<small>${money(parts)}</small><span class="save">Save ${money(parts - price)}</span>` : ""}</div>`;

    return `
      <article class="card product-card" data-product="${p.id}" data-size="${s ?? ""}">
        <div class="product-media">${badge}${productArt(p)}</div>
        <div class="product-body">
          <span class="product-cat">${esc(INST_LABEL[p.instrument])} · ${esc(CAT_LABEL[p.category])}</span>
          <h3>${esc(p.name)}</h3>
          <p class="product-tagline">${esc(p.tagline)}</p>
          ${p.category === "bundle" ? `<p class="product-includes">Includes: ${includesText(p, s)}</p>` : ""}
          <ul class="product-features">${p.features.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
          ${kind ? `<div class="size-picker" role="group" aria-label="${esc(kind.label)}"><span class="size-picker-label">${esc(kind.label)}</span>
            ${kind.options.filter((o) => !p.sizes || o.value in p.sizes).map((o) => `<button type="button" class="size-chip" data-pick="${o.value}" aria-pressed="${String(o.value) === String(s)}">${esc(o.label)}</button>`).join("")}</div>` : ""}
          <div class="product-foot">${priceHTML}${action}</div>
        </div>
      </article>`;
  }

  function wireProductGrid(grid, onSize) {
    grid.addEventListener("click", (e) => {
      const card = e.target.closest("[data-product]");
      if (!card) return;
      const p = MFX.byId[card.dataset.product];
      const size = card.dataset.size === "" ? null : MFX.sizeFor(p, card.dataset.size);
      const chip = e.target.closest("[data-pick]");
      if (chip) {
        const next = MFX.sizeFor(p, chip.dataset.pick);
        const tmp = document.createElement("div");
        tmp.innerHTML = productCard(p, next).trim();
        card.replaceWith(tmp.firstChild);
        onSize?.(p.sizeKind, next);
        return;
      }
      if (e.target.closest("[data-add]")) {
        cart.add(p.id, size);
        const label = sizeLong(p, size);
        toast(`${p.status === "preorder" ? "Pre-ordered" : "Added"} ${p.name}${label ? ` (${label})` : ""}`);
      }
      if (e.target.closest("[data-notify]")) {
        document.getElementById("signup")?.scrollIntoView({ behavior: "smooth" });
        toast(`We'll let you know when ${p.name} is available.`);
      }
    });
  }

  // ---------------------------------------------------------------- pages
  function initFeatured() {
    const grid = $("#featured-grid");
    if (!grid) return;
    grid.innerHTML = ["kit-complete", "kit-drums", "kit-guitar"].map((id) => productCard(MFX.byId[id])).join("");
    wireProductGrid(grid);
  }

  function initShop() {
    const grid = $("#shop-grid");
    if (!grid) return;
    const params = new URLSearchParams(location.search);
    const valid = (list, v) => (list.some((x) => x.id === v) ? v : "all");
    let inst = valid(MFX.INSTRUMENTS, params.get("inst"));
    let cat = valid(MFX.CATEGORIES, params.get("cat"));
    // Remembered size per size kind, so e.g. a 61-key choice carries across keyboard products.
    const sizes = {};

    const instTabs = $("#inst-tabs"), catTabs = $("#filter-tabs");
    instTabs.innerHTML = MFX.INSTRUMENTS.map((i) => `<button class="inst-tab" role="tab" type="button" data-inst="${i.id}">${i.label}</button>`).join("");
    catTabs.innerHTML = MFX.CATEGORIES.map((c) => `<button class="filter-tab" role="tab" type="button" data-cat="${c.id}">${c.label}</button>`).join("");

    function render() {
      const list = MFX.PRODUCTS.filter((p) =>
        (inst === "all" || p.instrument === inst || p.instrument === "all") && (cat === "all" || p.category === cat));
      grid.innerHTML = list.length
        ? list.map((p) => productCard(p, p.sizeKind ? sizes[p.sizeKind] : null)).join("")
        : `<p class="muted">Nothing in this category for ${esc(INST_LABEL[inst])} yet.</p>`;
      $$("[data-inst]", instTabs).forEach((t) => t.setAttribute("aria-selected", String(t.dataset.inst === inst)));
      $$("[data-cat]", catTabs).forEach((t) => t.setAttribute("aria-selected", String(t.dataset.cat === cat)));
      const url = new URL(location.href);
      inst === "all" ? url.searchParams.delete("inst") : url.searchParams.set("inst", inst);
      cat === "all" ? url.searchParams.delete("cat") : url.searchParams.set("cat", cat);
      history.replaceState(null, "", url);
      $$(".nav-links a").forEach((a) => {
        const m = a.getAttribute("href").match(/inst=(\w+)/);
        if (m) m[1] === inst ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current");
      });
      $$("[data-guide]").forEach((g) => { g.hidden = inst !== "all" && g.dataset.guide !== inst; });
    }
    instTabs.addEventListener("click", (e) => { const t = e.target.closest("[data-inst]"); if (t) { inst = t.dataset.inst; render(); } });
    catTabs.addEventListener("click", (e) => { const t = e.target.closest("[data-cat]"); if (t) { cat = t.dataset.cat; render(); } });
    // Nav links to other instruments stay on this page.
    document.addEventListener("click", (e) => {
      const a = e.target.closest('.nav-links a[href^="shop.html?inst="]');
      if (!a) return;
      e.preventDefault();
      inst = a.getAttribute("href").split("=")[1]; cat = "all"; render();
      scrollTo({ top: 0, behavior: "smooth" });
    });
    wireProductGrid(grid, (kind, value) => { sizes[kind] = value; });
    render();

    // Size guides
    const S = MFX.SIZE_KINDS, P = MFX.priceOf, B = MFX.byId;
    const guides = {
      keys: { kind: "keys", head: ["Keys", "Typical keyboards", "LEDs", "Strip length", "LightStrip", "Complete Kit"],
        row: (o) => [o.label, o.examples, o.leds, `~${o.lengthCm} cm`, money(P(B.strip, o.value)), money(P(B["kit-complete"], o.value))] },
      drums: { kind: "drum", head: ["Diameter", "Typically", "LEDs", "Ring length", "DrumRing"],
        row: (o) => [o.label, o.examples, o.leds, `~${o.lengthCm} cm`, money(P(B["drum-ring"], o.value))] },
      drumkits: { kind: "drumkit", head: ["Kit", "Drums", "DrumRings", "Drums Complete Kit"],
        row: (o) => [o.label, o.examples, o.drums.length, money(P(B["kit-drums"], o.value))] },
      guitar: { kind: "neck", head: ["Neck", "Fits", "LEDs", "FretStrip", "Guitar Complete Kit"],
        row: (o) => [o.label, o.examples, o.leds, money(P(B["fret-strip"], o.value)), money(P(B["kit-guitar"], o.value))] },
    };
    $$("[data-guide-table]").forEach((tbl) => {
      const g = guides[tbl.dataset.guideTable];
      tbl.innerHTML = `<thead><tr>${g.head.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
        <tbody>${S[g.kind].options.map((o) => `<tr>${g.row(o).map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody>`;
    });
  }

  function initSignup() {
    const form = $("#signup-form");
    if (!form) return;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const email = form.email.value.trim();
      const note = $("#signup-note");
      if (!/^\S+@\S+\.\S+$/.test(email)) { note.textContent = "Please enter a valid email address."; return; }
      // TODO: post to the mailing-list provider (Mailchimp / Buttondown / ConvertKit form endpoint).
      note.textContent = "Thanks! You're on the list — we'll email you at launch.";
      form.reset();
    });
  }

  // ---------------------------------------------------------------- hero animation
  // A keyboard with an LED strip above it; notes rise as glowing bars and the
  // matching LEDs light up.
  function initHero() {
    const canvas = $("#hero-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const WHITE = 21;
    const BLACK_AFTER = [0, 1, 3, 4, 5];
    let W, H, dpr, keys = [];

    function layout() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const r = canvas.getBoundingClientRect();
      W = r.width; H = r.height;
      canvas.width = W * dpr; canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const pad = W * 0.05, kw = (W - pad * 2) / WHITE;
      keys = [];
      for (let i = 0; i < WHITE; i++) keys.push({ x: pad + i * kw, w: kw, black: false });
      for (let i = 0; i < WHITE - 1; i++) if (BLACK_AFTER.includes(i % 7)) keys.push({ x: pad + (i + 1) * kw - kw * 0.3, w: kw * 0.6, black: true });
      keys.forEach((k) => { k.hue = 175 + ((k.x - pad) / (W - pad * 2)) * 160; k.level = 0; });
      notes.length = 0;
    }

    const notes = [];
    let t = 0, nextAt = 0;
    const kbTop = () => H * 0.7, stripY = () => H * 0.7 - 12;

    function spawn() {
      const pool = keys.filter((k) => !notes.some((n) => n.key === k && n.held));
      const k = pool[Math.floor(Math.random() * pool.length)];
      if (k) notes.push({ key: k, y: kbTop(), len: 0, held: true, dur: 18 + Math.random() * 50, age: 0 });
    }
    function step() {
      t++;
      if (t >= nextAt) { spawn(); if (Math.random() < 0.35) spawn(); nextAt = t + 8 + Math.random() * 22; }
      const speed = H / 260;
      for (let i = notes.length - 1; i >= 0; i--) {
        const n = notes[i];
        n.age++;
        if (n.held) { n.len += speed; if (n.age > n.dur) n.held = false; } else n.y -= speed;
        if (n.y < -20) notes.splice(i, 1);
        else if (n.held) n.key.level = 1;
      }
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);
      notes.forEach((n) => {
        const k = n.key, x = k.x + k.w * 0.14, w = k.w * 0.72, top = n.y - n.len;
        const g = ctx.createLinearGradient(0, top, 0, n.y);
        g.addColorStop(0, `hsla(${k.hue},100%,62%,0.05)`);
        g.addColorStop(1, `hsla(${k.hue},100%,62%,0.95)`);
        ctx.shadowColor = `hsl(${k.hue},100%,60%)`; ctx.shadowBlur = 18;
        ctx.fillStyle = g;
        roundRect(x, top, w, n.len, Math.min(6, w / 2));
        ctx.shadowBlur = 0;
      });

      const sy = stripY();
      ctx.fillStyle = "#1a1a26"; roundRect(keys[0].x - 4, sy - 6, W - keys[0].x * 2 + 8, 12, 6);
      const ww = keys[0].w;
      for (let i = 0; i < WHITE * 2; i++) {
        const lx = keys[0].x + (i + 0.5) * (ww / 2);
        const k = keys.reduce((best, kk) => (Math.abs(kk.x + kk.w / 2 - lx) < Math.abs(best.x + best.w / 2 - lx) ? kk : best), keys[0]);
        const lvl = k.level;
        ctx.fillStyle = lvl > 0.02 ? `hsla(${k.hue},100%,${45 + lvl * 20}%,${0.35 + lvl * 0.65})` : "#33334a";
        if (lvl > 0.02) { ctx.shadowColor = `hsl(${k.hue},100%,60%)`; ctx.shadowBlur = 14 * lvl; }
        ctx.beginPath(); ctx.arc(lx, sy, 2.6, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
      }

      const ky = kbTop(), kh = H * 0.26;
      keys.filter((k) => !k.black).forEach((k) => {
        ctx.fillStyle = k.level > 0.02 ? `hsl(${k.hue},70%,${92 - k.level * 22}%)` : "#ecebf3";
        roundRect(k.x + 1, ky, k.w - 2, kh, 4);
      });
      keys.filter((k) => k.black).forEach((k) => {
        ctx.fillStyle = k.level > 0.02 ? `hsl(${k.hue},80%,${18 + k.level * 30}%)` : "#14141c";
        roundRect(k.x, ky, k.w, kh * 0.6, 3);
      });
    }

    function frame() {
      step(); draw();
      keys.forEach((k) => { k.level *= 0.9; });
      requestAnimationFrame(frame);
    }
    function roundRect(x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); ctx.fill();
    }

    layout();
    addEventListener("resize", () => { layout(); if (reduce) still(); });
    function still() { for (let i = 0; i < 240; i++) step(); draw(); }
    reduce ? still() : requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- boot
  renderChrome();
  renderCart();
  renderInstrumentArt();
  initFeatured();
  initShop();
  initSignup();
  initHero();
})();
