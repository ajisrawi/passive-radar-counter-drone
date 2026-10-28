# Receiver enclosures

There are two options:
- **All-in-one (current):** one box holds the whole site: 4 Board A2 front ends and 8 receiver stacks.
- **Per band group (alternative):** one smaller box per band, as originally designed.

# All-in-one enclosure (current)

One outdoor box on the mast, below the antenna panels, holds all four band groups.

`enclosure_all_blender.py` builds it from the real board layouts: 20 boards, 6,164 components as blocks. It renders the two views:

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P hardware/enclosure/enclosure_all_blender.py -- exterior interior

| File | View |
|---|---|
| `render_all_exterior.png` | the box from below: finned cover, 24 antenna inputs in four groups, shared entries |
| `render_all_interior.png` | cover off: four band columns, cabling, shared modules |
| `../antenna/render_radome_site.png` | the full site: panels, LPDAs, this box and the 16 feed cables |
| `enclosure_all.blend` | the model |

## Layout

The inside is four columns, one per band, left to right: `uhf`, `mid` (1.8–2.2 GHz), `high` (2.6 GHz), `n78`. Each column holds:
- **two receiver stacks:** each is a Board B for that band on a Board C2, 220 mm apart vertically;
- **that band's Board A2** at the bottom, right above its 6 antenna connectors (REF, S1–S4, AUX). The short input cables keep A2's noise figure.

The 90 × 170 mm space next to each A2 holds the shared modules:

| Column | Shared module |
|---|---|
| `uhf` | GNSS 1:8 splitter: one antenna feeds all 8 C2s |
| `mid` | PSU: 48 V → 12 V, 250 W |
| `high` | fibre tray: the 8 SFP+ fibres go to one 12-fibre IP67 connector, leaving 4 spare fibres |
| `n78` | DC surge protection and terminal block |

Every stack uses Board C2, so there is one boss pattern (4.5 mm from each corner). The UHF stacks could use Board C instead, but that board's holes need their own bosses (listed under the alternative design below).

## Main dimensions

| | |
|---|---|
| Inside (W × H × D) | 980 × 690 × 70 mm |
| Outside | 990 × 700 × 81 mm without fins; 109 mm deep with fins; plus the mast bracket |
| Fins | 87 vertical fins, 3 mm thick, 11 mm pitch, 28 mm deep, 680 mm long |
| Cover | 6 mm, 26 M4 A4 screws, EPDM gasket; 8 pedestals onto the 8 Zynqs |
| Mass (estimate) | about 42 kg (37 kg of cast aluminium). It's a two-person lift; use a hook-on bracket so the box hangs before it's bolted |
| Mast bracket | two 600 mm arms, clamp rings for a 114 mm pole, 440 mm apart |
| Wind load on the face, 160 km/h | about 1.1 kN |

## Bottom face

| Entry | Connector |
|---|---|
| Antennas | 24 × N female in four groups of 6 (REF, S1–S4, AUX per band), labelled by band |
| GNSS | TNC female |
| Fibre | one 12-fibre IP67 MPO connector, carrying 8 × 10 GbE to the host |
| Power | 48 V DC, about 3.5 A, 7/8"-16 or M16 4-pin. At about 160 W, PoE++ (90 W max) is no longer enough |
| Vents | 2 × Gore-type pressure-equalisation vents |
| Earth | M6 stud |

## Thermal estimate

| Heat source | W |
|---|---|
| 8 × Board C2 | 8 × 12 = 96 |
| 8 × Board B | 8 × 4 = 32 |
| 4 × Board A2 | 4 × 3.5 = 14 |
| PSU losses (90%) | 16 |
| **Total** | **about 158** |

**Cooling:** the same method as the per-band box below.
- **Fins:** 2.8 m² of effective fin area, at about 3.4 W/m²K. Natural convection is a little weaker on the taller 680 mm fins.
- **Rest of the case:** about 0.6 m².
- **Radiation:** about 7.4 W/K.
- **Result:** about **19 W/K** in all.

| | K |
|---|---|
| Case above ambient (shade) | +8 |
| Full sun on the 0.69 m² face (800 W/m², absorptivity 0.6) | +17 |
| Zynq die to cover | +15 |
| **Zynq at 50 °C ambient, in sun** | **about 90 °C** (100 °C max for the industrial -2I grade) |

**A sun shield is needed for hot sites.** A white shield 30 mm off the top and the finned face removes most of the +17 K. In shade the Zynq runs at about 73 °C.

## Trade-offs against four smaller boxes

**Gained:**
- one mounting and earthing point;
- one power feed and one fibre cable instead of four of each;
- one GNSS antenna;
- one cover to open for service;
- a cleaner mast.

**Lost:**
- **Single point of failure:** a failed PSU or a water leak takes down all bands at once.
- **Handling:** the box is 42 kg and about 1 m wide.
- **Heat:** the sun shield becomes a requirement in hot climates.
- **Cable length:** the four antenna panels' cables all run to one place. They are phase-matched sets per band, so this only costs cable length, not accuracy.

---

# Per-band-group enclosure (alternative)

One outdoor unit per band group, mounted on the antenna mast just below the surveillance panel. This keeps the phase-matched antenna cables short.

It holds:
- the Board A2 front end;
- the two receiver stacks that A2 feeds, each a Board B digitizer on a Board C2 processor (Board C fits the same mounting; it is 2.5 mm narrower and 12.5 mm shorter).

`enclosure_blender.py` builds it in Blender from the parameters at the top of the script. The real board layouts go inside: outlines, plus all 443 + 2 × 220 + 224 components as blocks. It then renders the three views:

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P hardware/enclosure/enclosure_blender.py -- exterior interior mast

| File | View |
|---|---|
| `render_exterior.png` | the unit from below: finned cover, cable entries |
| `render_interior.png` | cover off: the two B-on-C2 stacks, A2, PSU, internal coax and fibre |
| `render_mast.png` | on the pole under the UHF surveillance panel (4 slant dipoles, from `../antenna/design.json`) |
| `enclosure.blend` | the model |

## Main dimensions

| | mm |
|---|---|
| Inside (W × H × D) | 640 × 250 × 70 |
| Outside, without fins | 650 × 260 × 81 (5 mm walls, 6 mm cover) |
| Fins | 56 vertical fins, 3 mm thick, 11 mm pitch, 28 mm deep, 240 mm long, on the cover |
| Outside overall | 650 × 260 × 109, plus a 60 mm mast bracket |
| Board mounting | C2 on 8 mm standoffs from the back wall; B 10 mm above C2 on the FMC; A2 on 8 mm standoffs |
| Pole | 50–114 mm, two clamps 160 mm apart (shown on a 76 mm pole) |
| Mass (estimate) | about 11 kg (cast AlSi10Mg about 3.6 L, boards, PSU) |

## Construction

- **Body and cover:** die-cast (or CNC-machined, for the first units) aluminium, powder-coated RAL 7035, IP65.
- **Seal:** an EPDM gasket in the cover flange, with 20 × M4 stainless screws.
- **Heat path:** the Zynq on each C2 and the B digitizers sit under machined pedestals on the inside of the cover, with 1 mm thermal pads. Heat goes straight into the finned cover, which faces away from the mast.
- **Bottom face:** every cable enters from below, so rain drains away from the seals:

| Entry | Connector | Inside to |
|---|---|---|
| REF, S1, S2, S3, S4, AUX | 6 × N-type female bulkhead | A2 CH0–CH5 SMA inputs (RG-316 pigtails) |
| GNSS | TNC female | Board C2 GNSS antenna input (both stacks share one antenna through a splitter) |
| FIBRE A / B | 2 × IP67 LC duplex feed-through | the SFP+ cage of each C2 (10 GbE to the host) |
| PWR | M12 4-pin (A-coded), 48 V DC or PoE++ | PSU module 48 V → 12 V, 60 W |
| VENT | Gore-type pressure-equalisation vent | stops condensation pumping |
| Earth | M6 stud | body, cable shields, lightning protection |

- **Inside:**
  - A2's 12 outputs go to the two digitizers, 6 each, over equal-length RG-316. Board A2's noise source calibrates everything from its switches onward, so these cables need only be equal to within about ±5 mm.
  - The antenna side is different: the cables from the panel to the bulkheads are outside the calibration and must be a phase-matched set (see `../antenna/ANTENNA.md`).

## Thermal estimate

| Heat source | W |
|---|---|
| 2 × Board C2 (XC7Z035, DDR3, SFP+) | 2 × 12 |
| 2 × Board B (3 × AD9361, receive only) | 2 × 4 |
| Board A2 (LNAs, switches) | 3.5 |
| PSU losses (90%) | 4 |
| **Total** | **about 40** |

**Cooling:**
- **Convection:** the fins, at about 85% efficiency, give 0.75 m², and the rest of the case about 0.3 m². At 4.5 W/m²K natural convection that's about 4.2 W/K.
- **Radiation:** the painted case (ε 0.9) adds about 1.8 W/K.
- **Result:** about 6 W/K in all, so the case runs **about 7 K above ambient** in shade.

| | K |
|---|---|
| Case above ambient (shade) | +7 |
| Full sun (800 W/m² on about 0.17 m² at absorptivity 0.6 for RAL 7035) | +13 |
| Zynq die to cover through pedestal and pad (about 1.5 K/W × 10 W) | +15 |
| **Zynq at 50 °C ambient, in sun** | **about 85 °C** (industrial grade -2I: 100 °C max) |

A white sun shield over the top and the finned face removes most of the solar term. Fit one for desert sites.

## Not done yet

- **No manufacturing CAD:** this is a concept model for layout, cabling, thermal path and appearance. A casting or CNC drawing needs a proper CAD model (draft angles, bosses, gasket groove) built from these dimensions.
- **Standoff positions:** they sit at the board corners in the model. Every board has four M3 holes, and the bosses in the CAD model must follow them:
  - **Board C2:** at 4.5 mm from each corner.
  - **Board B:** at 4.5 mm from each corner.
  - **Board A2:** at (4.5, 24), (125.5, 4.5), (4.5, 165.5) and (125.5, 165.5); the first one clears the DC jack.
  - **Board C:** at (4.5, 4.5), (213, 4.5), (4.5, 163.5) and (213, 183). So a Board C build needs its own boss pattern.
- **Thermal numbers are hand estimates:** check them with a thermal simulation or a powered prototype in a climate chamber.
