/*
 * MusicFX product catalog — the single source of truth for the shop.
 *
 * Edit prices, names and sizes here; shop.html and the home page lineup
 * render from this file. Prices are PLACEHOLDERS (USD) until pricing is final.
 *
 * Product fields:
 *   id          unique, stable (used in the cart)
 *   category    "bundle" | "led" | "controller" | "accessory" | "software"
 *   name, tagline, description, features[]
 *   price       number (flat price) — or omit and use `sizes`
 *   sizes       [{ keys, price }] — sized products (LED strips)
 *   includes    [productId, ...] — bundles: price = sum of parts − discount
 *   discount    bundles only, fraction (0.15 = 15% off the parts)
 *   free        true for free software (links out instead of add-to-cart)
 *   href        link for free software
 *   status      optional: "coming-soon" disables purchase
 *   badge       optional short label shown on the card
 */
(function () {
  // Keyboard sizes we make strips for. White-key count × ~23.5 mm gives the
  // playable width of a full-size keyboard; 2 LEDs per key matches the
  // visualizer's default `mirror_per_key: 2`.
  const KEYBOARD_SIZES = [
    { keys: 25, whiteKeys: 15, examples: "Mini / portable controllers" },
    { keys: 49, whiteKeys: 29, examples: "Compact controllers, synths" },
    { keys: 61, whiteKeys: 36, examples: "Most home keyboards & synths" },
    { keys: 76, whiteKeys: 45, examples: "Stage keyboards, workstations" },
    { keys: 88, whiteKeys: 52, examples: "Digital & stage pianos" },
  ].map((s) => ({
    ...s,
    leds: s.keys * 2,
    lengthCm: Math.round(s.whiteKeys * 2.35),
  }));

  const PRODUCTS = [
    // ---------------- Bundles ----------------
    {
      id: "kit-complete",
      category: "bundle",
      name: "MusicFX Complete Kit",
      tagline: "Everything to light up your keyboard",
      badge: "Best value",
      description:
        "A per-key LightStrip sized to your keyboard, the MusicFX Hub controller and a matched power supply. Plug in, open the visualizer, play.",
      includes: ["strip", "hub", "psu"],
      discount: 0.15,
      sized: true,
      features: [
        "Per-key LEDs that follow every note you play",
        "Works over USB or Bluetooth",
        "Free visualizer and practice software",
      ],
    },
    {
      id: "kit-stage",
      category: "bundle",
      name: "MusicFX Stage Kit",
      tagline: "Complete Kit + ambient light bar",
      badge: "For performers",
      description:
        "Adds a 1 m Ambient Bar that mirrors your playing behind or under the instrument — built for streams, gigs and video.",
      includes: ["strip", "hub", "psu", "ambient-bar"],
      discount: 0.18,
      sized: true,
      features: [
        "Second light zone driven by the same Hub",
        "Audience colour voting for live streams",
        "OBS overlay included",
      ],
    },

    // ---------------- LED strips ----------------
    {
      id: "strip",
      category: "led",
      name: "MusicFX LightStrip",
      tagline: "Per-key LED strip, cut to your keyboard",
      description:
        "Two addressable SK9822 LEDs per key in a low-profile aluminium channel with a frosted diffuser. Mounts above the keys with removable adhesive.",
      sizes: [
        { keys: 25, price: 39 },
        { keys: 49, price: 59 },
        { keys: 61, price: 69 },
        { keys: 76, price: 79 },
        { keys: 88, price: 89 },
      ],
      features: [
        "2 LEDs per key, full RGB",
        "Fast clocked SK9822 LEDs — no flicker",
        "Frosted diffuser, removable mounts",
      ],
    },
    {
      id: "ambient-bar",
      category: "led",
      name: "Ambient Bar",
      tagline: "1 m, 144-LED accent light",
      price: 29,
      description:
        "A 144-LED WS2812B bar that mirrors the keyboard on the Hub's second output. Put it behind the piano, under the stand or on the wall.",
      features: ["144 LEDs per metre", "Plugs into Hub output 2", "Mirrors or extends the main strip"],
    },

    // ---------------- Controllers ----------------
    {
      id: "hub",
      category: "controller",
      name: "MusicFX Hub",
      tagline: "The brain between your music and your lights",
      price: 49,
      description:
        "ESP32-S3 LED controller that receives note frames from the MusicFX visualizer over USB-C or Bluetooth LE and drives up to two LED zones.",
      features: [
        "USB-C serial or Bluetooth LE",
        "Two outputs: LightStrip + Ambient Bar",
        "Open-source, updatable firmware",
      ],
    },
    {
      id: "hub-pro",
      category: "controller",
      name: "MusicFX Hub Pro",
      tagline: "Standalone — no computer required",
      status: "coming-soon",
      price: 99,
      description:
        "Plug your keyboard's USB MIDI straight into the Hub Pro and the lights react with no computer, phone or app running.",
      features: ["Built-in USB MIDI host", "Onboard light themes", "App control over Bluetooth"],
    },

    // ---------------- Accessories ----------------
    {
      id: "psu",
      category: "accessory",
      name: "5 V 4 A Power Supply",
      tagline: "Matched supply for Hub + strips",
      price: 15,
      description: "Powers the Hub, a full 88-key LightStrip and an Ambient Bar at typical brightness.",
      features: ["Barrel plug to Hub", "US / EU / UK / AU plugs"],
    },
    {
      id: "ext-cable",
      category: "accessory",
      name: "LED Extension Cable (2 m)",
      tagline: "Put the Hub where you want it",
      price: 9,
      description: "Moves the Hub off the keyboard — under the stand or next to your computer.",
      features: ["Locking connectors", "Works on either Hub output"],
    },

    // ---------------- Software (free) ----------------
    {
      id: "sw-visualizer",
      category: "software",
      name: "MusicFX Visualizer",
      tagline: "Full-screen note highway in your browser",
      free: true,
      href: "../",
      description:
        "Real-time visualizer with Learn Mode, shader effects, themes and scenes. Drives MusicFX lights directly from Chrome or Edge.",
      features: ["No install — runs in the browser", "Learn Mode for MIDI & MusicXML", "Controls your MusicFX lights"],
    },
    {
      id: "sw-coach",
      category: "software",
      name: "MusicFX Practice Coach",
      tagline: "AI practice feedback with Claude",
      free: true,
      href: "https://github.com/nickprocenko/Piano-MIDI-visualizer/tree/main/midi_coach",
      description:
        "Records your playing and compares it with the score — wrong notes, timing, dynamics and pedal, bar by bar — and tracks your progress.",
      features: ["Bar-by-bar feedback", "Progress tracking", "Custom lessons in Learn Mode"],
    },
  ];

  const byId = Object.fromEntries(PRODUCTS.map((p) => [p.id, p]));

  /** Price of a product for a given keyboard size (keys may be undefined). */
  function priceOf(product, keys) {
    if (product.free) return 0;
    if (product.includes) {
      const parts = product.includes.reduce((sum, id) => sum + priceOf(byId[id], keys), 0);
      return Math.round(parts * (1 - (product.discount || 0)));
    }
    if (product.sizes) {
      const s = product.sizes.find((x) => x.keys === keys) || product.sizes[product.sizes.length - 1];
      return s.price;
    }
    return product.price;
  }

  /** Full (undiscounted) price of a bundle's parts. */
  function partsPriceOf(product, keys) {
    if (!product.includes) return priceOf(product, keys);
    return product.includes.reduce((sum, id) => sum + priceOf(byId[id], keys), 0);
  }

  function isSized(product) {
    return Boolean(product.sizes || product.sized);
  }

  window.MusicFX = Object.assign(window.MusicFX || {}, {
    KEYBOARD_SIZES,
    PRODUCTS,
    byId,
    priceOf,
    partsPriceOf,
    isSized,
    CATEGORIES: [
      { id: "all", label: "All" },
      { id: "bundle", label: "Bundles" },
      { id: "led", label: "LED Strips" },
      { id: "controller", label: "Controllers" },
      { id: "accessory", label: "Accessories" },
      { id: "software", label: "Software & Apps" },
    ],
  });
})();
