# Onshape Enclosure Specification
## LED Controller + Battery One-Box Enclosure

Use this guide to build the enclosure model directly in Onshape Part Studio.

---

## Step 1: Set Up Variables (in Onshape)

In Onshape Part Studio, go to **Variables** and set these:

```
wall_thickness = 3 mm
lid_gap = 0.3 mm
connector_clearance = 0.5 mm

# Outer enclosure
enc_width = 140 mm
enc_length = 200 mm
enc_height = 80 mm

# Internal space allocation
esp32_height = 15 mm
buck_height = 20 mm
charger_board_height = 15 mm
battery_height = 35 mm

# Clearances
cable_bend_radius = 25 mm
component_clearance = 5 mm

# Lid
lid_thickness = 2.5 mm
screw_boss_od = 8 mm
screw_boss_height = 6 mm
```

---

## Step 2: Create Base Shell

1. Sketch a rectangle: `140 mm × 200 mm`
2. Extrude up `80 mm`
3. Shell inward with thickness = `3 mm`
4. Keep the top open for now (we'll add a separate lid)

---

## Step 3: Add Panel Cutouts (Front Face)

Add these cutouts on the front panel (140×80 face):

### A) DC Input Jack (bottom-left)
- **Type**: 5.5×2.1 mm barrel jack
- **Hole**: 8 mm diameter
- **Position**: 15 mm from left edge, 10 mm from bottom
- **Depth**: Through-panel with flush mount

### B) Strip A Output (bottom-center)
- **Type**: 4-pin GX12 or M8 connector (≈12 mm diameter)
- **Hole**: 13 mm diameter (or slot 12×14 mm for square connectors)
- **Position**: 60 mm from left edge, 10 mm from bottom
- **Depth**: Through-panel with 5 mm mounting boss or nut capture

### C) Strip B Output (bottom-right)
- **Type**: Same as Strip A
- **Hole**: 13 mm diameter
- **Position**: 105 mm from left edge, 10 mm from bottom
- **Depth**: Through-panel with 5 mm mounting boss or nut capture

### D) Charge Status LED (optional, top-left)
- **Type**: 5 mm or 3 mm LED window
- **Hole**: 5.5 mm diameter or 3.5 mm diameter
- **Position**: 15 mm from left edge, 70 mm from bottom
- **Depth**: 2 mm recess for LED bezel

### E) Power Switch (optional, top-center)
- **Type**: Tactile push or rocker
- **Hole**: depends on switch (typically 12-16 mm)
- **Position**: 60 mm from left edge, 70 mm from bottom

---

## Step 4: Add Internal Standoffs

Create cylindrical or rectangular bosses inside at these locations:

### ESP32 Mount (rear-left area)
- **Position**: 20 mm from rear, 20 mm from left
- **Boss OD**: 4 mm (for M3 heat-set insert)
- **Boss Height**: 8 mm above base
- **Qty**: 2-4 bosses (depending on your board layout)

### Buck Converter Mount (rear-right)
- **Position**: 20 mm from rear, 100 mm from left
- **Boss OD**: 5 mm
- **Boss Height**: 10 mm above base
- **Qty**: 2-4

### Charger Board Mount (left side mid-height)
- **Position**: 30 mm from rear, 10 mm from left
- **Boss OD**: 4 mm
- **Boss Height**: 6 mm
- **Qty**: 2-3

### Battery Bay (center of base)
- **Usable space**: 120 mm × 80 mm × 35 mm
- **Strap anchors**: Two rectangular nubs on each long side, 15 mm from edge
- **Nub size**: 3 mm × 3 mm × 4 mm tall

---

## Step 5: Cable Routing Clearance

Add vertical **keepout zones** inside the base (use reference sketches, not solid bodies):

- **Rear panel**: 25 mm clearance from rear for battery connections
- **Right side**: 30 mm clearance for ESP32 USB cable bend radius
- **Top opening**: 20 mm minimum clearance for capacitors on boards

---

## Step 6: Create the Lid

1. Create a separate sketch for the lid top (140×200 mm)
2. Create walls: Inset 0.5 mm from outer edge, extrude down `25 mm`
3. Add fit ribs on inner walls to interlock with base (optional, skip for simplicity)
4. Add **screw posts**:
   - 4 posts at corners: 10 mm inset from edge
   - Post OD: 8 mm, height: 6 mm
   - Center a 3 mm pilot hole in each for self-tapping or heat-set M3

---

## Step 7: Add Ventilation (Optional but Recommended)

On the right side panel (opposite front panel):
- Add 6× 8 mm diameter holes in a 2×3 grid
- Position: 30 mm from top edge, 20 mm spacing
- Use **Hole** tool so they can be easily suppressed if not needed

---

## Step 8: Internal Features (Optional Refinement)

Add draft angle (1-2°) to all vertical walls for easier prints:
- Use **Draft** feature in Onshape
- Direction: outward
- Angle: 1.5°

---

## Step 9: Create Assembled View (Optional)

1. Create separate Part Studio for lid (`Lid_Enclosure`)
2. Create Assembly document
3. Insert both base and lid
4. Position lid to show assembled unit
5. Add fasteners (optional visualization)

---

## Connector Hole Details (for CNC or 3D Print Support)

If you plan to use threaded inserts or self-tapping machine screws:

### Option A: Heat-Set Inserts (Recommended for Reusability)
- Boss OD: Connector OD + 1.5 mm
- Depth: Insert length + 1 mm
- Material: ABS or PETG for 3D print
- Insert: M3 × 4 mm standard brass inserts

### Option B: Self-Tapping Screw Bosses
- Boss OD: 5-6 mm
- Depth: 8 mm
- Drill pilot hole after print: 2.2 mm

### Option C: Press-Fit Connectors (No Hardware)
- Slot size: Connector body width + 0.2 mm
- Depth: Full panel thickness + 1 mm
- Snap retention (advanced)

---

## Material Recommendations for 3D Print

| Material | Temp | Strength | Cost | Lead Time |
|----------|------|----------|------|-----------|
| **PLA** | 200-210°C | Medium | Low | 1-2 days |
| **PETG** | 230-250°C | High | Medium | 2-3 days |
| **ABS** | 240-250°C | Very High | Medium | 1-2 days |
| **Nylon** | 240-260°C | Extremely High | High | 3-5 days |

For this enclosure running 5V/3-5A with passive cooling, **PETG** is ideal.

---

## Test Print Checklist

- [ ] Connector holes fit actual connector bodies (test fit first)
- [ ] Lid closes with < 0.5 mm total gap
- [ ] All standoffs are perpendicular and level
- [ ] no internal supports blocking component access
- [ ] Cable bend radius respected in base layout

---

## Onshape Part Studio Export for 3D Print

Once model is complete:

1. **Right-click** part → **Export**
2. Select **STL** format
3. Set resolution: **0.1 mm** (fine detail)
4. Save as: `Enclosure_Base.stl` and `Enclosure_Lid.stl`
5. Upload to your 3D print service (Shapeways, Protolabs, local printer)

Estimated dimensions after print:
- Base: 140 × 200 × 80 mm (external)
- Lid: 140 × 200 × 25 mm (external)
- Total mass (PETG): ~250-350g depending on infill

---

## Quick Build Verification Checklist

- [ ] DC input position verified against wall thickness
- [ ] Both 4-wire outputs fit without interference
- [ ] ESP32 standoff height clears components below
- [ ] Battery bay has 5 mm clearance on all sides (heat)
- [ ] Lid screw posts are reinforced (extra 1-2 mm wall)
- [ ] Cable routing clearance respected
- [ ] Charge LED window is accessible
- [ ] Power switch (if added) is reachable

---

## Next Steps After Model Build

1. Export STL files
2. Do a papercraft mockup of cutout placement (print Enclosure_Base STL at 50% scale, check fit)
3. Order small test print in PETG or ABS
4. Test-fit all components and connectors
5. Add corner radii (2-3 mm) if sharp edges are a concern
6. Refine clearances based on test print results
7. Final production print

---

## Common Mistakes to Avoid

- ❌ Making lid walls too thin (<2.5 mm) — they will warp
- ❌ Forgetting cable bend radius — components get pinched
- ❌ No draft angle on deep bosses — hard to remove supports
- ❌ Connector holes too small — test with actual connector body first
- ❌ Screw bosses not reinforced — threads strip easily in plastic
- ✅ Start with 3 mm wall, 8 mm screw bosses, 1° draft angle

