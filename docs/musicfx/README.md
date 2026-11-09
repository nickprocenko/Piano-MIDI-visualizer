# MusicFX product website

Static marketing + shop site for MusicFX hardware (LED strips, controllers, accessories),
software and apps. No build step and no dependencies. It deploys with the rest of `docs/`
via GitHub Pages and is served at `/Piano-MIDI-visualizer/musicfx/`.

## Pages

| File | Purpose |
|------|---------|
| `index.html` | Home: hero, product ecosystem, how it works, featured products, software, FAQ, launch signup |
| `shop.html` | Full catalog with category filters, a global keyboard-size selector, per-card size chips, size guide and cart |
| `software.html` | Visualizer, Practice Coach, Hub firmware and streaming tools |

## Assets

| File | Purpose |
|------|---------|
| `assets/catalog.js` | **The product catalog**: names, sizes, prices, bundles. Edit products here. |
| `assets/app.js` | Shared header/footer, product cards and art, cart (saved in `localStorage`), hero animation |
| `assets/styles.css` | All styles; colour tokens at the top of `:root` |

### Catalog model

- **Sized products** (LightStrip) list a price per keyboard size: 25 / 49 / 61 / 76 / 88 keys.
- **Bundles** list the product ids they include plus a `discount`. Their price is always
  the sum of the parts at the chosen size, minus the discount, so changing a part's price
  updates every bundle.
- `status: "coming-soon"` shows a "Notify me" button instead of "Add to cart".
- `free: true` + `href` is for free software, which links out.

Shop URLs are shareable: `shop.html?cat=bundle&size=61`.

## Before launch (TODO)

- [ ] **Prices** in `catalog.js` are placeholders.
- [ ] **Checkout**: the "Checkout" button only shows a toast. Wire it to Stripe Checkout,
      Shopify Buy Button or similar (see `data-checkout` in `app.js`).
- [ ] **Email signup**: the form validates but doesn't send anything. Point it at a mailing-list
      provider (see `initSignup` in `app.js`).
- [ ] **Policies**: the shipping/returns/warranty cards on `shop.html` are placeholder copy.
      Confirm the terms, then add policy, privacy and contact pages.
- [ ] **Product photos**: cards use inline SVG illustrations. Replace them with real photos.
- [ ] **Hardware specs**: confirm strip lengths, LED type, PSU rating and the Hub Pro feature set.
- [ ] **Domain**: if MusicFX gets its own domain, move this folder to its own repo or Pages site.
