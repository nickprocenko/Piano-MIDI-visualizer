# MusicFX product website

Static marketing + shop site for MusicFX hardware for **keys, drums and guitar** (LED strips,
controllers, accessories), plus the one MusicFX app that runs them all. No build step and no dependencies. It deploys with the rest of `docs/`
via GitHub Pages and is served at `/Piano-MIDI-visualizer/musicfx/`.

## Pages

| File | Purpose |
|------|---------|
| `index.html` | Home: hero, instrument picker, product ecosystem, how it works, the three Complete Kits, software, FAQ, launch signup |
| `shop.html` | Full catalog with instrument tabs (`?inst=keys|drums|guitar`), category filters (`?cat=`), per-card size chips, per-instrument size guides and cart |
| `software.html` | Instrument modes (Keys / Drums / Guitar), Band Sync, Practice Coach, Hub firmware, streaming tools |

## Assets

| File | Purpose |
|------|---------|
| `assets/catalog.js` | **The product catalog**: names, sizes, prices, bundles. Edit products here. |
| `assets/app.js` | Shared header/footer, product cards and art, cart (saved in `localStorage`), hero animation |
| `assets/styles.css` | All styles; colour tokens at the top of `:root` |

### Catalog model

Every product has an `instrument` (`keys`, `drums`, `guitar` or `all`) and a `category`.

| Line | Lights | Controller | Kit sizes |
|------|--------|-----------|-----------|
| Keys | LightStrip (25/49/61/76/88 keys) | MusicFX Hub; Hub Pro (coming soon) | by key count |
| Drums | DrumRing inside each shell (8"–24") + Hit Sensors | Drum Hub (8 zones, trigger + MIDI in) | 4-piece / 5-piece / Fusion |
| Guitar | FretStrip on the fretboard's top edge (21/22/24 frets, acoustic, bass) | Guitar Hub (wireless) | by neck |

- **Sizes** live in `SIZE_KINDS` (`keys`, `drum`, `neck`, `drumkit`). Sized products list a
  price per size value.
- **Bundles** list their parts in `includes` (`size: "$"` = the bundle's chosen size) and, for
  drum kits, `includesBySize` (one DrumRing + Hit Sensor per drum in the configuration). Kit
  price = parts at that size − `discount`, so changing any part price updates every kit.
- `status: "preorder"` → "Pre-order" button (still goes in the cart). Drums and guitar are
  pre-order until their app modes ship. `status: "coming-soon"` → "Notify me", not purchasable.
- `free: true` + `href` is for free software, which links out.

## Before launch (TODO)

- [ ] **Prices** in `catalog.js` are placeholders.
- [ ] **Checkout**: the "Checkout" button only shows a toast. Wire it to Stripe Checkout,
      Shopify Buy Button or similar (see `data-checkout` in `app.js`).
- [ ] **Email signup**: the form validates but doesn't send anything. Point it at a mailing-list
      provider (see `initSignup` in `app.js`).
- [ ] **Policies**: the shipping/returns/warranty cards on `shop.html` are placeholder copy.
      Confirm the terms, then add policy, privacy and contact pages.
- [ ] **Product photos**: cards use inline SVG illustrations. Replace them with real photos.
- [ ] **Hardware specs**: confirm LED types/densities, DrumRing mounting and lengths, Hit Sensor design,
      FretStrip size per neck, Drum Hub zone count, Guitar Hub battery, PSU ratings, Hub Pro features.
- [ ] **Software status**: the Drums and Guitar modes and Band Sync are marked "in development" on
      `software.html`. Switch the pills to AVAILABLE and drop `status: "preorder"` in `catalog.js`
      when they ship.
- [ ] **Names**: check LightStrip / DrumRing / FretStrip / MusicFX for trademark conflicts before launch.
- [ ] **Domain**: if MusicFX gets its own domain, move this folder to its own repo or Pages site.
