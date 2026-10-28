# Antenna radomes

**Current design: one radome for all four surveillance panels.**
- **Layout:** the UHF panel sits on top, and the three 4G/5G panels are in a row below it, on one tray behind one cover.
- **References:** the two LPDA references stay outside, on their own arms. Each must point at its transmitter, which is in a different direction from the protected sector. The LPDA-H keeps its small paddle radome; the aluminium LPDA-U stays bare.
- **Alternative:** one radome per panel (described further down) keeps each band a separate module, for sites that don't fit all four bands.

Files:
- `radome_design.py` computes the sizes from `design.json` and writes `radome.json` and `radome_transmission.png`. It covers RF transmission through the wall (dry, wet, iced) and wind deflection of the front face.
- `radome_blender.py` builds the Blender model (`radome.blend`) and renders three views:

      python hardware/antenna/radome_design.py
      "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P hardware/antenna/radome_blender.py -- cutaway family site

| Render | View |
|---|---|
| `render_radome_cutaway.png` | the combined radome with a see-through cover: 4 UHF bowties on top, 3 × 4 slant dipoles below, reflectors and flanges, the rib, tray, flange screws |
| `render_radome_family.png` | the combined radome, the LPDA-H paddle and the bare LPDA-U, to scale |
| `render_radome_site.png` | the full site: the combined radome, both LPDAs on side arms, the all-in-one receiver enclosure (`../enclosure/ENCLOSURE.md`) and the 16 phase-matched feed cables |

## Combined radome (current)

```
   ┌──────────────────────────────────────────┐
   │      UHF panel: 4 bowties, 851 × 415     │  ← GRP wall 3 mm
   │                                          │
   ├──────────────────── rib ─────────────────┤  ← GRP rib, cover front to reflector plane
   │  mid 298×121  │ high 237×93 │ n78 168×68 │  ← GRP wall 2 mm (moulded thinner window)
   └──────────────────────────────────────────┘
     bottom: 16 × N (S1–S4 for each band), vent, drain
```

| | |
|---|---|
| Overall with tray flange (L × H × D) | 937 × 682 × 245 mm |
| Cover inside | 891 × 636 × 194 mm |
| Cover | moulded GRP: 3 mm over the UHF zone, 2 mm over the 4G/5G window, with an internal 4 mm GRP rib between the two zones |
| Panel positions | UHF centre 91 mm above the cover centre; 4G/5G row 237 mm below it; mid / high / n78 at x = −243 / +65 / +308 mm. There are 60 mm between the UHF reflector and the 4G/5G row and 40 mm between the small panels |
| Front deflection in 160 km/h wind | 3.3 mm (UHF zone); 0.2 mm (4G/5G zone) |
| Stress safety factor | 14 / 46 |
| Wind load on the face | about 985 N. The four separate radomes came to about 800 N in total, but they could catch the wind from more directions |
| Mass (estimate) | about 18 kg, about the same as the four separate radomes |
| Mounting | two clamps for a 114 mm pole |

**Why the wall is stepped:** a 3 mm GRP wall all over would cost 0.7–0.8 dB at n78. A 2 mm wall over the whole cover would bend 11 mm or more in wind, because the cover is 636 mm tall. So the wall is 3 mm where the span is large, over the UHF zone, and 2 mm over the short 4G/5G window. The rib between the zones halves the free span.

| Band (at band top) | Wall | Dry loss, broadside / 50° | Wet loss (0.2 mm film) | Cross-pol discrimination at 50° |
|---|---|---|---|---|
| UHF 821 MHz | GRP 3 mm | 0.05 / 0.06 dB | 0.3 dB | 30 dB |
| mid 2170 MHz | GRP 2 mm | 0.13 / 0.17 dB | 1.3 dB | 26 dB |
| high 2690 MHz | GRP 2 mm | 0.19 / 0.25 dB | 1.8 dB | 24 dB |
| n78 3800 MHz | GRP 2 mm | 0.34 / 0.44 dB | 2.9 dB | 21 dB |

**Costs against separate radomes:**
- **Loss at n78:** about 0.2 dB more dry loss at n78. GRP has a higher εr than ASA.
- **Shared pointing:** all four bands point the same way and share one tilt bracket.
- **Element coupling:** the UHF panel's lower flange is 60 mm from the 4G/5G reflectors. That can tilt the 4G/5G elevation patterns slightly; azimuth isn't affected.
- **Moulding tolerance:** GRP thickness must hold ±0.2 mm in the 4G/5G window. Use compression-moulded or RTM GRP, not hand lay-up.

Check each band on the VNA with the full radome fitted.

# Separate radomes, one per panel (alternative)

## Construction

```
   pole clamps ─┐
                ▼
   ┌──────────────────────┐  ← aluminium tray, 2 mm, powder-coated: SMAs and pigtails live here
   │ ══════ reflector ═════│  ← tray front plate = reflector; element stems pass through slots
   ├─┬──────────────────┬─┤  ← cover flange + EPDM gasket, M5 A4 screws at ≤ 100 mm pitch
   │ │  ╲  elements  ╱  │ │
   │ │                  │ │  ← side walls hold the front face's edges
   │ └──────────────────┘ │
   └── flat front face ───┘  ← thin wall, uniform thickness, faces the protected sector
        bottom face of the tray: 4 × N female (S1–S4), pressure vent, drain hole
```

- **Front face:** flat and of uniform thickness. Every element then sees the same wall, so the radome adds the same phase to all four channels.
  - This matters because Board A2's noise-source calibration starts behind the antenna and can't remove radome errors.
  - A ±0.2 mm thickness tolerance gives 0.7–1.7° of phase spread between elements, about 0.5° of bearing at worst.
- **Cover material:**
  - **UHF:** moulded GRP. Its 0.9 m span is too large for thermoplastic at 3 mm: ASA would deflect about 16 mm in the design wind.
  - **4G/5G:** thermoformed ASA, which is UV-stable without a coating. A first unit can be 3D-printed in ASA at 100% infill.
- **Clearance:** each cover sits at least 12 mm (UHF: 29 mm, 0.06 λ) in front of the element tips, and 15–20 mm outside the reflector edges.
- **Mounting:** two clamps for a 50–114 mm pole on the UHF panel, one on the smaller panels (60 mm stub or pole). Allow 0–10° of mechanical downtilt with a slotted bracket.
- **Drainage:** cables leave from the bottom face only. The vent stops the radome breathing in moisture as it heats and cools.

| | `uhf` | `mid` | `high` | `n78` |
|---|---|---|---|---|
| Cover | GRP 3.0 mm | ASA 2.5 mm | ASA 2.5 mm | ASA 2.5 mm |
| Wall thickness / λ in the material at band top | 0.017 | 0.031 | 0.039 | 0.055 |
| Cover inside, L × H × D (mm) | 891 × 455 × 194 | 328 × 151 × 57 | 267 × 123 × 47 | 198 × 98 × 38 |
| Overall with tray flange, L × H × D (mm) | 937 × 501 × 245 | 357 × 180 × 92 | 296 × 152 × 82 | 227 × 127 × 74 |
| Element tip → front face (mm) | 29 | 12 | 12 | 12 |
| Corner radius / flange (mm) | 25 / 20 | 10 / 12 | 10 / 12 | 10 / 12 |
| Flange screws (M5 A4) | 28 | 10 | 8 | 8 |
| Mass, panel complete (estimate, kg) | 12.9 | 1.9 | 1.6 | 1.4 |

## RF transmission (+45° slant, scanned in azimuth)

The model is an exact plane-wave multilayer slab, TE and TM. A slant wave is half TE and half TM. The material values are typical datasheet figures; confirm them with the supplier:

| Material | εr | tan δ |
|---|---|---|
| ASA | 3.0 | 0.012 |
| GRP | 4.4 | 0.016 |

| Loss (dB) at band top: broadside / 50° | `uhf` 821 MHz | `mid` 2170 MHz | `high` 2690 MHz | `n78` 3800 MHz |
|---|---|---|---|---|
| Dry | 0.05 / 0.06 | 0.07 / 0.09 | 0.11 / 0.14 | 0.19 / 0.25 |
| Wet: 0.2 mm water film | 0.28 / 0.38 | 1.2 / 1.4 | 1.6 / 1.9 | 2.7 / 2.9 |
| Iced: 10 mm ice | 0.31 / 0.40 | 1.0 / 1.2 | 1.2 / 1.4 | 1.3 / 1.6 |
| Cross-pol discrimination at 50°, dry (dB) | 30 | 29 | 28 | 25 |

What this means:
- **Dry:** under 0.25 dB in every band, out to the ±50° edge of the sector.
- **Wet:** a water film costs up to 2.9 dB at n78. It cuts detection range by about 15% while the film lasts.
  - The loss is equal on all elements and the reference, so it doesn't bias bearings.
  - A hydrophobic coating on the front face helps: water then beads and runs off instead of forming a film.
- **Polarization:** the cover turns a little of the slant wave into the opposite slant at wide angles, still 25 dB down or better at 50°. That is a negligible polarization loss.

## LPDA references

- **LPDA-H:** an ASA paddle radome, 2 mm wall, 244 × 109 × 26 mm.
  - **Build:** two shells clamp the PCB in a slot. A 40 mm solid stub at the rear clamps onto a 25 mm GRP mast arm.
  - **Cable:** it leaves the rear through an M12 gland on the boom's centre line.
  - **Rolled 45°** with the PCB, so it keeps the slant polarization.
  - **Loss:** under 0.2 dB from 1.7 to 4 GHz, out to 50°.
- **LPDA-U:** no radome; bare anodised aluminium with stainless hardware, like commercial UHF LPDAs.
  - Seal the feed end of the boom coax with adhesive-lined heat-shrink.
  - Leave a drain hole at the boom's low point.
  - Mount it on a GRP or aluminium arm behind the longest element. The beam points to the short end.

## Wind and structure (160 km/h, 1.19 kPa)

The front face is modelled as a rectangular plate with all edges fixed (Roark), since the side walls hold its edges.

| | `uhf` | `mid` | `high` | `n78` |
|---|---|---|---|---|
| Wind load on the face, Cd 1.3 (N) | 637 | 80 | 54 | 32 |
| Front face deflection (mm) | 3.0 | 0.5 | 0.2 | 0.1 |
| Front face stress / safety factor | 13.5 MPa / 15 | 2.2 MPa / 21 | 1.4 MPa / 32 | 0.9 MPa / 50 |

**Mast load:** a full site carries about 640 N on the UHF panel and 170 N on the 4G/5G panels in the design wind. Add the all-in-one enclosure: about 42 kg, and about 1.1 kN of wind on its face. Size the mast and its fixing for that, with a structural engineer for a rooftop site.

## Effect on tuning

Not computed. A thin wall this far from the elements usually lowers resonance by a few tenths of a percent to about 1%. Since the arms are drawn 3% long anyway, **do the VNA trim with the cover fitted.** Also check the reflector-plane match through an N bulkhead, since that is how the system sees the antenna.

## Not done yet

- **No manufacturing CAD:** this is a concept model. A real cover needs draft angles, a gasket groove and screw bosses.
- **No EM simulation:** the transmission figures are a plane-wave model. They leave out edge effects and near-field coupling to the elements. An openEMS run of one element with its cover (the script in `pcb/` is the starting point) would confirm the detuning and the pattern.
- **Material values:** εr and tan δ are typical figures; get the real ones from the chosen supplier's datasheet.
