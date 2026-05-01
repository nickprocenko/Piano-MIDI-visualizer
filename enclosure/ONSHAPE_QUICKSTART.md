# Onshape Build Quickstart Checklist

Follow these steps in order to build your enclosure in Onshape Part Studio.

---

## Phase 1: Part Studio Setup (5 minutes)

- [ ] Open Onshape → Create new document → Select **Part Studio**
- [ ] Click **Variables** panel (top-right)
- [ ] Copy the variable block from [COMPONENT_DIMENSIONS.md](COMPONENT_DIMENSIONS.md#example-onshape-variable-block-copy--paste)
- [ ] Paste all variable definitions and verify no errors
- [ ] Rename your Part Studio: `Enclosure_Base`

---

## Phase 2: Base Shell (15 minutes)

- [ ] Sketch on Top plane: Rectangle `140 × 200 mm`
- [ ] Extrude: Up `80 mm` (solid)
- [ ] Use **Shell** tool:
  - Select top face (leave it open — don't shell it off)
  - Wall thickness: `3 mm` (use variable `wall_thickness`)
  - Result: hollow box with no top
- [ ] Confirm: Box exterior is now 140×200×80, walls are 3mm thick, top is open

---

## Phase 3: Front Panel Cutouts (20 minutes)

- [ ] Select **front face** (the 140×80 panel facing you)
- [ ] Create sketch on front face named `Front_Cutouts`

### Add these circles/holes to the sketch:

1. **DC Input** (barrel jack)
   - Circle at X=15mm, Y=10mm (from bottom-left)
   - Diameter: `8 mm`
   - Pocket depth: `Through all` (through panel)

2. **Strip A Output**
   - Circle at X=60mm, Y=10mm
   - Diameter: `13 mm`
   - Pocket depth: Through all

3. **Strip B Output**
   - Circle at X=105mm, Y=10mm
   - Diameter: `13 mm`
   - Pocket depth: Through all

4. **Charge Status LED** (optional)
   - Circle at X=15mm, Y=70mm
   - Diameter: `5.5 mm`
   - Pocket depth: `2 mm` (recess, not through)

5. **Power Switch** (optional, skip if not using)
   - Circle at X=60mm, Y=70mm
   - Diameter: `14 mm` (adjust for your switch)
   - Pocket depth: Through all

- [ ] Exit sketch
- [ ] Use **Pocket** tool on each circle:
  - Depth: as specified above
  - **DO NOT group them** — create separate pocket features
- [ ] Result: Front panel now has five clean holes

---

## Phase 4: Internal Standoffs (30 minutes)

Standoffs are mounting posts for boards. Each consists of a small cylinder (boss) with a center hole for a screw.

### A) ESP32 Mount (rear-left)
- [ ] Create new sketch on `base` (bottom face)
- [ ] Draw two circles:
  - Circle 1: X=30mm, Y=30mm, diameter `5 mm` (boss OD)
  - Circle 2: X=30mm, Y=60mm, diameter `5 mm` (boss OD)
- [ ] Exit sketch, use **Pad** tool:
  - Extrude height: `8 mm`
  - Symmetric: NO
  - Result: Two short cylinders on the base floor
- [ ] On each boss, drill a `3.1 mm` hole (for M3 insert):
  - Create new sketch on top of boss
  - Draw circle `3.1 mm` diameter at center
  - Pocket through all
  - Repeat for both bosses

### B) Buck Converter Mount (rear-right)
- [ ] Create new sketch on base
- [ ] Four circles at:
  - (30, 130), (30, 160), (70, 130), (70, 160)
  - Each diameter `5 mm`
- [ ] Pad extrude: `10 mm`
- [ ] Drill `3.1 mm` holes in each (3-minute task per 4 bosses)

### C) Charger Board Mount (left side)
- [ ] Create new sketch on base
- [ ] Three circles at:
  - (20, 40), (20, 80), (60, 40)
  - Diameter `5 mm` each
- [ ] Pad: `6 mm` height
- [ ] Drill `3.1 mm` holes in all three

- [ ] **Save your work** (Ctrl+S)

---

## Phase 5: Lid Model (25 minutes)

- [ ] In the same Part Studio, create a **new body** (click **+** next to body name)
- [ ] Rename it: `Enclosure_Lid`
- [ ] Sketch on Top plane: Rectangle `140 × 200 mm`
- [ ] Extrude down (negative): `-25 mm` (lid sits inside, hollow part)
- [ ] Shell this box:
  - Wall thickness: `2.5 mm`
  - Select bottom face to leave it open
  - Result: Hollow lid cavity that interlocks with base top

### Add Lid Screw Bosses (4):
- [ ] Sketch on **interior top surface** of lid
- [ ] Four circles at:
  - (10, 10), (130, 10), (10, 190), (130, 190) — corners, 10mm inset
  - Diameter: `8 mm` each
- [ ] Pad extrude down: `6 mm`
- [ ] Drill `3.1 mm` holes in each (for M3 inserts)

- [ ] Result: Lid now has four posts that connect to base posts when assembled

---

## Phase 6: Cable Routing Clearance (reference, not geometry)

- [ ] No solids to create here — just verify your models leave:
  - **Rear panel**: 25 mm clearance for battery connections
  - **Right side**: 30 mm clearance for ESP32 USB bend radius
  - **Base floor**: Battery footprint leaves 5 mm on all sides

---

## Phase 7: Draft Angle (optional, improves 3D prints)

- [ ] Select base body
- [ ] Use **Draft** feature:
  - Select all vertical faces
  - Angle: `1.5 degrees`
  - Direction: outward
  - Result: Walls taper slightly for easier support removal
- [ ] Repeat for lid body

---

## Phase 8: Assembly View (optional visualization)

- [ ] Create new **Assembly** document
- [ ] Insert both `Enclosure_Base` and `Enclosure_Lid` part studios
- [ ] Position lid on top of base to show how they fit together
- [ ] Add a screenshot for your build notes

---

## ✓ Completion Checklist

- [ ] Base shell: 140×200×80 mm, hollow, top open, walls 3mm
- [ ] Front panel: 5 holes (DC, strip A, strip B, LED, power switch)
- [ ] Internal standoffs: ESP32 (2), buck converter (4), charger (3), all with 3.1mm pilot holes
- [ ] Lid: fits into base top, 4 corner screw bosses
- [ ] Draft angles applied (optional but recommended)
- [ ] Dimensions verified against [COMPONENT_DIMENSIONS.md](COMPONENT_DIMENSIONS.md)
- [ ] Models saved as separate Part Studio bodies

---

## Export for 3D Printing

Once model is complete:

1. **Right-click** `Enclosure_Base` body → **Export**
2. Select **STL** format
3. Resolution: **0.1 mm** (fine quality)
4. Save as: `Enclosure_Base.stl`
5. Repeat for `Enclosure_Lid`: `Enclosure_Lid.stl`

---

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| Lid doesn't sit flush | Walls too thick or gap too small | Adjust `lid_gap` variable and offset |
| Bosses too short | Standoff height wrong | Increase boss height by 2-3mm |
| Holes misaligned | Sketch origin offset | Use reference planes aligned to (0,0,0) |
| Variables show errors | Copy-paste formatting | Delete and re-type each line manually |
| Front panel holes too small | Dimensions copied wrong | Look up actual connector OD and add 0.5mm |
| Model appears inverted | Extrude direction wrong | Use negative extrude value for lid |

---

## Next: Print & Assemble

Once you export both STL files:
1. Upload to 3D print service (Shapeways, Protolabs, local printer)
2. Request **PETG** material (ABS also works)
3. Ask for **0.2mm layer height** (detail/strength balance)
4. Estimated print time: 6-8 hours per part
5. Post-process: sand edges, install heat-set inserts, test fit

