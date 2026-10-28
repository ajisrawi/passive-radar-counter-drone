# Passive Radar Receiver: Hardware

A custom 6-channel coherent receiver for the DVB-T passive radar in [`../docs/DESIGN.md`](../docs/DESIGN.md), built as three boards.

| | Board A: RF front end | Board B: digitizer | Board C: processing |
|---|---|---|---|
| Function | 6 × (switch → LNA → band filter) + calibration noise source | 3 × AD9361 = 6 phase-coherent RX channels, 40 MHz clock tree | Zynq-7020 + DDR3L, Gigabit Ethernet, GNSS time, FMC carrier |
| Key parts | SPF5043Z, PE4259, LT3045 | AD9361BBCZ, LMK1C1104, ADP1755 | XC7Z020-1CLG400C, NT5CC256M16, RTL8211F, MAX-M10S |
| Parts / nets | 194 / 98 | 228 / 166 | 314 / 251 |
| Layers, size | 4, 130 × 152 mm | 8, 150 × 105 mm | 8, 217.5 × 187.5 mm |
| Status | Routed, 0 DRC errors (KiCad); Gerbers not yet made | Routed with OpenBoard, Gerbers in `route/fab_routed/`; HDI (microvias + buried vias), needs JLCPCB's HDI service | Routed with OpenBoard, Gerbers in `route/fab_v10/`; HDI, needs JLCPCB's HDI service; BOM/CPL not yet made. For 4G/5G stacks see Board C2 |

```
 antennas ──6× SMA──► [A] switch/LNA/filter ──6× coax──► [B] 3× AD9361 ══FMC LPC══► [C] Zynq-7020 ──► Ethernet
 (1 ref + 4 surv + 1 spare)   ▲ noise source               ▲ 40 MHz TCXO ─► 1:4 buffer      │ GNSS PPS (multi-node sync)
                              └──────── CAL_EN (2-pin cable) ◄───────────────────────────────┘
```

## Files

| Path | What |
|---|---|
| `release/board_x/board_x_easyeda_import.zip` | **Import into EasyEDA Pro.** KiCad 8-format project: schematics, placed PCB, symbol and footprint library |
| `release/board_x/board_x_schematic.pdf` | Schematic for review |
| `release/board_x/board_x_BOM_JLCPCB.csv` | BOM with LCSC part numbers (JLCPCB assembly format) |
| `release/board_x/board_x_CPL_JLCPCB.csv` | Pick-and-place (regenerate after you route, in case parts move) |
| `release/board_x/board_x_top.png`, `_bottom.png` | Placement renders |
| `board_x/` | Native KiCad 10 project (open in KiCad 10 to edit or route) |
| `boards/board_x.py` | **Source of truth** for each schematic (Python). Edit here, regenerate |
| `boards/layout_x.py` | Placement scripts (run with KiCad's Python) |
| `tools/` | Generator, verifier, FMC pin map, filter designer, KiCad 8 converter, release builder |
| `parts.py` | Selected parts with LCSC numbers |

Regenerate everything:
```bash
python boards/board_a.py && python tools/verify.py board_a      # same for b, c
"C:/Program Files/KiCad/10.0/bin/python.exe" boards/layout_a.py
python tools/release.py
```

## What was verified

- **ERC:** KiCad electrical rules check reports **0 errors and 0 warnings** on all three schematics.
- **Netlist:** KiCad's exported netlist matches the intended design **pin for pin** (500 + 950 + 1355 connections, 0 differences; `tools/verify.py`).
- **Board-to-board:** all 160 FMC pins agree between B (mezzanine) and C (carrier). The only intentional asymmetries are noted in `tools/fmc.py`.
- **Placement DRC:** 0 overlaps, clearance or edge violations. Only silkscreen cosmetics and the expected unrouted connections remain.
- **Pin-outs:** symbols and footprints for every IC come from the LCSC/EasyEDA library (`easyeda2kicad`), not hand-drawn.
- **RF filter:** designed and simulated with 0402 losses (`tools/filter_design.py`): 0.7 dB in band, −34 dB at FM, −44 dB at 1.8 GHz.
- **Bring-up bug fixed in review:** Board C's 1.0 V power-good would not have enabled the next regulator (0.8 V < 0.9 V threshold). It now uses a 12 V divider.
- **KiCad 8 copy:** the KiCad 8 PCB copy reloads with identical footprints, copper-pad nets, zones and vias.

**Not done / not verifiable here:**
- **Routing:** not done, per your choice.
- **Signal and power integrity:** no SI/PI simulation.
- **Thermal:** no thermal analysis.
- **FPGA:** no firmware or bitstream.
- **EasyEDA import:** I could not test it. EasyEDA Pro's guide only promises KiCad 5.1/5.9 imports, so the zips use the older KiCad 8 format to maximize compatibility. If an import fails, open `board_x/` in KiCad 10 instead; KiCad can route and export Gerbers too.

## Board A: RF front end

- **Per-channel signal chain:** SMA → PE4259 SPDT (RF2 = antenna, RF1 = calibration) → SPF5043Z LNA (0.8 dB NF, ~18 dB, OIP3 35 dBm, biased via a 220 nH choke) → 3rd-order high-pass (420 MHz) + 5th-order low-pass (780 MHz) → SMA.
- **Noise figure:** about 1.2 dB at the antenna port.
- **Calibration source:** a 50 Ω termination feeds 3 cascaded SPF5043Z amplifiers with 3 dB pads between stages, then a 6-way 35.7 Ω star splitter. That gives about 39 dB ENR into every channel.
- **CAL_EN high:** the LT3045 that powers the noise amplifiers turns on, and all switches select RF1. The digitizer then measures each channel's phase and gain offset.
- **Power:** 12 V → TPS62130 (5.6 V) → LT3045 (5.0 V, 0.8 µV rms) for the LNAs and a second LT3045 for the noise source → TLV75533 (3.3 V) for the switches.
- **Layout:** six straight lanes, 13 mm apart, with GND via fences, a solid GND plane on L2 and the noise source above the lanes.
- **Known limitation:** LTE800 (791–821 MHz) is only attenuated by about 2 dB. Rejecting it sharply 14% above the band needs a SAW/cavity filter, which LCSC doesn't stock for this band. If a strong LTE800 site is nearby, insert a site-specific DVB-T channel filter in the coax between A and B.

## Board A2: multiband front end (TV + 4G + 5G), replaces Board A

One design (`boards/board_a2.py`) is built in four band versions. Each build feeds two receiver stacks through a 2-way splitter on every channel. The band plan is in [`../docs/DESIGN.md`](../docs/DESIGN.md) §3.1. Drawn with **OpenSchematic** and laid out and routed with **OpenBoard/OpenRoute**; the files are in `board_a2/<band>/`.

| Build | Pass band | LNA stages | Band filter (LCSC) | DC blocks | Bias choke |
|---|---|---|---|---|---|
| `uhf` | 470–821 MHz | 1 | LC 420–920 MHz: 0.7–1.1 dB, −34 dB at FM, −39 dB at 1.8 GHz | 100 pF | 220 nH 0603 |
| `mid` | 1805–2170 MHz | 2 | Walsin RFBPF1608060AAT, 1.5–2.4 GHz (C474007) | 33 pF | 100 nH 0603 |
| `high` | 2496–2690 MHz | 2 | TDK DEA162495BT-1289A1, 2.3–2.69 GHz, 1.4 dB (C432966) | 22 pF | 100 nH 0603 |
| `n78` | 3300–3800 MHz | 2 | TDK DEA203750BT-2292A1-H, 3.3–4.2 GHz, 1.5 dB, ~40 dB at 1.8–2.7 GHz (C3156235) | 10 pF | 22 nH 0402 |

**Per channel (6 channels):**
- **Signal chain:** SMA → DC block → **SKY13351-378LF** SPDT, 20 MHz–6 GHz, 0.35 dB (C129189) → SPF5043Z LNA (+ second SPF5043Z on `mid`/`high`/`n78`) → band filter → 3 × 16.5 Ω resistive splitter → 2 × SMA.
- **Why two stages up high:** SPF5043Z gain falls from 18 dB at 0.9 GHz to 8 dB at 3.5 GHz. With one stage, the n78 system noise figure would be about 5 dB; with two it is about 2.3 dB.

**Switch control:** VCTL1 = CAL_EN, and VCTL2 = NOT CAL_EN from an SN74LVC1G04 (C7827).
- CAL_EN low (the default, with a 100 k pull-down) connects the antenna on OUTPUT1.
- CAL_EN high connects the noise source on OUTPUT2 and powers the noise source.

**Calibration source:** the same 3-stage noise source and 6-way star splitter as Board A, with each build's DC blocks and chokes.
- **Noise level:** ENR is about 39 dB at UHF, falling to about 15 dB at 3.5 GHz as the LNA gain drops.
- **CAL line lengths:** the calibration lines run on the bottom layer to every switch. Their lengths are matched, because a length difference becomes a phase error in the calibration.

**Power:** 12 V → TPS62130 (5.6 V) → feeds the rails below.
- Two LT3045 LNA rails (channels 0–2 and 3–5). Up to 12 LNAs × 46 mA is more than one LT3045 can supply.
- One LT3045 for the noise source.
- A TLV75533 for the 3.3 V logic.

**Stack-up:** 4 layers.
- L1: RF, 50 Ω CPW, 0.36 mm wide.
- L2 and L3: solid GND.
- L4: calibration lines (0.36 mm over L3) and power traces.

**Board:** 130 × 170 mm. Six lanes 18 mm apart run from the antenna SMAs on the left to the output SMA pairs on the right.

**Verification:**
- **OpenSchematic ERC:** 0 errors and 0 warnings on all four builds.
- **Netlist:** OpenSchematic's netlist matches the generator net for net on all four builds (120–126 nets). The only extras are 5 intentionally unconnected regulator and inverter pins.

**Layout results:**

| Build | Connections routed | Vias | CAL lines (matched) | RF fence vias | OpenBoard DRC | GND pour islands | Drill |
|---|---|---|---|---|---|---|---|
| `uhf` | 456 / 456 | 108 | 182.17 mm, spread 0.0 mm | 586 | clean | 0 | through-hole only |
| `mid` | 456 / 456 | 105 | 182.17 mm, spread 0.0 mm | 617 | clean | 0 | through-hole only |
| `high` | 462 / 462 | 106 | 182.17 mm, spread 0.0 mm | 611 | clean | 0 | through-hole only |
| `n78` | 474 / 474 | 124 | 200.63 mm, spread 0.0 mm | 622 | clean | 0 | through-hole only |

**Fab files** are in `board_a2/<band>/fab/`: `board_a2_<band>-fab.zip` (Gerbers and drill), plus the BOM and CPL. Rebuild everything with:

```bash
python boards/board_a2.py all
python tools/layout_a2.py <band>
node ".../openpcb.js" route board_a2/<band>/board_a2_<band>.openboard.json --keep --passes 14
python tools/finish_a2.py <band>
```

Layout steps that make the boards routable:
- **Neck-down regions** (`openpcb region`):
  - around each SKY13351 (0.35 mm pitch) and the n78 filter (0.045 mm pad gaps): 0.2 mm tracks at 0.1 mm clearance;
  - around the fine-pitch power ICs: 0.25 / 0.15 mm.
- **Pre-routed, locked copper:**
  - the switch control lines: a stub and via per switch, plus two vertical B.Cu buses;
  - the switch INPUT → DC-block lines.

  The autorouter does the rest.
- **`tools/ob_footprints.py`** works around two OpenBoard KiCad-import bugs:
  - unnumbered (paste-only) pads become numbered copper. On the TPS62130's VQFN-16 that shorted SW, PG and GND;
  - custom-shape pads keep only their 0.005 mm anchor. The switch's T-shaped GND pad vanished; it is rebuilt from the polygon.

**Before ordering, check in JLCPCB's preview:**
- **Part rotations:** the CPL file comes from OpenBoard.
- **Generic passives:** the BOM carries LCSC numbers for every specific part. Generic resistors, capacitors and inductors are left to JLCPCB's value/footprint matching, as in the original BOMs.
- **SKY13351 GND pad:** check it on the paste layer.

## Board C2: 10 GbE processing board for the 4G/5G stacks

The 4G/5G stacks need 1–5.4 Gbit/s, beyond Board C's Gigabit Ethernet. C2 is Board C with a bigger Zynq and two 10 GbE ports. Drawn with OpenSchematic (`python boards/board_c2.py`) and laid out in OpenBoard (`python tools/setup_c2.py && python tools/layout_c2.py`, then `openpcb route`). Files are in `board_c2/`.

| Block | Board C | Board C2 |
|---|---|---|
| SoC | XC7Z020-1CLG400C | **XC7Z035-2FFG676I** (C1884735). 8 GTX transceivers, 10.3125 Gbit/s in the -2 FFG package; the cheaper FBG packages stop at 6.6 Gbit/s |
| DDR | 512 MB x16 | **1 GB x32**: 2 × NT5CC256M16, fly-by U2 → U3 → VTT |
| 10 GbE | — | **2 × SFP+** on GTX quad 112, lanes 0/1, 10GBASE-R. TE 1888247-1 connector (C305914) + 2227302-1 press-fit cage (C589577) |
| GTX clock | — | YXC 156.25 MHz LVDS oscillator (C7425469), AC-coupled into MGTREFCLK0_112 |
| GTX power | — | MGTAVCC 1.0 V and MGTAVTT 1.2 V on their own TPS62130 bucks with ferrite filters. MGTVCCAUX 1.8 V. MGTRREF: 100 Ω 1 % to MGTAVTTRCAL |
| SFP+ control | — | TX_DISABLE/TX_FAULT/RX_LOS/MOD_ABS on PS MIO 28–35, which are 3.3 V like the module's pull-ups. SFP+ I2C via a TCA9543A (C2653307) on I2C1, because both modules answer at 0xA0/0xA2. RS0/RS1 pulled high (full rate). SFF-8431 supply filters: 1 µH + 22 µF + 100 nF per rail |
| AD9361 LVDS | HR banks 34/35 | **HR banks 12/13 at 2.5 V**. On the 7Z035, banks 33–35 are HP (1.8 V max). DCLKs on MRCC pins B13.L12/L13 and B12.L12; FMC reference clock on B13.L11 (SRCC) |
| GNSS | bank 13 at 3.3 V | HP bank 33 at 1.8 V. The MAX-M10S V_IO runs at 1.8 V with **VIO_SEL tied to GND**, as u-blox requires for 1.8 V I/O |
| Management | GbE, USB console, QSPI/SD boot | unchanged |

**Power sequence:**
1. 1.0 V comes up first.
2. Then 1.8 V and MGTAVCC 1.0 V.
3. Then 1.35 V, 3.3 V, 2.5 V, and MGTAVTT 1.2 V after MGTAVCC (UG476).
4. Finally PS_POR_B is released.

**Board:**
- **Size and stack-up:** 220 × 200 mm, 10 layers, 6 of them signal:

  | Layer | Use |
  |---|---|
  | F.Cu | signal |
  | In1 | GND |
  | In2 | signal |
  | In3 | signal |
  | In4 | +1V35 island under the DDR3 / +1V0 everywhere else |
  | In5 | VADJ island over banks 12/13 and the FMC / +3V3 everywhere else |
  | In6 | signal |
  | In7 | signal |
  | In8 | GND |
  | B.Cu | signal |

  - **Why 10 layers:** with 8 layers (4 signal) the router stalled at about 1,100 conflicts. F.Cu carried 43 % of the copper and 57 % of the conflicts, from escape out of the FFG676 and the x32 DDR3 channel. With 10 layers it was down to 946 conflicts by pass 3.
- **Vias:** through-vias only, 0.4 / 0.2 mm. Rules use JLCPCB's multilayer limits: via hole to track 0.2 mm, via hole to hole 0.2 mm.
  - **Why through-vias:** so the board builds on JLCPCB's standard process.
  - **HDI fallback:** JLCPCB also offers HDI, with blind/buried vias on 4–32 layers, 0.075–0.15 mm laser microvias and 0.15–0.55 mm buried vias. It costs more, but is the fallback if the through-via layout cannot be completed.
- **Layout steps that made it routable:**
  - **Neck-down regions** (0.1 / 0.1 mm) around the 14 fine-pitch parts carrying power pins;
  - **BGA decoupling** moved to strips just outside the FPGA and DDR3 ball fields. Packed under the FPGA it had blocked 164 of 625 via sites;
  - **+1V35 and VADJ** as plane islands instead of 0.4 mm tracks;
  - **Differential pairs** allowed 5–10 mm uncoupled to escape the BGA.
- **Placement:**
  - DDR3 above the Zynq, close to the PS DDR balls;
  - SFP+ cages on the bottom edge, below GTX quad 112;
  - FMC on the right edge, facing banks 12/13;
  - PS peripherals on the left, GNSS bottom-left, power along the top.
  - Board B sits over the FMC end, and the tall SFP+ cages stay clear of it.
- **Routing rules:**
  - **43 differential pairs:** SFP+ lanes, reference clocks, DDR CK/DQS and every AD9361 LVDS pair.
  - **8 length groups:** 4 DDR byte lanes at ±0.5 mm, address/command at ±1 mm, and each AD9361's LVDS bus at ±1 mm.

**Schematic checks:**
- **Size:** 455 parts and 331 nets.
- **FPGA pins:** every power, ground and configuration pin of the FPGA is connected. Only spare I/O, the unused GTX lanes and reference clocks (left open per UG476) and 8 spare MIO pins are unconnected.
- **KiCad ERC:** 0 violations.
- **OpenSchematic ERC:** 0 errors. It still shows 3 "no driver" warnings on GNSS input pins that carry no-connect flags; KiCad honours the flags and OpenSchematic doesn't.
- **Netlist:** the OpenSchematic netlist matches the generator on all 331 nets.

## Board B band variants (mid, high, n78)

Board B's ATB2012-50011 input baluns cover only 40–860 MHz. The 4G/5G stacks therefore use a variant of the same board in which only two things change. Drawn with OpenSchematic (`python boards/board_b.py <band>`) and laid out in OpenBoard (`python tools/eco_b_band.py <band>`). Files are in `board_b_bands/<band>/`.

| Variant | Balun T1–T6 | Coupling caps (12 ×) |
|---|---|---|
| UHF (unchanged Board B) | TDK ATB2012-50011, 40–860 MHz (C92015) | 100 pF |
| `mid` | **Mini-Circuits TCM1-63AX+**, 10 MHz–6 GHz, 50:50 (C494678) | 33 pF |
| `high` | TCM1-63AX+ | 22 pF |
| `n78` | TCM1-63AX+ | 10 pF |

**The balun:**
- **Why this part:** TCM1-63AX+ is the balun ADI uses in front of the AD9361 on AD-FMCOMMS3, so one part covers all three upper bands. The band-specific Johanson baluns (1720BL15, 2450BL15, 3600BL14) are all out of stock at LCSC.
- **Pins:** 3 = unbalanced input, 2 = ground, 6 and 4 = balanced outputs, 1 and 5 unused.
- **Cost:** about $12.6 each, so about $76 per board.

**Layout:** the finished routed Board B (`board_b/route/board_b_routed.openboard.json`) is changed as a minimal ECO, not re-laid out.
- **Balun placement:** the larger TCM1 body (3.3 × 4.8 mm) is rotated 90° and moved 0.7 mm away from each SMA. On channel 5 it also moves 2 mm right to clear R29–R31.
- **Routing:** only the balun nets (CHx_BAL/BP/BN) and two ground vias under the new bodies were rerouted, with `openpcb route --keep`.
- **Why not a full sync:** a full `openpcb sch-to-board` sync was not used. It would also drop the do-not-fit attenuator footprints and rename footprints on the finished board.
- **mid → high and n78:** `mid` was routed first. `high` and `n78` share its copper and differ only in cap values.

**Checks (all three variants):**
- **ERC:** OpenSchematic ERC has 0 errors and 0 warnings.
- **Netlist:** the generator and OpenSchematic netlists match.
- **Routing and DRC:** 456/456 connections routed, OpenBoard DRC clean, no GND pour islands.
- **Board vs schematic:** all 166 nets of the routed board match the OpenSchematic netlist pin for pin. The only difference is the mounting-hole via pads listed under GND.
- **Values:** every part value matches.

**Fab files** are in `board_b_bands/<band>/fab/`: Gerbers and drill zip, BOM with LCSC numbers on every specific part (24 of 40 lines), and CPL.

**Not changed by this step:**
- **HDI vias:** the base Board B's layout uses laser microvias (0.25 / 0.1 mm, e.g. F.Cu–In1, In5–B.Cu) and buried vias (In2–In5). It can be built with **JLCPCB's HDI service** (blind/buried vias on 4–32 layers, 0.075–0.15 mm laser microvias), which costs more than a standard board. An earlier note here said these boards could not be made at JLCPCB; that was wrong. The same applies to the original Board C layout.
- **RF/LVDS routing:** the RF and LVDS lines are still plain 0.1 mm traces, with no impedance control.

Both still need fixing before fabrication, the same as for the UHF Board B.

## Board B: digitizer (FMC LPC mezzanine)

- **Channel map:** CH0 (reference) → AD1 RX1A, CH1 → AD1 RX2A, CH2/3 → AD2, CH4/5 → AD3. TX paths are unused.
- **Inputs:** SMA → π-attenuator positions (0 Ω fitted) → ATB2012-50011 1:1 balun (40–860 MHz) → 100 pF AC coupling → RXxA_P/N, with a DNP differential match position.
- **Coherence:**
  - **Shared clock:** one 40 MHz TCXO (±0.5 ppm) drives a 2.5 V resistive level shift into the LMK1C1104 1:4 buffer (< 50 fs added jitter).
  - **XTALN feed:** buffer outputs Y0–Y2 go to each AD9361 XTALN through 33 Ω + a 120/100 Ω divider, ~1.0 Vpp, AC-coupled. These three traces must be length-matched.
  - **FPGA reference:** Y3 → FMC CLK0_M2C.
  - **External reference:** a DNP SMA input accepts an external 40 MHz (e.g. GPS-disciplined) reference.
  - **Multi-chip sync:** AD_SYNC_IN from the FPGA fans out through 22 Ω to each SYNC_IN.
  - **Residual LO phase:** each chip locks its LO separately, so the inter-chip LO phase is fixed but unknown after every retune. It is measured with Board A's noise source.
- **Data interface:** LVDS, 9 pairs per chip (DATA_CLK on a clock-capable LA pair, RX_FRAME, RX_D0–5, FB_CLK), as in `tools/fmc.py`. Shared 4-wire SPI with three SPI_ENB lines.
- **Power:**
  - **1.3 V rails:** FMC 12P0V → TPS62130 (1.8 V) → 3 × ADP1755 (1.3 V, one per AD9361), split by ferrite beads into RF / SYNTH / BB / DIG rails as in ADI's FMCOMMS2.
  - **VDD_INTERFACE:** fed from **VADJ, which the carrier must set to 2.5 V**.
  - **Other rails:** VDD_GPO, the TCXO and the clock LDO come from FMC 3P3V.
- **Mechanical:** 150 × 105 mm (wider than a standard single-width FMC). The FMC connector is on the bottom side. Mount on 10 mm standoffs over Board C.

## Board C: Zynq processing board (FMC LPC carrier)

| Bank | Voltage | Use |
|---|---|---|
| 500 (MIO 0–15) | 3.3 V | QSPI boot flash, boot straps, I2C0 → FMC, LED, button |
| 501 (MIO 16–53) | 3.3 V | RGMII → RTL8211F, SD0 → microSD (no level shifter needed), UART1 → CP2102N, MDIO |
| 502 | 1.35 V | DDR3L x16 (512 MB), fly-by end termination to VTT (TPS51200) |
| 13 | 3.3 V | GNSS UART + PPS (on an SRCC pin), FMC_PRSNT_L, 2 LEDs |
| 34 / 35 | 2.5 V (VADJ) | AD9361 LVDS. AD1 + AD2 → bank 35 (DATA_CLK on MRCC L12/L13), AD3 + controls → bank 34 (DATA_CLK on MRCC L12) |

- **Boot:** QSPI with the jumper open, SD with it closed (MIO[5:3] = 100 / 110). The console is on USB-C (CP2102N, UART1). JTAG uses the Xilinx 14-pin 2 mm header.
- **Power sequence:**
  1. 12 V → 1.0 V (VCCINT, VCCPINT, VCCBRAM).
  2. PG → 1.8 V (VCCAUX, VCCPAUX, VCCPLL via filter, VCCADC).
  3. PG → 1.35 V, 3.3 V and 2.5 V together.
  4. All PGs good (wired-AND) → PG_C2M to the mezzanine, DDR VTT enable, and PS_POR_B release after ~10 ms.
- **GNSS:** u-blox MAX-M10S with an active-antenna bias from VCC_RF. The PPS lets several receiver nodes timestamp coherently for multistatic operation.

### Data link to the processing host (FPGA requirement)

Raw samples from 6 channels need 1.3–1.8 Gbit/s. The single Gigabit Ethernet port carries 957 Mbit/s of UDP payload (no jumbo frames on the Zynq-7000), and the design limit is 718 Mbit/s. The fix needs **no hardware change**; it lives in the FPGA design. The budget and the simulation behind it are in [`../docs/DESIGN.md`](../docs/DESIGN.md) §6.4 and `pcl/data_rate.py`.

| FPGA block | What it does |
|---|---|
| Resampler | 64/7 → 8.000 MS/s, exact 7/8 polyphase, on all streamed channels |
| Direct-signal canceller | 4 surveillance channels: subtract a 128-tap complex FIR of the reference. The host loads the taps between CPIs |
| Requantiser | Surveillance residual → 8-bit I/Q (6-bit fallback mode). Reference kept at 12 bits |
| Snapshot | About once a second, 65 k raw 12-bit samples of all 5 channels, for tap updates and noise-source calibration |
| Packetiser | UDP over PS GEM0. Each frame carries a sample counter, a PPS timestamp and the tap-set ID |

- **Stream rate:** 704 Mbit/s (74 % of the link), 576 Mbit/s in the 6-bit fallback mode.
- **Sensitivity cost:** −0.1 to −0.3 dB in simulation. Raw 8-bit samples would cost 8.5–13 dB.
- **AGC:** set the AD9361 gain so the signal RMS sits 14 dB below full scale.
- **Channels:** reference plus 4 surveillance are streamed; the sixth channel is a configurable spare.
- **DSP use:** about 94 of the XC7Z020's 220 DSP48 slices.

## Routing rules (for EasyEDA or KiCad)

Get exact widths from the JLCPCB impedance calculator for the stack-up you order. The values below assume JLC04161H-7628 (4-layer) and a JLC 8-layer 1.6 mm build.

| Net class | Nets | Rule |
|---|---|---|
| RF 50 Ω | Board A `CH*_ANT/SW_*/LNA_*/F*`, Board B `CH*_IN/BAL` | Grounded CPW on L1 over GND L2: ~0.36 mm track / 0.20 mm gap (4-layer). Short and straight, no vias, GND vias along both sides every 2 mm |
| RF diff 100 Ω | Board B `CH*_BP/BN/RXP/RXN` | Coupled pair on L1, ≤ 10 mm, matched to 0.1 mm |
| LVDS 100 Ω | `AD*_DCLK/FRAME/RXD*/FBCLK_P/N` (B and C) | Differential pairs on an inner layer between GND planes. Match within each chip's 9 pairs to ±1 mm (including connector). P/N matched to 0.1 mm |
| Reference clock | `CLK_Y0..2 → AD*_XTALN` | Single-ended 50 Ω. **All three equal length (±1 mm)**. Keep away from LVDS and switchers |
| DDR3L | `DDR_*` | 40 Ω single-ended, 80 Ω CK/DQS differential. DQ/DM byte lane matched to its DQS to ±0.5 mm. Address/command fly-by to the VTT terminations, matched to CK to ±2 mm. Keep everything on layers next to solid GND |
| RGMII | `RGMII_*` | 50 Ω, each direction matched to its clock to ±2 mm. Delays are provided by the PHY straps (RXDLY = TXDLY = 1) |
| Ethernet MDI | `ETH_D*` | 100 Ω differential to the magjack |
| Power | regulator in/out, `+12V*`, `*_1V3`, `+1V0`, `+1V8`, `+1V35` | ≥ 0.5 mm, or pours. Buck switch nodes (`*_SW`) short and wide, inductor right next to the pin |
| Default | everything else | 0.1 mm / 0.1 mm on boards B and C (0.8 mm BGA escape), 0.2 mm on board A |
| Vias | — | B/C: 0.45/0.2 mm (BGA dog-bone). A: 0.6/0.3 mm |

Decoupling 0402s for the BGAs are on the **bottom side** under each BGA, and the DDR decoupling is under the DRAM. Keep them there when you route.

## Review checklist (must be checked against datasheets before fabrication)

These are items where I relied on recalled datasheet details that I could not open and confirm here:

1. **PE4259:** single-pin mode truth table (assumed CTRL = H selects RFC–RF1). V_IH = 0.7 × VDD is 2.31 V and CAL_EN is 2.5 V logic, which is marginal. If it fails, run the switches at 2.5 V or add a buffer.
2. **LT3045:** PGFB tied to IN when PG is unused.
3. **AD9361:**
   - VDD_INTERFACE = 2.5 V in LVDS mode.
   - Unused pins: TX outputs, EXT_LO inputs, AUXADC and CTRL_OUT left open; TEST/ENABLE and CTRL_IN to GND.
   - XTALN external-clock drive level.
   - SPI_DO goes high-Z when SPI_ENB is high (needed for the shared bus).
4. **ATB2012-50011 balun:** pad functions (1 unbalanced, 2 GND, 3/4 balanced).
5. **FMC LPC pin map** in `tools/fmc.py` vs VITA 57.1 (written from the standard, not copied from it).
6. **Zynq:**
   - PS_DDR_VRN/VRP: 80.6 Ω to VCCO_DDR and GND.
   - Unused DDR byte lanes 2–3 left open.
   - RSVDVCC1–3 → 3.3 V, PS_MIO_VREF divider, PUDC_B, VCCBATT to GND, XADC unused handling.
   - Boot-mode encoding.
7. **RTL8211F:** strap meanings (CFG_LDO = 00 → 3.3 V RGMII, PHYAD, delays) and the switching-regulator inductor.
8. **HR911130C magjack:** P1 = centre tap, P10 = GND, LEDs unused.
9. **DC-005C-20A jack:** pin 1 = centre (+).
10. **MAX-M10S:** VIO_SEL left open, V_BCKP on 3.3 V.
11. **Noise source:** stability of three cascaded wideband amplifiers. Add a shield can and check for oscillation at bring-up.
12. **Thermal:** three AD9361s plus the Zynq dissipate about 6–8 W in total. Plan airflow or a heatsink.

## Parts cost (one set, LCSC prices observed 2026-10-20)

| Part | Cost |
|---|---|
| AD9361 × 3 | ~$315 |
| XC7Z020 | ~$79 |
| DDR3L | ~$27 |
| FMC connector pair | ~$39 |
| TCXO | ~$15 |
| LT3045 × 2 | ~$16 |
| Everything else | ~$100–150 |
| **Total** | **≈ $600–650 per receiver** |

PCBs and assembly are extra: an 8-layer 150 × 105 mm board with BGA assembly is typically $250–500 for 5 pieces at JLCPCB.

## Importing into EasyEDA Pro

1. EasyEDA Pro → **File → Import → KiCad**, then choose `release/board_x/board_x_easyeda_import.zip`. Import each board as its own project.
2. Check that the symbols and footprints resolved. They come from the LCSC library, so EasyEDA should recognize the LCSC numbers.
3. Route using the rules above. The EasyEDA autorouter is fine for low-speed nets, but route RF, LVDS, DDR and clock nets by hand first, then lock them.
4. Rebuild copper areas. EasyEDA re-pours on import; check that GND planes are continuous under RF and LVDS.
5. Run EasyEDA DRC, then order from JLCPCB using the BOM (LCSC numbers) and a regenerated pick-and-place file.
