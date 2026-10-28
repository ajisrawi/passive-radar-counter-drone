# Passive Radar for Counter-Drone: System Design

**Concept:** Passive Coherent Location (PCL) using existing DVB-T / DVB-T2 digital TV broadcasts as the illuminator.
**Status:** Design + validated simulation (`run_demo.py`). Hardware not yet built.

---

## 1. Why passive radar for counter-UAS

| Property | Passive radar | Active radar | RF detector | EO/IR camera |
|---|---|---|---|---|
| Emits RF / detectable | **No** (covert, no jamming of others) | Yes | No | No |
| Needs spectrum licence | **No** (receive only) | Yes | No | No |
| Detects autonomous / RF-silent drones | **Yes** | Yes | **No** | Yes |
| Range + velocity | Yes | Yes | Bearing only | Bearing only |
| Works at night / in fog | Yes | Yes | Yes | Degraded |
| Cost | Low–medium | High | Low | Medium |

Main drawbacks: it depends on a third-party transmitter, the geometry is bistatic, and the direct signal is 40–70 dB stronger than the echoes and has to be cancelled. Passive radar is best used as the wide-area **detect and track** layer that cues an EO/IR camera for identification.

## 2. Requirements (target)

| Parameter | Requirement |
|---|---|
| Targets | Group 1–2 UAS: quadcopters (RCS ≈ 0.001–0.01 m² at UHF), small fixed-wing (≈ 0.05 m²) |
| Detection range | ≥ 3 km for 0.01 m² (single node); ≥ 1.5 km for 0.001 m² |
| Coverage | 90–120° sector per array face; 360° with 3–4 faces or several nodes |
| Range resolution | ≤ 40 m bistatic |
| Velocity resolution | ≤ 1 m/s |
| Update rate | ≥ 4 Hz (CPI 0.25 s) |
| Position accuracy | ≤ 30 m at 2 km (single node, range × angle) |
| Latency | < 1 s detection-to-display |
| Outputs | Tracks (ASTERIX CAT-062 / JSON), camera cueing, alerts |

## 3. Illuminator selection

| Illuminator | Band | Bandwidth → bistatic range res. | Typical ERP | Verdict |
|---|---|---|---|---|
| FM radio | 88–108 MHz | ~100 kHz → ~1.5–3 km | 10–100 kW | ✗ Resolution too coarse; λ = 3 m puts drones deep in the Rayleigh region (very small RCS) |
| DAB | 174–240 MHz | 1.5 MHz → 200 m | 1–10 kW | △ Usable for longer-range coarse detection |
| **DVB-T/T2** | **470–694 MHz** | **7.6 MHz → 39 m** | **1–100 kW** | **✓ Primary choice.** Good resolution, high power, ubiquitous, continuous, noise-like OFDM |
| LTE / 5G NR (downlink) | 0.7–3.8 GHz | 10–100 MHz → 3–30 m | 10–100 W per sector | ✓ Secondary / urban short range. Better resolution and RCS, much less power, bursty (load-dependent) |
| Wi-Fi | 2.4 / 5 GHz | 20–160 MHz | < 1 W | Indoor / < 200 m only |
| GNSS / Starlink | L / Ku | — | very weak at ground | Research only |

**Choice (revised 2026-10-26): TV, 4G and 5G together, all received at the same time.** Each illuminator covers another's weakness:
- **DVB-T** gives long range: steady high power from a high mast, about 15 km against a 0.01 m² drone.
- **4G** gives 13–17 m range cells in cities, plus dense coverage.
- **5G n78** gives about 5 m range cells and the strongest micro-Doppler at 3.5 GHz.

Detections from all bands are fused in the tracker.

### 3.1 Multiband receiver: one stack per band

Each AD9361 has a single receive tuning shared by its two channels. Each band therefore needs its own coherent set of 1 reference + 4 surveillance channels, which is one receiver stack: front end A2 → digitizer B → processor C. All stacks at a site share one 40 MHz reference (Board B's `EXT_REF` input, through a clock distribution amplifier) and the GNSS PPS.

| Front-end build (Board A2) | Pass band | Stack A | Stack B | Range resolution (c/B) | Stack data rate | Array spacing (λ/2 at top of band) |
|---|---|---|---|---|---|---|
| `uhf` | 470–821 MHz | DVB-T (8 MHz) | LTE B20/B28 + 5G n28 (10 MHz) | 39 m / 30 m | 0.70 / 1.01 Gbit/s | 18 cm |
| `mid` | 1805–2170 MHz | LTE B3 (20 MHz) | LTE B1 (20 MHz) | 17 m | 2.0 Gbit/s each | 6.9 cm |
| `high` | 2496–2690 MHz | LTE B7 (20 MHz) | 5G n41 (56 MHz slice) | 17 m / 5.6 m | 2.0 / 5.4 Gbit/s | 5.6 cm |
| `n78` | 3300–3800 MHz | 5G n78 (56 MHz slice) | spare: a second operator | 5.6 m | 5.4 Gbit/s | 3.9 cm |

- **Board A2** (`hardware/boards/board_a2.py`) is one design built in four band versions. Each of its 6 channels has a 2-way splitter, so one antenna array and front end feed two stacks.
- **Up to 8 stacks:** 4 front-end builds × 2 outputs. Fit only the stacks for the bands your operators actually use.

**Consequences for the other boards (follow-up work):**
- **Board B input baluns (done 2026-10-26):** the `mid`, `high` and `n78` stacks use a Board B variant with Mini-Circuits TCM1-63AX+ baluns (10 MHz–6 GHz) and band-specific coupling caps. Details are in `hardware/HARDWARE.md` → *Board B band variants*. The AD9361's RXxA inputs themselves work up to 6 GHz.
- **Board C data link (Board C2 designed 2026-10-26):** only the TV stack fits Gigabit Ethernet (§6.4). The 4G/5G stacks need 1–5.4 Gbit/s even after FPGA cancelling, so they use **Board C2**: an XC7Z035-2FFG676I with 1 GB DDR3 and 2 × 10 GbE SFP+. Details are in `hardware/HARDWARE.md` → *Board C2*. The host side needs a 10 GbE NIC or switch port per 4G/5G stack.
- **Software:**
  - 4G/5G reference reconstruction, with suppression of their periodic structures (CRS/DMRS, SSB, CP);
  - 5G TDD gating, keeping downlink symbols only;
  - multi-band plot fusion in the tracker.
- **Antennas (designed 2026-10-27):** four surveillance panels plus log-periodic references, all at +45° slant. The spacing in the table above avoids grating lobes at the top of each band. Details are in §6.1 and `hardware/antenna/ANTENNA.md`.

**Site selection rule:** use a transmitter 5–30 km from the site, with the protected area *not* on the baseline. Targets near the baseline have almost zero bistatic range and Doppler (the forward-scatter region).

## 4. System architecture

```
                 DVB-T transmitter (third-party, 10–100 kW ERP)
                     │ direct path                ╲ illuminates drone
                     ▼                              ╲
   ┌──────────────┐      ┌─────────────────────────────┐
   │ Reference    │      │ Surveillance array           │◄── echo
   │ LPDA 7.5 dBi │      │ 4 slant dipoles, λ/2 ULA     │
   │ → Tx         │      │ boresight away from Tx       │
   └──────┬───────┘      └──────────────┬──────────────┘
          │ LNA + SAW BPF (per channel), matched cables
   ┌──────▼─────────────────────────────▼───────────────┐
   │ Coherent multichannel SDR (5–9 ch, shared LO/clock) │
   │ GPSDO 10 MHz + PPS · built-in noise-source calib.  │
   └──────────────────────┬──────────────────────────────┘
                          │ IQ samples (1 GbE, pre-cancelled in the FPGA, §6.4)
   ┌──────────────────────▼──────────────────────────────┐
   │ Processing (GPU)                                     │
   │ 1 Phase/amplitude calibration                        │
   │ 2 Reference reconstruction (DVB-T demod → remod)     │
   │ 3 Pilot / guard-interval ambiguity suppression       │
   │ 4 ECA-B clutter + direct-signal cancellation         │
   │ 5 Batched cross-ambiguity function (range-Doppler)   │
   │ 6 Digital beamforming (range-Doppler domain)         │
   │ 7 2D CA/OS-CFAR → plot extraction → DOA             │
   │ 8 Bistatic → Cartesian · multi-target tracker        │
   │ 9 Classification (kinematics, micro-Doppler, RCS)   │
   └──────────────────────┬──────────────────────────────┘
                          │ tracks
          C2 display · camera slew-to-cue · alerting · fusion
```

## 5. Link budget (from `python -m pcl.link_budget`)

Assumptions: ERP 10 kW, 600 MHz, 15 km baseline, 5 dBi element, NF 4 dB, 3 dB losses, CPI 0.25 s.

| Item | Value |
|---|---|
| Noise per sample (fs = 9.14 MHz) | −130.4 dBW |
| Coherent integration gain (fs·T) | 63.6 dB |
| Direct signal in a surveillance element (20 dB front/back) | **+43.8 dB above noise** |
| Reference channel SNR | +70.8 dB |
| Bistatic range / velocity resolution | 39 m / 1.0 m/s |

CAF SNR in dB for one element, target 15 km from the transmitter:

| RCS | 0.5 km | 1 km | 2 km | 3 km | 5 km | Free-space max range (1 / 4 el.) |
|---|---|---|---|---|---|---|
| 0.001 m² | 29.5 | 23.4 | 17.4 | 13.9 | 9.5 | 2.4 / 4.7 km |
| 0.01 m² | 39.5 | 33.4 | 27.4 | 23.9 | 19.5 | 7.4 / 14.9 km |
| 0.05 m² | 46.4 | 40.4 | 34.4 | 30.9 | 26.4 | 16.6 / 33 km |

**Planning ranges:** these free-space numbers are optimistic. Imperfect cancellation, multipath, terrain masking, line of sight to low drones, and RCS fluctuation reduce them in practice. Plan on **2–5 km for small quadcopters** and **5–10 km for small fixed-wing** from one node. The usual limit is the line-of-sight horizon at low altitude, so put the surveillance array on a mast (10–30 m).

**Dynamic-range requirement:** the reference channel SNR must exceed the direct signal in the surveillance channel by ≥ 10 dB. Otherwise reference noise leaks through the cancellation filter and raises the noise floor. This sets the reference antenna gain and ADC dynamic range (≥ 14-bit effective).

## 6. Hardware design

### 6.1 Antennas
**Designed 2026-10-27.** The full design is in [`../hardware/antenna/ANTENNA.md`](../hardware/antenna/ANTENNA.md) and is generated by `hardware/antenna/antenna_design.py`.

- **Polarisation:** +45° slant on every antenna. It matches one port of the ±45° 4G/5G base stations and costs 3 dB on DVB-T, whether the TV signal is horizontal or vertical.
- **Surveillance (CH1–CH4), one panel per band group:** 4 printed slant dipoles with built-in baluns, over a flanged aluminium reflector, at λ/2 of the band top.

  | Panel | Pitch | Reflector | Element |
  |---|---|---|---|
  | UHF | 180 mm | 851 × 415 mm | bowtie |
  | mid | 69 mm | 298 × 121 mm | strip dipole |
  | high | 56 mm | 237 × 93 mm | strip dipole |
  | n78 | 39 mm | 168 × 68 mm | strip dipole |

  - **Elements:** about 6.5 dBi each, with a 86–116° azimuth beam.
  - **Array:** the 4 elements give a 26–36° beam (48° at 470 MHz), with no grating lobes.
  - **Sector:** ±50° per panel, so 4 panels per band for 360°.
  - **Front-to-back:** the flanges are sized for ≥ 20 dB toward the transmitter. Physical shielding (an RF fence or terrain) adds another 10–20 dB.
- **Reference (CH0, and CH5 for stack B on another mast):** Carrel log-periodic arrays of about 7.5 dBi, aimed at the transmitter.
  - **LPDA-U** (450–870 MHz) is built from aluminium tubes.
  - **LPDA-H** (1.7–4.0 GHz) is a PCB that serves the mid, high and n78 groups.
  - With 7.5 dBi instead of the 12 dBi Yagi in §5, the reference SNR is about +66 dB. That still clears the ≥ +53.8 dB requirement.
- **Cables:** use a phase-matched set for CH1–CH4, plus a one-time far-field calibration using the transmitter's known bearing. The antenna cables are outside Board A2's noise-source calibration.
- **Elevation (option):** use CH5 as a fifth element above CH1, when stack B shares stack A's mast.

### 6.2 RF front end and receiver
| Tier | Receiver | Channels / BW | Use |
|---|---|---|---|
| Prototype (~$1–2k) | KrakenSDR (5 coherent RTL-SDR) | 5 ch / 2.4 MHz | Learn the chain. Only partial DVB-T bandwidth, so ~125 m range resolution |
| Field demonstrator (~$15–30k) | Ettus USRP N310 / X410, or 2× B210 locked to a GPSDO | 4–8 ch / ≥ 8 MHz | Full DVB-T, 39 m resolution |
| Product | Custom multichannel board (AD9361/AD9081 or RFSoC) | 8–16 ch / 8–100 MHz | Multi-band DVB-T + 5G |

Per-channel chain: SAW band-pass filter → LNA (NF < 1 dB, high IP3) → 6–8 MHz channel filter. All channels share the LO and sample clock. A GPSDO gives 10 MHz + PPS for multi-node time sync. A switched noise source handles phase/amplitude calibration of the array.

### 6.3 Compute
NVIDIA Jetson AGX Orin for an edge node, or an RTX-class GPU for a multi-face node. The CAF for 2.3 M samples × 330 range cells × 256 Doppler bins per channel runs in milliseconds on a GPU. The Python reference here takes about 1.5 s per CPI on a CPU.

### 6.4 Receiver-to-host data link (from `python -m pcl.data_rate`)

The custom receiver (Board C, Zynq-7020) sends samples to the GPU host over **one Gigabit Ethernet port**. The Zynq-7000 Ethernet controller has no jumbo frames (1522-byte maximum), so the UDP payload limit is **957 Mbit/s**. The design budget is 75 % of that, **718 Mbit/s**, which leaves room for the network stack, control traffic and bursts.

Raw samples do not fit:

| Stream | Mbit/s | Share of link | Fits? |
|---|---|---|---|
| 6 ch, 16-bit I/Q words (AD9361 native) | 1755 | 183 % | no |
| 6 ch, 12-bit packed | 1317 | 138 % | no |
| 5 ch, 12-bit packed | 1097 | 115 % | no |
| 5 ch, 12-bit, 8 MS/s | 960 | 100 % | no |
| 5 ch, 10-bit, 8 MS/s | 800 | 84 % | tight |
| 5 ch, 8-bit, 8 MS/s | 640 | 67 % | yes, but see below |
| **ref 12-bit + 4 surv 8-bit after FPGA cancel, 8 MS/s (chosen)** | **704** | **74 %** | **yes** |
| ref 12-bit + 4 surv 6-bit after FPGA cancel, 8 MS/s (fallback) | 576 | 60 % | yes |

**Simply dropping bits does not work.** Each surveillance channel is dominated by the direct signal, which is 44 dB above thermal noise at a 15 km baseline and 53 dB at 5 km. Quantisation noise scales with the strongest signal present. It is not correlated with the reference, so ECA cannot remove it.

Running simulated data through the real chain (ECA → CAF), mean of 3 runs, gives these target SNR losses against floating point:

| Scheme | Direct signal 43.8 dB | Direct signal 53.3 dB |
|---|---|---|
| 12-bit, all channels | −0.1 dB | −0.3 dB |
| 10-bit, all channels | −1.4 dB | −3.1 dB |
| 8-bit, all channels | **−8.5 dB** | **−13.1 dB** |
| FPGA canceller, then surveillance 8-bit, reference 12-bit | −0.1 dB | −0.3 dB |
| FPGA canceller, then surveillance 6-bit, reference 12-bit | −0.1 dB | −0.3 dB |

Losing 8.5 dB would cut the detection range by a factor of 2.7, so 8-bit raw samples are ruled out.

**Chosen fix: cancel in the FPGA, then requantise.** No board change is needed:

1. **Sample at 8 MS/s.** All channels run at **8.000 MS/s**, and the 7.61 MHz DVB-T band still fits.
   - *Revised 2026-10-27:* the AD9361s sample at 8.000 MS/s directly, with their programmable FIR doing the anti-alias filtering. The planned 7/8 FPGA resampler would have needed hundreds of taps for the 0.39 MHz transition band.
   - Firmware: [`../firmware/FIRMWARE.md`](../firmware/FIRMWARE.md).
2. **Cancel.** Each of the 4 surveillance channels passes through a **fixed 128-tap complex FIR canceller**, which subtracts the reference filtered by those taps. 128 taps cover 16 µs, or 4.8 km of bistatic delay.
   - The host computes the taps by least squares (the ECA solution) from a short raw snapshot and loads them into the FPGA between CPIs.
   - The taps never change inside a CPI, so the echoes are not modulated.
   - After cancelling, the surveillance residual is 1–6 dB above noise in simulation.
3. **Requantise.** The residual goes to **8 bits**, and the reference stays at **12 bits**. 8 bits still has about 39 dB of quantisation headroom, so it keeps working if the residual rises to roughly 25 dB above noise, for example with stale taps or moving clutter. The 6-bit mode tolerates only about 15 dB, so it is a fallback for a slow link only.
4. **Raw snapshots.** About once a second, a 65 k-sample raw 12-bit snapshot of all 5 channels (about 8 Mbit) goes to the host. The host uses it to recompute the canceller taps and for noise-source calibration.
5. **Host processing.** The host still runs ECA-B on the residual, for remaining and slowly varying clutter, then CAF, beamforming, CFAR and tracking as before.

**AGC setting.** Set the AD9361 gain so the signal RMS sits **14 dB below full scale** (full scale = 5 × RMS). With 12 dB back-off, the rare clipped OFDM peaks of the strong direct signal cost about 0.5 dB, even at 16 bits.

**Rejected alternatives:**
- **10 GbE:** the XC7Z020 has no multi-gigabit transceivers. It would need a Zynq-7030 or larger, which comes in a different package, so Board C would have to be redesigned.
- **Full CAF in the FPGA:** possible in principle, but it is a large firmware effort and fixes the processing in hardware.
- **Fewer channels:** 1 reference + 4 surveillance is already the minimum array.

The sixth AD9361 channel (spare) is not streamed. It can be swapped in for any channel by configuration.

**FPGA cost estimate:**
- The canceller needs 128 taps × 4 real multiplies × 4 channels × 8 MS/s, which is about 82 DSP48 slices at 200 MHz.
- The resampler adds about 12 more.
- That totals about 94 of the XC7Z020's 220 DSP slices.

## 7. Signal processing (implemented in `pcl/processing.py`)

1. **Calibration:** correct channel phase and gain from the noise-source or a known direct-signal angle.
2. **Reference conditioning** (planned): demodulate the DVB-T signal and remodulate it to get a noise-free reference. Then equalise or blank the scattered and continual pilots and the guard interval. Without this, the ambiguity function has spurious peaks.
3. **Clutter cancellation: ECA / ECA-B.** This is a least-squares projection of the surveillance signal onto K delayed copies of the reference. Here it is solved through Toeplitz normal equations (FFT + Levinson), so it runs in O(N log N). K = 160 taps (5 km of clutter). Batched (ECA-B) tracks moving clutter such as wind turbines and trees, at the cost of a wider zero-Doppler notch. **Simulated: 43.7 dB cancellation.**
4. **Cross-ambiguity function, batched.** The CPI is split into 256 segments. Range correlation uses FFTs, then an FFT across segments gives Doppler (±512 Hz). Doppler uses a Hann window. Range covers 330 cells (10.8 km).
5. **Beamforming** in the range-Doppler domain: max over a fan of beams adds +6 dB array gain with 4 elements.
6. **Detection:** 2D CA-CFAR (Pfa 1e-7), guard 3×3, training 8×8. The zero-Doppler ridge (|fd| < 3 Hz) is excluded. Peaks are picked as local maxima and refined with parabolic interpolation.
7. **Direction finding:** single-snapshot ML (Bartlett) on the per-element CAF values at the detected cell. Use MUSIC or Capon on multi-CPI snapshots when targets are close together.
8. **Localisation:** intersect the bistatic ellipse (range) with the DOA ray:
   `R_rx = (S² − L²) / (2(S − L·cos φ))`, with `S = R_b + L`.
   With several transmitters (several DVB-T sites or SFN channels), ellipse-intersection multilateration needs no DOA and is more accurate.
9. **Tracking** (implemented in `pcl/tracking.py`): an extended Kalman filter with a constant-velocity state in x/y. It updates directly on the raw measurements (bistatic range, bistatic Doppler, azimuth). Measuring Doppler gives velocity from the first plot, so a new track starts with a usable velocity. Association is global nearest neighbour (Hungarian algorithm, χ² gate). Tracks are confirmed 3-of-4 and deleted after 6 misses, which lets them coast through the zero-Doppler blind zone. Next step: an IMM (adding a coordinated-turn model) and JPDA for crossing targets.
10. **Classification** (implemented in `pcl/classify.py`, models in `pcl/micro_doppler.py`):
    - For each plot, beamform toward the target and store the Doppler spectrum of its range cell, centred on the body line.
    - Average these spectra over the track. Then find the strongest *symmetric* line (rotors give equal lines at +f and −f) in two bands:
      - **12–30 Hz** from the body: bird wing-beat sidebands.
      - **40–700 Hz**: rotor and propeller blades.
    - **Physics:** at 600 MHz, blades (~0.12 m) are short compared with λ = 0.5 m. Rotor echoes therefore appear as a few discrete lines at multiples of the blade rate, not a broad smear. An energy detector across the whole band dilutes them; the line detector does not.
    - **Decision rule:**
      - Rotor line z > 6 → **UAV**.
      - Otherwise wing-beat line z > 6 → **bird**.
      - Otherwise **unknown**.
      - At least 8 looks (2 s) are required before a class is given.
    - **False alarms:** on noise only, the rate is 0.5% at 4 looks and < 0.25% at ≥ 10 looks (Monte Carlo).
    - **On the receiver node (firmware, 2026-10-27):** the host cues up to 8 tracks to an FPGA micro-Doppler engine. The engine range-gates and beamforms each one continuously, giving 3.9 kHz slow-time with no CPI gaps. The ARM applies the same decision rule to continuous 0.52 s spectra and reports UAV / bird / unknown / no signal.
      - Simulated: a near quadcopter is classified UAV in 4 s (z 15), a bird → bird, an empty gate → no signal.
      - A far quadcopter, whose body line is at 31 dB, needs about 10 s.
      - False alarms: 0.25% at 8 looks.
      - See `firmware/FIRMWARE.md`.
    - **Future features:** kinematics (hovering, sharp turns), RCS statistics, behaviour near protected assets, and a small CNN on spectrograms.

## 8. Simulation results (`python run_demo.py`)

Scenario: transmitter 15 km south-west, 4-element array facing north-east, 8 clutter scatterers, direct signal +43.8 dB.

| Target | True Rb / fd / angle | Estimated | CAF SNR | Position error |
|---|---|---|---|---|
| Quadcopter, 0.01 m², 1.35 km | 2688.5 m / +57.3 Hz / −3.0° | 2688.8 m / +57.4 Hz / −2.8° | 29.2 dB | **5 m** |
| Fixed-wing, 0.05 m², 2.3 km | 4426.3 m / −47.5 Hz / −29.7° | 4426.9 m / −47.6 Hz / −30.2° | 31.5 dB | **17 m** |

There were no false alarms. Before ECA, the direct-signal sidelobes and clutter bury both targets (`output/range_doppler.png`).

### 8.1 Tracking and classification (`python run_tracking_demo.py`, 40 CPIs = 10 s)

The scenario has three targets, each with CPI-to-CPI RCS fluctuation (Swerling 1) and a micro-Doppler model:
- **Quadcopter:** 0.01 m², 4 rotors at ~100 rev/s, then an 8°/s turn.
- **Fixed-wing UAV:** 0.05 m², one propeller at 120 rev/s.
- **Bird:** 0.02 m², 6 Hz wing beat, weaving path.

| Track | Truth | Hits / scans | Position RMS | Velocity RMS | z wing-beat | z rotor | Class |
|---|---|---|---|---|---|---|---|
| T1 | bird | 23 / 40 | 5.3 m | 3.8 m/s | 1337 | 2.5 | **bird** ✓ |
| T2 | fixed-wing | 39 / 40 | 18.8 m | 5.6 m/s | 1.4 | 142 | **UAV** ✓ |
| T3 | quadcopter | 31 / 39 | 6.4 m | 3.6 m/s | 0.4 | 13.9 | **UAV** ✓ |

All three targets were tracked and classified correctly, with one short-lived tentative track and no false confirmed tracks.
- **Bird misses:** the bird is missed in some scans because its Doppler crosses the zero-Doppler clutter notch while it weaves. The tracker coasts through these gaps.
- **Fixed-wing velocity error:** this is mostly cross-range error at 2.6 km, where a 0.8° angle error is about 36 m. A multistatic network removes most of it.
- **Simulation limits:** the simulation does not yet model DVB-T pilots, multipath in the reference channel, terrain or receiver non-linearity, so field margins will be lower. The rotor-line amplitude (−12 dB relative to the body for a quadcopter) is an assumption and must be measured on real drones at UHF.

## 9. Multistatic network (recommended deployment)

- 3–4 receiver nodes, 1–3 km apart, around the protected site. Each node uses 1–3 transmitters (different DVB-T muxes or sites).
- Each node–transmitter pair adds a bistatic ellipse, so fused tracks get 3D position and accuracy around 10 m.
- Coverage overlaps, which fills the blind zone along each baseline.
- Nodes are time-synchronised by GPSDO. Plots are fused centrally.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Transmitter off or reconfigured (outage, mux change) | Monitor several transmitters and channels, plus an LTE/5G fallback channel |
| Direct signal saturates the ADC | Shielding, front/back ratio, AGC with 14 dB back-off, high-IP3 LNA, 12-bit or better ADC |
| Direct signal limits the sample precision the link can carry | Cancel the direct signal and clutter in the FPGA before reducing to 8 bits (§6.4). Never send raw 8-bit samples (−8.5 to −13 dB) |
| SFN (several transmitters on one frequency) creates ghost targets | Model the SFN delays in the reference reconstruction, or use them as extra bistatic pairs |
| Birds and cars cause false tracks | Track confirmation, elevation, micro-Doppler classification, road masks |
| Low drones hidden by terrain | Raise the array on a mast, add nodes |
| Low SNR for very small drones (< 0.001 m²) | Longer CPI (with range-migration compensation), more array elements, 5G at higher frequency |

## 11. Development roadmap

1. **Simulation (done):** link budget, ECA, CAF, CFAR, DOA, localisation.
2. **Done:** multi-CPI simulation, EKF tracking, micro-Doppler drone/bird classification. Next: DVB-T pilot handling, IMM/JPDA tracking.
3. **Custom receiver hardware (schematics, placement and routing done; Ethernet data-rate budget done, §6.4; fabrication checks open):** 3 boards: RF front end with calibration noise source, 3 × AD9361 coherent digitizer, Zynq-7020 processing board. See [`../hardware/HARDWARE.md`](../hardware/HARDWARE.md).
4. **Bench prototype:** KrakenSDR + 4-element array. Record real DVB-T data and replay it through this pipeline (add a file-input reader).
4. **Field trial:** USRP-class receiver, test against a co-operative drone with GPS truth logging. Measure Pd vs range, false-alarm rate and position error.
5. GPU real-time port (CuPy / CUDA), track output and camera cueing.
6. Multi-node network and fusion.

## 12. Regulatory notes

Passive radar transmits nothing, so in most countries it needs no spectrum licence. Check local rules on receiving and processing broadcast signals, data protection (if cameras are cued), and any rules on operating counter-UAS systems. This design covers **detection and tracking only**. Mitigation such as jamming or takeover is regulated separately and is out of scope.
