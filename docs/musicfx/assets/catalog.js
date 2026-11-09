/*
 * MusicFX product catalog — the single source of truth for the shop.
 *
 * Edit prices, names and sizes here; every page renders from this file.
 * Prices are PLACEHOLDERS (USD) until pricing is final.
 *
 * Product fields:
 *   id          unique, stable (used in the cart)
 *   instrument  "keys" | "drums" | "guitar" | "all"
 *   category    "bundle" | "led" | "controller" | "accessory" | "software"
 *   name, tagline, description, features[]
 *   price       flat price — or use `sizeKind` + `sizes`
 *   sizeKind    key into SIZE_KINDS (keys | drum | neck | drumkit)
 *   sizes       { [sizeValue]: price } for sized products
 *   includes    bundles: [{ id, size?, qty? }] — size "$" means "the bundle's chosen size"
 *   includesBySize  bundles: { [sizeValue]: [{ id, size, qty }] } extra parts per option
 *   discount    bundles only, fraction off the parts (0.15 = 15%)
 *   free, href  free software that links out
 *   status      "preorder" (can buy, ships later) | "coming-soon" (not purchasable)
 *   badge       short label on the card
 */
(function () {
  const IN = 2.54;

  // ---------------------------------------------------------------- sizes
  // Keyboard strips: 2 LEDs per key; length ≈ white keys × 2.35 cm.
  const keyboard = [
    { value: 25, white: 15, examples: "Mini / portable controllers" },
    { value: 49, white: 29, examples: "Compact controllers, synths" },
    { value: 61, white: 36, examples: "Most home keyboards & synths" },
    { value: 76, white: 45, examples: "Stage keyboards, workstations" },
    { value: 88, white: 52, examples: "Digital & stage pianos" },
  ].map((s) => ({
    ...s,
    label: `${s.value}`,
    long: `${s.value}-key`,
    leds: s.value * 2,
    lengthCm: Math.round(s.white * 2.35),
  }));

  // Drum rings: run around the inside of the shell at 60 LEDs/m.
  const drum = [
    [8, "Small rack tom"], [10, "Rack tom"], [12, "Rack tom"], [13, "Rack tom / snare"],
    [14, "Snare / floor tom"], [16, "Floor tom"], [18, "Floor tom / kick"],
    [20, "Kick"], [22, "Kick"], [24, "Kick"],
  ].map(([d, examples]) => {
    const lengthCm = Math.round(Math.PI * d * IN);
    return { value: d, label: `${d}"`, long: `${d}" drum`, examples, lengthCm, leds: Math.round(lengthCm * 0.6) };
  });

  // Fretboard strips: one LED per fret plus the open position, along the
  // top (player-facing) edge of the fretboard.
  const neck = [
    { value: "g21", label: "21 frets", long: "Guitar, 21 frets", frets: 21, examples: "Many Strat-style guitars" },
    { value: "g22", label: "22 frets", long: "Guitar, 22 frets", frets: 22, examples: "Most modern electrics, Les Paul-style" },
    { value: "g24", label: "24 frets", long: "Guitar, 24 frets", frets: 24, examples: "Superstrats, extended-range" },
    { value: "a20", label: "Acoustic", long: "Acoustic, 20 frets", frets: 20, examples: "Steel-string & classical acoustics" },
    { value: "b24", label: "Bass", long: "Bass, 20–24 frets", frets: 24, examples: "4 & 5-string basses (trim to fit)" },
  ].map((s) => ({ ...s, leds: s.frets + 1 }));

  // Drum kit bundle configurations (drum sizes in inches).
  const drumkit = [
    { value: "4pc", label: "4-piece", long: "4-piece kit", drums: [12, 14, 16, 22], examples: "12\" tom · 14\" snare · 16\" floor · 22\" kick" },
    { value: "5pc", label: "5-piece", long: "5-piece kit", drums: [10, 12, 14, 16, 22], examples: "10\" & 12\" toms · 14\" snare · 16\" floor · 22\" kick" },
    { value: "fusion", label: "Fusion", long: "Fusion kit", drums: [10, 12, 14, 14, 20], examples: "10\" & 12\" toms · 14\" snare · 14\" floor · 20\" kick" },
  ];

  const SIZE_KINDS = {
    keys: { label: "Keyboard size", options: keyboard, default: 88 },
    drum: { label: "Drum diameter", options: drum, default: 14 },
    neck: { label: "Neck", options: neck, default: "g22" },
    drumkit: { label: "Kit configuration", options: drumkit, default: "5pc" },
  };

  // ---------------------------------------------------------------- products
  const drumRingPrices = { 8: 25, 10: 25, 12: 29, 13: 29, 14: 32, 16: 36, 18: 39, 20: 45, 22: 45, 24: 49 };
  const drumParts = Object.fromEntries(drumkit.map((k) => [k.value, [
    ...k.drums.map((d) => ({ id: "drum-ring", size: d })),
    { id: "hit-sensor", qty: k.drums.length },
  ]]));

  const PRODUCTS = [
    // ======================= KEYS =======================
    {
      id: "kit-complete", instrument: "keys", category: "bundle",
      name: "Keys Complete Kit", tagline: "Everything to light up your keyboard", badge: "Best value",
      description: "A per-key LightStrip sized to your keyboard, the MusicFX Hub and a matched power supply.",
      sizeKind: "keys", includes: [{ id: "strip", size: "$" }, { id: "hub" }, { id: "psu" }], discount: 0.15,
      features: ["Per-key LEDs that follow every note", "Works over USB or Bluetooth", "Free MusicFX software"],
    },
    {
      id: "kit-stage", instrument: "keys", category: "bundle",
      name: "Keys Stage Kit", tagline: "Complete Kit + ambient light bar", badge: "For performers",
      description: "Adds a 1 m Ambient Bar that mirrors your playing behind or under the instrument.",
      sizeKind: "keys", includes: [{ id: "strip", size: "$" }, { id: "hub" }, { id: "psu" }, { id: "ambient-bar" }], discount: 0.18,
      features: ["Second light zone from the same Hub", "Audience colour voting for streams", "OBS overlay included"],
    },
    {
      id: "strip", instrument: "keys", category: "led",
      name: "LightStrip", tagline: "Per-key LED strip, sized to your keyboard",
      description: "Two SK9822 LEDs per key in a low-profile aluminium channel with a frosted diffuser.",
      sizeKind: "keys", sizes: { 25: 39, 49: 59, 61: 69, 76: 79, 88: 89 },
      features: ["2 LEDs per key, full RGB", "Flicker-free SK9822 LEDs", "Frosted diffuser, removable mounts"],
    },
    {
      id: "hub", instrument: "keys", category: "controller",
      name: "MusicFX Hub", tagline: "Light controller for keyboards", price: 49,
      description: "ESP32-S3 controller that receives note frames from the MusicFX app over USB-C or Bluetooth LE and drives two LED zones.",
      features: ["USB-C serial or Bluetooth LE", "Two outputs: LightStrip + Ambient Bar", "Open-source, updatable firmware"],
    },
    {
      id: "hub-pro", instrument: "keys", category: "controller", status: "coming-soon",
      name: "MusicFX Hub Pro", tagline: "Standalone — no computer required", price: 99,
      description: "Plug your keyboard's USB MIDI straight in and the lights react with no computer running.",
      features: ["Built-in USB MIDI host", "Onboard light themes", "App control over Bluetooth"],
    },

    // ======================= DRUMS =======================
    {
      id: "kit-drums", instrument: "drums", category: "bundle", status: "preorder",
      name: "Drums Complete Kit", tagline: "Light every drum in your kit", badge: "Pre-order",
      description: "A DrumRing for every drum, a Hit Sensor for each one, the Drum Hub and a power supply — matched to your kit configuration.",
      sizeKind: "drumkit", includes: [{ id: "drum-hub" }, { id: "psu-8a" }], includesBySize: drumParts, discount: 0.15,
      features: ["Each drum flashes on every hit", "Works with acoustic and electronic kits", "Free MusicFX software"],
    },
    {
      id: "drum-ring", instrument: "drums", category: "led", status: "preorder",
      name: "DrumRing", tagline: "LED ring that mounts inside the shell",
      description: "A flexible LED strip that runs around the inside of the drum shell and lights the whole drum from within. Mounts with removable clips without changing your drum's sound.",
      sizeKind: "drum", sizes: drumRingPrices,
      features: ["60 LEDs/m, full RGB", "Mounts inside the shell, no drilling", "Cable exits through the air vent"],
    },
    {
      id: "drum-hub", instrument: "drums", category: "controller", status: "preorder",
      name: "Drum Hub", tagline: "8-zone controller with trigger inputs", price: 79,
      description: "Drives up to eight DrumRings. Reads Hit Sensors on acoustic drums or MIDI from an electronic kit, and connects to the MusicFX app over USB-C or Bluetooth.",
      features: ["8 LED zones + 8 trigger inputs", "USB & 5-pin MIDI in for e-kits", "Reacts instantly, even without a computer"],
    },
    {
      id: "hit-sensor", instrument: "drums", category: "accessory", status: "preorder",
      name: "Hit Sensor", tagline: "Clip-on trigger for acoustic drums", price: 12,
      description: "A small piezo sensor that clips to the rim and tells the Drum Hub how hard each drum was hit. Not needed with electronic kits.",
      features: ["Velocity-sensitive", "Tool-free rim clip", "One per drum"],
    },

    // ======================= GUITAR =======================
    {
      id: "kit-guitar", instrument: "guitar", category: "bundle", status: "preorder",
      name: "Guitar Complete Kit", tagline: "Light up your fretboard", badge: "Pre-order",
      description: "A FretStrip sized to your neck plus the wireless Guitar Hub.",
      sizeKind: "neck", includes: [{ id: "fret-strip", size: "$" }, { id: "guitar-hub" }], discount: 0.12,
      features: ["See notes, scales and chord shapes on the neck", "Wireless — no cable to the computer", "Free MusicFX software"],
    },
    {
      id: "fret-strip", instrument: "guitar", category: "led", status: "preorder",
      name: "FretStrip", tagline: "LEDs along the top edge of your fretboard",
      description: "An ultra-thin LED strip that sits along the player-facing top edge of the fretboard, with a light at every fret. You can see it while you play, and it doesn't touch the strings or the playing surface.",
      sizeKind: "neck", sizes: { g21: 49, g22: 49, g24: 55, a20: 49, b24: 59 },
      features: ["A light at every fret", "Thin, low-profile, finish-safe adhesive", "Guitar, acoustic and bass sizes"],
    },
    {
      id: "guitar-hub", instrument: "guitar", category: "controller", status: "preorder",
      name: "Guitar Hub", tagline: "Wireless controller for your FretStrip", price: 59,
      description: "A small rechargeable controller that clips to the headstock or strap. It drives the FretStrip and receives lights from the MusicFX app over Bluetooth.",
      features: ["Rechargeable, USB-C", "Clips to headstock or strap", "Bluetooth LE to the MusicFX app"],
    },

    // ======================= SHARED =======================
    {
      id: "ambient-bar", instrument: "all", category: "led",
      name: "Ambient Bar", tagline: "1 m, 144-LED accent light", price: 29,
      description: "A 144-LED bar that mirrors your instrument from any Hub's spare output. Put it behind the piano, under the drum riser or on the wall.",
      features: ["144 LEDs per metre", "Works with any MusicFX Hub", "Mirrors or extends your main lights"],
    },
    {
      id: "psu", instrument: "keys", category: "accessory",
      name: "5 V 4 A Power Supply", tagline: "For the Hub + LightStrip", price: 15,
      description: "Powers the Hub, a full 88-key LightStrip and an Ambient Bar at typical brightness.",
      features: ["Barrel plug to Hub", "US / EU / UK / AU plugs"],
    },
    {
      id: "psu-8a", instrument: "drums", category: "accessory", status: "preorder",
      name: "5 V 8 A Power Supply", tagline: "For the Drum Hub + DrumRings", price: 22,
      description: "Powers a Drum Hub and up to eight DrumRings.",
      features: ["Locking barrel plug", "US / EU / UK / AU plugs"],
    },
    {
      id: "ext-cable", instrument: "all", category: "accessory",
      name: "LED Extension Cable (2 m)", tagline: "Put the Hub where you want it", price: 9,
      description: "Moves the Hub off the instrument — under the stand, behind the kit or next to your computer.",
      features: ["Locking connectors", "Works with every MusicFX Hub"],
    },

    // ======================= SOFTWARE =======================
    {
      id: "sw-visualizer", instrument: "all", category: "software", free: true, href: "../",
      name: "MusicFX App", tagline: "One app for keys, drums and guitar",
      description: "The visualizer and light controller for every MusicFX product, with Learn Mode, effects, themes and scenes.",
      features: ["Runs in your browser, no install", "Learn Mode for MIDI & MusicXML", "Controls all your MusicFX lights"],
    },
    {
      id: "sw-coach", instrument: "all", category: "software", free: true,
      href: "https://github.com/nickprocenko/Piano-MIDI-visualizer/tree/main/midi_coach",
      name: "MusicFX Practice Coach", tagline: "AI practice feedback with Claude",
      description: "Records your playing and compares it with the score — wrong notes, timing, dynamics — bar by bar.",
      features: ["Bar-by-bar feedback", "Progress tracking", "Custom lessons in Learn Mode"],
    },
  ];

  // ---------------------------------------------------------------- helpers
  const byId = Object.fromEntries(PRODUCTS.map((p) => [p.id, p]));

  function sizeOption(kind, value) {
    const k = SIZE_KINDS[kind];
    return k && k.options.find((o) => String(o.value) === String(value));
  }
  /** Normalise a size for a product: valid value of its kind, else the kind's default. */
  function sizeFor(product, value) {
    if (!product.sizeKind) return null;
    return sizeOption(product.sizeKind, value) ? sizeOption(product.sizeKind, value).value : SIZE_KINDS[product.sizeKind].default;
  }
  /** Bundle contents at a size: [{ id, size, qty }]. */
  function partsOf(product, size) {
    const s = sizeFor(product, size);
    const list = [...(product.includes || []), ...((product.includesBySize || {})[s] || [])];
    return list.map((x) => ({ id: x.id, size: x.size === "$" ? s : x.size ?? null, qty: x.qty || 1 }));
  }
  function priceOf(product, size) {
    if (product.free) return 0;
    if (product.includes || product.includesBySize) {
      return Math.round(partsPriceOf(product, size) * (1 - (product.discount || 0)));
    }
    if (product.sizes) return product.sizes[sizeFor(product, size)];
    return product.price;
  }
  function partsPriceOf(product, size) {
    if (!(product.includes || product.includesBySize)) return priceOf(product, size);
    return partsOf(product, size).reduce((sum, x) => sum + priceOf(byId[x.id], x.size) * x.qty, 0);
  }

  window.MusicFX = Object.assign(window.MusicFX || {}, {
    SIZE_KINDS, PRODUCTS, byId, sizeOption, sizeFor, partsOf, priceOf, partsPriceOf,
    INSTRUMENTS: [
      { id: "all", label: "All instruments" },
      { id: "keys", label: "Keys" },
      { id: "drums", label: "Drums" },
      { id: "guitar", label: "Guitar" },
    ],
    CATEGORIES: [
      { id: "all", label: "All" },
      { id: "bundle", label: "Kits" },
      { id: "led", label: "LEDs" },
      { id: "controller", label: "Controllers" },
      { id: "accessory", label: "Accessories" },
      { id: "software", label: "Software & Apps" },
    ],
  });
})();
