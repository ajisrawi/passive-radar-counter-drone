"""End-to-end passive radar simulation: two drones, DVB-T illuminator, 4-element array.

    python run_demo.py            # writes figures to ./output
"""
import time
from pathlib import Path as FsPath

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pcl import geometry as geo
from pcl import processing as proc
from pcl.link_budget import C, LinkBudget
from pcl.signal_model import FS_DVBT, Path, dvbt_like_ofdm, simulate_receiver

OUT = FsPath(__file__).parent / "output"
RNG = np.random.default_rng(7)

# ---------------- scenario ----------------
N_EL = 4  # 1 reference + 4 surveillance = 5 coherent channels (e.g. KrakenSDR-class)
BORESIGHT_DEG = 45.0  # array faces north-east, away from the transmitter
RX = np.array([0.0, 0.0, 10.0])
TX = np.array([-12_000.0, -9_000.0, 300.0])  # DVB-T mast 15 km south-west
N_RANGE = 330  # bistatic range cells (~10.8 km)
N_SEG = 256  # Doppler bins

DRONES = [
    # label, position (m), velocity (m/s), RCS (m^2)
    ("quadcopter", np.array([1000.0, 900.0, 120.0]), np.array([-12.0, -8.0, 0.0]), 0.01),
    ("fixed-wing", np.array([2200.0, 600.0, 200.0]), np.array([5.0, 18.0, 0.0]), 0.05),
]

lb = LinkBudget(fs_hz=FS_DVBT, cpi_s=0.25)
fs = lb.fs_hz
n = int(fs * lb.cpi_s)
baseline = np.linalg.norm(TX - RX)


def rel_angle(pos):
    return float(geo.wrap180(geo.azimuth_deg(RX, pos) - BORESIGHT_DEG))


# ---------------- build propagation paths ----------------
paths = [Path("direct signal", 0.0, 0.0, lb.dsi_snr_db(baseline), rel_angle(TX))]
for k in range(8):  # stationary ground clutter (buildings, hills, masts)
    paths.append(Path(f"clutter{k}", float(RNG.integers(3, 120)), 0.0,
                      float(RNG.uniform(10, 35)), float(RNG.uniform(-80, 80))))

truth = []
for label, pos, vel, rcs in DRONES:
    b = geo.bistatic(TX, RX, pos, vel, lb.wavelength)
    snr = lb.echo_snr_sample_db(b["r_tx"], b["r_rx"], rcs)
    paths.append(Path(label, b["rb"] * fs / C, b["fd"], snr, rel_angle(pos)))
    truth.append({"label": label, "pos": pos, **b, "snr": snr, "angle": rel_angle(pos),
                  "caf_snr": lb.echo_snr_caf_db(b["r_tx"], b["r_rx"], rcs)})

print(f"CPI {lb.cpi_s*1e3:.0f} ms = {n:,} samples at {fs/1e6:.3f} MS/s, baseline {baseline/1e3:.1f} km")
print(f"Direct signal in surveillance: {lb.dsi_snr_db(baseline):.1f} dB above noise")
for t in truth:
    print(f"  {t['label']:<11} Rb={t['rb']:7.1f} m  fd={t['fd']:+6.1f} Hz  angle={t['angle']:+6.1f} deg  "
          f"SNR/sample={t['snr']:6.1f} dB  expected CAF SNR={t['caf_snr']:5.1f} dB (+{10*np.log10(N_EL):.0f} dB array)")

# ---------------- simulate receiver ----------------
t0 = time.time()
ref_clean = dvbt_like_ofdm(n, RNG)
ref_snr = min(lb.ref_snr_db(baseline), 50.0)  # dynamic range / multipath limited
ref, surv = simulate_receiver(ref_clean, paths, N_EL, fs, ref_snr, RNG)
print(f"\nSimulated {N_EL+1} channels in {time.time()-t0:.1f} s (reference SNR {ref_snr:.0f} dB)")

# ---------------- processing ----------------
t0 = time.time()
raw_caf, doppler, rng_axis = proc.caf(ref, surv[0], fs, N_RANGE, N_SEG)
clean = np.stack([proc.eca(ref, surv[k], n_taps=160) for k in range(N_EL)])
cafs = np.stack([proc.caf(ref, clean[k], fs, N_RANGE, N_SEG)[0] for k in range(N_EL)])
power = proc.beam_max_map(cafs, np.arange(-90, 91, 1.0))
dets = proc.detect(power, doppler)
print(f"Processing (ECA x{N_EL}, CAF x{N_EL+1}, beamforming, CFAR) in {time.time()-t0:.1f} s")

dsi_before = np.mean(np.abs(surv[0]) ** 2)
dsi_after = np.mean(np.abs(clean[0]) ** 2)
print(f"ECA: surveillance power {10*np.log10(dsi_before):.1f} dB -> {10*np.log10(dsi_after):.1f} dB "
      f"(noise = 0 dB), cancellation {10*np.log10(dsi_before/dsi_after):.1f} dB")

floor = np.median(power)
dr = rng_axis[1]
dd = doppler[1] - doppler[0]
print(f"\n{len(dets)} detection(s):")
results = []
for di, ri, margin in dets:
    fdi, fri = proc.refine_peak(power, di, ri)
    rb = fri * dr
    fd = doppler[0] + fdi * dd
    ang, _ = proc.doa_bartlett(cafs[:, di, ri])
    xy, r_rx = geo.localize_2d(rb, BORESIGHT_DEG + ang, TX, RX)
    snr_db = 10 * np.log10(power[di, ri] / floor)
    match = min(truth, key=lambda t: np.hypot((t["rb"] - rb) / 50, (t["fd"] - fd) / 5))
    err = np.linalg.norm(xy - match["pos"][:2])
    results.append((rb, fd, ang, xy, match, err))
    print(f"  Rb={rb:7.1f} m  fd={fd:+6.1f} Hz  angle={ang:+6.1f} deg  SNR={snr_db:5.1f} dB  "
          f"(CFAR margin {margin:4.1f} dB) -> x={xy[0]:7.1f} y={xy[1]:7.1f}  "
          f"[{match['label']}, position error {err:.0f} m]")

# ---------------- figures ----------------
OUT.mkdir(exist_ok=True)
ext = [rng_axis[0] / 1e3, rng_axis[-1] / 1e3, doppler[0], doppler[-1]]
raw_db = 20 * np.log10(np.abs(raw_caf) + 1e-12)
raw_db -= np.median(raw_db)
cl_db = 10 * np.log10(power / floor)

fig, axs = plt.subplots(1, 2, figsize=(14, 5.5), constrained_layout=True)
for ax, img, title in ((axs[0], raw_db, "Before clutter cancellation (element 1)"),
                       (axs[1], cl_db, "After ECA + beamforming")):
    im = ax.imshow(img, aspect="auto", origin="lower", extent=ext, cmap="viridis", vmin=-3, vmax=35)
    ax.set_xlabel("Bistatic range (km)")
    ax.set_ylabel("Bistatic Doppler (Hz)")
    ax.set_title(title)
    ax.set_ylim(-150, 150)
    for t in truth:
        ax.plot(t["rb"] / 1e3, t["fd"], "o", mfc="none", mec="r", ms=14, mew=1.5)
        ax.annotate(t["label"], (t["rb"] / 1e3, t["fd"]), xytext=(8, 10), textcoords="offset points", color="w")
fig.colorbar(im, ax=axs, label="dB above noise floor")
fig.savefig(OUT / "range_doppler.png", dpi=130)

fig, ax = plt.subplots(figsize=(7.5, 7), constrained_layout=True)
for rb, fd, ang, xy, match, err in results:
    e = geo.bistatic_ellipse(rb, TX, RX)
    ax.plot(e[:, 0] / 1e3, e[:, 1] / 1e3, "--", lw=0.8, color="gray")
    ax.plot([0, xy[0] / 1e3 * 1.3], [0, xy[1] / 1e3 * 1.3], ":", color="tab:blue", lw=0.8)
    ax.plot(xy[0] / 1e3, xy[1] / 1e3, "x", color="tab:blue", ms=10, mew=2)
for t in truth:
    ax.plot(t["pos"][0] / 1e3, t["pos"][1] / 1e3, "o", mfc="none", mec="r", ms=12, mew=1.5)
    ax.annotate(t["label"], t["pos"][:2] / 1e3, xytext=(8, -14), textcoords="offset points")
ax.plot(0, 0, "k^", ms=10)
ax.annotate("Rx", (0, 0), xytext=(8, 4), textcoords="offset points")
u = (TX[:2] - RX[:2]) / baseline
ax.annotate(f"to Tx ({baseline/1e3:.0f} km)", xy=u * 0.6, xytext=u * 0.2,
            arrowprops=dict(arrowstyle="->"), ha="center")
ax.set(xlim=(-1, 3.5), ylim=(-1.5, 3), xlabel="East (km)", ylabel="North (km)", aspect="equal",
       title="Localisation: bistatic ellipse x DOA (o truth, x estimate)")
ax.grid(alpha=0.3)
fig.savefig(OUT / "geometry.png", dpi=130)
print(f"\nFigures written to {OUT}")
