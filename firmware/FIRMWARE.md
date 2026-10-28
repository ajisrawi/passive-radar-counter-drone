# Receiver-node firmware (Board C / C2) with on-board micro-Doppler

The firmware runs on the Zynq of each receiver stack (Board C: XC7Z020, TV; Board C2: XC7Z035, 4G/5G).
- **Signal path:** the board takes the three AD9361s' samples, cancels the direct signal, and streams the residual to the GPU host.
- **Micro-Doppler engine:** for every target the host is tracking, the board watches that target's range cell continuously. It classifies the target as **UAV / bird / unknown** from its micro-Doppler.

```
AD9361 x3 ─LVDS─► axi_ad9361 x3 (ADI) ─► ad_merge ─► pcl_core ─┬► canceller ─► stream_pack ─► AXI DMA ─► pcl_streamd ─UDP─► host
                                       (CDC, ref sel)          │      (128 taps, host-loaded)          (C program)
                                                               └────────────► md_engine ─► ring ─► pcl_noded ─UDP─► host
                                                                  (8 cued gates, beam + range gate)   (Python: classifier, control)
host tracker ── cues (delay, azimuth), canceller taps, config ──────────────────────────────► pcl_noded
```

## Why on-board micro-Doppler

The host sees each target only through 0.25 s CPIs. The FPGA engine has no such limit:
- **Continuous output:** it correlates every cued target's range cell and beam continuously, giving a gap-free slow-time signal at fs/2^block_log2 (3906 Hz on the TV stack).
- **Cheap to run:** it costs about 5 complex multiplies per sample per target.
- **Long, clean spectra:** the ARM classifies on continuous 0.52 s spectra. Its decision rule is the same as the host's (`pcl/classify.py`): a symmetric rotor line in 40–700 Hz means **UAV**, and a wing-beat line in 12–30 Hz means **bird**, with z > 6 after ≥ 8 looks.

## Files

| Path | What |
|---|---|
| `hdl/canceller.v` | direct-signal canceller: 128 complex taps (Q2.16) per surveillance channel, 8 multipliers per channel, two tap banks that swap only at a CPI boundary |
| `hdl/md_engine.v` | micro-Doppler engine (details below) |
| `hdl/stream_pack.v` | requantises the reference to 12 bits and the residual to 8 bits; packs 88-bit samples into 64-bit AXI-Stream words, 1408-byte packets (128 samples) |
| `hdl/pcl_core.v` | the above, plus the AXI4-Lite registers (map in the file header), sample counter, GNSS PPS latch, md ring (128 records at 0x800) |
| `hdl/ad_merge.v` | joins the three AD9361 clock domains (async FIFOs) into one aligned sample; reference CH0 or CH5 (stack B) |
| `model/fixedpoint.py` | bit-true Python models: the reference the RTL must match exactly |
| `sim/run_tests.py` | Icarus testbenches vs the models (canceller, md engine, whole core over AXI-Lite, 3-clock merge) |
| `sim/test_e2e.py` | simulated UHF scene → bit-true FPGA → ARM classifier |
| `sim/test_link.py` | host ↔ node control link over loopback |
| `sim/test_md_falsealarm.py` | classifier false-alarm rate (Monte Carlo) |
| `ps/pcl_noded.py` | ARM daemon: radios, cues, taps, md readout, classification, reports |
| `ps/md_classifier.py` | the on-board classifier |
| `ps/hw.py` | UIO register access with bulk ring reads, and `SimRegs` (the same API on the model) |
| `ps/radio.py` | the three AD9361s through libiio: rate, LO, bandwidth, manual gain, multi-chip sync |
| `ps/streamd/` | `pcl_streamd.c`: AXI DMA (SG, user space) → `sendmmsg` UDP, plus Makefile |
| `ps/node_config*.json` | node configs (Board C TV, Board C2 n78) |
| `vivado/gen_xdc.py` | pin constraints generated from the board netlists → `board_c.xdc`, `board_c2.xdc` |
| `vivado/build.tcl` | block design: PS7 from the netlist MIO map, ADI AD9361 cores, merge, core, DMA, address map, bitstream, .xsa |
| `vivado/system_top_c*.v` | board pins → block design |
| `linux/pl-overlay.dtsi` | UIO nodes, u-dma-buf, three AD9361s on SPI0 |
| `../pcl/node_protocol.py`, `../pcl/cueing.py` | the UDP protocol, and the host side (`NodeLink`: cue tracks, load taps, read reports) |

## Micro-Doppler engine

For target slot t, with delay τ (in samples) and beam weights w (Q1.15):

    b[n] = round(Σc s_c[n]·conj(w_c) / 2^15),   z[n] = b[n]·conj(r[n−τ]),   Y[m] = sat32(round(Σblock z / 2^out_shift))

- **What Y[m] is:** the cross-ambiguity value of the target's range cell and beam for block m (2^block_log2 samples).
- **Throughput:** targets are processed one per clock, so samples must be at least NTGT+1 clocks apart.
- **Safe parameter changes:** new cues go into a shadow set and are copied at the first sample of a block, so a block is never mixed.
- **Reference delay line:** 4096 samples, which is 154 km of bistatic range at 8 MS/s.
- **Output:** records go into a 128-entry ring at `0x800`. `pcl_noded` copies all new records with one numpy read of the mapped window and writes `MD_RD` back.
- **out_shift:** pick it so that noise per block is about 10³–10⁴. TV stack: 4 at block_log2 11.

On the ARM (`md_classifier.py`):
- **Spectra:** 2048-point Hann segments with 50% hop; noise floor from the median; re-centred on the body line.
- **Empty gate:** segments with a body line under 12 dB don't count as looks, so an empty or lost gate reports **no signal**.
- **Decision:** spectra are averaged over the track, then the decision rule is applied.
- **Hann window:** a Blackman-Harris window cost 2.5× in z, because it spreads a rotor line over 4 bins. Hann still keeps body leakage into the wing-beat band about 54 dB down.

## Verification (all run here)

| Test | Result |
|---|---|
| `run_tests.py canceller` | 600 samples, 0 mismatches, including a tap-bank swap at a CPI boundary and 100 saturated outputs |
| `run_tests.py md` | 36 records, 0 mismatches; 8 slots, delays 0–4095, parameter change at a block boundary |
| `run_tests.py core` | configured over AXI4-Lite: 5632 stream words and 48 md records, 0 mismatches; TLAST every 176 words; PPS latch, ring read pointer and REF_SEL checked |
| `run_tests.py merge` | three unrelated chip clocks to 200 MHz: 955 samples aligned across all 6 channels, no loss, both reference selections |
| `test_link.py` | cues, drop, taps (Q2.16 exact), config, MD_REPORT and STATUS over UDP loopback: 9/9 checks |
| `test_md_falsealarm.py` | body line with no micro-Doppler, 400 tracks: P(z > 6) = 0.25% at 8 looks, 0% at 20 |
| `test_e2e.py` (4 s) | near quad → **UAV** (z_far 15.4, line at 214 Hz); bird → **bird** (z 539); empty gate → **no signal**; far quad → unknown (z 3.5; 5.5 after 8 s); canceller −43.6 dB |
| Yosys `synth_xilinx` (Board C parameters) | 148 DSP48 (67% of XC7Z020), ~11.8k LUT (22%), 9.1k FF (9%), 4 RAMB36 |
| Yosys `synth_xilinx` (Board C2: 64 taps, 32 lanes, 3 md slots) | 532 DSP48 (59% of XC7Z035), ~30k LUT (18%), 5k FF, 4 RAMB36 |

**What the far quadcopter shows:**
- **Why it's slow:** at UHF most rotor energy sits on the body line, so a single rotor line is about 28 dB below the body. A drone with a 31 dB body line needs about 10 s of dwell before it's called UAV.
- **Why it's still safe:** it's never misclassified as a bird. The host classifier has the same physics.
- **What helps:** the 4G/5G stacks, at 4–6× shorter wavelength, spread the rotor energy into stronger lines.

## Not verified here (needs the hardware or AMD tools)

- **Vivado flow:** `vivado/build.tcl`, PS7 settings, timing at 200 MHz (Yosys only estimates resources) and the bitstream. Run it with ADI's HDL library built.
- **Linux:** the device tree overlay (`linux/pl-overlay.dtsi`), the AD9361 driver binding for three chips, and multi-chip sync.
- **Streamer:** `ps/streamd/pcl_streamd.c` was not compiled here (no C compiler); build it on the board. 704 Mbit/s through user-space `sendmmsg` on a Cortex-A9 is the main performance risk. If it falls short, use the 6-bit stream (needs a 6-bit `stream_pack` build) or Board C2's 10 GbE.
- **Board C2 builds:**
  - **Canceller:** the 61.44 MS/s 5G stack leaves 4 clocks per sample at 245.76 MHz. That allows a 64-tap canceller (32 multipliers per channel, about 1 µs or 300 m of clutter) and 3 md slots per engine; a second engine instance is needed for 6 slots.
  - **10 GbE:** the UDP path from `pcl_core.m_axis` to the SFP+ GTX (e.g. the open-source verilog-ethernet 10G MAC/UDP) is **not written yet**.
- **Hardware check:** both boards run Zynq MIO bank 501 at 3.3 V with RGMII Ethernet on it. Confirm in Xilinx UG585 / DS187 that RGMII on MIO is supported at 3.3 V. If not, bank 501 must move to 1.8 or 2.5 V, a Board C/C2 change.

## Changes against DESIGN.md §6.4

- **No PL resampler:** the AD9361 samples at 8.000 MS/s directly, using its own programmable FIR as the anti-alias filter. A 7/8 FPGA resampler would need hundreds of taps for the 0.39 MHz transition band.
- **Taps:** the canceller taps are Q2.16 (18-bit).
- **Reference select:** the reference channel can be CH5 (`REF_SEL`), for stack-B nodes whose transmitter is on another mast.

## Quick start

    python firmware/sim/run_tests.py          # HDL vs models (needs OSS CAD Suite / Icarus)
    python firmware/sim/test_e2e.py 4         # scene -> FPGA model -> classifier (~2 min)
    python firmware/vivado/gen_xdc.py         # after any board change
    vivado -mode batch -source firmware/vivado/build.tcl -tclargs c     # ADI_HDL set, library built
    # on the board:
    sudo python3 firmware/ps/pcl_noded.py --config firmware/ps/node_config.json
    make -C firmware/ps/streamd && sudo firmware/ps/streamd/pcl_streamd --host <gpu host>
