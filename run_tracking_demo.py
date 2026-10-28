"""Multi-CPI passive radar simulation: detection -> EKF tracking -> drone/bird classification.

Scenario: a quadcopter (turning), a small fixed-wing UAV and a bird (gull/pigeon class)
observed for 10 s (40 CPIs of 0.25 s) by a DVB-T passive radar with a 4-element array.

    python run_tracking_demo.py [--cpis 40]   # figures in ./output
"""
import argparse
import time
from pathlib import Path as FsPath

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pcl import classify as cls
from pcl import geometry as geo
from pcl import processing as proc
from pcl.link_budget import C, LinkBudget
from pcl.micro_doppler import Rotor, RotorSignature, WingBeatSignature, quadcopter_rotors
from pcl.signal_model import FS_DVBT, FastReceiver, Path
from pcl.targets import Target, Trajectory, echo_params
from pcl.tracking import Measurement, Tracker

ap = argparse.ArgumentParser()
ap.add_argument("--cpis", type=int, default=40)
ap.add_argument("--seed", type=int, default=11)
args = ap.parse_args()

OUT = FsPath(__file__).parent / "output"
RNG = np.random.default_rng(args.seed)

N_EL, BORESIGHT_DEG = 4, 45.0
RX = np.array([0.0, 0.0, 10.0])
TX = np.array([-12_000.0, -9_000.0, 300.0])
N_RANGE, N_SEG = 330, 512  # 512 segments -> +/-1 kHz Doppler span, room for rotor micro-Doppler
lb = LinkBudget(fs_hz=FS_DVBT, cpi_s=0.25)
fs, lam, cpi = lb.fs_hz, lb.wavelength, lb.cpi_s
n = int(fs * cpi)
duration = args.cpis * cpi
baseline = np.linalg.norm(TX - RX)

# ---------------- targets ----------------
targets = [
    Target("quadcopter", "uav",
           Trajectory(np.array([1300.0, 1150.0, 120.0]), 10.0,
                      lambda t: 215.0 + (8.0 * (t - 4.0) if t > 4.0 else 0.0), duration),
           0.01, RotorSignature(quadcopter_rotors(RNG), rel_power_db=-12.0)),
    Target("fixed-wing", "uav",
           Trajectory(np.array([2600.0, -300.0, 200.0]), 20.0, lambda t: 100.0, duration),
           0.05, RotorSignature([Rotor(0.15, 120.0, 2, 0.0)], rel_power_db=-15.0)),
    Target("bird", "bird",
           Trajectory(np.array([600.0, 1700.0, 60.0]), 11.0,
                      lambda t: 300.0 + 25.0 * np.sin(2 * np.pi * t / 5.0), duration),
           0.02, WingBeatSignature(beat_hz=6.0, excursion_m=0.12, am_depth=0.3, rel_power_db=-3.0,
                                   phase0=RNG.uniform(0, 2 * np.pi))),
]

static_paths = [Path("direct", 0.0, 0.0, lb.dsi_snr_db(baseline),
                     float(geo.wrap180(geo.azimuth_deg(RX, TX) - BORESIGHT_DEG)))]
for k in range(8):
    static_paths.append(Path(f"clutter{k}", float(RNG.integers(3, 120)), 0.0,
                             float(RNG.uniform(10, 35)), float(RNG.uniform(-80, 80))))

rx_sim = FastReceiver(n, static_paths, N_EL, fs, min(lb.ref_snr_db(baseline), 50.0), RNG)
tracker = Tracker(TX, RX, lam, cpi)
angles = np.arange(-90, 91, 2.0)
doppler = np.fft.fftshift(np.fft.fftfreq(N_SEG, d=(n // N_SEG) / fs))  # same axis proc.caf returns
dd, dr = doppler[1] - doppler[0], C / fs

truth_log = {t.label: [] for t in targets}
n_meas_log = []
t_start = time.time()
print(f"{args.cpis} CPIs x {cpi*1e3:.0f} ms, {N_EL} elements, DSI {lb.dsi_snr_db(baseline):.1f} dB")

for c in range(args.cpis):
    t0 = c * cpi
    t_mid = t0 + cpi / 2

    # ---- simulate this CPI ----
    echoes = []
    for tg in targets:
        e = echo_params(tg, t_mid, TX, RX, lam, BORESIGHT_DEG)
        snr = lb.echo_snr_sample_db(e["r_tx"], e["r_rx"], tg.rcs_m2)
        if tg.swerling1:
            snr += 10 * np.log10(RNG.exponential(1.0))
        sig = tg.signature
        echoes.append({"delay_samples": e["rb"] * fs / C, "doppler_hz": e["fd"], "snr_db": snr,
                       "angle_deg": e["angle"],
                       "modulation": (lambda t, s=sig, kh=e["k_h"], kf=e["k_full"]: s.modulation(t, kh, kf))})
        truth_log[tg.label].append((t_mid, e))
    ref, surv = rx_sim.cpi(t0, echoes)

    # ---- process ----
    clean = np.stack([proc.eca(ref, surv[k], n_taps=160) for k in range(N_EL)])
    cafs = np.stack([proc.caf(ref, clean[k], fs, N_RANGE, N_SEG)[0] for k in range(N_EL)])
    power = proc.beam_max_map(cafs, angles)
    dets = proc.detect(power, doppler)

    meas = []
    for di, ri, margin in dets:
        fdi, fri = proc.refine_peak(power, di, ri)
        ang, _ = proc.doa_bartlett(cafs[:, di, ri])
        feats = cls.micro_doppler_features(cafs, doppler, di, ri, ang)
        meas.append(Measurement(fri * dr, doppler[0] + fdi * dd, BORESIGHT_DEG + ang, margin, feats))
    n_meas_log.append(len(meas))
    tracker.step(meas, t_mid)
    if (c + 1) % 10 == 0:
        print(f"  CPI {c+1:3d}/{args.cpis}  detections {len(meas)}  live tracks {len(tracker.tracks)}  "
              f"({time.time()-t_start:.0f} s)")

# ---------------- evaluate ----------------
confirmed = [t for t in tracker.all_tracks() if t.status in ("confirmed", "deleted")]
print(f"\nDetections per CPI: mean {np.mean(n_meas_log):.2f}; confirmed tracks: {len(confirmed)}; "
      f"dropped tentative tracks: {sum(t.status == 'dropped' for t in tracker.all_tracks())}")


def truth_at(label, t):
    return min(truth_log[label], key=lambda p: abs(p[0] - t))[1]


report = []
for trk in confirmed:
    best, best_err = None, np.inf
    for tg in targets:
        errs = [np.linalg.norm(x[:2] - truth_at(tg.label, t)["pos"][:2]) for t, x, _ in trk.history]
        if np.mean(errs) < best_err:
            best, best_err = tg, np.mean(errs)
    hist = trk.history[3:] if len(trk.history) > 6 else trk.history  # skip convergence
    pos_err = [np.linalg.norm(x[:2] - truth_at(best.label, t)["pos"][:2]) for t, x, _ in hist]
    vel_err = [np.linalg.norm(x[2:] - truth_at(best.label, t)["vel"][:2]) for t, x, _ in hist]
    feats = [m.features for _, m in trk.meas]
    speed = float(np.hypot(*trk.x[2:]))
    label, zn, zf = cls.classify_track(feats, speed)
    truth_cls = "UAV" if best.kind == "uav" else "bird"
    report.append((trk, best, label, zn, zf, pos_err, vel_err, feats))
    print(f"  Track {trk.tid:2d} -> {best.label:<11} {len(trk.meas):2d} hits/{len(trk.history):2d} scans  "
          f"pos RMS {np.sqrt(np.mean(np.square(pos_err))):5.1f} m  vel RMS {np.sqrt(np.mean(np.square(vel_err))):4.2f} m/s  "
          f"speed {speed:4.1f} m/s  z_near {zn:6.1f}  z_far {zf:6.1f}  => {label:<7} "
          f"[{'correct' if label == truth_cls else 'WRONG'}]")

# ---------------- figures ----------------
OUT.mkdir(exist_ok=True)
colors = {"quadcopter": "tab:red", "fixed-wing": "tab:orange", "bird": "tab:green"}
fig, ax = plt.subplots(figsize=(8, 7.5), constrained_layout=True)
for tg in targets:
    p = np.array([e["pos"] for _, e in truth_log[tg.label]])
    ax.plot(p[:, 0] / 1e3, p[:, 1] / 1e3, "-", color=colors[tg.label], lw=6, alpha=0.25)
    ax.annotate(f"{tg.label} (truth)", p[0, :2] / 1e3, xytext=(6, 6), textcoords="offset points",
                color=colors[tg.label])
for trk, best, label, zn, zf, *_ in report:
    x = np.array([h[1] for h in trk.history])
    ax.plot(x[:, 0] / 1e3, x[:, 1] / 1e3, ".-", color="k", lw=1, ms=3)
    for _, m in trk.meas:
        xy, _ = geo.localize_2d(m.rb, m.az_deg, TX, RX)
        ax.plot(xy[0] / 1e3, xy[1] / 1e3, "+", color=colors[best.label], ms=5, alpha=0.6)
    ax.annotate(f"T{trk.tid}: {label}", x[-1, :2] / 1e3, xytext=(6, -12), textcoords="offset points",
                fontweight="bold")
ax.plot(0, 0, "k^", ms=10)
ax.annotate("Rx", (0, 0), xytext=(8, 4), textcoords="offset points")
ax.set(xlabel="East (km)", ylabel="North (km)", aspect="equal",
       title="EKF tracks (black) over truth (shaded); + = single-CPI plots")
ax.grid(alpha=0.3)
fig.savefig(OUT / "tracking.png", dpi=130)

n_show = len(report)
fig, axs = plt.subplots(2, max(n_show, 1), figsize=(5 * max(n_show, 1), 8), constrained_layout=True, squeeze=False)
off_axis = (np.arange(N_SEG) - N_SEG // 2) * dd
for col, (trk, best, label, zn, zf, _, _, feats) in enumerate(report):
    S = np.array([10 * np.log10(np.maximum(np.nan_to_num(f["spectrum"], nan=1.0), 1e-3)) for f in feats])
    tt = [t for t, _ in trk.meas]
    axs[0, col].imshow(S, aspect="auto", origin="lower", cmap="viridis", vmin=-5, vmax=25,
                       extent=[off_axis[0], off_axis[-1], tt[0], tt[-1]])
    axs[0, col].set(xlim=(-700, 700), xlabel="Doppler offset from body (Hz)", ylabel="Time (s)",
                    title=f"T{trk.tid} ({best.label}) -> {label}")
    mean_spec = 10 * np.log10(np.maximum(np.nanmean([f["spectrum"] for f in feats], axis=0), 1e-3))
    axs[1, col].plot(off_axis, mean_spec, lw=0.8)
    for lo, hi, cname in ((*cls.NEAR_BAND_HZ, "tab:green"), (*cls.FAR_BAND_HZ, "tab:red")):
        for s in (-1, 1):
            axs[1, col].axvspan(s * lo, s * hi, color=cname, alpha=0.08)
    axs[1, col].set(xlim=(-700, 700), ylim=(-3, 40), xlabel="Doppler offset from body (Hz)",
                    ylabel="dB above noise", title=f"Track mean: z_near {zn:.1f}, z_far {zf:.1f}")
    axs[1, col].grid(alpha=0.3)
fig.suptitle("Micro-Doppler: green band = wing beat (bird), red band = rotor blades (UAV)")
fig.savefig(OUT / "micro_doppler.png", dpi=120)
print(f"\nTotal {time.time()-t_start:.0f} s. Figures: {OUT/'tracking.png'}, {OUT/'micro_doppler.png'}")
