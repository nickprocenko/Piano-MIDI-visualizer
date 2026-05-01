# Component Dimension Reference
## Paste these into your Onshape variables as you confirm actual part sizes

| Component | Dimension | Value (mm) | Status | Source |
|-----------|-----------|-----------|--------|--------|
| **Enclosure Exterior** | | | | |
| Overall Width | 140 | 140 | ✓ Locked | Design fixed |
| Overall Length | 200 | 200 | ✓ Locked | Design fixed |
| Overall Height | 80 | 80 | ✓ Locked | Design fixed |
| Wall Thickness | wall_thickness | 3 | ✓ Default | 3D print typical |
| Lid Thickness | lid_thickness | 2.5 | ✓ Default | Adequate strength |
| **DC Charging Input** | | | | |
| Connector Type | — | 5.5×2.1 mm barrel | — | Standard laptop PSU |
| Panel Hole Diameter | dc_hole_dia | 8 | ✓ Standard | Flush mount |
| Mounting Depth | dc_depth | 12 | ✓ Standard | Recessed barrel |
| Position from Left | dc_x | 15 | ⚠ Verify fit | Avoid top stress |
| Position from Bottom | dc_y | 10 | ⚠ Adjust if needed | Easy access |
| **Strip A Output (4-wire)** | | | | |
| Connector Body OD | connector_od | 12 | ⚠ Measure actual | GX12/M8 variants differ |
| Panel Hole Diameter | strip_hole_dia | 13 | ⚠ Add 1mm clearance | Nut capture or snug fit |
| Mounting Boss OD | strip_boss_od | 5 | ✓ Standard | M3 heat-set insert |
| Position from Left | strip_a_x | 60 | ⚠ Center reference | Even spacing |
| Position from Bottom | strip_ab_y | 10 | ⚠ Adjust symmetry | Aligned with DC jack |
| **Strip B Output (4-wire)** | | | | |
| Same as Strip A | — | — | — | — |
| Position from Left | strip_b_x | 105 | ⚠ Verify spacing | 45 mm center-to-center |
| Position from Bottom | strip_ab_y | 10 | ⚠ Align with A | Horizontal plane |
| **Status LED (optional)** | | | | |
| LED Type | led_type | 5 mm or 3 mm | ⚠ Choose size | Diffused preferred |
| Panel Hole Diameter | led_hole_dia | 5.5 / 3.5 | ⚠ Pick one | Add 0.5mm to nominal |
| Recess Depth | led_recess | 2 | ✓ Standard | Bezel sits flush |
| Position from Left | led_x | 15 | ⚠ Adjust to preference | Top-left for visibility |
| Position from Bottom | led_y | 70 | ⚠ Adjust to preference | Visible with lid on |
| **ESP32-S3 Mini** | | | | |
| PCB Width | esp32_w | 26 | ⚠ Measure board | Check your specific variant |
| PCB Length | esp32_l | 50 | ⚠ Measure board | Pin headers add ~3mm |
| PCB Height | esp32_h | 4 | ⚠ Measure board | Body only (no components) |
| Component Clearance | esp32_clr | 8 | ✓ Conservative | Tallest caps ~5mm |
| Standoff Boss Count | esp32_bosses | 3 | ✓ Typical | Rear-left corner area |
| Standoff Height | esp32_standoff_h | 8 | ⚠ Adjust for clearance | ESP32 + 2mm above cap |
| **Buck Converter (8-10A 5V)** | | | | |
| Module Width | buck_w | 35 | ⚠ Verify part | Typically 35-45mm |
| Module Length | buck_l | 55 | ⚠ Verify part | Typically 50-60mm |
| Module Height | buck_h | 18 | ⚠ Check potentiometer height | Pots add 8-10mm |
| Standoff Boss Count | buck_bosses | 4 | ✓ Typical | All corners |
| Standoff Height | buck_standoff_h | 10 | ⚠ Potentiometer clearance | Adjust if taller pot |
| **Charger + Power Path Board** | | | | |
| Module Width | charger_w | 40 | ⚠ Verify part | Typically 35-50mm |
| Module Length | charger_l | 60 | ⚠ Verify part | Typically 50-70mm |
| Module Height | charger_h | 12 | ⚠ Check USB connector | USB-C adds 8mm above |
| Standoff Boss Count | charger_bosses | 3 | ⚠ Pick diagonal 3 or all 4 | Depends on layout |
| Standoff Height | charger_standoff_h | 6 | ⚠ Minimal clearance | Just above battery |
| USB Port Clearance | usb_access_x | 20 | ⚠ Leave space in rear | For charging cable |
| **Battery (Internal 2S or 3S Li-ion)** | | | | |
| Cell Count | battery_cells | 2 or 3 | — | 7.4V or 11.1V nominal |
| Pack Width | batt_w | 60 | ⚠ Measure your battery | Custom packs vary widely |
| Pack Length | batt_l | 110 | ⚠ Measure your battery | Arranged lengthwise |
| Pack Height | batt_h | 15 | ⚠ Measure your battery | Single layer in base |
| BMS Module Size | bms_w × bms_l | 30 × 50 | ⚠ Verify part | Mounted on battery top |
| Battery Bay Width (internal) | battery_bay_w | 120 | ✓ With 5mm clearance | 140 - 2×(3mm wall + 5mm clr) |
| Battery Bay Length | battery_bay_l | 80 | ✓ With 5mm clearance | 200 - 2×(3mm wall + 5mm clr) |
| Battery Bay Height | battery_bay_h | 35 | ⚠ Adjust if taller pack | Space for BMS + thermal gap |
| Thermal Clearance | thermal_clr | 5 | ✓ Minimum | Heat dissipation margin |
| **Capacitors (bulk energy storage on PSU rails)** | | | | |
| Qty & Rating | cap_count | 2× 1000-2200uF 10V | — | Parallel bulk caps on 5V rail |
| Individual Can Diameter | cap_dia | 10 | ⚠ Measure specific part | Radial caps 10-16mm |
| Individual Can Height | cap_h | 12 | ⚠ Measure specific part | Typically 12-20mm tall |
| Standoff Height (above buck) | cap_clear | 5 | ⚠ Mount on heatsink board | Shouldn't interfere with lid |
| **Main Fuse (10A, on +5V rail)** | | | | |
| Fuse Type | fuse_type | 10A 250V | — | Automotive ATC or cartridge |
| Holder Footprint | fuse_holder_w × l | 20 × 15 | ⚠ Verify holder dimensions | Blade/cartridge holder size |
| Mounting Height | fuse_h | 8 | ⚠ Above base standoff | Top of inserted fuse |
| **Screw & Insert Hardware** | | | | |
| Heat-Set Insert Type | insert_type | M3 × 4 mm | ✓ Standard | Brass, 0.5mm deep thread |
| Screw Boss OD (around insert) | boss_od | 5 | ✓ Standard | 1mm wall around insert |
| Screw Boss Height | boss_h | 6 | ✓ Standard | Insert + 1mm above |
| Lid Screw Posts (Qty) | screw_qty | 4 | ✓ Minimum | One per corner |
| Lid Screw Posts OD | screw_post_od | 8 | ✓ Standard | Captures M3 insert |
| Lid Screw Posts Height | screw_post_h | 6 | ✓ Standard | Match base insert depth |
| **Cable & Connector Routing** | | | | |
| Minimum Bend Radius | bend_radius | 25 | ✓ Data cable spec | Avoid kinking USB/UART |
| Rear Clearance for Connections | rear_clr | 25 | ✓ Conservative | Board connectors & battery leads |
| Strain Relief Loop | relief_loop_w | 15 | ✓ Extra safety | USB cable loop in base |
| **Lid Features** | | | | |
| Lid Screw Posts (Qty) | lid_posts | 4 | ✓ Fixed | One per corner |
| Lid to Base Fit Gap | lid_gap | 0.3 | ✓ Print tolerance | 0.1-0.5mm typical |
| Screw Boss Height | lid_boss_h | 6 | ✓ Standard | Down from lid interior |
| Ventilation Holes (optional) | vent_count | 6 | ⚠ Add if passive cooling needed | 8mm ∅, 2×3 grid |
| Ventilation Hole Spacing | vent_space | 20 | ✓ Even distribution | x=30mm from top, y-center |

---

## How to Use This Table

1. **Status Column Legend**:
   - ✓ **Locked** = Design-fixed, don't change unless redesigning enclosure
   - ⚠ **Verify fit** = Measure your actual components and confirm before ordering parts
   - — **N/A** = Reference-only, not a Onshape variable

2. **Action Items**:
   - [ ] Measure or look up specs for ESP32, buck converter, charger board, battery (fill in ⚠ rows)
   - [ ] Create a Onshape document with a text sketch listing all variables at top
   - [ ] Paste this table values directly into variable definitions
   - [ ] Model the enclosure using these constraints
   - [ ] Test-fit components before final print

3. **If You Change Any Key Dimension**:
   - Update the table and recalculate related dimensions (e.g., if battery is 120mm long, reduce `battery_bay_l`)
   - Propagate changes to internal clearances and boss positions
   - Test fit in your Onshape model before printing

---

## Example Onshape Variable Block (Copy & Paste)

```
# Units: millimeters

# Enclosure Shell
wall_thickness = 3
lid_thickness = 2.5
enc_width = 140
enc_length = 200
enc_height = 80

# Clearances
connector_clearance = 0.5
component_clearance = 5
thermal_clearance = 5
cable_bend_radius = 25

# DC Input
dc_hole_dia = 8
dc_x = 15
dc_y = 10

# Strip Outputs
connector_od = 12
strip_hole_dia = 13
strip_boss_od = 5
strip_a_x = 60
strip_b_x = 105
strip_ab_y = 10

# LED Status (optional)
led_hole_dia = 5.5
led_recess = 2
led_x = 15
led_y = 70

# ESP32 Mount
esp32_w = 26
esp32_l = 50
esp32_h = 4
esp32_standoff_h = 8
esp32_bosses = 3

# Buck Converter Mount
buck_w = 35
buck_l = 55
buck_h = 18
buck_standoff_h = 10
buck_bosses = 4

# Charger Board Mount
charger_w = 40
charger_l = 60
charger_h = 12
charger_standoff_h = 6
charger_bosses = 3

# Battery Bay
battery_bay_w = 120
battery_bay_l = 80
battery_bay_h = 35
batt_w = 60
batt_l = 110
batt_h = 15

# Screw Hardware
insert_type = "M3 x 4mm"
boss_od = 5
boss_h = 6
screw_qty = 4
screw_post_od = 8
screw_post_h = 6

# Lid
lid_gap = 0.3
lid_posts = 4
```

---

## Final Step: Export & 3D Print

Once your Onshape model is complete:
1. Right-click part → **Export as STL**
2. Save both `Enclosure_Base.stl` and `Enclosure_Lid.stl`
3. Send to 3D print service or your local printer
4. Print in **PETG** for durability (ABS also works)
5. Post-process: inspect fitment, sand rough edges, paint if desired

