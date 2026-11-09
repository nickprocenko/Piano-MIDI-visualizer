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
    { href: "index.html", label: "Home", page: "home" },
    { href: "shop.html", label: "Shop", page: "shop" },
    { href: "software.html", label: "Software & Apps", page: "software" },
    { href: "shop.html#size-guide", label: "Size Guide", page: "size" },
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
    const page = document.body.dataset.page;
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
            <p style="margin-top:14px;max-width:300px">Lights, visuals and practice tools that react to every note you play.</p>
          </div>
          <div><h4>Shop</h4><ul>
            <li><a href="shop.html?cat=bundle">Bundles</a></li>
            <li><a href="shop.html?cat=led">LED Strips</a></li>
            <li><a href="shop.html?cat=controller">Controllers</a></li>
            <li><a href="shop.html?cat=accessory">Accessories</a></li>
          </ul></div>
          <div><h4>Software</h4><ul>
            <li><a href="../">Launch Visualizer</a></li>
            <li><a href="software.html#coach">Practice Coach</a></li>
            <li><a href="software.html#firmware">Hub Firmware</a></li>
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

    // Cart drawer + toast
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
  const CART_KEY = "musicfx.cart.v1";
  const cart = {
    items: load(),
    add(id, keys) {
      const key = keys || null;
      const line = this.items.find((i) => i.id === id && i.keys === key);
      if (line) line.qty += 1;
      else this.items.push({ id, keys: key, qty: 1 });
      this.save();
    },
    setQty(index, qty) {
      if (qty <= 0) this.items.splice(index, 1);
      else this.items[index].qty = qty;
      this.save();
    },
    total() {
      return this.items.reduce((sum, i) => sum + MFX.priceOf(MFX.byId[i.id], i.keys) * i.qty, 0);
    },
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
        const unit = MFX.priceOf(p, i.keys);
        return `
          <div class="cart-item">
            <div>
              <div class="cart-item-name">${esc(p.name)}</div>
              <div class="cart-item-meta">${i.keys ? `${i.keys}-key` : esc(p.tagline)}${p.includes ? " · bundle" : ""}</div>
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

  // ---------------------------------------------------------------- product art
  // Simple inline illustrations so the shop works before real photos exist.
  // Swap for <img> product shots by adding an `image` field in catalog.js.
  function keyboardSVG(y, w, x = 20) {
    const white = 14, ww = w / white;
    let s = `<rect x="${x}" y="${y}" width="${w}" height="46" rx="4" fill="#e9e8f0"/>`;
    for (let i = 1; i < white; i++) s += `<line x1="${x + i * ww}" y1="${y}" x2="${x + i * ww}" y2="${y + 46}" stroke="#b9b8c6" stroke-width="1"/>`;
    [0, 1, 3, 4, 5, 7, 8, 10, 11, 12].forEach((i) => { s += `<rect x="${x + (i + 1) * ww - ww * 0.3}" y="${y}" width="${ww * 0.6}" height="28" rx="2" fill="#16161e"/>`; });
    return s;
  }
  function stripSVG(y, w, n, x = 20) {
    let s = `<rect x="${x - 4}" y="${y - 7}" width="${w + 8}" height="14" rx="7" fill="#22222f" stroke="#33334a"/>`;
    const colors = ["#00d2c8", "#2ab7ff", "#7a6bff", "#ff3d9a", "#ff6a5c", "#ffb547"];
    for (let i = 0; i < n; i++) {
      const c = colors[Math.floor((i / n) * colors.length)];
      const on = [2, 3, 7, 11, 12, 16, 20, 21, 25].includes(i % 28);
      s += `<circle cx="${x + 4 + (i * (w - 8)) / (n - 1)}" cy="${y}" r="2.6" fill="${on ? c : "#3a3a50"}"${on ? ` filter="url(#glow)"` : ""}/>`;
    }
    return s;
  }
  const DEFS = `<defs><filter id="glow" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <linearGradient id="beam" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-opacity=".9"/><stop offset="1" stop-opacity="0"/></linearGradient></defs>`;
  function hubSVG(cx, cy, scale = 1) {
    const w = 96 * scale, h = 58 * scale, x = cx - w / 2, y = cy - h / 2;
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${12 * scale}" fill="#1f1f2c" stroke="#3a3a52" stroke-width="1.5"/>
      <rect x="${x + 12 * scale}" y="${y + 12 * scale}" width="${34 * scale}" height="${6 * scale}" rx="3" fill="#2d2d40"/>
      <text x="${x + 12 * scale}" y="${y + h - 14 * scale}" fill="#9a99ad" font-family="Space Grotesk, sans-serif" font-size="${11 * scale}" font-weight="700">MusicFX</text>
      <circle cx="${x + w - 18 * scale}" cy="${y + 18 * scale}" r="${5 * scale}" fill="#00d2c8" filter="url(#glow)"/>
      <rect x="${x + w - 30 * scale}" y="${y + h - 20 * scale}" width="${18 * scale}" height="${7 * scale}" rx="2" fill="#0b0b10"/>`;
  }

  function productArt(p) {
    const W = 320, H = 180;
    let body = "";
    switch (p.category) {
      case "bundle":
        body = stripSVG(70, 200, 28, 30) + keyboardSVG(84, 200, 30) + hubSVG(272, 104, 0.62);
        if (p.includes.includes("ambient-bar")) body = `<rect x="30" y="30" width="200" height="8" rx="4" fill="#ff3d9a" opacity=".85" filter="url(#glow)"/>` + body;
        break;
      case "led":
        if (p.id === "ambient-bar") {
          body = `<rect x="30" y="84" width="260" height="12" rx="6" fill="#22222f" stroke="#33334a"/>` +
            Array.from({ length: 36 }, (_, i) => `<circle cx="${38 + i * 7.1}" cy="90" r="2.2" fill="hsl(${300 + i * 2},100%,62%)" filter="url(#glow)"/>`).join("") +
            `<rect x="30" y="96" width="260" height="50" fill="url(#beam)" style="color:#ff3d9a" opacity=".18"/>`;
        } else {
          body = stripSVG(62, 260, 36, 30) + keyboardSVG(78, 260, 30);
        }
        break;
      case "controller":
        body = hubSVG(160, 90, 1.5) + (p.status ? `<text x="160" y="160" text-anchor="middle" fill="#ffb547" font-family="Inter, sans-serif" font-size="11" font-weight="600">+ USB MIDI HOST</text>` : "");
        break;
      case "accessory":
        body = p.id === "psu"
          ? `<rect x="110" y="56" width="62" height="70" rx="10" fill="#1f1f2c" stroke="#3a3a52" stroke-width="1.5"/><rect x="128" y="74" width="8" height="18" rx="2" fill="#555"/><rect x="146" y="74" width="8" height="18" rx="2" fill="#555"/><path d="M172 104 C 220 104, 200 140, 250 130" stroke="#3a3a52" stroke-width="5" fill="none"/><circle cx="252" cy="130" r="6" fill="#00d2c8"/>`
          : `<path d="M60 120 C 120 30, 200 160, 260 70" stroke="#3a3a52" stroke-width="6" fill="none"/><rect x="44" y="112" width="24" height="16" rx="3" fill="#00d2c8"/><rect x="252" y="62" width="24" height="16" rx="3" fill="#ff3d9a"/>`;
        break;
      case "software":
        body = `<rect x="40" y="26" width="240" height="132" rx="10" fill="#0b0b10" stroke="#3a3a52"/><rect x="40" y="26" width="240" height="18" rx="10" fill="#1f1f2c"/>
          <circle cx="54" cy="35" r="3" fill="#ff6a5c"/><circle cx="64" cy="35" r="3" fill="#ffb547"/><circle cx="74" cy="35" r="3" fill="#00d2c8"/>` +
          (p.id === "sw-coach"
            ? [30, 52, 40, 70, 58, 84, 76].map((h, i) => `<rect x="${70 + i * 28}" y="${146 - h}" width="16" height="${h}" rx="3" fill="${h > 60 ? "#00d2c8" : "#ff3d9a"}" opacity=".9"/>`).join("")
            : [[70, 60], [100, 82], [130, 50], [170, 90], [200, 66], [240, 76]].map(([x, h], i) => `<rect x="${x}" y="${132 - h}" width="12" height="${h}" rx="6" fill="hsl(${175 + i * 30},100%,60%)" filter="url(#glow)"/>`).join("") +
              keyboardSVG(132, 220, 50).replace(/height="46"/, 'height="22"').replace(/height="28"/g, 'height="13"'));
        break;
    }
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(p.name)} illustration">${DEFS}${body}</svg>`;
  }

  // ---------------------------------------------------------------- product cards
  const CAT_LABEL = Object.fromEntries(MFX.CATEGORIES.map((c) => [c.id, c.label]));
  const DEFAULT_KEYS = 88;

  function productCard(p, keys) {
    const sized = MFX.isSized(p);
    const k = sized ? keys || DEFAULT_KEYS : undefined;
    const price = MFX.priceOf(p, k);
    const parts = MFX.partsPriceOf(p, k);
    const soon = p.status === "coming-soon";
    const badge = soon ? `<span class="product-badge soon">Coming soon</span>`
      : p.free ? `<span class="product-badge free">Free</span>`
      : p.badge ? `<span class="product-badge">${esc(p.badge)}</span>` : "";

    const sizes = sized ? (p.sizes ? p.sizes.map((s) => s.keys) : MFX.KEYBOARD_SIZES.map((s) => s.keys)) : [];
    const includes = p.includes
      ? `<p class="product-includes">Includes: ${p.includes.map((id) => `<b>${esc(MFX.byId[id].name)}</b>${MFX.isSized(MFX.byId[id]) ? ` (${k}-key)` : ""}`).join(", ")}</p>`
      : "";

    const action = p.free
      ? `<a class="btn btn-ghost btn-sm" href="${esc(p.href)}">Get it free</a>`
      : soon
        ? `<button class="btn btn-ghost btn-sm" type="button" data-notify="${p.id}">Notify me</button>`
        : `<button class="btn btn-primary btn-sm" type="button" data-add="${p.id}">Add to cart</button>`;

    const priceHTML = p.free ? `<div class="price">Free</div>`
      : `<div class="price">${soon ? "~" : ""}${money(price)}${parts > price ? `<small>${money(parts)}</small><span class="save">Save ${money(parts - price)}</span>` : ""}</div>`;

    return `
      <article class="card product-card" data-product="${p.id}" data-keys="${k || ""}">
        <div class="product-media">${badge}${productArt(p)}</div>
        <div class="product-body">
          <span class="product-cat">${esc(CAT_LABEL[p.category])}</span>
          <h3>${esc(p.name)}</h3>
          <p class="product-tagline">${esc(p.tagline)}</p>
          ${includes}
          <ul class="product-features">${p.features.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
          ${sized ? `<div class="size-picker" role="group" aria-label="Keyboard size"><span class="size-picker-label">Keyboard size</span>
            ${sizes.map((s) => `<button type="button" class="size-chip" data-size="${s}" aria-pressed="${s === k}">${s}</button>`).join("")}</div>` : ""}
          <div class="product-foot">${priceHTML}${action}</div>
        </div>
      </article>`;
  }

  function wireProductGrid(grid, getKeys) {
    grid.addEventListener("click", (e) => {
      const card = e.target.closest("[data-product]");
      if (!card) return;
      const p = MFX.byId[card.dataset.product];
      const chip = e.target.closest("[data-size]");
      if (chip) {
        const tmp = document.createElement("div");
        tmp.innerHTML = productCard(p, Number(chip.dataset.size)).trim();
        card.replaceWith(tmp.firstChild);
        return;
      }
      if (e.target.closest("[data-add]")) {
        const keys = card.dataset.keys ? Number(card.dataset.keys) : null;
        cart.add(p.id, keys);
        toast(`Added ${p.name}${keys ? ` (${keys}-key)` : ""} to cart`);
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
    const ids = ["kit-complete", "strip", "hub"];
    grid.innerHTML = ids.map((id) => productCard(MFX.byId[id])).join("");
    wireProductGrid(grid);
  }

  function initShop() {
    const grid = $("#shop-grid");
    if (!grid) return;
    const params = new URLSearchParams(location.search);
    let cat = MFX.CATEGORIES.some((c) => c.id === params.get("cat")) ? params.get("cat") : "all";
    let keys = Number(params.get("size")) || DEFAULT_KEYS;
    if (!MFX.KEYBOARD_SIZES.some((s) => s.keys === keys)) keys = DEFAULT_KEYS;

    const tabs = $("#filter-tabs");
    tabs.innerHTML = MFX.CATEGORIES.map((c) => `<button class="filter-tab" role="tab" type="button" data-cat="${c.id}" aria-selected="${c.id === cat}">${c.label}</button>`).join("");
    const select = $("#global-size");
    select.innerHTML = MFX.KEYBOARD_SIZES.map((s) => `<option value="${s.keys}"${s.keys === keys ? " selected" : ""}>${s.keys} keys</option>`).join("");

    function render() {
      const list = MFX.PRODUCTS.filter((p) => cat === "all" || p.category === cat);
      grid.innerHTML = list.map((p) => productCard(p, keys)).join("");
      $$(".filter-tab", tabs).forEach((t) => t.setAttribute("aria-selected", String(t.dataset.cat === cat)));
      const url = new URL(location.href);
      cat === "all" ? url.searchParams.delete("cat") : url.searchParams.set("cat", cat);
      keys === DEFAULT_KEYS ? url.searchParams.delete("size") : url.searchParams.set("size", keys);
      history.replaceState(null, "", url);
    }
    tabs.addEventListener("click", (e) => { const t = e.target.closest("[data-cat]"); if (t) { cat = t.dataset.cat; render(); } });
    select.addEventListener("change", () => { keys = Number(select.value); render(); });
    wireProductGrid(grid);
    render();

    const tbody = $("#size-guide-body");
    if (tbody) {
      const strip = MFX.byId.strip, kit = MFX.byId["kit-complete"];
      tbody.innerHTML = MFX.KEYBOARD_SIZES.map((s) => `
        <tr>
          <td>${s.keys}</td><td>${s.examples}</td><td>${s.leds}</td><td>~${s.lengthCm} cm</td>
          <td>${money(MFX.priceOf(strip, s.keys))}</td><td>${money(MFX.priceOf(kit, s.keys))}</td>
          <td><a href="shop.html?cat=bundle&size=${s.keys}" data-pick-size="${s.keys}">Shop ${s.keys}-key →</a></td>
        </tr>`).join("");
      tbody.addEventListener("click", (e) => {
        const a = e.target.closest("[data-pick-size]");
        if (!a) return;
        e.preventDefault();
        keys = Number(a.dataset.pickSize); cat = "bundle"; select.value = keys; render();
        $("#products").scrollIntoView({ behavior: "smooth" });
      });
    }
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
  // matching LEDs light up — the product in one picture.
  function initHero() {
    const canvas = $("#hero-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const WHITE = 21; // three octaves
    const BLACK_AFTER = [0, 1, 3, 4, 5]; // within each 7-white octave
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
      keys.forEach((k, i) => { k.hue = 175 + ((k.x - pad) / (W - pad * 2)) * 160; k.level = 0; k.id = i; });
    }

    const notes = [];
    let t = 0, nextAt = 0;
    const kbTop = () => H * 0.7, stripY = () => H * 0.7 - 12;

    function spawn() {
      const pool = keys.filter((k) => !notes.some((n) => n.key === k && n.held));
      const k = pool[Math.floor(Math.random() * pool.length)];
      if (!k) return;
      notes.push({ key: k, y: kbTop(), len: 0, held: true, dur: 18 + Math.random() * 50, age: 0 });
    }

    function frame() {
      t++;
      if (t >= nextAt) { spawn(); if (Math.random() < 0.35) spawn(); nextAt = t + 8 + Math.random() * 22; }
      ctx.clearRect(0, 0, W, H);
      const speed = H / 260;

      // rising notes
      for (let i = notes.length - 1; i >= 0; i--) {
        const n = notes[i];
        n.age++;
        if (n.held) { n.len += speed; if (n.age > n.dur) n.held = false; } else n.y -= speed;
        const top = n.y - n.len;
        if (n.y < -20) { notes.splice(i, 1); continue; }
        const k = n.key, x = k.x + k.w * 0.14, w = k.w * 0.72;
        const g = ctx.createLinearGradient(0, top, 0, n.y);
        g.addColorStop(0, `hsla(${k.hue},100%,62%,0.05)`);
        g.addColorStop(1, `hsla(${k.hue},100%,62%,0.95)`);
        ctx.shadowColor = `hsl(${k.hue},100%,60%)`; ctx.shadowBlur = 18;
        ctx.fillStyle = g;
        roundRect(x, top, w, n.len, Math.min(6, w / 2));
        ctx.shadowBlur = 0;
        if (n.held) k.level = 1;
      }

      // LED strip
      const sy = stripY();
      ctx.fillStyle = "#1a1a26"; roundRect(keys[0].x - 4, sy - 6, W - keys[0].x * 2 + 8, 12, 6);
      const whites = keys.filter((k) => !k.black);
      const ledN = WHITE * 2;
      for (let i = 0; i < ledN; i++) {
        const lx = whites[0].x + (i + 0.5) * (whites[0].w / 2);
        const k = keys.reduce((best, kk) => (Math.abs(kk.x + kk.w / 2 - lx) < Math.abs(best.x + best.w / 2 - lx) ? kk : best), keys[0]);
        const lvl = k.level;
        ctx.fillStyle = lvl > 0.02 ? `hsla(${k.hue},100%,${45 + lvl * 20}%,${0.35 + lvl * 0.65})` : "#33334a";
        if (lvl > 0.02) { ctx.shadowColor = `hsl(${k.hue},100%,60%)`; ctx.shadowBlur = 14 * lvl; }
        ctx.beginPath(); ctx.arc(lx, sy, 2.6, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
      }

      // keyboard
      const ky = kbTop(), kh = H * 0.26;
      keys.filter((k) => !k.black).forEach((k) => {
        ctx.fillStyle = k.level > 0.02 ? `hsl(${k.hue},70%,${92 - k.level * 22}%)` : "#ecebf3";
        roundRect(k.x + 1, ky, k.w - 2, kh, 4);
      });
      keys.filter((k) => k.black).forEach((k) => {
        ctx.fillStyle = k.level > 0.02 ? `hsl(${k.hue},80%,${18 + k.level * 30}%)` : "#14141c";
        roundRect(k.x, ky, k.w, kh * 0.6, 3);
      });
      keys.forEach((k) => { k.level *= 0.9; });

      if (!reduce) requestAnimationFrame(frame);
    }

    function roundRect(x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); ctx.fill();
    }

    layout();
    addEventListener("resize", layout);
    if (reduce) {
      // Static frame: pre-run the simulation so the still image shows notes in flight.
      for (let i = 0; i < 240; i++) { t++; if (t >= nextAt) { spawn(); nextAt = t + 12; } notes.forEach((n) => { n.age++; if (n.held) { n.len += H / 260; if (n.age > n.dur) n.held = false; } else n.y -= H / 260; }); }
      frame();
    } else requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- boot
  renderChrome();
  renderCart();
  initFeatured();
  initShop();
  initSignup();
  initHero();
})();
